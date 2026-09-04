#!/usr/bin/env python3
"""corresp_backfill: 给程序根下全部论文条目回填通讯作者显式记录 → _corresp_cache.json。

用法:
  corresp_backfill.py <program_root> [--dry-run] [--refresh] [--limit N] [--professor NAME]
  corresp_backfill.py --boshu-root DIR [--dry-run] [--refresh]     # 全库

渠道顺序（命中即停）:
  A pdf_footnote   库内 PDF 第一页脚注（零网络；附件路径按 Zotero storage 约定拼）
  B springer_curl  DOI 解析后是 Springer/Nature 系落地页 → #corresponding-author-list
  B2 crossref_api  Crossref REST role 字段
全无 → 落 channel="none" 否定记录，重跑跳过；--refresh 重抓。
每条新记录保留 itemKey / DOI / paper_year / channel，并保留旧 names[] / emails[]
兼容字段；contacts[] 仅由 extractor 在来源结构证明 name/email 关系时写入。
网络渠道串行限速约 1 req/s。本脚本只抓取与落盘，姓名比对归 tagger。
"""

import argparse
import concurrent.futures as cf
import json
import threading
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corresp_extractor as E  # noqa: E402
import tagger as T  # noqa: E402

CACHE_NAME = "_corresp_cache.json"
RATE = 1.0


def out(s=""):
    print(s, flush=True)


def load_cache(prog_root):
    p = prog_root / "教授研究" / CACHE_NAME
    if p.is_file():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            out(f"[warn] cache 损坏，重建: {p}")
    return {}


def save_cache(prog_root, cache):
    p = prog_root / "教授研究" / CACHE_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


RE_DOI_IN_URL = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
RE_DOI_FIELD = re.compile(r"^10\.\d{4,9}/\S+")
RE_YEAR = re.compile(r"(?<!\d)(?:18|19|20|21)\d{2}(?!\d)")


# --------------------------------------------------------------------------- #
# Record classification: distinguishes three kinds of cache records.
#
#   modern_verified  — carries schema marker AND has at least one contact pair.
#   modern_negative  — carries schema marker, contacts=[], but was evaluated
#                      under the verified-pair contract (valid skip).
#   legacy           — no schema marker; independent names[]/emails[] predate
#                      verified pairing and may need re-evaluation.
#
# The critical invariant: legacy records with a non-empty channel are NOT
# silently treated as equivalent to modern records. Downstream reconciliation
# can then tell "verified no pair" from "never evaluated under the contract".
# --------------------------------------------------------------------------- #

def is_modern_record(rec):
    """True when the record was produced under the verified-pair contract.

    A modern record carries the schema marker.  It may be a verified hit
    (contacts non-empty) or a modern negative (contacts empty but checked).
    """
    return isinstance(rec, dict) and rec.get("schema") == E.SCHEMA_VERSION


def is_legacy_record(rec):
    """True when the record predates the verified-pair contract.

    Legacy records have independent names[]/emails[] arrays without a schema
    marker.  They may look positive (non-empty channel) but cannot be trusted
    as verified pairs.
    """
    if not isinstance(rec, dict):
        return False
    return "schema" not in rec


def classify_record(rec):
    """Return one of 'modern_verified', 'modern_negative', 'legacy'."""
    if not isinstance(rec, dict):
        return "legacy"
    if is_modern_record(rec):
        if rec.get("contacts"):
            return "modern_verified"
        return "modern_negative"
    return "legacy"


def is_cache_hit(rec):
    """True when the record is safe to skip during backfill.

    Only modern records (verified OR negative) are valid skip targets.
    Legacy records are never silently skipped — they may carry stale
    independent arrays that were never evaluated for verified pairing.
    """
    return is_modern_record(rec)


