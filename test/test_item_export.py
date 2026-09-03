import json

import pytest

from zotero_tools import item_export


def rpc_text(payload):
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
        }
    )


def test_single_item_export_normalizes_and_writes_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(item_export, "_create_session", lambda: "SID")
    calls = []

    def fake_call(session_id, name, arguments, request_id):
        calls.append((session_id, name, arguments, request_id))
        if name == "get_item_details":
            return {
                "title": "Paper Title",
                "creators": [
                    {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
                    {"creatorType": "editor", "name": "Ignored Editor"},
                ],
                "date": "2025-04-01",
                "publicationTitle": "Journal of Tests",
                "DOI": "10.1234/example",
                "tags": ["must-not-leak"],
            }
        return {"abstract": "Abstract text"}

    monkeypatch.setattr(item_export, "_call_tool", fake_call)
    output = tmp_path / "paper.json"
    item_export.main(["ITEMKEY01", "--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "schema": 1,
        "kind": "paper-analysis-input",
        "level": "abstract",
        "source": "zotero",
        "item_key": "ITEMKEY01",
        "metadata": {
            "title": "Paper Title",
            "authors": ["Ada Lovelace"],
            "year": 2025,
            "venue": "Journal of Tests",
            "doi": "10.1234/example",
        },
        "abstract": "Abstract text",
    }
    assert [call[1] for call in calls] == ["get_item_details", "get_item_abstract"]
    assert calls[0][2] == {"itemKey": "ITEMKEY01", "mode": "standard"}
    assert calls[1][2] == {"itemKey": "ITEMKEY01", "format": "json"}
    stdout = capsys.readouterr().out
    assert json.loads(stdout) == {"status": "ok", "output": str(output.resolve())}
    assert "Abstract text" not in stdout
    assert "Paper Title" not in stdout


def test_batch_export_reuses_one_session(tmp_path, monkeypatch, capsys):
    sessions = []

    def fake_session():
        sessions.append("created")
        return "SID"

    monkeypatch.setattr(item_export, "_create_session", fake_session)
    monkeypatch.setattr(
        item_export,
        "_call_tool",
        lambda _sid, name, args, _request_id: (
            {"title": f"Title {args['itemKey']}"} if name == "get_item_details" else {"abstract": ""}
        ),
    )

    item_export.main(
        [
            "--item-key",
            "AAAAAAAA",
            "--item-key",
            "BBBBBBBB",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert sessions == ["created"]
    assert (tmp_path / "AAAAAAAA.json").exists()
    assert (tmp_path / "BBBBBBBB.json").exists()
    status = json.loads(capsys.readouterr().out)
    assert status == {
        "status": "ok",
        "exported": 2,
        "failed": 0,
        "output_dir": str(tmp_path.resolve()),
    }


def test_missing_abstract_exports_empty_string(tmp_path, monkeypatch):
    monkeypatch.setattr(item_export, "_create_session", lambda: "SID")

    def fake_call(_sid, name, _args, _request_id):
        if name == "get_item_details":
            return {"title": "No Abstract"}
        raise item_export.ExportError("No abstract found for this item")

    monkeypatch.setattr(item_export, "_call_tool", fake_call)
    output = tmp_path / "missing.json"
    item_export.main(["MISSING01", "--output", str(output)])
    assert json.loads(output.read_text(encoding="utf-8"))["abstract"] == ""


def test_mcp_error_is_compact_and_does_not_dump_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(item_export, "_create_session", lambda: "SID")

    def fail(_sid, _name, _args, _request_id):
        raise item_export.ExportError("permission denied")

    monkeypatch.setattr(item_export, "_call_tool", fail)
    with pytest.raises(SystemExit) as exc:
        item_export.main(["BADITEM1", "--output", str(tmp_path / "bad.json")])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    status = json.loads(captured.out)
    assert status["errors"] == [{"item_key": "BADITEM1", "reason": "permission denied"}]
    assert captured.err == ""


def test_invalid_nested_json_is_rejected():
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "{not-json"}]},
        }
    )
    with pytest.raises(item_export.ExportError, match="invalid nested JSON"):
        item_export._parse_tool_payload(body)


def test_sse_response_with_nested_json_is_supported():
    body = "event: message\ndata: " + rpc_text({"abstract": "from sse"}) + "\n\n"
    assert item_export._parse_tool_payload(body) == {"abstract": "from sse"}


def test_atomic_replacement_leaves_complete_json(tmp_path):
    output = tmp_path / "paper.json"
    output.write_text('{"old":true}\n', encoding="utf-8")
    item_export._atomic_write_json(output, {"new": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"new": True}
    assert list(tmp_path.glob(".paper.json.*.tmp")) == []


def test_stdout_stays_compact_for_large_payload(tmp_path, monkeypatch, capsys):
    large = "x" * 100_000
    monkeypatch.setattr(item_export, "_create_session", lambda: "SID")
    monkeypatch.setattr(
        item_export,
        "_call_tool",
        lambda _sid, name, _args, _request_id: {"title": large} if name == "get_item_details" else {"abstract": large},
    )
    output = tmp_path / "large.json"
    item_export.main(["LARGE001", "--output", str(output)])
    captured = capsys.readouterr()
    assert len(captured.out) < 500
    assert captured.err == ""
    assert large not in captured.out


def test_nested_item_error_is_not_silently_exported(monkeypatch):
    class Result:
        returncode = 0
        stdout = rpc_text({"error": "Item with key BADITEM1 not found"})

    monkeypatch.setattr(item_export.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(item_export.ExportError, match="not found"):
        item_export._call_tool("SID", "get_item_details", {"itemKey": "BADITEM1"}, 2)
