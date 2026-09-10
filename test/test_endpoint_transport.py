"""Transport instrumentation tests for issue #21.

These tests assert the FINAL request targets (curl argv / urllib request URLs)
of the packaged surfaces, not module constants. Every override case also
asserts zero production-default destination attempts.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from zotero_tools import item_export


ROOT = Path(__file__).resolve().parents[1]
OVERRIDE_HTTP = "http://127.0.0.1:19991"
OVERRIDE_MCP = "http://127.0.0.1:19992/mcp"
DEFAULT_HTTP = "http://127.0.0.1:23119"
DEFAULT_MCP = "http://127.0.0.1:23120/mcp"


def assert_zero_default_attempts(observed_targets: list[str]) -> None:
    offenders = [t for t in observed_targets if "127.0.0.1:23119" in t or "127.0.0.1:23120" in t]
    assert not offenders, f"production-default destination attempted despite override: {offenders}"


# ------------------------------------------------------------------ helpers


def rpc_text(payload: dict) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
        }
    )


class _FakeCompleted:
    def __init__(self, argv: list[str], *, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeResponse:
    def __init__(self, body: bytes = b"", headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _default_responder(url: str) -> _FakeResponse:
    if "/connector/ping" in url:
        return _FakeResponse(b"Zotero is running")
    if "/api/users/0/collections/" in url:
        return _FakeResponse(b"[]", {"Total-Results": "0"})
    return _FakeResponse(
        rpc_text({}).encode(),
        {"Mcp-Session-Id": "S1"},
    )


def _write_fake_curl(tmp_path: Path, log_path: Path) -> Path:
    """Fake curl that logs its argv and satisfies the new-session.sh header parse."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "curl"
    script.write_text(
        "#!/bin/bash\n"
        'printf \'%s\\n\' "$@" >> "$FAKE_CURL_LOG"\n'
        "while [[ $# -gt 0 ]]; do\n"
        '  if [[ "$1" == "-D" ]]; then printf \'Mcp-Session-Id: FAKE-SID-123\\r\\n\' > "$2"; fi\n'
        "  shift\n"
        "done\n",
        encoding="utf-8",
    )
    mode = script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    script.chmod(mode)
    return bin_dir