def item_doi(d):
    for field in ("DOI", "doi"):
        v = (d.get(field) or "").strip()
        if RE_DOI_FIELD.match(v):
            return v
    for u in [d.get("url") or "", d.get("archive") or ""]:
        m = RE_DOI_IN_URL.search(u)
        if m:
            return m.group(0).rstrip(".")
    return None


def item_year(d):
    """Best-effort publication year from Zotero publication metadata only."""
    for v in (d.get("year"), d.get("date")):
        m = RE_YEAR.search(str(v or ""))
        if m:
            return int(m.group(0))
    return None


def collect_items(mcp, prog_root, only_prof=None):
    mapping_path = prog_root / "教授研究" / T.MAPPING_NAME
    if not mapping_path.is_file():
        out(f"[skip] {prog_root.name}: 无 {T.MAPPING_NAME}")
        return None
    mapping = json.load(open(mapping_path, encoding="utf-8"))
    professors = mapping.get("professors") or {}
    names = sorted(professors)
    if only_prof:
        names = [n for n in names if n == only_prof]
        if not names:
            out(f"[error] 映射里没有教授: {only_prof}")
            return None

    keys = []
    for name in names:
        for p in professors[name]:
            k = mapping.get("collections", {}).get(p, {}).get("key")
            if k and k not in keys:
                keys.append(k)

    items = {}
    for k in keys:
        for ik, it in T.fetch_collection_items(k).items():
            items.setdefault(ik, it)
        for sk in T.get_subcollections(mcp, k):
            for aik, ait in T.fetch_collection_items(sk).items():
                items.setdefault(aik, ait)

    configured_storage_root = os.environ.get("ZOTERO_STORAGE_ROOT")
    storage_root = (Path(configured_storage_root) if configured_storage_root
                    else Path.home() / "Zotero" / "storage")
    real, pdf_of = {}, {}
    for ik, it in items.items():
        d = it["data"]
        if d["itemType"] == "attachment":
            pid = d.get("parentItem")
            ct = d.get("contentType") or ""
            fn = d.get("filename") or d.get("title") or ""
            if pid and ik not in pdf_of and (ct == "application/pdf" or fn.lower().endswith(".pdf")):
                pdf_of[pid] = storage_root / ik / fn
        elif d["itemType"] not in T.SKIP_ITEM_TYPES:
            real[ik] = it
    return real, pdf_of


