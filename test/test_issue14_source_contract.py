"""Characterization tests for issue #14's producer-local compatibility migration.

These tests intentionally freeze facts that are already true on master and must remain
true while Codex compatibility is implemented. They do *not* encode an assumed APM
Codex projection: the implementation must first re-measure the installed APM version,
then add projection/runtime tests for the verified conversion contract.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / ".apm" / "agents" / "zotero-collection-cleaner.agent.md"
SKILL_PATH = ROOT / ".apm" / "skills" / "zotero-collection-cleaner" / "SKILL.md"

EXPECTED_PERMISSION_MAP = {
    "read": "allow",
    "glob": "allow",
    "grep": "allow",
    "edit": "allow",
    "write": "allow",
    "bash": "allow",
    "webfetch": "allow",
    "websearch": "allow",
    "skill": "allow",
    "skill_mcp": "allow",
    "todowrite": "allow",
    "question": "allow",
    "external_directory": "allow",
}

CENTRAL_RUNTIME_MARKERS = (
    "scholarflow-codex",
    "bootstrap-codex",
    "codex_agent_normalize",
    "codex-agents-override",
    "consumer compatibility overlay",
)


def _scalar(value: str):
    value = value.strip()
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        pass
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", f"{path}: missing frontmatter opener"
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise AssertionError(f"{path}: missing frontmatter closer") from exc

    frontmatter: dict = {}
    nested: dict | None = None
    for line in lines[1:closing]:
        if not line.strip():
            continue
        if line[0].isspace():
            assert nested is not None, f"{path}: unexpected nested field"
            key, separator, value = line.strip().partition(":")
            assert separator, f"{path}: malformed nested field"
            nested[key] = _scalar(value)
            continue
        key, separator, value = line.partition(":")
        assert separator, f"{path}: malformed frontmatter field"
        if value.strip():
            nested = None
            frontmatter[key] = _scalar(value)
        else:
            nested = {}
            frontmatter[key] = nested

    return frontmatter, "\n".join(lines[closing + 1 :])


def test_manifest_keeps_both_targets_and_python_runtime_independent() -> None:
    apm = (ROOT / "apm.yml").read_text(encoding="utf-8")
    assert "targets: [opencode, codex]" in apm

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"].get("dependencies") == []


def test_opencode_cleaner_frontmatter_contract_is_frozen() -> None:
    frontmatter, body = _parse_frontmatter(AGENT_PATH)

    assert frontmatter["name"] == "zotero-collection-cleaner"
    assert frontmatter["mode"] == "subagent"
    assert frontmatter["hidden"] is True
    assert frontmatter["temperature"] == 0.2
    assert frontmatter["permission"] == EXPECTED_PERMISSION_MAP
    assert body.strip()


def test_current_opencode_interaction_semantics_are_characterized() -> None:
    _, body = _parse_frontmatter(AGENT_PATH)

    assert 'skill(name: "zotero-collection-cleaner")' in body
    assert 'question` (multiple: true): "清理哪些 program root 的 Zotero 分类？"' in body
    assert "tie → `question`" in body
    assert "`执行` / `放弃` / `放弃，仅看报告`" in body
    assert "mode == \"plan\"" in body


def test_canonical_cleanup_business_invariants_are_frozen() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")

    required_markers = (
        "所有名字匹配必须 NFKC 归一化",
        "Tier-2",
        "绝不动作",
        "执行前必须已获得用户确认",
        "fail-stop",
        "_zotero_cleanup_actions.jsonl",
        "逐个串行",
        "幂等契约",
        "不写 `_zotero_collections.json`",
    )
    for marker in required_markers:
        assert marker in skill, f"missing protected cleanup invariant: {marker}"

    priority = (
        "**mapping 记录**",
        "**直接条目更多**",
        "**直接子分类更多**",
        "**快照顺序第一**",
    )
    positions = [skill.index(marker) for marker in priority]
    assert positions == sorted(positions), "canonical selection priority changed"


def test_cleaner_final_business_result_contract_is_characterized() -> None:
    _, body = _parse_frontmatter(AGENT_PATH)

    for marker in (
        '"result": "ok|partial|error|needs_input"',
        '"program_root": "<abs>"',
        '"mapping_file": "<abs or null>"',
        '"plan_file": "<abs or null>"',
        '"report_md": "<abs or null>"',
        '"status": "clean|cleaned|report_only|error"',
        '"dup_groups": 0',
        '"tier1_deletes": 0',
        '"tier1_reparents": 0',
        '"item_moves": 0',
        '"tier2_groups_reported": 0',
        '"hanging_reported": 0',
        '"empty_reported": 0',
        '"mapping_updated": true',
    ):
        assert marker in body, f"cleaner result contract changed: {marker}"


def test_active_runtime_surfaces_do_not_depend_on_central_codex_control_plane() -> None:
    surfaces = [ROOT / "apm.yml", ROOT / "pyproject.toml"]
    surfaces.extend((ROOT / ".apm").rglob("*.md"))
    surfaces.extend((ROOT / ".apm").rglob("*.py"))
    surfaces.extend((ROOT / "zotero_tools").rglob("*.py"))

    for surface in surfaces:
        text = surface.read_text(encoding="utf-8").lower()
        for marker in CENTRAL_RUNTIME_MARKERS:
            assert marker not in text, f"{surface}: forbidden runtime dependency {marker!r}"
