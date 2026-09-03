#!/usr/bin/env python3
"""Seed deterministic Zotero items through the real MCP plugin for CI."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

MCP_URL = "http://127.0.0.1:23120/mcp"


def _parse_rpc(body: str) -> dict:
    candidates = [body.strip()]
    candidates.extend(line[5:].strip() for line in body.splitlines() if line.startswith("data:"))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and ("result" in value or "error" in value):
            return value
    raise RuntimeError("invalid MCP response")


def _post(payload: dict, session_id: str | None = None) -> tuple[dict, str | None]:
    data = json.dumps(payload, separators=(",", ":")).encode()
    request = urllib.request.Request(
        MCP_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **({"Mcp-Session-Id": session_id} if session_id else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
        new_session = response.headers.get("Mcp-Session-Id")
    return _parse_rpc(body), new_session


def _initialize() -> str:
    rpc, session_id = _post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "zotero-tools-ci", "version": "1"},
            },
        }
    )
    if "error" in rpc or not session_id:
        raise RuntimeError("failed to initialize MCP session")
    return session_id


def _call(session_id: str, request_id: int, name: str, arguments: dict) -> dict:
    rpc, _ = _post(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        session_id,
    )
    if "error" in rpc:
        raise RuntimeError(f"MCP {name} call failed")
    result = rpc.get("result")
    if not isinstance(result, dict) or result.get("isError"):
        raise RuntimeError(f"MCP {name} call failed")
    for part in result.get("content", []):
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            try:
                payload = json.loads(part["text"])
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid nested JSON from {name}") from exc
            if isinstance(payload, dict):
                return payload
    raise RuntimeError(f"missing result payload from {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    sentinel = "CI_SENTINEL_ABSTRACT_DO_NOT_PRINT_7f43a1"
    items = [
        {
            "title": "Zotero Tools CI Synthetic Paper A",
            "date": "2024-03-14",
            "publicationTitle": "Journal of Deterministic Integration Tests",
            "DOI": "10.5555/zotero-tools-ci-a",
            "abstractNote": f"{sentinel} alpha",
            "creators": [
                {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
                {"creatorType": "author", "firstName": "Alan", "lastName": "Turing"},
            ],
        },
        {
            "title": "Zotero Tools CI Synthetic Paper B",
            "date": "2025-06-01",
            "publicationTitle": "Journal of Deterministic Integration Tests",
            "DOI": "10.5555/zotero-tools-ci-b",
            "abstractNote": f"{sentinel} beta",
            "creators": [
                {"creatorType": "author", "firstName": "Grace", "lastName": "Hopper"},
            ],
        },
    ]

    session_id = _initialize()
    seeded = []
    for index, item in enumerate(items, start=2):
        payload = _call(
            session_id,
            index,
            "write_item",
            {
                "action": "create",
                "itemType": "journalArticle",
                "fields": {key: value for key, value in item.items() if key != "creators"},
                "creators": item["creators"],
            },
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        item_key = data.get("itemKey") if isinstance(data, dict) else None
        if not isinstance(item_key, str) or not item_key:
            raise RuntimeError("write_item did not return itemKey")
        seeded.append({**item, "item_key": item_key})

    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump({"sentinel": sentinel, "items": seeded}, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"status": "ok", "seeded": len(seeded)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
