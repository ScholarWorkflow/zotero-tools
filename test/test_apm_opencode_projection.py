"""OpenCode projection regression tests for issue #14.

The measured APM 0.29.0 OpenCode conversion deploys the canonical agent verbatim
(frontmatter and body byte-identical) plus byte-identical canonical skills. These
gates freeze that contract and verify that the Codex compatibility wording added to
the canonical body does not redirect OpenCode away from its native `question()` path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apm_projection import AGENT_PATH, SKILL_PATH, project_to_consumer

CANONICAL_SKILLS = (
    "zotero-collection-cleaner",
    "zotero-collections",
    "zotero-paper-tagger",
    "zotero-read",
)

#: Native OpenCode interaction semantics that must stay intact in the projection.
OPENCODE_INTERACTION_MARKERS = (
    'skill(name: "zotero-collection-cleaner")',
    "`question` (multiple: true)",
    "tie → `question`",
    "`执行` / `放弃` / `放弃，仅看报告`",
    'mode == "plan"',
)


@pytest.fixture(scope="module")
def opencode_consumer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return project_to_consumer(tmp_path_factory.mktemp("opencode"), "opencode")


def test_opencode_projection_preserves_canonical_agent_verbatim(
    opencode_consumer: Path,
) -> None:
    deployed = opencode_consumer / ".opencode" / "agents" / "zotero-collection-cleaner.md"
    assert deployed.is_file(), "cleaner agent not deployed to the OpenCode consumer"
    assert deployed.read_bytes() == AGENT_PATH.read_bytes(), (
        "OpenCode projection is not a verbatim copy of the canonical agent"
    )


def test_opencode_projection_deploys_canonical_skills_verbatim(
    opencode_consumer: Path,
) -> None:
    for skill in CANONICAL_SKILLS:
        deployed = opencode_consumer / ".agents" / "skills" / skill / "SKILL.md"
        source = SKILL_PATH.parents[1] / skill / "SKILL.md"
        assert deployed.is_file(), f"canonical skill not deployed: {skill}"
        assert deployed.read_bytes() == source.read_bytes(), (
            f"deployed skill diverged from producer canonical source: {skill}"
        )


def test_opencode_projection_keeps_native_interaction_semantics(
    opencode_consumer: Path,
) -> None:
    deployed = opencode_consumer / ".opencode" / "agents" / "zotero-collection-cleaner.md"
    text = deployed.read_text(encoding="utf-8")
    for marker in OPENCODE_INTERACTION_MARKERS:
        assert marker in text, f"native OpenCode interaction semantics lost: {marker}"


def test_codex_wording_does_not_redirect_opencode_off_question(
    opencode_consumer: Path,
) -> None:
    """The needs_input bridge is scoped to runtimes without `question`."""
    deployed = opencode_consumer / ".opencode" / "agents" / "zotero-collection-cleaner.md"
    text = deployed.read_text(encoding="utf-8")
    assert (
        "if the native `question` tool is available (OpenCode), use it exactly as "
        "specified above and change nothing" in text
    ), "OpenCode must keep its native question() behaviour unchanged"
    assert "Only when `question` is NOT available (Codex)" in text, (
        "needs_input bridge must stay scoped to question-less runtimes"
    )
