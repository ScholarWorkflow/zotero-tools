#!/usr/bin/env python3
"""zotero-paper-tagger: 给 Zotero 教授分类下的条目批量打 大学/教授/一作/通讯作者 四类标签。

用法:
  tagger.py <program_root> [--professor NAME] [--dry-run]
  tagger.py [--boshu-root DIR] [--dry-run]            # 全库一键
  tagger.py add-tags <itemKey> <tag> [<tag>...]       # 人工确认补打
  tagger.py remove-tags <itemKey> <tag> [<tag>...]    # 分歧清单确认后的显式删除

通讯作者判定采用「显式记录优先」（读 _corresp_cache.json，由上游抓取流程产出），无记录回落末位启发式。主流程只增不删；删除走两段式——
报告出分歧清单，人工确认编号后用 remove-tags 批量执行。

只增不删（remove-tags 除外）; 幂等可重跑。读 23119 本地 API, 写 23120 zotero-mcp 插件 write_tag。
"""

import argparse
import itertools
import json
import re
import sys
import time
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path

READ_BASE = "http://127.0.0.1:23119"
MCP_URL = "http://127.0.0.1:23120/mcp"
SKIP_ITEM_TYPES = {"attachment", "note", "annotation"}
REPORT_NAME = "_论文标签报告.md"
MAPPING_NAME = "_zotero_collections.json"
SIGNATURE_NAME = "_署名对照.json"
CORRESP_CACHE_NAME = "_corresp_cache.json"

# 异体字归一表（人名常见新旧字形/异体），NFKC 之后再过一遍
VARIANT_MAP = {
    "髙": "高",   # U+9AD9
    "﨑": "崎",   # U+FA11
    "𠮷": "吉",   # U+20BB7
    "澤": "沢",
    "廣": "広",
    "萬": "万",
    "邊": "辺", "邉": "辺",
    "嶋": "島", "嶌": "島",
    "濱": "浜",
    "國": "国", "實": "実", "龍": "竜",
    "戶": "戸",
    "會": "会", "檜": "桧",
    "龜": "亀", "榮": "栄",
}


def out(s=""):
    print(s, flush=True)


# ---------------------------------------------------------------- connectivity

def check_read_api():
    try:
        with urllib.request.urlopen(f"{READ_BASE}/connector/ping", timeout=5) as r:
            return b"running" in r.read()
    except Exception:
        return False


class Mcp:
    """23120 zotero-mcp 插件的 Streamable HTTP 会话。"""

    def __init__(self):
        self.sid = None
        self._id = 0

    def connect(self):
        body = json.dumps({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "zotero-paper-tagger", "version": "1"}},
        }).encode()
        req = urllib.request.Request(MCP_URL, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            self.sid = r.headers.get("Mcp-Session-Id")
        if not self.sid:
            raise RuntimeError("23120 initialize 未返回 Mcp-Session-Id")

    def call(self, tool, args, retries=2):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}}).encode()
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(MCP_URL, data=body, method="POST", headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Mcp-Session-Id": self.sid,
                })
                with urllib.request.urlopen(req, timeout=60) as r:
                    resp = json.load(r)
                if "error" in resp:
                    raise RuntimeError(resp["error"].get("message", str(resp["error"])))
                text = resp["result"]["content"][0]["text"]
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return {"_raw": text}
            except Exception:
                if attempt >= retries:
                    raise
                time.sleep(1.0)


# ---------------------------------------------------------------- name matching

def _nfkc(s):
    return unicodedata.normalize("NFKC", s)


def norm_kanji(s):
    s = _nfkc(s or "")
    s = re.sub(r"[\s\u3000・·.,，、。\-‐–—]+", "", s)
    return s


def norm_variant(s):
    return "".join(VARIANT_MAP.get(ch, ch) for ch in norm_kanji(s))


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def romaji_tokens(s):
    s = strip_accents(_nfkc(s or "")).lower()
    # 'and' 只来自脏字段拼接（"A and B"），真名不含独立词 and
    return [t for t in re.split(r"[^a-z]+", s) if t and t != "and"]


def romaji_variants(name_romaji):
    """Parse a name and optional parenthesized alternate spelling."""
    if not name_romaji:
        return []
    parts = [p.strip() for p in re.split(r"[()]", name_romaji) if p.strip()]
    return parts or []


def name_str_to_creator(name_str):
    """显式记录里的人名字符串 → judge_author 能吃的伪 creator。

    带逗号的缩写名拆成姓/名；其余整体放 lastName（①③⑦④⑤⑥ 全是
    last+first 拼接或词序无关多重集比对，放哪个字段不影响判定）。"""
    s = re.sub(r"[()（）]", "", (name_str or "").strip())
    if "," in s:
        ln, _, fn = s.partition(",")
        return {"lastName": ln.strip(), "firstName": fn.strip(),
                "creatorType": "author"}
    return {"lastName": s.strip(), "firstName": "", "creatorType": "author"}


