"""Review regressions for PR #17 target-child/session scoping.

These tests encode issue #16's hard invariant that unrelated children and
unrelated rollout files must never participate in a probe verdict.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "test" / "acceptance" / "runtime_evidence.sh"
BASH = shutil.which("bash") or "/bin/bash"

PARENT = "11111111-1111-4111-8111-111111111111"
TARGET = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
SENTINEL = "SYNTH-SCOPING-UNIV-31415"


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def _spawn(child: str) -> dict:
    return {
        "type": "item.completed",
        "item": {
            "type": "collab_tool_call",
            "tool": "spawn_agent",
            "receiver_thread_ids": [child],
        },
    }


def _target_parent_rollout() -> list[dict]:
    return [
        {"type": "session_meta", "payload": {"id": PARENT}},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "call_id": "call_target_spawn",
                "arguments": json.dumps(
                    {"agent_type": "zotero-collection-cleaner"}, separators=(",", ":")
                ),
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_target_spawn",
                "output": json.dumps({"agent_id": TARGET}, separators=(",", ":")),
            },
        },
    ]


def _native_c2_rollout(child: str) -> list[dict]:
    return [
        {"type": "session_meta", "payload": {"id": child}},
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "get_collections",
                "namespace": "mcp__zotero",
                "call_id": "call_get_collections",
                "arguments": "{}",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_get_collections",
                "output": [{"type": "input_text", "text": SENTINEL}],
            },
        },
    ]


def _freshen(path: Path, marker: Path) -> None:
    t = marker.stat().st_mtime + 1.0
    os.utime(path, (t, t))


def _check(
    contract: str,
    stream: Path,
    marker: Path,
    sessions: Path,
    *,
    sentinel: str | None = None,
) -> subprocess.CompletedProcess:
    args = [
        BASH,
        str(CONTROLLER),
        "check",
        "--contract",
        contract,
        "--stream",
        str(stream),
        "--start-marker",
        str(marker),
        "--scan-dir",
        str(sessions),
    ]
    if sentinel is not None:
        args += ["--sentinel", sentinel]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def test_c2_other_spawned_child_cannot_satisfy_target_contract(tmp_path: Path) -> None:
    """Issue #16 T3: target=A, but only spawned child B has the valid MCP call."""
    stream = tmp_path / "stream.jsonl"
    _write_jsonl(
        stream,
        [
            {"type": "thread.started", "thread_id": PARENT},
            _spawn(TARGET),
            _spawn(OTHER),
        ],
    )

    marker = tmp_path / "marker"
    marker.touch()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    parent = sessions / "parent.jsonl"
    other = sessions / "other.jsonl"
    _write_jsonl(parent, _target_parent_rollout())
    _write_jsonl(other, _native_c2_rollout(OTHER))
    _freshen(parent, marker)
    _freshen(other, marker)

    result = _check("c2", stream, marker, sessions, sentinel=SENTINEL)
    assert result.returncode == 1, result.stderr


def test_c3_leg1_other_spawned_child_cannot_satisfy_target_contract(tmp_path: Path) -> None:
    """Issue #16 T3: B is spawned too, but B's needs_input must not stand in for A."""
    wait_message = json.dumps(
        {
            "control": "needs_input",
            "interaction": {
                "category": "root_selection",
                "multiple": True,
                "question": "Choose a root",
                "options": ["root-A", "root-B"],
            },
        },
        separators=(",", ":"),
    )
    stream = tmp_path / "stream.jsonl"
    _write_jsonl(
        stream,
        [
            {"type": "thread.started", "thread_id": PARENT},
            _spawn(TARGET),
            _spawn(OTHER),
            {
                "type": "item.completed",
                "item": {
                    "type": "collab_tool_call",
                    "tool": "wait",
                    "receiver_thread_ids": [OTHER],
                    "agents_states": {OTHER: {"message": wait_message}},
                },
            },
        ],
    )

    marker = tmp_path / "marker"
    marker.touch()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    parent = sessions / "parent.jsonl"
    _write_jsonl(parent, _target_parent_rollout())
    _freshen(parent, marker)

    result = _check("c3-leg1", stream, marker, sessions)
    assert result.returncode == 1, result.stderr


def test_unrelated_fresh_malformed_rollout_does_not_poison_target_c2(tmp_path: Path) -> None:
    """Only a scoped rollout may make formal evidence MALFORMED."""
    stream = tmp_path / "stream.jsonl"
    _write_jsonl(
        stream,
        [
            {"type": "thread.started", "thread_id": PARENT},
            _spawn(TARGET),
        ],
    )

    marker = tmp_path / "marker"
    marker.touch()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    target = sessions / "target.jsonl"
    unrelated = sessions / "unrelated.jsonl"
    _write_jsonl(target, _native_c2_rollout(TARGET))
    unrelated.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": OTHER}}) + "\n"
        + '{"type":"response_item","payload": BROKEN}\n',
        encoding="utf-8",
    )
    _freshen(target, marker)
    _freshen(unrelated, marker)

    result = _check("c2", stream, marker, sessions, sentinel=SENTINEL)
    assert result.returncode == 0, result.stderr
