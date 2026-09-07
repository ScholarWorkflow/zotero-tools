"""Focused regression gates for the issue #14 Codex acceptance harness."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "test" / "acceptance" / "codex_probe.sh"


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