def backfill_root(mcp, prog_root, dry_run=False, refresh=False, limit=None,
                  only_prof=None, workers=6, refresh_legacy=False):
    got = collect_items(mcp, prog_root, only_prof)
    if not got:
        return None
    real, pdf_of = got
    cache = {} if refresh else load_cache(prog_root)

    stats = {"hit_pdf_footnote": 0, "hit_springer_curl": 0, "hit_crossref_api": 0,
             "none": 0, "cached": 0, "no_source": 0, "errors": []}
    samples = []
    lock = threading.Lock()
    counters = {"processed": 0, "net": 0}

    def is_todo(k):
        old = cache.get(k)
        if refresh:
            return True
        # In refresh_legacy mode, only legacy records are re-evaluated.
        # Modern records (verified or negative) are preserved.
        if refresh_legacy:
            return is_legacy_record(old)
        # Default: legacy records always re-evaluate — they may carry stale
        # independent arrays that were never checked under the verified-pair
        # contract. Modern records are valid skip targets.
        return not is_cache_hit(old)

    todo = [k for k in sorted(real) if is_todo(k)]
    stats["cached"] = len(real) - len(todo)
    if limit:
        todo = todo[:limit]
    todo_a = [k for k in todo if (pdf_of.get(k) or Path("-")).is_file()]
    todo_net = [k for k in todo if k not in set(todo_a) and item_doi(real[k]["data"])]
    todo_none = [k for k in todo if k not in set(todo_a) and not item_doi(real[k]["data"])]
    out(f"条目总数 {len(real)} | 本次将处理 {len(todo)}"
        f"（A渠道 {len(todo_a)} + 网络 {len(todo_net)} + 无源 {len(todo_none)}）"
        + (f" | 并行 {workers} 线程" if workers > 1 else ""))

    def record(ikey, rec, via, outcome="verified_negative"):
        """Write a cache record for ikey.

        outcome distinguishes three cases:
          - "verified_negative": a channel was checked under the verified-pair
            contract and found no pair. Carries schema → becomes a cache hit.
          - "unavailable": no source available (no PDF, no DOI) or a channel
            failed (PDF parse error, network error). No schema → stays retryable.
          - "hit": rec is a non-None record with at least one name/email.
        """
        d = real[ikey]["data"]
        title = (d.get("title") or "").strip() or "（无标题）"
        provenance = {"itemKey": ikey, "doi": item_doi(d), "paper_year": item_year(d),
                      "title": title[:120]}
        with lock:
            if rec:
                cache[ikey] = dict(rec, **provenance)
                stats[f"hit_{rec['channel']}"] += 1
                if len(samples) < 12:
                    samples.append((ikey, rec["channel"], rec["confidence"],
                                    ", ".join(rec["names"][:3]) or "(仅邮箱)", title[:60]))
            elif outcome == "verified_negative":
                # Modern negative: a channel completed successfully but found no
                # verified pair. Carries schema so future runs skip it.
                cache[ikey] = {"schema": E.SCHEMA_VERSION, "contacts": [],
                               "channel": "none", "names": [], "emails": [],
                               "raw_text": "", "fetched_at": E._now(), **provenance}
                stats["none"] += 1
            else:
                # "unavailable": no source or channel failed. No schema marker →
                # stays retryable on the next backfill (not a verified negative).
                cache[ikey] = {"contacts": [], "channel": "none", "names": [],
                               "emails": [], "raw_text": "",
                               "fetched_at": E._now(), **provenance}
                if via == "none":
                    stats["no_source"] += 1
                else:
                    stats["none"] += 1
            counters["processed"] += 1
            n = counters["processed"]
            if n % 25 == 0 and not dry_run:
                save_cache(prog_root, cache)
            if n % 50 == 0 or n == len(todo):
                out(f"  …进度 {n}/{len(todo)}（A命中 {stats['hit_pdf_footnote']}"
                    f" B命中 {stats['hit_springer_curl'] + stats['hit_crossref_api']}）")

    def work_a(ikey):
        title = (real[ikey]["data"].get("title") or "")[:44]
        pdf = pdf_of.get(ikey)
        rec, outcome = None, "unavailable"
        try:
            rec = E.extract_from_pdf(pdf)
            outcome = "verified_negative"  # PDF parsed successfully, just no pair found
        except E.PdfUnavailable as e:
            # PDF had no extractable text (scan, empty, etc.) — NOT a verified
            # negative. Stay retryable so a future OCR or text-layer fix can
            # re-evaluate.
            with lock:
                stats["errors"].append(f"{ikey} PDF 无可分析文本: {type(e).__name__}")
            outcome = "unavailable"
        except Exception as e:
            with lock:
                stats["errors"].append(f"{ikey} PDF 解析失败: {type(e).__name__}")
            outcome = "unavailable"  # channel failed, stay retryable
        if rec:
            out(f"  [A] {ikey} 《{title}》→ {', '.join(rec['names'][:2]) or '(仅邮箱)'}")
        record(ikey, rec, "A", outcome)

    def work_net(ikey):
        title = (real[ikey]["data"].get("title") or "")[:44]
        doi = item_doi(real[ikey]["data"])
        rec, outcome = None, "unavailable"
        try:
            rec = E.extract_from_doi(doi)
            outcome = "verified_negative"  # all channels completed, no pair
        except Exception as e:
            with lock:
                stats["errors"].append(f"{ikey} DOI 网络失败: {type(e).__name__}")
            outcome = "unavailable"  # network failed, stay retryable
        if rec:
            out(f"  [net] {ikey} 《{title}》→ [{rec['channel']}] {', '.join(rec['names'][:2])}")
        record(ikey, rec, "net", outcome)

    for k in todo_none:
        # No PDF and no DOI: pair check was never performed, not a verified negative.
        record(k, None, "none", outcome="unavailable")

    t0 = time.time()
    if workers > 1:
        E.set_net_throttle(0.25)
        with cf.ThreadPoolExecutor(workers) as ex:
            list(ex.map(work_a, todo_a))
            if todo_net:
                out(f"—— A 渠道完成，进入网络阶段 {len(todo_net)} 条 ——")
            list(ex.map(work_net, todo_net))
    else:
        E.set_net_throttle(RATE)
        for k in todo_a:
            work_a(k)
        for k in todo_net:
            work_net(k)

    if not dry_run:
        save_cache(prog_root, cache)

    hits = sum(v for kk, v in stats.items() if kk.startswith("hit_"))
    out(f"\n[{prog_root.name}] 条目 {len(real)} | 本次处理 {len(todo)} | 缓存跳过 "
        f"{len(real) - len(todo)}"
        f" | 命中 A {stats['hit_pdf_footnote']} B {stats['hit_springer_curl']}"
        f" B2 {stats['hit_crossref_api']} | 无显式 {stats['none']}"
        f" + 无PDF无DOI {stats['no_source']} | 错误 {len(stats['errors'])}"
        f" | 耗时 {(time.time()-t0)/60:.1f}m")
    out(f"  显式覆盖率（本次新处理）: {hits}/{len(todo)}"
        + ("  [dry-run 未写盘]" if dry_run else ""))
    for s in samples:
        out(f"    [{s[1]}|{s[2]}] {s[0]} 《{s[4]}》→ {s[3]}")
    for e in stats["errors"][:8]:
        out(f"    [err] {e}")
    return {"stats": stats, "cache": cache}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:]
    ap = argparse.ArgumentParser(description="corresp_backfill")
    ap.add_argument("program_root", nargs="?", help="boshu_output/<学校__専攻> 程序根")
    ap.add_argument("--boshu-root", default="boshu_output")
    ap.add_argument("--professor", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="刷新全部缓存记录（含已验证的现代记录）")
    ap.add_argument("--refresh-legacy", action="store_true",
                    help="仅刷新无 schema 标记的旧记录，保留现代已验证/否定记录")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)

    if not T.check_read_api():
        out("错误: 23119 不通，Zotero 没开。请打开 Zotero 后重试。")
        sys.exit(1)
    mcp = T.Mcp()
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
        roots = sorted(d for d in broot.iterdir()
                       if d.is_dir() and not d.name.startswith("_")
                       and (d / "教授研究" / T.MAPPING_NAME).is_file()) \
            if broot.is_dir() else []
        if not roots:
            out(f"错误: {args.boshu_root} 下没有含 {T.MAPPING_NAME} 的程序根")
            sys.exit(1)
        out(f"全库模式: {len(roots)} 个程序根")

    grand = {"hit_pdf_footnote": 0, "hit_springer_curl": 0, "hit_crossref_api": 0,
             "none": 0, "cached": 0}
    for root in roots:
        out(f"== {root.name} ==")
        r = backfill_root(mcp, root, args.dry_run, args.refresh,
                          args.limit, args.professor, args.workers,
                          args.refresh_legacy)
        if r:
            for k in grand:
                grand[k] += r["stats"].get(k, 0)
    out(f"\n总计: A {grand['hit_pdf_footnote']} + B {grand['hit_springer_curl']}"
        f" + B2 {grand['hit_crossref_api']} 命中, 无显式 {grand['none']},"
        f" 缓存跳过 {grand['cached']}" + ("（dry-run）" if args.dry_run else ""))


if __name__ == "__main__":
    main()
