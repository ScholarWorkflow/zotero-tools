"""Endpoint contract tests for issue #21 (frozen before implementation).

Contract:
- ZOTERO_HTTP_URL: base URL of the Zotero local HTTP API. Unset/empty ->
  http://127.0.0.1:23119. Explicit values may carry a trailing slash; callers
  strip trailing slashes before appending exactly one target path.
- ZOTERO_MCP_URL: FULL MCP endpoint URL (already includes /mcp). Unset/empty ->
  http://127.0.0.1:23120/mcp. Trailing slash is normalized away; callers must
  never append /mcp again.
"""

from __future__ import annotations

from zotero_tools import endpoints


DEFAULT_HTTP = "http://127.0.0.1:23119"
DEFAULT_MCP = "http://127.0.0.1:23120/mcp"


def test_http_default_when_unset(monkeypatch):
    monkeypatch.delenv("ZOTERO_HTTP_URL", raising=False)
    assert endpoints.zotero_http_url() == DEFAULT_HTTP


def test_http_default_when_empty(monkeypatch):
    monkeypatch.setenv("ZOTERO_HTTP_URL", "")
    assert endpoints.zotero_http_url() == DEFAULT_HTTP


def test_mcp_default_when_unset(monkeypatch):
    monkeypatch.delenv("ZOTERO_MCP_URL", raising=False)
    assert endpoints.zotero_mcp_url() == DEFAULT_MCP


def test_mcp_default_when_empty(monkeypatch):
    monkeypatch.setenv("ZOTERO_MCP_URL", "")
    assert endpoints.zotero_mcp_url() == DEFAULT_MCP


def test_http_override_is_returned_exactly(monkeypatch):
    monkeypatch.setenv("ZOTERO_HTTP_URL", "http://127.0.0.1:19991")
    assert endpoints.zotero_http_url() == "http://127.0.0.1:19991"


def test_mcp_override_is_returned_exactly(monkeypatch):
    monkeypatch.setenv("ZOTERO_MCP_URL", "http://127.0.0.1:19992/mcp")
    assert endpoints.zotero_mcp_url() == "http://127.0.0.1:19992/mcp"


def test_http_override_with_trailing_slash_is_normalized(monkeypatch):
    monkeypatch.setenv("ZOTERO_HTTP_URL", "http://127.0.0.1:19991/")
    assert endpoints.zotero_http_url() == "http://127.0.0.1:19991"


def test_mcp_override_with_trailing_slash_is_normalized(monkeypatch):
    monkeypatch.setenv("ZOTERO_MCP_URL", "http://127.0.0.1:19992/mcp/")
    assert endpoints.zotero_mcp_url() == "http://127.0.0.1:19992/mcp"


def test_http_resource_path_is_appended_exactly_once(monkeypatch):
    monkeypatch.setenv("ZOTERO_HTTP_URL", "http://127.0.0.1:19991/")
    assert endpoints.zotero_http_url() + "/connector/ping" == "http://127.0.0.1:19991/connector/ping"


def test_mcp_override_never_grows_a_second_mcp_segment(monkeypatch):
    monkeypatch.setenv("ZOTERO_MCP_URL", "http://127.0.0.1:19992/mcp/")
    resolved = endpoints.zotero_mcp_url()
    assert resolved == "http://127.0.0.1:19992/mcp"
    assert not resolved.endswith("/mcp/mcp")


def test_resolver_reads_environment_at_call_time(monkeypatch):
    monkeypatch.delenv("ZOTERO_MCP_URL", raising=False)
    assert endpoints.zotero_mcp_url() == DEFAULT_MCP
    monkeypatch.setenv("ZOTERO_MCP_URL", "http://127.0.0.1:19992/mcp")
    assert endpoints.zotero_mcp_url() == "http://127.0.0.1:19992/mcp"
    monkeypatch.setenv("ZOTERO_MCP_URL", "")
    assert endpoints.zotero_mcp_url() == DEFAULT_MCP


def test_defaults_are_pinned_to_the_production_endpoints():
    assert endpoints.DEFAULT_ZOTERO_HTTP_URL == DEFAULT_HTTP
    assert endpoints.DEFAULT_ZOTERO_MCP_URL == DEFAULT_MCP
