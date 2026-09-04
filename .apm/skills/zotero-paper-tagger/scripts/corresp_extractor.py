#!/usr/bin/env python3
"""corresp_extractor: 论文通讯作者显式信息提取（纯函数库 + CLI 自检）。

渠道（v2）:
  A pdf_footnote  — 本地 PDF 第一页文本层找脚注标注（pdftotext，零网络）
  B springer_curl — Springer/Nature 系落地页 #corresponding-author-list（1 次 HTTP）
  B2 crossref_api — Crossref REST author[].role 含 corresponding-author

统一输出 record（dict）:
  {"contacts": [{"name": ..., "email": ..., "confidence": ..., "channel": ...}],
   "names": [...], "emails": [...], "raw_text": str,
   "channel": "pdf_footnote|springer_curl|crossref_api|none",
   "confidence": "high|low", "fetched_at": ISO8601-UTC}

contacts[] 只收来源结构能直接证明的 name/email 配对。独立 names[] / emails[]
继续保留以兼容旧 _corresp_cache.json，但绝不按数组位置推断配对。

抓不到返回 None；全渠道试过仍无 → 调用方可自行落 channel="none" 的否定记录。
本模块不做教授姓名比对——比对是 zotero-paper-tagger 署名簿规则的事。
浏览器渠道不在这里实现：abstract-fetch 的 evaluate_script 片段见
abstract-fetch SKILL.md「通讯作者提取」节，返回值由调用方转成同一 record schema；
只有 DOM 节点本身证明 name/email 关系时才应填 contacts[]。

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

# Schema version marker for records evaluated under the verified-pair contract.
# Presence of this field distinguishes modern records from legacy records whose
# independent names[]/emails[] arrays predate verified pairing semantics.
SCHEMA_VERSION = "corresp/v1"

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
    print(msg, flush=True, file=sys.stderr)


RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
RE_INITIALS_NAME = re.compile(
    r"(?:[A-Z]\.\s*)+[A-Z][A-Za-z'\u2019\-]{1,}(?![a-z])")
RE_FULL_NAME = re.compile(
    r"[A-Z][a-z\u00c0-\u017f'\u2019\-]{1,}(?:\s+[A-Z](?:[a-z\u00c0-\u017f]+|\.)?){1,3}")
RE_CJK_NAME = re.compile(r"[\u4e00-\u9fff]{2,6}(?=[\s，,;；()（）:：]|$)")
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

MARK_EN = re.compile(r"(?:correspond\w*|author to whom)", re.I)
MARK_JP = re.compile(r"(対応著者|責任著者|連絡先)")
SYMBOLS = "*†‡✉§¶"

# 显式邮箱字段：去掉邮箱字段标签（E-mail:/Email:/メール:）和邮箱地址后，
# 整行只剩符号/标点才算干净的邮箱字段行。
RE_EMAIL_FIELD_LABEL = re.compile(
    r"\b(?:e-?mail|mail|メール(?:アドレス)?)\s*[:：]\s*", re.I)
RE_EMAIL_LINE_RESIDUE = re.compile(
    r"^[\s*†‡§¶✉()（）\[\]【】<>、。，,.．;；:：!！?？\-–—=~|]*$")


def _is_author_note(m, text):
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


RE_IPSJ_BEFORE = re.compile(
    r"\(\s*((?:[A-Z]\.\s*)*[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)?)\s*\)"
    r"(?:\s*\(\s*[A-Za-z]{1,4}\s*\)\s*){1,4}$")
RE_BEFORE_PLAIN = re.compile(
    r"((?:[A-Z]\.\s*)*[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,2})\s*,?\s*"
    r"\b(?:is|was)\b\s*(?:\bthe\b|\ba\b)?\s*$")
FUNDING_KWS = ("This research", "This work", "This study", "was supported",
               "supported by", "funded by", "Financial support",
               "Acknowledg", "grant-in-aid", "Grand-in-Aid", "Grant-in-Aid")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_names(cands):
    out, seen = [], set()
    for c in cands:
        c = re.sub(r"\s+", " ", (c or "").strip()).strip(".,;:()（）")
        if not c or len(c) < 4 or re.search(r"\d", c):
            continue
        low = c.lower()
        core = re.findall(r"[a-z]+", low)
        while core and len(core[0]) == 1:
            core.pop(0)
        if any(t in NAME_STOP for t in core):
            continue
        if low not in seen:
            seen.add(low)
            out.append(c)
    return out


def _names_in(text):
    # 先剥离显式邮箱字段标签：标签紧跟姓名时（"Alex Example E-mail: ..."），
    # 其大写 "E" 会被姓名正则粘成 "Alex Example E"。
    text = RE_EMAIL_FIELD_LABEL.sub(" ", text or "")
    found = list(RE_INITIALS_NAME.findall(text))
    for m in RE_FULL_NAME.finditer(text):
        s = m.group(0)
        if "." not in s:
            found.append(s)
    for m in RE_CJK_NAME.finditer(text):
        found.append(m.group(0))
    return found


def _normalize_email(email):
    return (email or "").strip().strip(".").lower()


def _contact(name, email, channel, confidence="high"):
    names = _clean_names([name])
    email = _normalize_email(email)
    if not names or not email or not RE_EMAIL.fullmatch(email):
        return None
    return {"name": names[0], "email": email,
            "confidence": confidence, "channel": channel}


def _dedupe_contacts(contacts):
    out, seen = [], set()
    for c in contacts or []:
        if not isinstance(c, dict):
            continue
        clean = _contact(c.get("name"), c.get("email"), c.get("channel") or "none",
                         c.get("confidence") or "low")
        if not clean:
            continue
        key = (clean["name"].casefold(), clean["email"], clean["channel"])
        if key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def _single_proven_pair(text, channel, confidence="high"):
    """只在同一个结构块里恰有 1 个姓名和 1 个邮箱时形成 pair。

    多姓名或多邮箱都视为关系不明，留在 names[]/emails[]，不做位置配对。
    """
    names = _clean_names(_names_in(text or ""))
    emails = sorted({_normalize_email(e) for e in RE_EMAIL.findall(text or "")})
    if len(names) != 1 or len(emails) != 1:
        return []
    c = _contact(names[0], emails[0], channel, confidence)
    return [c] if c else []


def _is_email_field_line(line):
    """该行本身是否为显式邮箱字段：行内确有邮箱地址或邮箱字段标签，且去掉
    标签和地址后只剩符号/标点。纯标点/分隔线（-----、*、()）不含任何邮箱
    证据，是结构边界而非邮箱字段；带散文注记的行（"E-mail: office@example.org
    (Editorial Office)"）同样不是干净字段，都不得吸进有界通讯块。"""
    line = (line or "").strip()
    if not line:
        return False
    if not (RE_EMAIL.search(line) or RE_EMAIL_FIELD_LABEL.search(line)):
        return False
    residue = RE_EMAIL.sub(" ", RE_EMAIL_FIELD_LABEL.sub(" ", line))
    return bool(RE_EMAIL_LINE_RESIDUE.match(residue))


