"""Deterministic Zotero item exporter for file-based downstream analysis."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


MCP_URL = "http://127.0.0.1:23120/mcp"
MCP_TIMEOUT_SECONDS = 60


class ExportError(RuntimeError):
    """A concise, user-safe exporter failure."""


def _compact_reason(value: object, fallback: str) -> str:
    text = " ".join(str(value).split()) if value is not None else ""
    if not text:
        return fallback
    return text[:200]


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


def _extract_json_rpc(body: str) -> dict[str, Any]:
    stripped = body.strip()
    candidates: list[str] = []
    if stripped:
        candidates.append(stripped)
    for line in body.splitlines():
        if line.startswith("data:"):
            candidates.append(line[5:].strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
            return parsed
    raise ExportError("invalid MCP response")


def _parse_tool_payload(body: str) -> Any:
    rpc = _extract_json_rpc(body)
    if "error" in rpc:
        error = rpc.get("error")
        if isinstance(error, dict):
            reason = _compact_reason(error.get("message"), "MCP tool error")
        else:
            reason = "MCP tool error"
        raise ExportError(reason)

    result = rpc.get("result")
    if not isinstance(result, dict):
        raise ExportError("invalid MCP result")
    if result.get("isError"):
        raise ExportError("MCP tool error")

    content = result.get("content")
    if not isinstance(content, list):
        raise ExportError("invalid MCP result content")

    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        text = part.get("text")
        if not isinstance(text, str):
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExportError("invalid nested JSON from MCP tool") from exc

    raise ExportError("missing MCP text result")


def _call_tool(session_id: str, name: str, arguments: dict[str, Any], request_id: int) -> Any:
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    command = [
        "curl",
        "-sS",
        "--max-time",
        str(MCP_TIMEOUT_SECONDS),
        "-X",
        "POST",
        MCP_URL,
        "-H",
        "Content-Type: application/json",
        "-H",
        "Accept: application/json, text/event-stream",
        "-H",
        f"Mcp-Session-Id: {session_id}",
        "-d",
        json.dumps(request, ensure_ascii=False, separators=(",", ":")),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=MCP_TIMEOUT_SECONDS + 5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExportError(f"{name} request failed") from exc
    if result.returncode != 0:
        raise ExportError(f"{name} request failed")
    payload = _parse_tool_payload(result.stdout)
    if isinstance(payload, dict) and payload.get("error"):
        raise ExportError(_compact_reason(payload.get("error"), f"{name} failed"))
    return payload


def _unwrap_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    return data if isinstance(data, dict) else value


def _normalize_authors(creators: Any) -> list[str]:
    if not isinstance(creators, list):
        return []
    authors: list[str] = []
    for creator in creators:
        if isinstance(creator, str):
            name = creator.strip()
        elif isinstance(creator, dict):
            creator_type = creator.get("creatorType") or creator.get("type")
            if creator_type not in (None, "author"):
                continue
            name = str(creator.get("name") or "").strip()
            if not name:
                name = " ".join(
                    part.strip()
                    for part in (str(creator.get("firstName") or ""), str(creator.get("lastName") or ""))
                    if part.strip()
                )
        else:
            continue
        if name:
            authors.append(name)
    return authors


def _normalize_year(details: dict[str, Any]) -> int | None:
    year = details.get("year")
    if isinstance(year, int):
        return year
    if isinstance(year, str) and year.isdigit() and len(year) == 4:
        return int(year)
    date = details.get("date")
    if isinstance(date, str):
        match = re.search(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|21\d{2})(?!\d)", date)
        if match:
            return int(match.group(1))
    return None


def _first_text(details: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = details.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_abstract(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    abstract_data = _unwrap_mapping(payload)
    return _first_text(abstract_data, ("abstract", "abstractNote"))


def normalize_item(item_key: str, details_payload: Any, abstract_payload: Any) -> dict[str, Any]:
    details = _unwrap_mapping(details_payload)
    creators = details.get("creators")
    if creators is None:
        creators = details.get("authors")
    return {
        "schema": 1,
        "kind": "paper-analysis-input",
        "level": "abstract",
        "source": "zotero",
        "item_key": item_key,
        "metadata": {
            "title": _first_text(details, ("title",)),
            "authors": _normalize_authors(creators),
            "year": _normalize_year(details),
            "venue": _first_text(
                details,
                ("publicationTitle", "proceedingsTitle", "conferenceName", "journalAbbreviation"),
            ),
            "doi": _first_text(details, ("DOI", "doi")),
        },
        "abstract": _normalize_abstract(abstract_payload),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def export_item(session_id: str, item_key: str, output_path: Path, request_id: int) -> None:
    try:
        details = _call_tool(
            session_id,
            "get_item_details",
            {"itemKey": item_key, "mode": "standard"},
            request_id,
        )
        try:
            abstract = _call_tool(
                session_id,
                "get_item_abstract",
                {"itemKey": item_key, "format": "json"},
                request_id + 1,
            )
        except ExportError as exc:
            if "no abstract found" in str(exc).lower():
                abstract = {}
            else:
                raise
        _atomic_write_json(output_path, normalize_item(item_key, details, abstract))
    except ExportError as exc:
        raise ExportError(f"{item_key}: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zotero-item-export")
    parser.add_argument("item_keys", nargs="*", metavar="ITEM_KEY")
    parser.add_argument("--item-key", action="append", default=[], dest="option_item_keys")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path)
    destination.add_argument("--output-dir", type=Path)
    return parser


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _print_status(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    item_keys = _ordered_unique([*args.item_keys, *args.option_item_keys])
    if not item_keys:
        parser.error("at least one item key is required")
    if args.output is not None and len(item_keys) != 1:
        parser.error("--output requires exactly one item key")

    if args.output is not None:
        outputs = {item_keys[0]: args.output.expanduser().resolve()}
    else:
        output_dir = args.output_dir.expanduser().resolve()
        outputs = {key: output_dir / f"{key}.json" for key in item_keys}

    try:
        session_id = _create_session()
    except ExportError as exc:
        errors = [{"item_key": key, "reason": str(exc)} for key in item_keys]
        _print_status({"status": "error", "exported": 0, "failed": len(errors), "errors": errors})
        raise SystemExit(1)

    errors: list[dict[str, str]] = []
    exported = 0
    for index, item_key in enumerate(item_keys):
        try:
            export_item(session_id, item_key, outputs[item_key], request_id=2 + index * 2)
            exported += 1
        except ExportError as exc:
            _, _, reason = str(exc).partition(": ")
            errors.append({"item_key": item_key, "reason": reason or "export failed"})

    if len(item_keys) == 1 and not errors:
        _print_status({"status": "ok", "output": str(outputs[item_keys[0]])})
        return

    status = "ok" if not errors else ("partial" if exported else "error")
    result: dict[str, Any] = {"status": status, "exported": exported, "failed": len(errors)}
    if args.output_dir is not None:
        result["output_dir"] = str(args.output_dir.expanduser().resolve())
    if errors:
        result["errors"] = errors
    _print_status(result)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
