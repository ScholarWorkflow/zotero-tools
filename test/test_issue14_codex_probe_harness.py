"""Focused regression gates for the issue #14 Codex acceptance harness."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "test" / "acceptance" / "codex_probe.sh"


def _availability_regex() -> str:
    text = HARNESS.read_text(encoding="utf-8")
    match = re.search(r"^AVAILABILITY_RE='([^']+)'$", text, flags=re.MULTILINE)
    assert match is not None, "acceptance harness must define AVAILABILITY_RE"
    return match.group(1)


def _matches_ere(pattern: str, message: str) -> bool:
    result = subprocess.run(
        ["grep", "-Eq", pattern],
        input=message,
        text=True,
        check=False,
    )
    return result.returncode == 0


def test_resume_uses_codex_exec_resume_subcommand_without_duplicate_exec() -> None:
    """`codex exec resume` must not be emitted as `codex exec ... exec resume`.

    The harness already prefixes every invocation with `codex exec`.  Therefore the
    resume-specific argument vector must begin with `resume`, not another `exec`.
    Keeping this as a deterministic source gate prevents C3's SAME-child evidence
    from being invalidated by a malformed CLI invocation.
    """

    text = HARNESS.read_text(encoding="utf-8")

    assert 'RESUME_ARGS=(resume "$RESUME_THREAD")' in text
    assert 'RESUME_ARGS=(exec resume "$RESUME_THREAD")' not in text


def test_model_unavailable_404_is_classified_as_harness_availability() -> None:
    """A removed/unavailable configured model is infrastructure, not repo failure.

    The final-SHA acceptance run actually observed this OpenRouter failure shape.
    Project consensus requires model/provider availability failures to stop quickly
    and be reported as HARNESS_MODEL_AVAILABILITY rather than FAIL_NO_EVIDENCE.
    """

    pattern = _availability_regex()

    assert _matches_ere(
        pattern,
        "HTTP 404: This model is unavailable for free — use minimax/minimax-m3",
    ), "model-unavailable HTTP 404 must classify as HARNESS_MODEL_AVAILABILITY"

    assert not _matches_ere(
        pattern,
        "Model metadata for openrouter/free not found; using fallback metadata",
    ), "benign model-metadata fallback must not be classified as availability failure"