def _pdf_bounded_block_proven_pair(text, marker):
    """Only pair evidence inside the marker's bounded correspondence block.

    The block is the marker's own line plus immediately following lines that are
    themselves explicit email fields: lines holding nothing beyond email-field
    labels (`E-mail:`/`Email:`/`メール:`), the address(es) itself, and allowed
    punctuation. Annotated or prose email lines (editorial/support notes) do
    not qualify. The first line that is not an email field — a blank line,
    affiliation, editorial/funding prose — ends the block, so an email in a
    later unrelated block is never absorbed. Within the block the counts must
    still be exactly one name and one email; anything else stays unpaired.
    """
    line_start = text.rfind("\n", 0, marker.start()) + 1
    nl = text.find("\n", marker.end())
    parts = [text[line_start:nl if nl >= 0 else len(text)]]
    while nl >= 0:
        nxt = text.find("\n", nl + 1)
        line = text[nl + 1:nxt if nxt >= 0 else len(text)]
        if not _is_email_field_line(line):
            break
        parts.append(line)
        nl = nxt
    return _single_proven_pair("\n".join(parts), "pdf_footnote")


def _mk(names, emails, raw, channel, contacts=None):
    names = _clean_names(names)
    emails = sorted({_normalize_email(e) for e in emails if _normalize_email(e)})
    return {
        "schema": SCHEMA_VERSION,
        "contacts": _dedupe_contacts(contacts),
        "names": names,
        "emails": emails,
        "raw_text": re.sub(r"\s+", " ", raw).strip()[:300],
        "channel": channel,
        "confidence": "high" if names else "low",
        "fetched_at": _now(),
    }


# ---------------------------------------------------------------- 渠道 A: PDF 脚注

def pdf_page_text(pdf_path, pages=1):
    try:
        r = subprocess.run(["pdftotext", "-f", "1", "-l", str(pages), str(pdf_path), "-"],
                           capture_output=True, timeout=30)
        t = r.stdout.decode("utf-8", "ignore")
        if len(t.strip()) >= 50:
            return t
    except Exception:
        pass
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        t = "\n".join(doc[i].get_text() for i in range(min(pages, doc.page_count)))
        doc.close()
        return t
    except Exception:
        return ""


