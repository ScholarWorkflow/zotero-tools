"""Regression for PR #17 C1 structured eval evidence.

A completed eval-stream ``spawn_agent`` event is a valid evidence surface.  The
controller must use structured receiver identity when the runtime exposes it;
a child report that merely repeats producer-owned headings is not a substitute
for that identity.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACC = ROOT / "test" / "acceptance"
CONTROLLER = ACC / "runtime_evidence.sh"
STREAM_EVAL_C1 = ACC / "fixtures" / "common" / "stream_eval_c1.jsonl"


def _run_c1(stream: Path, marker: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(CONTROLLER),
            "check",
            "--contract",
            "c1",
            "--stream",
            str(stream),
            "--start-marker",
            str(marker),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _rewrite_spawn_receiver_agents(stream: Path, receiver_agents: list[dict[str, str]]) -> None:
    rows = []
    for line in stream.read_text().splitlines():
        row = json.loads(line)
        item = row.get("item") if isinstance(row, dict) else None
        if (
            row.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "collab_tool_call"
            and item.get("tool") == "spawn_agent"
        ):
            item["receiver_agents"] = receiver_agents
        rows.append(row)
    stream.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))


def test_c1_eval_spawn_without_structured_role_is_no_match(tmp_path: Path) -> None:
    stream = tmp_path / "stream.jsonl"
    marker = tmp_path / "marker"
    marker.touch()
    shutil.copy(STREAM_EVAL_C1, stream)
    _rewrite_spawn_receiver_agents(stream, [])

    result = _run_c1(stream, marker)

    assert result.returncode == 1, (
        "C1 must stay NO_MATCH when eval proves that a child was spawned but "
        "does not structurally identify the spawned role; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_c1_eval_spawn_with_wrong_structured_role_is_no_match(tmp_path: Path) -> None:
    stream = tmp_path / "stream.jsonl"
    marker = tmp_path / "marker"
    marker.touch()
    shutil.copy(STREAM_EVAL_C1, stream)
    _rewrite_spawn_receiver_agents(
        stream,
        [
            {
                "thread_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "agent_role": "default",
            }
        ],
    )

    result = _run_c1(stream, marker)

    assert result.returncode == 1, (
        "C1 must stay NO_MATCH when eval structurally says the spawned child "
        "used the wrong role, even if the child message echoes cleaner headings; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
