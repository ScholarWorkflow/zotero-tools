"""Codex projection regression tests for issue #14.

The APM Codex conversion was re-measured with APM 0.29.0: the Codex target deploys
``.codex/agents/<name>.toml`` keeping only ``name``, ``description`` and
``developer_instructions`` (the agent body verbatim) and dropping the OpenCode-native
``mode`` / ``hidden`` / ``temperature`` / ``permission`` frontmatter. These gates
freeze that measured contract and require the body-level compatibility conventions
(root cause of lost metadata) to survive into the generated ``developer_instructions``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from apm_projection import (
    AGENT_PATH,
    SKILL_PATH,
    canonical_agent_body,
    canonical_agent_description,
    project_to_consumer,
)

#: Body-level conventions that must survive Codex conversion verbatim. They cover
#: the measured metadata losses (mode/hidden/temperature/permission) and the
#: interaction bridge contract required by issue #14.
CONVENTION_MARKERS = (
    # lost frontmatter must be re-expressed as orchestration convention, never ACL
    "orchestration convention, not a security boundary",
    "no runtime (including Codex) provides OpenCode-style per-agent permission enforcement",
    # single business source of truth
    "ONLY from the canonical `zotero-collection-cleaner` skill",
    # native Zotero MCP route, no shim
    "Codex hard rule — Zotero route",
    "your first and only Zotero access path is the session's native Zotero MCP tools",
    "a failed curl probe must NOT be reported as Zotero being unreachable",
    "Absence of MCP *resources* is irrelevant: check for MCP *tools*",
    "native Zotero MCP server configured for the session/consumer",
    "Do not implement or expect a `skill_mcp()` shim",
    "never use bash curl to probe or reach Zotero",
    "the reachability signal is whether the session's native Zotero MCP tools respond",
    # interaction bridge: no implicit defaults, transient needs_input, same-child resume
    "Only when `question` is NOT available (Codex)",
    "(a) root selection when no `program_roots` is given",
    "(b) canonical tie-break when the priority chain still ties",
    "(c) plan confirmation (`执行` / `放弃` / `放弃，仅看报告`)",
    "do NOT pick any default or recommended option silently",
    "MUST resume the SAME child thread/session",
    "Spawning a fresh child is NOT a resume",
    # interaction cardinality: per-category selection semantics must survive projection
    "Selection cardinality per category",
    "`root_selection` → `multiple: true`",
    "`canonical_tie_break` → `multiple: false`",
    "`plan_confirmation` → `multiple: false`",
    '"multiple": "<true for root_selection; false for canonical_tie_break and plan_confirmation',
    # transient control message, no business schema change
    '"control": "needs_input"',
    '"category": "root_selection|canonical_tie_break|plan_confirmation"',
    '"resume_token"',
    "NOT a persisted business artifact",
)

#: APM 0.29.0 measured contract: the Codex agent TOML has exactly these keys.
CODEX_AGENT_KEYS = {"name", "description", "developer_instructions"}


def _codex_conventions_missing(instructions: str) -> list[str]:
    return [marker for marker in CONVENTION_MARKERS if marker not in instructions]


def _load_codex_agent(consumer: Path) -> dict:
    generated = consumer / ".codex" / "agents" / "zotero-collection-cleaner.toml"
    assert generated.is_file(), f"missing generated Codex agent: {generated}"
    return tomllib.loads(generated.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def codex_consumer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return project_to_consumer(tmp_path_factory.mktemp("codex"), "codex")


def test_codex_projection_generates_exact_name_agent(codex_consumer: Path) -> None:
    agent = _load_codex_agent(codex_consumer)
    assert agent["name"] == "zotero-collection-cleaner"


def test_codex_projection_is_traceable_to_canonical_source(codex_consumer: Path) -> None:
    agent = _load_codex_agent(codex_consumer)
    assert agent["description"] == canonical_agent_description()
    assert agent["developer_instructions"].strip() == canonical_agent_body().strip()


def test_codex_projection_drops_opencode_metadata_without_substitutes(
    codex_consumer: Path,
) -> None:
    agent = _load_codex_agent(codex_consumer)
    # Measured APM 0.29.0 behaviour: OpenCode-native metadata is dropped, and the
    # generated TOML must not invent permission-enforcement substitutes either.
    assert set(agent) == CODEX_AGENT_KEYS
    for dropped in ("mode", "hidden", "temperature", "permission"):
        assert dropped not in agent


def test_codex_body_conventions_survive_conversion(codex_consumer: Path) -> None:
    instructions = _load_codex_agent(codex_consumer)["developer_instructions"]
    missing = _codex_conventions_missing(instructions)
    assert not missing, f"conventions lost in Codex conversion: {missing}"


def test_codex_instructions_distinguish_convention_from_enforcement(
    codex_consumer: Path,
) -> None:
    instructions = _load_codex_agent(codex_consumer)["developer_instructions"]
    assert "orchestration convention, not a security boundary" in instructions
    assert "no runtime (including Codex) provides OpenCode-style per-agent permission enforcement" in instructions
    # The generated TOML must not fabricate a permission enforcement surface.
    agent = _load_codex_agent(codex_consumer)
    assert "permission" not in agent


def test_codex_projection_deploys_canonical_skill_without_overlay_copy(
    codex_consumer: Path,
) -> None:
    deployed = codex_consumer / ".agents" / "skills" / "zotero-collection-cleaner" / "SKILL.md"
    assert deployed.is_file(), "canonical cleaner skill not deployed to the consumer"
    assert deployed.read_bytes() == SKILL_PATH.read_bytes(), (
        "deployed skill diverged from the producer canonical SKILL.md"
    )

    # apm_modules/ is APM's internal source cache, not a deployed surface; the
    # overlay check only covers what a runtime would actually load.
    deployed_surfaces = [codex_consumer / ".agents", codex_consumer / ".codex"]
    copies = [
        path
        for surface in deployed_surfaces
        for path in surface.rglob("SKILL.md")
        if path.parent.name == "zotero-collection-cleaner"
    ]
    assert copies == [deployed], f"unexpected consumer overlay copy: {copies}"


def test_codex_projection_surfaces_have_no_central_runtime_dependency(
    codex_consumer: Path,
) -> None:
    surfaces = [codex_consumer / "apm.yml"]
    surfaces.extend((codex_consumer / ".codex").rglob("*"))
    surfaces.extend((codex_consumer / ".agents").rglob("*"))
    markers = (
        "scholarflow-codex",
        "bootstrap-codex",
        "codex_agent_normalize",
        "codex-agents-override",
        "consumer compatibility overlay",
    )
    for surface in surfaces:
        if not surface.is_file():
            continue
        text = surface.read_text(encoding="utf-8", errors="replace").lower()
        for marker in markers:
            assert marker not in text, f"{surface}: forbidden runtime dependency {marker!r}"


def test_convention_gate_is_not_vacuous(tmp_path: Path) -> None:
    """Deleting the compatibility section from the source must break the gate."""

    def drop_compatibility_section(producer: Path) -> None:
        agent = producer / ".apm" / "agents" / "zotero-collection-cleaner.agent.md"
        text = agent.read_text(encoding="utf-8")
        cut = text.index("## Runtime compatibility (Codex)")
        agent.write_text(text[:cut], encoding="utf-8")

    consumer = project_to_consumer(tmp_path, "codex", mutate=drop_compatibility_section)
    instructions = _load_codex_agent(consumer)["developer_instructions"]
    missing = _codex_conventions_missing(instructions)
    assert missing, "mutation did not affect the gate; the convention gate is vacuous"
