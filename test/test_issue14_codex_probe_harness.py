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


def test_probe_delegates_codex_execution_to_eval_service() -> None:
    """The harness must not start a local Codex CLI process.

    Project consensus owns Codex lifecycle and provider selection in the local
    eval service. The checked-in probe is only its JSON request/evidence
    adapter.
    """

    text = HARNESS.read_text(encoding="utf-8")

    assert "EVAL_PORT" in text
    assert "direnv exec" in text
    assert "--data-binary" not in text
    assert " -d " in text
    assert "--rawfile command" in text
    assert "--consumer-dir" in text
    assert "--cd" in text
    assert "--sandbox workspace-write" in text
    assert "codex exec" not in text


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


def test_rate_limit_exceeded_is_classified_as_harness_availability() -> None:
    """Free-tier daily rate-limit exhaustion is provider availability, not repo failure.

    The final-SHA acceptance run actually observed this OpenRouter failure shape:
    a 429 "Rate limit exceeded: free-models-per-day-high-balance" surfaced as a
    top-level stream error and must classify as HARNESS_MODEL_AVAILABILITY
    instead of FAIL_NO_EVIDENCE.
    """

    pattern = _availability_regex()

    assert _matches_ere(
        pattern,
        "Rate limit exceeded: free-models-per-day-high-balance",
    ), "free-tier rate-limit exhaustion must classify as HARNESS_MODEL_AVAILABILITY"

    assert not _matches_ere(
        pattern,
        "Model metadata for openrouter/free not found; using fallback metadata",
    ), "benign model-metadata fallback must not be classified as availability failure"
