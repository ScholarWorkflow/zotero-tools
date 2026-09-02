#!/usr/bin/env python3
"""corresp_extractor: 论文通讯作者显式信息提取（纯函数库 + CLI 自检）。

渠道（v1）:
  A pdf_footnote  — 本地 PDF 第一页文本层找脚注标注（pdftotext，零网络）
  B springer_curl — Springer/Nature 系落地页 #corresponding-author-list（1 次 HTTP）
  B2 crossref_api — Crossref REST author[].role 含 corresponding-author

统一输出 record（dict）:
  {"names": [...], "emails": [...], "raw_text": str,
   "channel": "pdf_footnote|springer_curl|crossref_api|none",
   "confidence": "high|low", "fetched_at": ISO8601-UTC}

抓不到返回 None；全渠道试过仍无 → 调用方可自行落 channel="none" 的否定记录。
本模块不做教授姓名比对——比对是 zotero-paper-tagger 署名簿规则的事。
浏览器渠道不在这里实现：abstract-fetch 的 evaluate_script 片段见
abstract-fetch SKILL.md「通讯作者提取」节，返回值由调用方转成同一 record schema。

CLI 自检:
  corresp_extractor.py <pdf路径>
  corresp_extractor.py --doi <doi>
"""

import json
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
TIMEOUT = 20

# 并行限速：所有网络请求发起前过一道全局闸，min_interval 秒内最多发一个请求。
# 默认关闭（0）；corresp_backfill 并行模式下设为 0.25（≈4 req/s 上限）。
_net_gate_lock = threading.Lock()
_net_gate_min = 0.0
_net_gate_last = 0.0


def set_net_throttle(min_interval):
    global _net_gate_min, _net_gate_last
    with _net_gate_lock:
        _net_gate_min = float(min_interval)
        _net_gate_last = 0.0


def _throttle_wait():
    global _net_gate_last
    if _net_gate_min <= 0:
        return
    with _net_gate_lock:
        now = __import__("time").time()
        delta = _net_gate_min - (now - _net_gate_last)
        if delta > 0:
            now += delta
            _net_gate_last = now
            need = delta
        else:
            _net_gate_last = now
            need = 0.0
    if need > 0:
        __import__("time").sleep(need)


def log(msg):
    """请求级日志 → stderr（stdout 留给数据输出）。"""
    print(msg, flush=True, file=sys.stderr)

# ---------------------------------------------------------------- 名字/邮箱模式

RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
# 缩写名: A. Example / B. Sample / C. D. Author
RE_INITIALS_NAME = re.compile(
    r"(?:[A-Z]\.\s*)+[A-Z][A-Za-z'\u2019\-]{1,}(?![a-z])")
# 全名: Alex Example / Jean-Francois Author（2~4 个词，首词非缩写）
RE_FULL_NAME = re.compile(
    r"[A-Z][a-z\u00c0-\u017f'\u2019\-]{1,}(?:\s+[A-Z](?:[a-z\u00c0-\u017f]+|\.)?){1,3}")
# 日文姓名: 汉字 2-6 字（可含平假名）
RE_CJK_NAME = re.compile(r"[\u4e00-\u9fff]{2,6}(?=[\s，,;；()（）:：]|$)")
# 停用词：出现在候选名里就丢弃（防把机构/套话当地名）
NAME_STOP = {"university", "institute", "corresponding", "author", "address",
             "department", "email", "mail", "japan", "science", "technology",
             "abstract", "keywords", "introduction", "copyright", "license",
             "journal", "press", "correspondence", "editor", "the", "and",
             "for", "with", "from", "to", "peer", "review", "reviewer",
             "graduate", "school", "faculty", "college", "center", "centre",
             "laboratory", "society", "foundation", "academic", "creative",
             "commons", "systems", "design", "received", "revised", "accepted",
             "published", "advance", "member", "open", "access", "identifier",
             "digital", "object", "download", "downloaded", "corp", "ltd", "inc",
             "engineering", "health", "sciences", "intelligence", "informatics",
             "networks", "psychology", "metropolitan", "universitas", "content",
             "source", "oriented", "unit", "units", "summary", "related", "work"}

MARK_EN = re.compile(
    r"(?:correspond\w*|author to whom)", re.I)
MARK_JP = re.compile(r"(対応著者|責任著者|連絡先)")
SYMBOLS = "*†‡✉§¶"


