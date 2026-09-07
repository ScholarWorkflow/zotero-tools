from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / ".apm" / "agents"


def _frontmatter_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", f"{path}: missing opening frontmatter delimiter"
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise AssertionError(f"{path}: missing closing frontmatter delimiter") from exc
    return lines[1:end]


def test_agent_descriptions_quote_yaml_colon_space_scalars() -> None:
    agents = sorted(AGENTS_DIR.glob("*.agent.md"))
    assert agents, "expected at least one APM agent"

    for agent in agents:
        description_lines = [
            line for line in _frontmatter_lines(agent) if line.startswith("description:")
        ]
        assert len(description_lines) == 1, f"{agent}: expected exactly one description field"

        value = description_lines[0].split(":", 1)[1].strip()
        assert value, f"{agent}: description must be non-empty"

        if ": " in value:
            assert (
                len(value) >= 2
                and value[0] in {"'", '"'}
                and value[-1] == value[0]
            ), f"{agent}: description containing ': ' must be quoted for valid YAML"


def test_agent_frontmatter_fields_are_well_formed() -> None:
    agents = sorted(AGENTS_DIR.glob("*.agent.md"))
    assert agents, "expected at least one APM agent"

    for agent in agents:
        lines = _frontmatter_lines(agent)

        name_lines = [line for line in lines if line.startswith("name:")]
        assert len(name_lines) == 1, f"{agent}: expected exactly one name field"
        assert name_lines[0].split(":", 1)[1].strip(), f"{agent}: name must be non-empty"

        mode_lines = [line for line in lines if line.startswith("mode:")]
        assert len(mode_lines) == 1, f"{agent}: expected exactly one mode field"
        assert mode_lines[0].split(":", 1)[1].strip() in {"subagent", "primary", "all"}, (
            f"{agent}: unknown mode value"
        )

        permission_values = [
            line.split(":", 1)[1].strip()
            for line in lines
            if line.startswith("  ") and ":" in line
        ]
        for value in permission_values:
            assert value in {"allow", "ask", "deny"}, (
                f"{agent}: unexpected permission value {value!r}"
            )
