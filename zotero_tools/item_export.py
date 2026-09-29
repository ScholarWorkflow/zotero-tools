"""Package entry point for the deterministic Zotero item exporter.

The exporter behavior itself lives in :mod:`zotero_tools.item_export_core`, the
canonical core that is also deployed inside the ``zotero-read`` skill. This
adapter supplies the two package-specific runtime seams: the installed
``zotero-mcp-session`` path and the central endpoint resolver.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from zotero_tools import item_export_core as core
from zotero_tools.endpoints import zotero_mcp_url
# Re-exported so the package module keeps its established exporter surface.
from zotero_tools.item_export_core import (
    MCP_TIMEOUT_SECONDS,
    ExportError,
    _atomic_write_json,
    _parse_tool_payload,
    normalize_item,
)


def _create_session() -> str:
    """Reuse the existing zotero-mcp-session implementation and capture its SID."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "zotero_tools.session"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExportError("failed to initialize Zotero MCP session") from exc

    session_id = result.stdout.strip()
    if result.returncode != 0 or not session_id:
        raise ExportError("failed to initialize Zotero MCP session")
    return session_id


def _call_tool(
    session_id: str,
    name: str,
    arguments: dict[str, Any],
    request_id: int,
) -> Any:
    return core.call_tool(session_id, name, arguments, request_id, zotero_mcp_url())


def _wiring() -> core.ExporterWiring:
    # Resolved at call time so a patched adapter function is used by the core loop.
    return core.ExporterWiring(
        create_session=lambda: _create_session(),
        call_tool=lambda *arguments: _call_tool(*arguments),
    )


def main(argv: list[str] | None = None) -> None:
    core.main(argv, wiring=_wiring())


if __name__ == "__main__":
    main()