def _is_author_note(m, text):
    """EN 命中是否为作者注脚而非正文用词。

    正文里 "values corresponding to..." 这类普通用词会误命中；作者注脚的特征：
    ① 标记后 60 字符内出现 author/authors（"Corresponding author."）；
    ② 标记在行首或行首只有符号（脚注行典型形态）；
    ③ 紧邻标记前的字符是上标符号（作者标记换行后符号贴着下一行）。"""
    after = text[m.end():m.end() + 60]
    if re.search(r"\bauthors?\b", after, re.I):
        return True
    ls = text.rfind("\n", 0, m.start()) + 1
    prefix = text[ls:m.start()]
    if re.fullmatch(rf"\s*[{re.escape(SYMBOLS)}]?\s*", prefix):
        return True
    if prefix.rstrip().endswith(tuple(SYMBOLS)):
        return True
    return False
# 逐词分词形态：(A. Chen) (is) (the) (corresponding) (author)
# 名字在标记【前】的紧邻括号里；其他形态一律不收标记前的词（防作者行污染）
RE_IPSJ_BEFORE = re.compile(
    r"\(\s*((?:[A-Z]\.\s*)*[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)?)\s*\)"
    r"(?:\s*\(\s*[A-Za-z]{1,4}\s*\)\s*){1,4}$")
# 普通语序倒装：… A. Chen is the | *Corresponding author
# 名字紧邻标记前，中间只隔 is/was/(the)；锚定到 before 串末尾，防误抓远处的词
RE_BEFORE_PLAIN = re.compile(
    r"((?:[A-Z]\.\s*)*[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,2})\s*,?\s*"
    r"\b(?:is|was)\b\s*(?:\bthe\b|\ba\b)?\s*$")
# 致谢/基金关键词：后窗在这里截断，防止把资助语句里的词当人名
FUNDING_KWS = ("This research", "This work", "This study", "was supported",
               "supported by", "funded by", "Financial support",
               "Acknowledg", "grant-in-aid", "Grand-in-Aid", "Grant-in-Aid")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mk(names, emails, raw, channel):
    names = _clean_names(names)
    return {
        "names": names,
        "emails": sorted({e.strip(".").lower() for e in emails}),
        "raw_text": re.sub(r"\s+", " ", raw).strip()[:300],
        "channel": channel,
        "confidence": "high" if names else "low",
        "fetched_at": _now(),
    }


def _clean_names(cands):
    out, seen = [], set()
    for c in cands:
        c = re.sub(r"\s+", " ", (c or "").strip()).strip(".,;:()（）")
        if not c or len(c) < 4 or re.search(r"\d", c):
            continue
        low = c.lower()
        # 去掉开头连续的单字母缩写词元，其余词元过停用词
        core = re.findall(r"[a-z]+", low)
        while core and len(core[0]) == 1:
            core.pop(0)
        if any(t in NAME_STOP for t in core):
            continue
        key = low
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _names_in(text):
    """一段文本里提取人名候选：优先缩写名，再全名，再日文名。"""
    found = list(RE_INITIALS_NAME.findall(text))
    for m in RE_FULL_NAME.finditer(text):
        s = m.group(0)
        # 全名里若含缩写词，RE_INITIALS 已抓过整串；这里补纯词全名
        if "." not in s:
            found.append(s)
    for m in RE_CJK_NAME.finditer(text):
        found.append(m.group(0))
    return found


# ---------------------------------------------------------------- 渠道 A: PDF 脚注

def pdf_page_text(pdf_path, pages=1):
    """读 PDF 前 N 页文本层。pdftotext 优先，fitz 兜底；都失败返回 ''。"""
    try:
        r = subprocess.run(["pdftotext", "-f", "1", "-l", str(pages), str(pdf_path), "-"],
                           capture_output=True, timeout=30)
        t = r.stdout.decode("utf-8", "ignore")
        if len(t.strip()) >= 50:
            return t
    except Exception:
        pass
    try:
        import fitz  # PyMuPDF，可选依赖
        doc = fitz.open(str(pdf_path))
        t = "\n".join(doc[i].get_text() for i in range(min(pages, doc.page_count)))
        doc.close()
        return t
    except Exception:
        return ""


def parse_pdf_text(text):
    """第一页文本 → record | None。

    名字只从标记【后】窗口收（*Corresponding author: Name / 邮箱括号缩写名 / 日文名）；
     标记【前】仅认逐词分词紧邻形态 (A. Example) (is) (the) (corresponding)，
    其余前置文本一律不碰——作者行里的非通讯名字绝不能混进来。"""
    if not text or len(text.strip()) < 50:
        return None
    emails = RE_EMAIL.findall(text[:4000])
    hits = list(MARK_JP.finditer(text))
    for m in MARK_EN.finditer(text):
        if _is_author_note(m, text):
            hits.append(m)
    if not hits:
        return None
    names = []
    raw_parts = []
    for m in hits[:6]:
        after_raw = text[m.end():min(len(text), m.end() + 400)]
        for kw in FUNDING_KWS:
            i = after_raw.find(kw)
            if i >= 0:
                after_raw = after_raw[:i]
        before = text[max(0, m.start() - 80):m.start()].rstrip().rstrip("(（").rstrip()
        raw_parts.append(before[-40:] + " ⟂ " + after_raw)
        names.extend(_names_in(after_raw))
        ip = RE_IPSJ_BEFORE.search(before)
        bp = RE_BEFORE_PLAIN.search(before)
        if ip:
            names.append(ip.group(1))
        elif bp:
            names.append(bp.group(1))
    rec = _mk(names, emails, " || ".join(raw_parts), "pdf_footnote")
    return rec if (rec["names"] or rec["emails"]) else None


