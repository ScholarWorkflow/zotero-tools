"""Regression gate for issue #21 packaged shell endpoint normalization.

The frozen endpoint contract allows an explicit override to carry one trailing
slash. Every executable packaged shell surface that expands the endpoint
default must remove that slash before curl uses the destination. This keeps
installed skill/agent commands aligned with the Python resolver and the
zotero-read session helper.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MCP_DEFAULT = "ZOTERO_MCP_URL:-http://127.0.0.1:23120/mcp"
MCP_NORMALIZER = 'ZOTERO_MCP_URL="${ZOTERO_MCP_URL%/}"'
HTTP_DEFAULT = "ZOTERO_HTTP_URL:-http://127.0.0.1:23119"
HTTP_NORMALIZER = 'ZOTERO_HTTP_URL="${ZOTERO_HTTP_URL%/}"'

MCP_SHELL_SURFACES = (
    ROOT / ".apm/skills/zotero-read/scripts/new-session.sh",
    ROOT / ".apm/skills/zotero-read/SKILL.md",
    ROOT / ".apm/skills/zotero-collections/SKILL.md",
    ROOT / ".apm/skills/zotero-collection-cleaner/SKILL.md",
    ROOT / ".apm/agents/zotero-collection-cleaner.agent.md",
)
HTTP_SHELL_SURFACES = (
    ROOT / ".apm/skills/zotero-read/SKILL.md",
)


def _normalization_violations(text: str, default_marker: str, normalizer: str) -> list[str]:
    """Find default expansions whose next curl use precedes normalization."""
    violations: list[str] = []
    cursor = 0
    occurrence = 0

    while True:
        marker_at = text.find(default_marker, cursor)
        if marker_at == -1:
            break
        occurrence += 1

        line_start = text.rfind("\n", 0, marker_at) + 1
        line_end = text.find("\n", marker_at)
        if line_end == -1:
            line_end = len(text)

        curl_on_line = text.find("curl", line_start, line_end)
        normalizer_on_line = text.find(normalizer, marker_at, line_end)
        if curl_on_line != -1:
            if normalizer_on_line == -1 or normalizer_on_line > curl_on_line:
                violations.append(
                    f"default expansion #{occurrence} is used by curl before trailing-slash normalization"
                )
            cursor = marker_at + len(default_marker)
            continue

        next_curl = text.find("curl", marker_at)
        next_normalizer = text.find(normalizer, marker_at + len(default_marker))
        if next_normalizer == -1 or (next_curl != -1 and next_curl < next_normalizer):
            violations.append(
                f"default expansion #{occurrence} reaches curl before trailing-slash normalization"
            )

        cursor = marker_at + len(default_marker)

    if occurrence == 0:
        violations.append("expected endpoint default expansion is missing")
    return violations


def test_packaged_shell_surfaces_normalize_trailing_slash_before_curl():
    failures: list[str] = []

    for path in MCP_SHELL_SURFACES:
        text = path.read_text(encoding="utf-8")
        for violation in _normalization_violations(text, MCP_DEFAULT, MCP_NORMALIZER):
            failures.append(f"{path.relative_to(ROOT)}: {violation}")

    for path in HTTP_SHELL_SURFACES:
        text = path.read_text(encoding="utf-8")
        for violation in _normalization_violations(text, HTTP_DEFAULT, HTTP_NORMALIZER):
            failures.append(f"{path.relative_to(ROOT)}: {violation}")

    assert not failures, "packaged shell endpoint normalization violations:\n" + "\n".join(failures)


def test_normalization_gate_is_non_vacuous():
    bad = 'curl -s "${ZOTERO_MCP_URL:-http://127.0.0.1:23120/mcp}"\n'
    assert _normalization_violations(bad, MCP_DEFAULT, MCP_NORMALIZER)

    good = (
        'ZOTERO_MCP_URL="${ZOTERO_MCP_URL:-http://127.0.0.1:23120/mcp}"\n'
        'ZOTERO_MCP_URL="${ZOTERO_MCP_URL%/}"\n'
        'curl -s "$ZOTERO_MCP_URL"\n'
    )
    assert _normalization_violations(good, MCP_DEFAULT, MCP_NORMALIZER) == []