def parse_pdf_text(text):
    if not text or len(text.strip()) < 50:
        return None
    emails = RE_EMAIL.findall(text[:4000])
    hits = list(MARK_JP.finditer(text))
    for m in MARK_EN.finditer(text):
        if _is_author_note(m, text):
            hits.append(m)
    if not hits:
        return None
    names, contacts, raw_parts = [], [], []
    for m in hits[:6]:
        after_raw = text[m.end():min(len(text), m.end() + 400)]
        for kw in FUNDING_KWS:
            i = after_raw.find(kw)
            if i >= 0:
                after_raw = after_raw[:i]
        before = text[max(0, m.start() - 80):m.start()].rstrip().rstrip("(（").rstrip()
        raw_parts.append(before[-40:] + " ⟂ " + after_raw)
        local_names = _names_in(after_raw)
        ip = RE_IPSJ_BEFORE.search(before)
        bp = RE_BEFORE_PLAIN.search(before)
        if ip:
            local_names.append(ip.group(1))
        elif bp:
            local_names.append(bp.group(1))
        names.extend(local_names)

        # contacts[] is intentionally stricter than the compatibility arrays: only
        # the marker's bounded correspondence block may prove a pair. The block is
        # the marker line plus immediately following explicit email-field lines and
        # ends at the first non-field line, so later prose is never paired merely
        # because it is nearby.
        contacts.extend(_pdf_bounded_block_proven_pair(text, m))
    rec = _mk(names, emails, " || ".join(raw_parts), "pdf_footnote", contacts)
    return rec if (rec["names"] or rec["emails"]) else None


def extract_from_pdf(pdf_path):
    """Extract correspondence info from a PDF's first page.

    Returns a record dict if correspondence evidence was found.
    Returns None if the PDF was successfully parsed but no verified pair found
    (verified negative).
    Raises PdfUnavailable if the PDF could not be opened or yielded too
    little text to analyze (no extractable text layer, scan, etc.) — this is
    distinct from "checked and found no pair".
    """
    text = pdf_page_text(pdf_path)
    if not text or len(text.strip()) < 50:
        raise PdfUnavailable(f"PDF yielded no analyzable text: {pdf_path}")
    return parse_pdf_text(text)


class PdfUnavailable(Exception):
    """Raised when a PDF cannot be analyzed (no text layer, scan, etc.).

    This is distinct from a verified negative: the PDF was never actually
    checked for correspondence pairs, so the result should NOT carry the
    schema marker and should remain retryable.
    """
    pass


# ---------------------------------------------------------------- 渠道 B: Springer/Nature 落地页

SPRINGER_HOSTS = ("link.springer.com", "www.nature.com", "nature.com",
                  "link.biomedcentral.com", "bmcpublichealth.biomedcentral.com")
HOST_SUFFIXES = (".springer.com", ".nature.com", ".biomedcentral.com",
                 ".springeropen.com", ".bmcmedicine.com")
RE_CORR_LIST = re.compile(r'<p id="corresponding-author-list"[^>]*>(.*?)</p>', re.S)
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
    inner = m.group(1)
    text = re.sub(r"\s+", " ", RE_TAG.sub(" ", inner)).strip()
    if not text:
        return None
    seg = re.sub(r"^Correspondence to\s*", "", text, flags=re.I)
    names = _names_in(seg) or _names_in(text)
    emails = RE_EMAIL.findall(html[max(0, m.start() - 300):m.end() + 500])
    # 配对比旧 emails[] 更严格：只看 corresponding-author-list 自身，不借邻接 HTML 猜关系。
    contacts = _single_proven_pair(RE_TAG.sub(" ", inner), "springer_curl")
    return _mk(names, emails, text, "springer_curl", contacts)


def extract_from_doi(doi, net_sleeper=None):
    """Try all DOI-backed channels for correspondence evidence.

    Returns a record dict if a verified pair is found.
    Returns None if a channel was successfully checked but no pair found.
    Raises an exception if every attempted channel failed with an error
    (so the caller can distinguish "checked, no pair" from "request failed").
    """
    def nap():
        if net_sleeper:
            net_sleeper()
    final = None
    try:
        final = resolve_doi(doi)
        nap()
    except Exception:
        final = None
    is_springer = (final and (any(h in final for h in SPRINGER_HOSTS)
                              or any(final.split("/")[2].endswith(s) for s in HOST_SUFFIXES)))
    checked = False  # True if any channel completed successfully
    if is_springer:
        try:
            rec = parse_springer_html(fetch_html(final))
            nap()
            checked = True
            if rec:
                return rec
        except Exception:
            pass
    try:
        return fetch_crossref_role(doi)  # may be None (valid negative) or a record
    except Exception:
        if checked:
            # Springer completed successfully but found no pair; Crossref failed
            # afterwards. The valid negative from Springer stands.
            return None
        # No channel completed successfully — let the caller know.
        raise


# ---------------------------------------------------------------- 渠道 B2: Crossref role

def fetch_crossref_role(doi):
    url = ("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe=""))
    log("  → GET api.crossref.org（role 字段）")
    req = urllib.request.Request(url, headers={"User-Agent": "corresp-extractor/1.0 (mailto:none@example.com)"})
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
    # Crossref role 在当前字段里只证明“谁是通讯作者”，不提供对应邮箱，因此 contacts=[]。
    return _mk(names, [], "Crossref corresponding-author role", "crossref_api", [])


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