def load_corresp_cache(prog_root):
    """读 _corresp_cache.json（corresp_backfill / abstract-fetch 钩子产出）。
    文件不存在 = 全库无显式记录，使用末位作者启发式。"""
    p = prog_root / "教授研究" / CORRESP_CACHE_NAME
    if not p.is_file():
        return {}
    try:
        data = json.load(open(p, encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def email_hits_prof(emails, romaji_vars):
    """规则⑧：通讯脚注里的邮箱本地部命中教授姓氏罗马字。

    学术邮箱惯例 localpart=姓氏（surname@）或 姓+编号（surname123@）。
    只认「全等」或「姓氏开头+≤3 位尾随数字」两种形态，宁漏勿错。"""
    hits = []
    for em in emails or []:
        lp = re.sub(r"[^a-z]", "", str(em).split("@")[0].lower())
        if len(lp) < 4:
            continue
        for rv in romaji_vars or []:
            toks = romaji_tokens(rv)
            if not toks:
                continue
            for surname in {toks[0], toks[-1]}:
                if len(surname) < 4:
                    continue
                if lp == surname or (
                        lp.startswith(surname) and len(lp) <= len(surname) + 3
                        and lp[len(surname):].isdigit()):
                    hits.append(f"{em} ↔ {rv}")
                    break
    return hits


# ---------------------------------------------------------------- 署名簿（signature book）

def creator_tokens(c):
    return Counter(romaji_tokens((c.get("lastName") or "") + " " +
                                 (c.get("firstName") or "")))


def creator_raw(c):
    return f"{c.get('lastName') or ''}, {c.get('firstName') or ''}".strip(", ")


def _lev1(a, b):
    """编辑距离 ≤1（含相邻字符换位）。"""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        if len(diff) == 1:
            return True
        return (len(diff) == 2 and diff[1] == diff[0] + 1
                and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    if len(a) > len(b):
        a, b = b, a
    i = j = diff = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diff += 1
            if diff > 1:
                return False
            j += 1
    return True


def explain_variant(tc, pc):
    """tc/pc: Counter（罗马字词多重集）。广义对齐判断 tc 是不是教授全名 pc 的署名形态。
    允许: 任意多个词缩写成首字母 + 任意多个词缺失 + 至多 1 个多余首字母 + 至多 1 个笔误词
    （编辑距离≤1 或字母换位乱序，词长≥4）。
    返回 kind 字符串（"seed" 全同 / "abbr" 缩略形 / "typo" 整体笔误形 / "mash" 含全名的脏拼接 / None）。"""
    if not tc or sum(pc.values()) < 2:
        return None
    exact = tc & pc
    if not exact:
        # 整体是某个词的笔误? （某个姓氏拼写接近但不完全相同的情形；
         # 这里处理 tc 与 pc 完全无交集但逐词笔误的极端形态——不认, 直接 None)
        lt0, lp0 = tc - pc, pc - tc
        if sum(lt0.values()) == 1 and sum(lp0.values()) >= 1 and sum(exact.values()) == 0:
            return None
        return None
    lt, lp = tc - exact, pc - exact
    if not lt and not lp:
        return "seed"
    if not lp:
        # 教授全部词都在: 至多 1 个多余单字母 → 合法 extra-initial 缩略; 其余是脏拼接
        if sum(lt.values()) <= 1 and all(len(t) == 1 for t in lt):
            return "abbr"
        return "mash"
    lp_words = list(lp.elements())
    used, extra, typo = [], 0, 0
    for t in list(lt.elements()):
        if len(t) == 1:
            h = next((w for w in lp_words if w not in used and w.startswith(t)), None)
            if h:
                used.append(h)
            else:
                extra += 1
            continue
        if len(t) == 2:
        # 双首字母挤在一个词里
            wa = next((w for w in lp_words if w not in used and w.startswith(t[0])), None)
            wb = next((w for w in lp_words if w not in used and w.startswith(t[1]) and w != wa), None)
            if wa and wb:
                used.extend([wa, wb])
                continue
        h = next((w for w in lp_words if w not in used and len(w) >= 4 and
                  (_lev1(t, w) or Counter(t) == Counter(w))), None) if len(t) >= 4 else None
        if h:
            used.append(h)
            typo += 1
            continue
        # 反向拼合: 整词 t 等于 pc 剩余碎片的某种顺序拼接
        rest = [w for w in lp_words if w not in used]
        m = None
        if len(t) >= 5 and len(rest) >= 2:
            for r in range(2, len(rest) + 1):
                for perm in itertools.permutations(rest, r):
                    if "".join(perm) == t:
                        m = perm
                        break
                if m:
                    break
        if m:
            used.extend(m)
            continue
        return None   # 有解释不了的外人完整词 → 不是教授形态
    if extra > 1 or typo > 1:
        return None
    if typo and not used:
        return "typo"
    return "abbr"


def given_letters(tc, pc):
    """tc 相对 pc 的 given 表示：非共享词的首字母集合。空集=纯子集形态(裸姓/缺词无given)。"""
    tc, pc = Counter(tc), Counter(pc)
    lt = tc - (tc & pc)
    return {t[0] for t in lt}


def hyphen_merge(seq, pc_words):
    """把相邻片段拼成 pc 里的整词（连字符或碎片姓名若 pc 有对应整词才拼）。
    seq: token 列表; pc_words: 整词集合。贪心最长优先。"""
    out, i, n = [], 0, len(seq)
    while i < n:
        hit = None
        for j in range(n, i + 1, -1):
            if j - i >= 2:
                cat = "".join(seq[i:j])
                if cat in pc_words:
                    hit = (cat, j)
                    break
        if hit:
            out.append(hit[0])
            i = hit[1]
        else:
            out.append(seq[i])
            i += 1
    return out


def subsumes(ot, cand_tokens):
    """外人词集 ot 是否包含候选形态的全部词（多字词须在场，单字母须有词以它开头）。"""
    ot = Counter(ot) if not isinstance(ot, Counter) else ot
    for w in cand_tokens:
        if len(w) == 1:
            if not any(t.startswith(w) for t in ot):
                return False
        elif ot[w] < 1:
            return False
    return True


def build_signature_book(real_items, prof_romaji_variants, overrides=None):
    """从教授分类下全部条目的全部 creators 攒「署名簿」。
    种子 = 规则①②③能确认是他本人的署名；候选变体 = 与种子同源（共享全名词）的缩略形态；
    分类里若存在共享某个词但无法解释为变体的其他作者，该组变体全部降级存疑。
    overrides: 人工确认过的形态（排序词元组列表）——无条件并入自动变体。
    返回 {"books": [...], "seed_count": int} 或 None（无罗马字材料）。"""
    ovr = {tuple(sorted(o)) for o in (overrides or [])}
    pcs = []
    for rv in prof_romaji_variants or []:
        pc = Counter(romaji_tokens(rv))
        if sum(pc.values()) >= 2 and pc not in pcs:
            pcs.append(pc)
    if not pcs:
        return None

    entries = []
    for it in real_items:
        for c in it["data"].get("creators", []) or []:
            tl = romaji_tokens((c.get("lastName") or "") + " " + (c.get("firstName") or ""))
            if tl:
                entries.append((tl, creator_raw(c)))

    books, seed_count = [], 0
    for pc in pcs:
        pc_words = set(pc.elements())
        cands, offenders, typos, mashes = {}, set(), set(), set()
        book_seeds = 0
        for tl, raw in entries:
            tc = Counter(hyphen_merge(tl, pc_words))
            kind = explain_variant(tc, pc)
            if kind == "seed":
                seed_count += 1
                book_seeds += 1
            elif kind in ("abbr", "typo"):
                key = (kind, tuple(sorted(tc.elements())))
                e = cands.setdefault(key, {"kind": kind, "count": 0, "example": raw,
                                           "given": given_letters(tc, pc)})
                e["count"] += 1
            elif kind == "mash":
                mashes.add(raw)   # 含教授全名的脏拼接: 中性证据
            elif set(tl) <= pc_words:
                mashes.add(raw)   # 名字自重复的垃圾格: 中性
            elif sum((tc & pc).values()) >= 1:
                offenders.add(raw)
        # 逐候选判冲突:
        #  given 非空 → 异人 given 相撞才拦
        #  纯子集(裸姓/缺词) → 只有「外人包含候选全部词」才算真撞车
        auto, conflicted = {}, {}
        for k, e in cands.items():
            blocked = False
            if not e["given"]:
                blocked = any(subsumes(romaji_tokens(o), k[1]) for o in offenders)
            else:
                for o in offenders:
                    if e["given"] & given_letters(romaji_tokens(o), pc):
                        blocked = True
                        break
            (auto if not blocked else conflicted)[k] = e
        if conflicted:
            reason = "同分类存在同词但无法解释的作者: " + "; ".join(sorted(offenders)[:3])                 if offenders else "形态出现次数不足且无 given 可区分"
            for e in conflicted.values():
                e.setdefault("reason", reason)
        for k in [k for k in conflicted if k[1] in ovr]:
            e = conflicted.pop(k)
            e["confirmed_by"] = "人工确认"
            auto[k] = e
        books.append({"pc": pc, "auto": auto, "conflicted": conflicted,
                      "offenders": sorted(offenders), "typos": sorted(typos),
                      "mashes": sorted(mashes), "seed_count": book_seeds})
    return {"books": books, "seed_count": seed_count}


def sigbook_lookup(sigbook, a_tokens):
    """第一/末位作者词集查署名簿。返回 (verdict, reason) 或 None（未命中任何变体）。"""
    if not sigbook:
        return None
    for book in sigbook["books"]:
        tc = Counter(hyphen_merge(a_tokens, set(book["pc"].elements())))
        kind = explain_variant(tc, book["pc"])
        if kind == "seed":
            continue   # 规则③已处理
        if kind in ("abbr", "typo"):
            key = (kind, tuple(sorted(tc.elements())))
            if key in book["auto"]:
                e = book["auto"][key]
                tag = "笔误形" if kind == "typo" else "变体"
                return "auto", f"规则⑦ 署名簿{tag}({e['example']} ×{e['count']})"
            if key in book["conflicted"]:
                e = book["conflicted"][key]
                return "pending", f"规则⑦存疑 {e['example']}（{e.get('reason', '无法区分')}）"
    return None


def sigbook_serialize(sigbook):
    """转成可落盘的纯 JSON 结构。"""
    if not sigbook:
        return None
    out_books = []
    for b in sigbook["books"]:
        toks = sorted(b["pc"].elements())
        out_books.append({
            "prof_name_tokens": toks,
            "seed_count": b.get("seed_count", 0),
            "auto": [{"kind": e["kind"], "example": e["example"], "count": e["count"]}
                     for _, e in sorted(b["auto"].items(), key=lambda kv: -kv[1]["count"])],
            "conflicted": [{"kind": e["kind"], "example": e["example"],
                            "count": e["count"], "reason": e.get("reason", "")}
                           for _, e in sorted(b["conflicted"].items(), key=lambda kv: -kv[1]["count"])],
            "offenders": b["offenders"],
            "typos": b["typos"],
            "mashes": b.get("mashes", []),
        })
    return {"books": out_books, "seed_count": sigbook["seed_count"]}


def judge_author(creator, prof_kanji_norms, prof_kanji_varnorms,
                 prof_romaji_variants, sigbook=None):
    """姓名比对（位置无关，一作/通讯共用）。返回 (verdict, reason)。verdict: auto / pending / no"""
    last = creator.get("lastName") or ""
    first = creator.get("firstName") or ""

    # 规则①②: 汉字（任意文字）精确全同
    forms = {norm_kanji(last + first), norm_kanji(last)}
    if forms & prof_kanji_norms:
        return "auto", "规则① 汉字全同"
    vforms = {norm_variant(last + first), norm_variant(last)}
    if vforms & prof_kanji_varnorms:
        return "auto", "规则② 异体字归一后全同"

    # 规则③: 罗马字全名，姓前姓后均可（词序无关多重集相等）
    a_tokens = romaji_tokens(last) + romaji_tokens(first)
    if prof_romaji_variants:
        for rv in prof_romaji_variants:
            p_tokens = romaji_tokens(rv)
            if len(p_tokens) >= 2 and len(a_tokens) == len(p_tokens) \
                    and Counter(a_tokens) == Counter(p_tokens):
                return "auto", f"规则③ 罗马字全名({' '.join(a_tokens)})"

    # 规则⑦: 署名簿变体（种子全名确认过 + 分类内无冲突 → 自动；有冲突 → 存疑 pending）
    hit = sigbook_lookup(sigbook, a_tokens)
    if hit:
        return hit

    if prof_romaji_variants:
        # 规则④: 姓氏全拼 + 名首字母（进待确认，不自动打）
        for rv in prof_romaji_variants:
            p_tokens = romaji_tokens(rv)
            if len(p_tokens) < 2:
                continue
            pairs = {(p_tokens[0], p_tokens[1]),
                     (p_tokens[-1], p_tokens[0])}
            if len(p_tokens) > 2:
                pairs.add((p_tokens[0], p_tokens[-1]))  # 越南式: 姓=首词, 名=末词
            for surname, given in pairs:
                if len(a_tokens) == 2:
                    t0, t1 = a_tokens
                    if t1 == surname and len(t0) == 1 and t0 == given[0]:
                        return "pending", f"规则④ 姓 {t1} + 名首字母 {t0}. ↔ {rv}"
                    if t0 == surname and len(t1) == 1 and t1 == given[0]:
                        return "pending", f"规则④ 姓 {t0} + 名首字母 {t1}. ↔ {rv}"
         # 规则⑥: 罗马字全名 + 恰好多出一个单字母缩写 → 待确认
        for rv in prof_romaji_variants:
            p_tokens = romaji_tokens(rv)
            if len(p_tokens) >= 2 and len(a_tokens) == len(p_tokens) + 1:
                extra = Counter(a_tokens) - Counter(p_tokens)
                if sum(extra.values()) == 1:
                    (tok, _), = extra.items()
                    if len(tok) == 1:
                        return "pending", f"规则⑥ 全名+首字母 {' '.join(a_tokens)} ↔ {rv}"

    # 规则⑤: 汉字姓名姓/名顺序颠倒（轮转同形）→ 自动
    # (误判需要「别人全名恰是教授名倒序且出现在教授本人分类里」，实际不可能)
    for form in vforms:
        for pv in prof_kanji_varnorms:
            if len(form) >= 3 and len(form) == len(pv):
                for k in range(1, len(pv)):
                    if form == pv[k:] + pv[:k]:
                        return "auto", f"规则⑤ 姓名顺序颠倒 {form} ↔ {pv}"
    return "no", ""


def alphabetical_suspicion(authors):
    """≥4 位作者且姓氏（罗马字）全部非降序 → 疑似按字母排序论文，通讯标签存疑。
    返回姓氏列表；不满足返回 None。汉字姓氏无法比对，直接放过。"""
    if len(authors) < 4:
        return None
    surnames = []
    for c in authors:
        ln = strip_accents(_nfkc(c.get("lastName") or "")).strip().lower()
        if not ln or not re.fullmatch(r"[a-z][a-z\-' ]*", ln):
            return None
        surnames.append(ln)
    if all(surnames[i] <= surnames[i + 1] for i in range(len(surnames) - 1)):
        return surnames
    return None


# ---------------------------------------------------------------- zotero read

_FETCH_CACHE = {}


def fetch_collection_items(key):
    """拉一个分类的全部条目（含子分类条目，已按 key 去重——本地 API 实测语义）。带缓存。"""
    if key in _FETCH_CACHE:
        return _FETCH_CACHE[key]
    items, start, page = {}, 0, 0
    while True:
        url = f"{READ_BASE}/api/users/0/collections/{key}/items?format=json&limit=100&start={start}"
        with urllib.request.urlopen(url, timeout=60) as r:
            total = int(r.headers.get("Total-Results", "0"))
            batch = json.load(r)
        for it in batch:
            items[it["key"]] = it
        start += len(batch)
        page += 1
        if not batch or start >= total or page > 200:
            break
    _FETCH_CACHE[key] = items
    return items


def get_subcollections(mcp, key):
    try:
        subs = mcp.call("get_subcollections", {"collectionKey": key, "recursive": True})
        if isinstance(subs, list):
            return [s["key"] for s in subs if isinstance(s, dict) and s.get("key")]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------- core per-professor

def process_professor(mcp, prog_root, prof_name, paths, mapping, univ_tag,
                      live_tags, dry_run, stats, overrides=None, corresp=None):
    leaf = paths[0].rstrip("/").split("/")[-1]
    labs = []
    for p in paths:
        seg = p.rstrip("/").split("/")
        if len(seg) >= 2:
            lab = seg[-2]
            if lab and lab not in labs:
                labs.append(lab)
    lab_str = "、".join(labs)

    coll_keys = []
    for p in paths:
        k = mapping.get("collections", {}).get(p, {}).get("key")
        if k and k not in coll_keys:
            coll_keys.append(k)
    if not coll_keys:
        stats["errors"].append(f"[{prof_name}] 映射里拿不到分类 key: {paths}")
        return None

    # 拉条目: 主分类 + 子分类并集兜底（fetch 带缓存，跨教授共享）
    _t = time.time()
    items = {}
    for k in coll_keys:
        for ik, it in fetch_collection_items(k).items():
            items.setdefault(ik, it)
        for sk in get_subcollections(mcp, k):
            for aik, ait in fetch_collection_items(sk).items():
                items.setdefault(aik, ait)
    t_fetch = time.time() - _t
    real = {k: v for k, v in items.items()
            if v["data"]["itemType"] not in SKIP_ITEM_TYPES}
    for ik, it in real.items():
        if ik not in live_tags:
            live_tags[ik] = {t.get("tag") for t in it["data"].get("tags", []) if t.get("tag")}

    # 教授姓名材料
    prof_kanji_norms = {norm_kanji(leaf), norm_kanji(prof_name)} - {""}
    prof_kanji_varnorms = {norm_variant(leaf), norm_variant(prof_name)} - {""}
    romaji = None
    pj = load_papers_json(prog_root, paths, leaf)
    if pj:
        romaji = pj.get("professor", {}).get("name_romaji")
        pname = pj.get("professor", {}).get("name")
        if pname:
            prof_kanji_norms.add(norm_kanji(pname))
            prof_kanji_varnorms.add(norm_variant(pname))
    romaji_vars = romaji_variants(romaji)

    # 署名簿：从他分类里全部 creators 攒种子 → 长缩略变体（无冲突才自动用；人工确认的 overrides 直接放行）
    _t = time.time()
    sigbook = build_signature_book(list(real.values()), romaji_vars, (overrides or {}).get(prof_name))
    t_sig = time.time() - _t

    first_author_items, non_first = [], []
    pending_first, pending_corr = [], []
    corr_items, alpha_suspect = [], []
    corr_explicit, divergences = [], []
    explicit_overridden = explicit_ambiguous = 0
    channels = Counter()
    seven_first = seven_corr = 0
    timings = [0.0]  # 写入耗时累计
    _tloop = time.time()
    for ikey in sorted(real):
        it = real[ikey]
        d = it["data"]
        title = (d.get("title") or "").strip() or "（无标题）"
        existing = set(live_tags.get(ikey, ()))
        want = {univ_tag, leaf}

        authors = [c for c in (d.get("creators") or [])
                   if c.get("creatorType") == "author"]

        # 一作判定（首位 author）
        verdict, reason = judge_author(authors[0], prof_kanji_norms,
                                       prof_kanji_varnorms, romaji_vars,
                                       sigbook) \
            if authors else ("no", "无 author creator")
        if verdict == "auto":
            want.add("一作")
            first_author_items.append((ikey, title))
            if reason.startswith("规则⑦"):
                seven_first += 1
        elif verdict == "pending":
            fa_str = f"{authors[0].get('lastName', '')}, {authors[0].get('firstName', '')}"
            pending_first.append((ikey, title, fa_str, reason))
        else:
            non_first.append((ikey, title))

        # ---- 通讯作者判定: 显式记录优先，末位启发式兜底 ----
        rec = (corresp or {}).get(ikey) or {}
        rec_channel = rec.get("channel") or ""
        rec_names = [n for n in (rec.get("names") or []) if n]
        rec_active = bool(rec) and rec_channel != "none"
        ehits = email_hits_prof(rec.get("emails"), romaji_vars) if rec_active else []

        def _heuristic_corr():
            """末位 author 命中即打（含字母排序存疑标注）。"""
            nonlocal seven_corr
            if len(authors) < 2:
                return
            cverdict, creason = judge_author(authors[-1], prof_kanji_norms,
                                             prof_kanji_varnorms, romaji_vars,
                                             sigbook)
            if cverdict == "auto":
                want.add("通讯作者")
                corr_items.append((ikey, title))
                if creason.startswith("规则⑦"):
                    seven_corr += 1
                sus = alphabetical_suspicion(authors)
                if sus:
                    alpha_suspect.append((ikey, title, sus))
            elif cverdict == "pending":
                la_str = f"{authors[-1].get('lastName', '')}, {authors[-1].get('firstName', '')}"
                pending_corr.append((ikey, title, la_str, creason))

        if rec_active and (rec_names or ehits):
            if rec_names:
                verdicts = [judge_author(name_str_to_creator(n), prof_kanji_norms,
                                         prof_kanji_varnorms, romaji_vars, sigbook)
                            for n in rec_names]
                autos = [x for x in verdicts if x[0] == "auto"]
                pends = [x for x in verdicts if x[0] == "pending"]
            else:
                autos, pends = [], []
            channels[rec_channel] += 1
            if autos or ehits:
                # 显式记录命中教授（名字或脚注邮箱）→ 打，不限作者位置；字母排序存疑自动销案
                want.add("通讯作者")
                corr_items.append((ikey, title))
                reason = (f"规则⑧ 邮箱命中 {('; '.join(ehits))[:60]}" if ehits and not autos
                          else "名字命中")
                corr_explicit.append((ikey, title, dict(rec, _reason=reason)))
            elif pends:
                # 名字模糊命中 → 回落末位启发式 + 待确认（显式记录未解决）
                explicit_ambiguous += 1
                _heuristic_corr()
                pending_corr.append((ikey, title, "; ".join(rec_names),
                                     "显式记录名字待比对: " + "; ".join(p for _, p in pends)))
            else:
                # 全部 "no": 显式记录指向别人 → 不打（推翻末位启发式）
                explicit_overridden += 1
                if "通讯作者" in existing:
                    divergences.append((ikey, title,
                                        rec.get("raw_text") or "; ".join(rec_names)))
        elif len(authors) >= 2 and rec_active and not rec_names and not ehits:
            # 显式记录只有邮箱没名字（且邮箱也不命中）→ 回落启发式 + 待确认
            explicit_ambiguous += 1
            _heuristic_corr()
            pending_corr.append((ikey, title,
                                 (rec.get("raw_text") or "")[:60],
                                 f"显式记录({rec_channel})只有邮箱/无名字"))
        else:
            _heuristic_corr()

        missing = sorted(want - existing)
        _t = time.time()
        if missing:
            if dry_run:
                after = existing | want
            else:
                try:
                    resp = mcp.call("write_tag", {"action": "add", "itemKey": ikey,
                                                  "tags": missing})
                    after_tags = ((resp.get("data") or {}).get("afterTags")) if isinstance(resp, dict) else None
                except Exception as e:
                    stats["errors"].append(f"[{prof_name}] 写入失败 {ikey}: {e}")
                    continue
                after = set(after_tags) if after_tags is not None else (existing | want)
                time.sleep(0.02)
            live_tags[ikey] = after
            stats["written"] += len(missing)
            stats["skipped"] += len(want & existing)
        else:
            stats["skipped"] += len(want)
        t_write = time.time() - _t
        timings[0] += t_write

    # papers.json 差异
    t_judge = (time.time() - _tloop) - timings[0]
    diff = []
    if pj:
        lib_keys = set(real)
        for p in pj.get("papers", []):
            k = p.get("item_key")
            if not k or k not in lib_keys:
                diff.append((p.get("title") or "（无标题）",
                             p.get("zotero_status") or "?", k or "-"))

    all_tagged = all(univ_tag in live_tags.get(k, set()) and leaf in live_tags.get(k, set())
                     for k in real)
    sb_ser = sigbook_serialize(sigbook)
    if sb_ser:
        sb_ser["rule7_first"] = seven_first
        sb_ser["rule7_corr"] = seven_corr
    return {
        "prof": prof_name, "lab": lab_str, "leaf": leaf,
        "total": len(real),
        "first_author_items": first_author_items,
        "non_first": non_first,
        "corr_items": corr_items,
        "corr_explicit": corr_explicit,
        "explicit_overridden": explicit_overridden,
        "explicit_ambiguous": explicit_ambiguous,
        "channels": channels,
        "divergences": divergences,
        "alpha_suspect": alpha_suspect,
        "pending_first": pending_first,
        "pending_corr": pending_corr,
        "diff": diff,
        "romaji_missing": bool(pj) and not romaji_vars,
        "no_papers_json": pj is None,
        "all_tagged": all_tagged,
        "sigbook": sb_ser,
        "t_fetch": t_fetch, "t_sig": t_sig, "t_judge": t_judge, "t_write": timings[0],
    }


def load_papers_json(prog_root, paths, leaf):
    """教授研究/<lab>/<prof>/papers.json（按该教授全部分类路径的 lab 逐个试）；找不到返回 None。
    顶层 list 会归一成 {"professor": {}, "papers": [...]}。"""
    base = Path(prog_root) / "教授研究"
    candidates = []
    for p in paths:
        seg = p.rstrip("/").split("/")
        if len(seg) >= 2:
            candidates.append(base / seg[-2] / leaf / "papers.json")
    candidates += list(base.glob(f"*/{leaf}/papers.json"))
    candidates += list(base.glob(f"{leaf}/papers.json"))
    for f in candidates:
        if not f.is_file():
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, list):
            return {"professor": {}, "papers": d}
        if isinstance(d, dict):
            return d
    return None


# ---------------------------------------------------------------- report

def render_report(prog_root, univ_tag, results, stats, dry_run, ts):
    lines = [
        f"# 论文标签报告 — {prog_root.name}",
        "",
        f"- 运行时间: {ts}",
        f"- 模式: {'dry-run（未写入 Zotero）' if dry_run else '写入'}",
        f"- 大学标签: `{univ_tag}`",
        "",
    ]
    for r in results:
        lines.append(f"## {r['prof']}（{r['lab'] or '（无中间层）'}）")
        lines.append("")
        tagged_word = "全部带标签" if r["all_tagged"] else "部分条目写入失败"
        lines.append(f"- 条目 {r['total']} 篇，{tagged_word}：{univ_tag}、{r['leaf']}")
        lines.append(f"- 一作 {len(r['first_author_items'])} 篇：")
        for k, t in r["first_author_items"]:
            lines.append(f"  - 《{t}》 zotero://select/library/items/{k}")
        lines.append(f"- 通讯作者 {len(r['corr_items'])} 篇：")
        for k, t in r["corr_items"]:
            lines.append(f"  - 《{t}》 zotero://select/library/items/{k}")
        if r["corr_explicit"] or r["explicit_overridden"] or r["explicit_ambiguous"]:
            ch = "、".join(f"{c}×{n}" for c, n in r["channels"].most_common()) or "-"
            lines.append(f"- 显式通讯记录: 命中 {len(r['corr_explicit'])}"
                         f" / 推翻末位 {r['explicit_overridden']}"
                         f" / 模糊回落 {r['explicit_ambiguous']}（渠道: {ch}）")
            for k, t, rec in r["corr_explicit"]:
                nm = "; ".join(rec.get("names") or []) or "(仅邮箱)"
                lines.append(f"  - [{k}] 《{t}》记录: `{(rec.get('raw_text') or '')[:80]}`"
                             f" → {nm}（{rec.get('_reason', '名字命中')}）")
        if r["divergences"]:
            lines.append(f"- 分歧清单（显式记录 vs 已打「通讯作者」标签结论相反；"
                         f"确认后 remove-tags 删除）{len(r['divergences'])} 篇：")
            for k, t, raw in r["divergences"]:
                lines.append(f"  - [{k}] 《{t}》记录: `{raw[:80]}` → 补删: remove-tags {k} 通讯作者")
        lines.append(f"- 非一作 {len(r['non_first'])} 篇")
        sb = r.get("sigbook")
        if sb:
            n_auto = sum(len(b["auto"]) for b in sb["books"])
            n_conf = sum(len(b["conflicted"]) for b in sb["books"])
            lines.append(f"- 署名簿: 种子 {sb['seed_count']} 处；自动变体 {n_auto} 个"
                         f"（规则⑦命中: 一作 {sb.get('rule7_first', 0)} / 通讯 {sb.get('rule7_corr', 0)}）；"
                         f"存疑变体 {n_conf} 个")
            for b in sb["books"]:
                for e in b["conflicted"]:
                    lines.append(f"  - 存疑 `{e['example']}`（{e['kind']} ×{e['count']}）— {e['reason']}")
        if r["alpha_suspect"]:
            lines.append(f"- 疑似字母排序（通讯标签存疑，建议抽查）{len(r['alpha_suspect'])} 篇：")
            for k, t, sus in r["alpha_suspect"]:
                lines.append(f"  - [{k}] 《{t}》姓氏 {' → '.join(sus)}")
        lines.append(f"- 待人工确认（一作）{len(r['pending_first'])} 篇：")
        for k, t, fa, why in r["pending_first"]:
            lines.append(f"  - [{k}] 《{t}》首位作者 `{fa}`（{why}）→ 补打: add-tags {k} 一作")
        lines.append(f"- 待人工确认（通讯）{len(r['pending_corr'])} 篇：")
        for k, t, la, why in r["pending_corr"]:
            lines.append(f"  - [{k}] 《{t}》末位作者 `{la}`（{why}）→ 补打: add-tags {k} 通讯作者")
        lines.append(f"- papers.json 记了但库里没有 {len(r['diff'])} 篇：")
        for t, st, k in r["diff"]:
            lines.append(f"  - 《{t}》（{st}, item_key: {k}）")
        if r["romaji_missing"]:
            lines.append("- 注意: papers.json 无 name_romaji，规则③④不可用（只用了①②）")
        if r["no_papers_json"]:
            lines.append("- 注意: 未找到 papers.json，罗马字判定不可用")
        lines.append("")
    lines += [
        "## 汇总",
        "",
        f"- 新写标签 {stats['written']} 处；跳过（已带）{stats['skipped']} 处",
        f"- 一作共 {sum(len(r['first_author_items']) for r in results)} 篇；"
        f"通讯作者共 {sum(len(r['corr_items']) for r in results)} 篇"
        f"（其中显式记录确证 {sum(len(r['corr_explicit']) for r in results)} 篇）；"
        f"显式推翻末位 {sum(r['explicit_overridden'] for r in results)} 处；"
        f"疑似字母排序 {sum(len(r['alpha_suspect']) for r in results)} 篇；"
        f"待人工确认 {sum(len(r['pending_first']) + len(r['pending_corr']) for r in results)} 篇；"
        f"分歧 {sum(len(r['divergences']) for r in results)} 篇；"
        f"差异共 {sum(len(r['diff']) for r in results)} 篇",
    ]
    if stats["errors"]:
        lines.append(f"- 错误 {len(stats['errors'])} 条：")
        for e in stats["errors"]:
            lines.append(f"  - {e}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- program roots

def process_program_root(mcp, prog_root, dry_run, only_prof):
    mapping_path = prog_root / "教授研究" / MAPPING_NAME
    if not mapping_path.is_file():
        out(f"[skip] {prog_root.name}: 无 {MAPPING_NAME}")
        return None
    mapping = json.load(open(mapping_path, encoding="utf-8"))
    univ_tag = mapping.get("university")
    professors = mapping.get("professors") or {}
    if not univ_tag or not professors:
        out(f"[skip] {prog_root.name}: 映射缺 university/professors")
        return None

    # 读已有 _署名对照.json 里的人工确认 overrides（写回时原样保留）
    overrides = {}
    sig_file = prog_root / "教授研究" / SIGNATURE_NAME
    if sig_file.is_file():
        try:
            overrides = json.load(open(sig_file, encoding="utf-8")).get("overrides") or {}
        except Exception:
            overrides = {}

    stats = {"written": 0, "skipped": 0, "errors": []}
    corresp = load_corresp_cache(prog_root)
    if corresp:
        n_active = sum(1 for v in corresp.values() if (v.get("channel") or "none") != "none")
        out(f"  显式通讯记录: {n_active}/{len(corresp)} 条（_corresp_cache.json）")
    else:
        out("  无 _corresp_cache.json → 通讯判定全部走末位启发式")
    results = []
    live_tags = {}
    names = sorted(professors)
    if only_prof:
        names = [n for n in names if n == only_prof]
        if not names:
            out(f"[error] 映射里没有教授: {only_prof}")
            return None
    for i, name in enumerate(names, 1):
        paths = professors[name]
        out(f"  [{i}/{len(names)}] {name} 处理中…")
        _tp = time.time()
        try:
            r = process_professor(mcp, prog_root, name, paths, mapping, univ_tag,
                                  live_tags, dry_run, stats, overrides, corresp)
        except Exception as e:
            stats["errors"].append(f"[{name}] 处理失败: {e}")
            r = None
        if r:
            results.append(r)
            out(f"      条目 {r['total']} 一作 {len(r['first_author_items'])} "
                f"通讯 {len(r['corr_items'])}（显式 {len(r['corr_explicit'])}/推翻 {r['explicit_overridden']}"
                f"/模糊 {r['explicit_ambiguous']}）待确认 "
                f"{len(r['pending_first']) + len(r['pending_corr'])} 分歧 {len(r['divergences'])} "
                f"差异 {len(r['diff'])} | {time.time()-_tp:.1f}s"
                f"（拉 {r['t_fetch']:.1f} 簿 {r['t_sig']:.1f}"
                f" 判 {r['t_judge']:.1f} 写 {r['t_write']:.1f}）")

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    report_path = None
    sigbook_path = None
    if not only_prof:  # 试跑单教授时不覆写完整报告
        report = render_report(prog_root, univ_tag, results, stats, dry_run, ts)
        report_path = prog_root / "教授研究" / REPORT_NAME
        report_path.write_text(report, encoding="utf-8")
        sigbooks = {r["prof"]: r["sigbook"] for r in results if r.get("sigbook")}
        if sigbooks:
            sigbook_path = prog_root / "教授研究" / SIGNATURE_NAME
            sigbook_path.write_text(json.dumps(
                {"updated_at": ts, "overrides": overrides, "professors": sigbooks},
                ensure_ascii=False, indent=1), encoding="utf-8")

    out(f"[done] {prog_root.name}: 教授 {len(results)} 新写 {stats['written']} "
        f"跳过 {stats['skipped']} 待确认 "
        f"{sum(len(r['pending_first']) + len(r['pending_corr']) for r in results)} 差异 "
        f"{sum(len(r['diff']) for r in results)}")
    if report_path:
        out(f"  报告: {report_path}")
    return {"results": results, "stats": stats, "report": report_path}


def print_pending(all_pending):
    if not all_pending:
        out("\n待人工确认清单: （空）")
        return
    out("\n待人工确认清单（规则④⑤⑥命中，回复编号后按提示用 add-tags 补打）:")
    for i, (prog, prof, k, t, author, why, tag) in enumerate(all_pending, 1):
        out(f"  {i}. [{prog} / {prof}] {k} 《{t}》`{author}`（{why}）→ add-tags {k} {tag}")


def print_divergences(all_div):
    """显式记录 vs 已打标签结论相反的条目。删除是显式动作，等用户确认后逐条执行。"""
    if not all_div:
        return
    out("\n分歧清单（显式通讯记录指向别人，旧「通讯作者」标签待删；"
        "确认后执行 remove-tags）:")
    for i, (prog, prof, k, t, raw) in enumerate(all_div, 1):
        out(f"  {i}. [{prog} / {prof}] {k} 《{t}》\n     记录: `{raw[:90]}`\n"
            f"     → remove-tags {k} 通讯作者")


# ---------------------------------------------------------------- main

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]

    if argv and argv[0] in ("add-tags", "remove-tags"):
        action = "add" if argv[0] == "add-tags" else "remove"
        if len(argv) < 3:
            out(f"用法: tagger.py {argv[0]} <itemKey> <tag> [<tag>...]")
            sys.exit(1)
        item_key, tags = argv[1], argv[2:]
        if not check_read_api():
            out("错误: Zotero 没开（23119 不通）。请打开 Zotero 后重试。")
            sys.exit(1)
        mcp = Mcp()
        try:
            mcp.connect()
        except Exception as e:
            out(f"错误: 23120 zotero-mcp 插件不通（{e}）。请确认 Zotero 已开且插件启用。")
            sys.exit(1)
        resp = mcp.call("write_tag", {"action": action, "itemKey": item_key, "tags": tags})
        out(json.dumps(resp, ensure_ascii=False, indent=2))
        return

    ap = argparse.ArgumentParser(description="zotero-paper-tagger")
    ap.add_argument("program_root", nargs="?", help="boshu_output/<学校__専攻> 程序根；缺省=全库")
    ap.add_argument("--boshu-root", default="boshu_output", help="全库模式根目录（默认 ./boshu_output）")
    ap.add_argument("--professor", default=None, help="只处理指定教授")
    ap.add_argument("--dry-run", action="store_true", help="算标签写报告，不写 Zotero")
    args = ap.parse_args(argv)

    if not check_read_api():
        out("错误: 23119 不通，Zotero 没开。请打开 Zotero 后重试。")
        sys.exit(1)
    mcp = Mcp()
    try:
        mcp.connect()
    except Exception as e:
        out(f"错误: 23120 zotero-mcp 插件不通（{e}）。请确认 Zotero 已开且插件启用。")
        sys.exit(1)

    if args.program_root:
        roots = [Path(args.program_root)]
        if not roots[0].is_dir():
            out(f"错误: 程序根不存在: {args.program_root}")
            sys.exit(1)
    else:
        broot = Path(args.boshu_root)
        if not broot.is_dir():
            out(f"错误: boshu 根目录不存在: {args.boshu_root}")
            sys.exit(1)
        roots = sorted(d for d in broot.iterdir()
                       if d.is_dir() and not d.name.startswith("_")
                       and (d / "教授研究" / MAPPING_NAME).is_file())
        if not roots:
            out(f"错误: {args.boshu_root} 下没有含 {MAPPING_NAME} 的程序根")
            sys.exit(1)
        out(f"全库模式: {len(roots)} 个程序根")

    all_pending = []
    all_div = []
    grand = {"written": 0, "skipped": 0}
    for root in roots:
        out(f"== {root.name} ==")
        res = process_program_root(mcp, root, args.dry_run, args.professor)
        if not res:
            continue
        grand["written"] += res["stats"]["written"]
        grand["skipped"] += res["stats"]["skipped"]
        for r in res["results"]:
            for k, t, fa, why in r["pending_first"]:
                all_pending.append((root.name, r["prof"], k, t, fa, why, "一作"))
            for k, t, la, why in r["pending_corr"]:
                all_pending.append((root.name, r["prof"], k, t, la, why, "通讯作者"))
            for k, t, raw in r["divergences"]:
                all_div.append((root.name, r["prof"], k, t, raw))

    out(f"\n总计: 新写标签 {grand['written']} 处, 跳过 {grand['skipped']} 处"
        + ("（dry-run，未实际写入）" if args.dry_run else ""))
    print_pending(all_pending)
    print_divergences(all_div)


if __name__ == "__main__":
    main()