def _load_tagger():
    source = ROOT / ".apm/skills/zotero-paper-tagger/scripts/tagger.py"
    spec = importlib.util.spec_from_file_location("tagger_issue21_transport", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tagger():
    return _load_tagger()


# ------------------------------------------------- T4: zotero-item-export argv


def test_item_export_tool_calls_carry_override_url(monkeypatch):
    argvs: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        argvs.append(list(cmd))
        if cmd[:1] == [sys.executable]:
            return _FakeCompleted(list(cmd), stdout="SID")
        return _FakeCompleted(list(cmd), stdout=rpc_text({"title": "T"}))

    monkeypatch.setenv("ZOTERO_MCP_URL", OVERRIDE_MCP)
    monkeypatch.setattr(item_export.subprocess, "run", fake_run)
    item_export._call_tool("SID", "get_item_details", {"itemKey": "K1"}, 2)

    curl_argv = [argv for argv in argvs if argv[:1] == ["curl"]]
    assert len(curl_argv) == 1
    assert OVERRIDE_MCP in curl_argv[0]
    assert_zero_default_attempts([token for argv in argvs for token in argv])


def test_item_export_uses_default_url_when_env_unset(monkeypatch):
    argvs: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        argvs.append(list(cmd))
        return _FakeCompleted(list(cmd), stdout=rpc_text({"title": "T"}))

    monkeypatch.delenv("ZOTERO_MCP_URL", raising=False)
    monkeypatch.setattr(item_export.subprocess, "run", fake_run)
    item_export._call_tool("SID", "get_item_details", {"itemKey": "K1"}, 2)

    curl_argv = [argv for argv in argvs if argv[:1] == ["curl"]]
    assert DEFAULT_MCP in curl_argv[0]


def test_item_export_full_flow_uses_one_resolved_endpoint(monkeypatch, tmp_path):
    """initialize + both tool calls resolve the same override; output schema unchanged."""
    argvs: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        argvs.append(list(cmd))
        if cmd[:1] == [sys.executable]:
            return _FakeCompleted(list(cmd), stdout="SID-FULL")
        body_index = cmd.index("-d") + 1
        request = json.loads(cmd[body_index])
        tool = request["params"]["name"]
        payload = {"title": "Flow"} if tool == "get_item_details" else {"abstract": "A"}
        return _FakeCompleted(list(cmd), stdout=rpc_text(payload))

    monkeypatch.setenv("ZOTERO_MCP_URL", OVERRIDE_MCP)
    monkeypatch.setattr(item_export.subprocess, "run", fake_run)
    output = tmp_path / "flow.json"
    item_export.main(["FLOWKEY1", "--output", str(output)])

    assert json.loads(output.read_text(encoding="utf-8"))["item_key"] == "FLOWKEY1"
    curl_argv_urls = [next(t for t in argv if t.startswith("http")) for argv in argvs if argv[:1] == ["curl"]]
    assert curl_argv_urls == [OVERRIDE_MCP, OVERRIDE_MCP]
    assert_zero_default_attempts([token for argv in argvs for token in argv])


def test_item_export_initialize_reaches_override_via_real_helper(
    monkeypatch, tmp_path
):
    """The real zotero-mcp-session helper resolves the same override end to end."""
    log_path = tmp_path / "curl.log"
    bin_dir = _write_fake_curl(tmp_path, log_path)
    monkeypatch.setenv("ZOTERO_MCP_URL", OVERRIDE_MCP)
    monkeypatch.setenv("FAKE_CURL_LOG", str(log_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    session_id = item_export._create_session()

    assert session_id == "FAKE-SID-123"
    logged = log_path.read_text(encoding="utf-8").splitlines()
    assert OVERRIDE_MCP in logged
    assert_zero_default_attempts(logged)
    assert not any(token.endswith("/mcp/mcp") for token in logged)


# ------------------------------------------------------ T5: new-session.sh argv


def _run_new_session(monkeypatch, tmp_path: Path, mcp_env: str | None) -> tuple[list[str], str]:
    helper = ROOT / ".apm/skills/zotero-read/scripts/new-session.sh"
    log_path = tmp_path / "argv.log"
    bin_dir = _write_fake_curl(tmp_path, log_path)
    monkeypatch.setenv("FAKE_CURL_LOG", str(log_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    if mcp_env is None:
        monkeypatch.delenv("ZOTERO_MCP_URL", raising=False)
    else:
        monkeypatch.setenv("ZOTERO_MCP_URL", mcp_env)

    import subprocess as subprocess_module

    result = subprocess_module.run(
        ["bash", str(helper)],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
    )
    argv = log_path.read_text(encoding="utf-8").splitlines()
    return argv, result.stdout.strip()


def test_new_session_helper_posts_to_override_url(monkeypatch, tmp_path):
    argv, sid = _run_new_session(monkeypatch, tmp_path, OVERRIDE_MCP)
    assert OVERRIDE_MCP in argv
    assert sid == "FAKE-SID-123"
    assert_zero_default_attempts(argv)
    assert not any(token.endswith("/mcp/mcp") for token in argv)


def test_new_session_helper_posts_to_default_url_when_unset(monkeypatch, tmp_path):
    argv, sid = _run_new_session(monkeypatch, tmp_path, None)
    assert DEFAULT_MCP in argv
    assert sid == "FAKE-SID-123"


def test_new_session_helper_empty_env_falls_back_to_default(monkeypatch, tmp_path):
    argv, _ = _run_new_session(monkeypatch, tmp_path, "")
    assert DEFAULT_MCP in argv
    assert OVERRIDE_MCP not in argv


# ------------------------------------------------- T6: zotero-paper-tagger URLs


def test_tagger_read_ping_uses_http_override(tagger, monkeypatch):
    seen: list[str] = []

    def fake_urlopen(target, *args, **kwargs):
        seen.append(getattr(target, "full_url", target))
        return _FakeResponse(b"Zotero is running")

    monkeypatch.setenv("ZOTERO_HTTP_URL", OVERRIDE_HTTP)
    monkeypatch.setattr(tagger.urllib.request, "urlopen", fake_urlopen)
    assert tagger.check_read_api() is True
    assert seen == [f"{OVERRIDE_HTTP}/connector/ping"]
    assert_zero_default_attempts(seen)


def test_tagger_read_ping_uses_default_when_unset(tagger, monkeypatch):
    seen: list[str] = []

    def fake_urlopen(target, *args, **kwargs):
        seen.append(getattr(target, "full_url", target))
        return _FakeResponse(b"Zotero is running")

    monkeypatch.delenv("ZOTERO_HTTP_URL", raising=False)
    monkeypatch.setattr(tagger.urllib.request, "urlopen", fake_urlopen)
    assert tagger.check_read_api() is True
    assert seen == [f"{DEFAULT_HTTP}/connector/ping"]


def test_tagger_mcp_initialize_and_call_use_mcp_override(tagger, monkeypatch):
    seen: list[str] = []

    def fake_urlopen(target, *args, **kwargs):
        seen.append(getattr(target, "full_url", target))
        return _FakeResponse(rpc_text({}).encode(), {"Mcp-Session-Id": "S1"})

    monkeypatch.setenv("ZOTERO_MCP_URL", OVERRIDE_MCP)
    monkeypatch.setattr(tagger.urllib.request, "urlopen", fake_urlopen)
    mcp = tagger.Mcp()
    mcp.connect()
    mcp.call("write_tag", {"action": "add", "itemKey": "K1", "tags": ["t"]})
    assert seen == [OVERRIDE_MCP, OVERRIDE_MCP]
    assert_zero_default_attempts(seen)


def test_tagger_mcp_uses_default_when_unset(tagger, monkeypatch):
    seen: list[str] = []

    def fake_urlopen(target, *args, **kwargs):
        seen.append(getattr(target, "full_url", target))
        return _FakeResponse(rpc_text({}).encode(), {"Mcp-Session-Id": "S1"})

    monkeypatch.delenv("ZOTERO_MCP_URL", raising=False)
    monkeypatch.setattr(tagger.urllib.request, "urlopen", fake_urlopen)
    mcp = tagger.Mcp()
    mcp.connect()
    assert seen == [DEFAULT_MCP]


def test_tagger_read_and_mcp_overrides_are_independent(tagger, monkeypatch):
    seen: list[str] = []

    def fake_urlopen(target, *args, **kwargs):
        seen.append(getattr(target, "full_url", target))
        if "/connector/ping" in getattr(target, "full_url", target):
            return _FakeResponse(b"Zotero is running")
        return _FakeResponse(rpc_text({}).encode(), {"Mcp-Session-Id": "S1"})

    monkeypatch.setenv("ZOTERO_HTTP_URL", OVERRIDE_HTTP)
    monkeypatch.delenv("ZOTERO_MCP_URL", raising=False)
    monkeypatch.setattr(tagger.urllib.request, "urlopen", fake_urlopen)
    assert tagger.check_read_api() is True
    tagger.Mcp().connect()
    assert seen == [f"{OVERRIDE_HTTP}/connector/ping", DEFAULT_MCP]

    seen.clear()
    monkeypatch.delenv("ZOTERO_HTTP_URL", raising=False)
    monkeypatch.setenv("ZOTERO_MCP_URL", OVERRIDE_MCP)
    assert tagger.check_read_api() is True
    tagger.Mcp().connect()
    assert seen == [f"{DEFAULT_HTTP}/connector/ping", OVERRIDE_MCP]


def test_tagger_read_api_pagination_uses_http_override(tagger, monkeypatch):
    seen: list[str] = []
    tagger._FETCH_CACHE.clear()

    def fake_urlopen(target, *args, **kwargs):
        seen.append(getattr(target, "full_url", target))
        return _FakeResponse(b"[]", {"Total-Results": "0"})

    monkeypatch.setenv("ZOTERO_HTTP_URL", f"{OVERRIDE_HTTP}/")
    monkeypatch.setattr(tagger.urllib.request, "urlopen", fake_urlopen)
    tagger.fetch_collection_items("COLLTEST")
    assert seen == [
        f"{OVERRIDE_HTTP}/api/users/0/collections/COLLTEST/items?format=json&limit=100&start=0"
    ]
    assert_zero_default_attempts(seen)


def test_tagger_all_transports_avoid_defaults_when_overridden(tagger, monkeypatch):
    seen: list[str] = []
    tagger._FETCH_CACHE.clear()

    def fake_urlopen(target, *args, **kwargs):
        seen.append(getattr(target, "full_url", target))
        return _default_responder(getattr(target, "full_url", target))

    monkeypatch.setenv("ZOTERO_HTTP_URL", OVERRIDE_HTTP)
    monkeypatch.setenv("ZOTERO_MCP_URL", OVERRIDE_MCP)
    monkeypatch.setattr(tagger.urllib.request, "urlopen", fake_urlopen)
    assert tagger.check_read_api() is True
    mcp = tagger.Mcp()
    mcp.connect()
    mcp.call("write_tag", {"action": "add", "itemKey": "K1", "tags": ["t"]})
    tagger.fetch_collection_items("COLLALL")
    assert_zero_default_attempts(seen)


# --------------------------------------------------- T8: the gates are not vacuous


def test_zero_default_gate_fails_an_override_ignoring_caller():
    with pytest.raises(AssertionError):
        assert_zero_default_attempts([DEFAULT_MCP])
    with pytest.raises(AssertionError):
        assert_zero_default_attempts([OVERRIDE_MCP, DEFAULT_HTTP + "/connector/ping"])
