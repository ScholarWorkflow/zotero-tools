"""PR #17 regression gates for the pre-correlation target-scope race.

A spawned child is only a candidate until the parent rollout structurally
confirms the exact-name ``zotero-collection-cleaner`` spawn. Candidate evidence
must not be allowed to terminate a live probe before that correlation exists.
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
CANDIDATE = "22222222-2222-4222-8222-222222222222"
SENTINEL = "SYNTH-TRANSIENT-SCOPE-271828"


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


def _stream(path: Path, *extra: dict) -> Path:
    _write_jsonl(
        path,
        [
            {"type": "thread.started", "thread_id": PARENT},
            _spawn(CANDIDATE),
            *extra,
        ],
    )
    return path


def _native_c2_rollout(path: Path) -> Path:
    _write_jsonl(
        path,
        [
            {"type": "session_meta", "payload": {"id": CANDIDATE}},
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
        ],
    )
    return path


def _freshen(path: Path, marker: Path) -> None:
    stamp = marker.stat().st_mtime + 1.0
    os.utime(path, (stamp, stamp))


def _check(
    contract: str,
    stream: Path,
    marker: Path,
    *,
    sessions: Path | None = None,
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
    ]
    if sessions is not None:
        args += ["--scan-dir", str(sessions)]
    if sentinel is not None:
        args += ["--sentinel", sentinel]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def test_c2_candidate_cannot_match_before_exact_name_target_is_confirmed(tmp_path: Path) -> None:
    """A perfect MCP call from an unconfirmed spawned child is still pending."""
    stream = _stream(tmp_path / "stream.jsonl")
    marker = tmp_path / "marker"
    marker.touch()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    rollout = _native_c2_rollout(sessions / "candidate.jsonl")
    _freshen(rollout, marker)

    result = _check("c2", stream, marker, sessions=sessions, sentinel=SENTINEL)
    assert result.returncode == 1, result.stderr


def test_c3_leg1_candidate_cannot_match_before_exact_name_target_is_confirmed(
    tmp_path: Path,
) -> None:
    """A valid needs_input from an unconfirmed spawned child cannot terminate leg 1."""
    message = json.dumps(
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
    wait = {
        "type": "item.completed",
        "item": {
            "type": "collab_tool_call",
            "tool": "wait",
            "receiver_thread_ids": [CANDIDATE],
            "agents_states": {CANDIDATE: {"message": message}},
        },
    }
    stream = _stream(tmp_path / "stream.jsonl", wait)
    marker = tmp_path / "marker"
    marker.touch()

    result = _check("c3-leg1", stream, marker)
    assert result.returncode == 1, result.stderr


def test_unconfirmed_candidate_malformed_rollout_is_not_formal_evidence(
    tmp_path: Path,
) -> None:
    """MALFORMED applies only after a candidate becomes the confirmed target."""
    stream = _stream(tmp_path / "stream.jsonl")
    marker = tmp_path / "marker"
    marker.touch()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    rollout = sessions / "candidate.jsonl"
    rollout.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": CANDIDATE}})
        + "\n"
        + '{"type":"response_item","payload": BROKEN}\n',
        encoding="utf-8",
    )
    _freshen(rollout, marker)

    result = _check("c2", stream, marker, sessions=sessions, sentinel=SENTINEL)
    assert result.returncode == 1, result.stderr
