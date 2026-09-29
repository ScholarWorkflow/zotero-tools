"""Regression gate for issue #23: the APM-deployed Zotero item exporter entry.

These cases drive ``.apm/skills/zotero-read/scripts/zotero_item_export.py`` and the
generated core copy beside it, so the deployed route is proven on the files APM
installs rather than on the package module.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from test_endpoint_transport import _run_new_session

from zotero_tools import endpoints


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".apm/skills/zotero-read/scripts"
ENTRY = SCRIPTS / "zotero_item_export.py"
OVERRIDE_MCP = "http://127.0.0.1:19992/mcp"
SESSION_ID = "DEPLOYED-SID-1"


class _Completed:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = ""


def _load_deployed_entry():
    spec = importlib.util.spec_from_file_location("deployed_item_export_entry", ENTRY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rpc_text(payload: dict) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
        }
    )


def _tool_names(curl_argv: list[list[str]]) -> list[str]:
    return [
        json.loads(argv[argv.index("-d") + 1])["params"]["name"]
        for argv in curl_argv
    ]


def _item_keys(curl_argv: list[list[str]]) -> list[str]:
    return [
        json.loads(argv[argv.index("-d") + 1])["params"]["arguments"]["itemKey"]
        for argv in curl_argv
    ]


def test_deployed_entry_exports_one_item_through_the_deployed_session_and_endpoint(
    monkeypatch, tmp_path, capsys
):
    entry = _load_deployed_entry()
    observed: list[list[str]] = []

    def fake_run(command, *args, **kwargs):
        argv = list(command)
        observed.append(argv)
        if argv[:1] == ["bash"]:
            return _Completed(stdout=f"{SESSION_ID}\n")
        request = json.loads(argv[argv.index("-d") + 1])
        if request["params"]["name"] == "get_item_details":
            return _Completed(stdout=_rpc_text({
                "title": "Deployed Export Title",
                "creators": [
                    {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
                    {"creatorType": "editor", "name": "Ignored Editor"},
                ],
                "date": "2025-04-01",
                "publicationTitle": "Journal of Tests",
                "DOI": "10.1234/example",
                "tags": ["must-not-leak"],
            }))
        return _Completed(stdout=_rpc_text({"abstract": "Abstract text"}))

    monkeypatch.setenv("ZOTERO_MCP_URL", OVERRIDE_MCP)
    monkeypatch.setattr(entry.subprocess, "run", fake_run)
    output = tmp_path / "paper.json"
    entry.main(["ITEMKEY01", "--output", str(output)])

    # Session initialization goes to the deployed sibling helper, not a PATH command
    # and not the repository package.
    assert observed[0] == ["bash", str(SCRIPTS / "new-session.sh")]
    curl_argv = [argv for argv in observed if argv[:1] == ["curl"]]
    assert _tool_names(curl_argv) == ["get_item_details", "get_item_abstract"]
    assert _item_keys(curl_argv) == ["ITEMKEY01", "ITEMKEY01"]
    for argv in curl_argv:
        assert OVERRIDE_MCP in argv
        assert f"Mcp-Session-Id: {SESSION_ID}" in argv
    assert not any("23119" in token or "23120" in token for argv in observed for token in argv)

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "schema": 1,
        "kind": "paper-analysis-input",
        "level": "abstract",
        "source": "zotero",
        "item_key": "ITEMKEY01",
        "metadata": {
            "title": "Deployed Export Title",
            "authors": ["Ada Lovelace"],
            "year": 2025,
            "venue": "Journal of Tests",
            "doi": "10.1234/example",
        },
        "abstract": "Abstract text",
    }
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "ok", "output": str(output.resolve())}
    assert captured.err == ""


def test_deployed_entry_batch_keeps_order_dedup_and_one_session(monkeypatch, tmp_path, capsys):
    entry = _load_deployed_entry()
    sessions: list[str] = []
    calls: list[tuple[str, str, int]] = []

    def fake_session():
        sessions.append("created")
        return SESSION_ID

    def fake_call(session_id, name, arguments, request_id):
        assert session_id == SESSION_ID
        calls.append((name, arguments["itemKey"], request_id))
        if name == "get_item_details":
            return {"title": f"Title {arguments['itemKey']}"}
        return {"abstract": ""}

    monkeypatch.setattr(entry, "_create_session", fake_session)
    monkeypatch.setattr(entry, "_call_tool", fake_call)
    entry.main(
        [
            "AAAAAAAA",
            "CCCCCCCC",
            "--item-key",
            "BBBBBBBB",
            "--item-key",
            "AAAAAAAA",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert sessions == ["created"]
    assert calls == [
        ("get_item_details", "AAAAAAAA", 2),
        ("get_item_abstract", "AAAAAAAA", 3),
        ("get_item_details", "CCCCCCCC", 4),
        ("get_item_abstract", "CCCCCCCC", 5),
        ("get_item_details", "BBBBBBBB", 6),
        ("get_item_abstract", "BBBBBBBB", 7),
    ]
    assert {path.name for path in tmp_path.glob("*.json")} == {
        "AAAAAAAA.json",
        "CCCCCCCC.json",
        "BBBBBBBB.json",
    }
    status = json.loads(capsys.readouterr().out)
    assert status == {
        "status": "ok",
        "exported": 3,
        "failed": 0,
        "output_dir": str(tmp_path.resolve()),
    }


def test_deployed_endpoint_resolver_matches_package_while_session_helper_is_unchanged(
    monkeypatch, tmp_path
):
    # The two existing surfaces keep their own trailing-slash rules: the exporter
    # resolver strips all of them, the session helper strips only one.
    override = f"{OVERRIDE_MCP}///"
    monkeypatch.setenv("ZOTERO_MCP_URL", override)
    entry = _load_deployed_entry()

    assert entry._mcp_url() == OVERRIDE_MCP
    assert endpoints.zotero_mcp_url() == OVERRIDE_MCP

    argv, session_id = _run_new_session(monkeypatch, tmp_path, override)
    assert f"{OVERRIDE_MCP}//" in argv
    assert session_id == "FAKE-SID-123"
    assert not any(token.endswith("/mcp/mcp") for token in argv)