def extract_from_pdf(pdf_path):
    return parse_pdf_text(pdf_page_text(pdf_path))


# ---------------------------------------------------------------- 渠道 B: Springer/Nature 落地页

SPRINGER_HOSTS = ("link.springer.com", "www.nature.com", "nature.com",
                  "link.biomedcentral.com", "bmcpublichealth.biomedcentral.com")
HOST_SUFFIXES = (".springer.com", ".nature.com", ".biomedcentral.com",
                 ".springeropen.com", ".bmcmedicine.com")

RE_CORR_LIST = re.compile(
    r'<p id="corresponding-author-list"[^>]*>(.*?)</p>', re.S)
RE_TAG = re.compile(r"<[^>]+>")


def resolve_doi(doi):
    _throttle_wait()
    log(f"  → GET doi.org/{doi}（解析落地页）")
    req = urllib.request.Request(f"https://doi.org/{doi}",
                                 headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    try:
        final = urllib.request.urlopen(req, timeout=TIMEOUT).geturl()
        log(f"  ← 302 落地: {final[:90]}")
        return final
    except Exception as e:
        log(f"  ← 失败: {type(e).__name__} {getattr(e, 'code', '')}")
        raise


def fetch_html(url):
    _throttle_wait()
    log(f"  → GET {url[:80]}")
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "identity"})
    html = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8", "ignore")
    log(f"  ← 200, {len(html)} bytes")
    return html


def parse_springer_html(html):
    m = RE_CORR_LIST.search(html)
    if not m:
        return None
    text = re.sub(r"\s+", " ", RE_TAG.sub(" ", m.group(1))).strip()
    if not text:
        return None
    seg = re.sub(r"^Correspondence to\s*", "", text, flags=re.I)
    names = _names_in(seg) or _names_in(text)
    emails = RE_EMAIL.findall(html[max(0, m.start() - 300):m.end() + 500])
    return _mk(names, emails, text, "springer_curl")


def extract_from_doi(doi, net_sleeper=None):
    """DOI → 先 Springer/Nature 落地页，再 Crossref role。都无 → None。

    net_sleeper: 可选回调，每次网络请求前调用一次（调用方用来限速）。"""
    def nap():
        if net_sleeper:
            net_sleeper()
    try:
        final = resolve_doi(doi)
        nap()
    except Exception:
        final = None
    if final and (any(h in final for h in SPRINGER_HOSTS)
                  or any(final.split("/")[2].endswith(s) for s in HOST_SUFFIXES)):
        try:
            rec = parse_springer_html(fetch_html(final))
            nap()
            if rec:
                return rec
        except Exception:
            pass
    try:
        return fetch_crossref_role(doi)
    except Exception:
        return None


# ---------------------------------------------------------------- 渠道 B2: Crossref role

def fetch_crossref_role(doi):
    url = ("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=""))
    log(f"  → GET api.crossref.org（role 字段）")
    req = urllib.request.Request(url, headers={"User-Agent": f"corresp-extractor/1.0 (mailto:none@example.com)"})
    data = json.load(urllib.request.urlopen(req, timeout=TIMEOUT))["message"]
    names = []
    for a in data.get("author") or []:
        for r in a.get("role") or []:
            if r.get("role") == "corresponding-author":
                nm = " ".join(x for x in [a.get("given"), a.get("family")] if x)
                if nm:
                    names.append(nm)
    log(f"  ← 200, corresponding-author role: {len(names)} 个")
    if not names:
        return None
    return _mk(names, [], "Crossref corresponding-author role", "crossref_api")


# ---------------------------------------------------------------- CLI 自检

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    if len(argv) == 2 and argv[0] == "--doi":
        rec = extract_from_doi(argv[1])
    elif len(argv) == 1 and argv[0] not in ("--help", "-h"):
        rec = extract_from_pdf(argv[0])
    else:
        print(__doc__)
        sys.exit(1)
    print(json.dumps(rec, ensure_ascii=False, indent=2) if rec else "null（未抓到显式通讯信息）")
