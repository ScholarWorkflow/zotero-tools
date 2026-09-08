"""Regression for PR #17 C1 eval-only evidence.

The eval stream can prove that a child thread was spawned and later completed,
but the measured stream shape in ``stream_eval_c1.jsonl`` does not prove either
that the child was selected with ``agent_type == zotero-collection-cleaner`` or
that the child actually loaded/read the canonical SKILL.md. A child report that
merely contains producer-owned headings is model output, not wiring evidence.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACC = ROOT / "test" / "acceptance"
CONTROLLER = ACC / "runtime_evidence.sh"
STREAM_EVAL_C1 = ACC / "fixtures" / "common" / "stream_eval_c1.jsonl"


def test_c1_eval_only_child_report_cannot_prove_exact_agent_or_skill_load(
    tmp_path: Path,
) -> None:
    stream = tmp_path / "stream.jsonl"
    marker = tmp_path / "marker"
    marker.touch()
    shutil.copy(STREAM_EVAL_C1, stream)

    result = subprocess.run(
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

    assert result.returncode == 1, (
        "C1 must stay NO_MATCH until structured evidence proves both the exact "
        "producer-owned subagent identity and a real canonical SKILL.md read; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
