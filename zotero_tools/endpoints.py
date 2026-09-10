"""Runtime endpoint resolution for Zotero HTTP and MCP connections.

Single authority for transport destinations across the package. Defaults
preserve the historical production endpoints; overrides are read from the
environment at call time (never cached at import) so tests and clean consumers
can redirect every repo-owned connection without editing installed files.

Contract:
- ``ZOTERO_HTTP_URL`` — base URL of the Zotero local HTTP API. Callers append
  exactly one resource path (e.g. ``/connector/ping``) after trailing slashes
  are stripped.
- ``ZOTERO_MCP_URL`` — FULL MCP endpoint URL, already including ``/mcp``.
  Callers must never append ``/mcp`` again.
"""

from __future__ import annotations

import os


DEFAULT_ZOTERO_HTTP_URL = "http://127.0.0.1:23119"
DEFAULT_ZOTERO_MCP_URL = "http://127.0.0.1:23120/mcp"


def _resolve(raw: str | None, default: str) -> str:
    value = (raw or "").strip().rstrip("/")
    return value or default


def zotero_http_url() -> str:
    """Resolved Zotero HTTP API base URL (``ZOTERO_HTTP_URL`` or the default)."""
    return _resolve(os.environ.get("ZOTERO_HTTP_URL"), DEFAULT_ZOTERO_HTTP_URL)


def zotero_mcp_url() -> str:
    """Resolved full Zotero MCP endpoint URL (``ZOTERO_MCP_URL`` or the default)."""
    return _resolve(os.environ.get("ZOTERO_MCP_URL"), DEFAULT_ZOTERO_MCP_URL)
