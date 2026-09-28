#!/usr/bin/env python3
"""Zotero item exporter deployed with the zotero-read skill.

Run it by absolute installed path, with no ``zotero-tools`` package install and
no ``zotero-item-export`` command on PATH::

    uv run <skill_dir>/scripts/zotero_item_export.py ITEMKEY01 --output paper.json

``item_export_core.py`` next to this file is the generated copy of the producer's
canonical exporter core; ``new-session.sh`` next to it owns MCP session creation.
A missing or unreadable sibling is reported as an exporter failure, never repaired
here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import item_export_core as core  # noqa: E402

DEFAULT_ZOTERO_MCP_URL = "http://127.0.0.1:23120/mcp"
SESSION_HELPER = SCRIPT_DIR / "new-session.sh"


def _mcp_url() -> str:
    """Resolve ZOTERO_MCP_URL as the complete MCP endpoint, never appending /mcp."""
    value = (os.environ.get("ZOTERO_MCP_URL") or "").strip().rstrip("/")
    return value or DEFAULT_ZOTERO_MCP_URL


def _create_session() -> str:
    """Initialize the session through the sibling helper shipped with this skill."""
    try:
        result = subprocess.run(
            ["bash", str(SESSION_HELPER)],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise core.ExportError("failed to initialize Zotero MCP session") from exc

    session_id = result.stdout.strip()
    if result.returncode != 0 or not session_id:
        raise core.ExportError("failed to initialize Zotero MCP session")
    return session_id


def _call_tool(
    session_id: str,
    name: str,
    arguments: dict[str, Any],
    request_id: int,
) -> Any:
    return core.call_tool(session_id, name, arguments, request_id, _mcp_url())


def _wiring() -> core.ExporterWiring:
    # Resolved at call time so a patched adapter function is used by the core loop.
    return core.ExporterWiring(
        create_session=lambda: _create_session(),
        call_tool=lambda *arguments: _call_tool(*arguments),
    )


def main(argv: list[str] | None = None) -> None:
    core.main(sys.argv[1:] if argv is None else argv, wiring=_wiring())


if __name__ == "__main__":
    main()
