"""PR #17 regression gates for C1 canonical-skill-read semantics.

A successful tool call that merely mentions the canonical SKILL.md path must
not count as a skill load/read. C1 should require evidence that the tool action
actually reads the canonical skill, not just that its parsed arguments contain
the path token.
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
CHILD = "22222222-2222-4222-8222-222222222222"


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def _run_c1_command_case(tmp_path: Path, command: str) -> subprocess.CompletedProcess:
    stream = tmp_path / "stream.jsonl"
    _write_jsonl(
        stream,
        [
            {"type": "thread.started", "thread_id": PARENT},
            {
                "type": "item.completed",
                "item": {
                    "type": "collab_tool_call",
                    "tool": "spawn_agent",
                    "receiver_thread_ids": [CHILD],
                },
            },
        ],
    )

    marker = tmp_path / "marker"
    marker.touch()
    sessions = tmp_path / "sessions"
    sessions.mkdir()

    parent = sessions / "parent.jsonl"
    _write_jsonl(
        parent,
        [
            {"type": "session_meta", "payload": {"id": PARENT}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "spawn_agent",
                    "call_id": "call_spawn",
                    "arguments": json.dumps(
                        {"agent_type": "zotero-collection-cleaner"}, separators=(",", ":")
                    ),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call_spawn",
                    "output": json.dumps({"agent_id": CHILD}, separators=(",", ":")),
                },
            },
        ],
    )

    child = sessions / "child.jsonl"
    _write_jsonl(
        child,
        [
            {"type": "session_meta", "payload": {"id": CHILD}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call_noop",
                    "arguments": json.dumps({"cmd": command}, separators=(",", ":")),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call_noop",
                    "output": "Chunk ID: deadbeef\nProcess exited with code 0\nOutput:\n",
                },
            },
        ],
    )

    fresh = marker.stat().st_mtime + 1.0
    os.utime(parent, (fresh, fresh))
    os.utime(child, (fresh, fresh))

    return subprocess.run(
        [
            BASH,
            str(CONTROLLER),
            "check",
            "--contract",
            "c1",
            "--stream",
            str(stream),
            "--start-marker",
            str(marker),
            "--scan-dir",
            str(sessions),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_c1_path_mention_inside_successful_tool_call_is_not_a_skill_read(tmp_path: Path) -> None:
    result = _run_c1_command_case(
        tmp_path,
        "printf '%s\\n' zotero-collection-cleaner/SKILL.md >/dev/null",
    )
    assert result.returncode == 1, (
        "C1 must stay NO_MATCH when the tool call only mentions the SKILL.md path "
        f"without reading it; controller stderr: {result.stderr}"
    )


def test_c1_path_in_shell_comment_after_cat_is_not_a_skill_read(tmp_path: Path) -> None:
    result = _run_c1_command_case(
        tmp_path,
        "cat /dev/null # zotero-collection-cleaner/SKILL.md",
    )
    assert result.returncode == 1, (
        "C1 must stay NO_MATCH when cat reads a different file and the canonical "
        "SKILL.md path appears only in a shell comment; "
        f"controller stderr: {result.stderr}"
    )
