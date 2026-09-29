#!/usr/bin/env python3
"""Sync, or verify, the deployed copy of the canonical exporter core.

The APM artifact must ship the same exporter behavior the package command runs,
so ``.apm/skills/zotero-read/scripts/item_export_core.py`` is only ever a
deterministic copy of ``zotero_tools/item_export_core.py``.

Usage::

    uv run python scripts/sync_deployed_exporter.py          # rewrite the copy
    uv run python scripts/sync_deployed_exporter.py --check  # fail when it is stale
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "zotero_tools" / "item_export_core.py"
DEPLOYED = ROOT / ".apm" / "skills" / "zotero-read" / "scripts" / "item_export_core.py"


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sync_deployed_exporter")
    parser.add_argument("--check", action="store_true", help="verify the copy without writing it")
    args = parser.parse_args(argv)

    canonical = CANONICAL.read_bytes()
    deployed = DEPLOYED.read_bytes() if DEPLOYED.is_file() else None

    if args.check:
        if deployed == canonical:
            print(f"deployed exporter core is fresh: {_digest(canonical)}")
            return 0
        state = "missing" if deployed is None else f"stale: {_digest(deployed)} != {_digest(canonical)}"
        print(
            f"deployed exporter core is {state}; run scripts/sync_deployed_exporter.py",
            file=sys.stderr,
        )
        return 1

    DEPLOYED.parent.mkdir(parents=True, exist_ok=True)
    DEPLOYED.write_bytes(canonical)
    print(f"wrote {DEPLOYED.relative_to(ROOT)}: {_digest(canonical)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
