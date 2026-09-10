"""Packaged-surface endpoint source contract for issue #21 (T7/T8).

Locks the shape that actually affects transport:
- every repo-owned active caller resolves ZOTERO_HTTP_URL / ZOTERO_MCP_URL at
  runtime instead of baking a production literal into the final request URL;
- packaged executable docs use the same default-expansion contract;
- the MCP endpoint variable is a FULL endpoint (never composed with /mcp again);
- the Codex cleaner keeps its native-MCP-only hard rule.

The gate is implemented as a pure function over surface texts so the negative
test can prove it detects reintroduced hardcodes (non-vacuous check).
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ENDPOINTS_PATH = ROOT / "zotero_tools/endpoints.py"
ITEM_EXPORT_PATH = ROOT / "zotero_tools/item_export.py"
NEW_SESSION_PATH = ROOT / ".apm/skills/zotero-read/scripts/new-session.sh"
TAGGER_SCRIPT_PATH = ROOT / ".apm/skills/zotero-paper-tagger/scripts/tagger.py"
READ_SKILL_PATH = ROOT / ".apm/skills/zotero-read/SKILL.md"
COLLECTIONS_SKILL_PATH = ROOT / ".apm/skills/zotero-collections/SKILL.md"
CLEANER_SKILL_PATH = ROOT / ".apm/skills/zotero-collection-cleaner/SKILL.md"
TAGGER_SKILL_PATH = ROOT / ".apm/skills/zotero-paper-tagger/SKILL.md"
CLEANER_AGENT_PATH = ROOT / ".apm/agents/zotero-collection-cleaner.agent.md"

ACTIVE_CALLER_SURFACES = (
    ENDPOINTS_PATH,
    ITEM_EXPORT_PATH,
    NEW_SESSION_PATH,
    TAGGER_SCRIPT_PATH,
)
DOC_SURFACES = (
    READ_SKILL_PATH,
    COLLECTIONS_SKILL_PATH,
    CLEANER_SKILL_PATH,
    TAGGER_SKILL_PATH,
    CLEANER_AGENT_PATH,
)
CONTRACT_SURFACES = (*ACTIVE_CALLER_SURFACES, *DOC_SURFACES)

BARE_DEFAULT_URL_PATTERN = re.compile(r"http://(?:127\.0\.0\.1|localhost):(23119|23120)")
MCP_FULL_ENDPOINT_DEFAULT = "ZOTERO_MCP_URL:-http://127.0.0.1:23120/mcp"
HTTP_BASE_DEFAULT = "ZOTERO_HTTP_URL:-http://127.0.0.1:23119"
CODEX_NATIVE_MCP_MARKER = "never use bash curl to probe or reach Zotero"


def endpoint_violations(surfaces: dict[Path, str]) -> list[str]:
    violations: list[str] = []

    endpoints_text = surfaces.get(ENDPOINTS_PATH, "")
    for env_name in ("ZOTERO_HTTP_URL", "ZOTERO_MCP_URL"):
        if env_name not in endpoints_text:
            violations.append(f"{ENDPOINTS_PATH}: central resolver missing {env_name}")

    item_export_text = surfaces.get(ITEM_EXPORT_PATH, "")
    if re.search(r'^MCP_URL\s*=\s*"http', item_export_text, re.MULTILINE):
        violations.append(f"{ITEM_EXPORT_PATH}: independent MCP endpoint constant reintroduced")
    if "zotero_mcp_url()" not in item_export_text:
        violations.append(f"{ITEM_EXPORT_PATH}: transport must resolve zotero_mcp_url() at call time")

    new_session_text = surfaces.get(NEW_SESSION_PATH, "")
    if MCP_FULL_ENDPOINT_DEFAULT not in new_session_text:
        violations.append(f"{NEW_SESSION_PATH}: missing default-expansion contract ({MCP_FULL_ENDPOINT_DEFAULT})")
    if 'ZOTERO_MCP_URL="${ZOTERO_MCP_URL' not in new_session_text:
        violations.append(f"{NEW_SESSION_PATH}: MCP URL must come from the environment with a default")

    tagger_text = surfaces.get(TAGGER_SCRIPT_PATH, "")
    if re.search(r'^READ_BASE\s*=\s*"http', tagger_text, re.MULTILINE):
        violations.append(f"{TAGGER_SCRIPT_PATH}: unconditional READ_BASE constant reintroduced")
    if re.search(r'^MCP_URL\s*=\s*"http', tagger_text, re.MULTILINE):
        violations.append(f"{TAGGER_SCRIPT_PATH}: unconditional MCP_URL constant reintroduced")
    for env_name in ("ZOTERO_HTTP_URL", "ZOTERO_MCP_URL"):
        if env_name not in tagger_text:
            violations.append(f"{TAGGER_SCRIPT_PATH}: transport must honor {env_name}")

    for path in surfaces:
        if path in DOC_SURFACES:
            text = surfaces[path]
            uses_mcp_var = "$ZOTERO_MCP_URL" in text
            uses_http_var = "$ZOTERO_HTTP_URL" in text
            if uses_mcp_var and MCP_FULL_ENDPOINT_DEFAULT not in text:
                violations.append(f"{path}: must state the full-endpoint default ({MCP_FULL_ENDPOINT_DEFAULT})")
            if uses_http_var and HTTP_BASE_DEFAULT not in text:
                violations.append(f"{path}: must state the HTTP base default ({HTTP_BASE_DEFAULT})")
            if uses_mcp_var and "$ZOTERO_MCP_URL/mcp" in text:
                violations.append(f"{path}: $ZOTERO_MCP_URL is a full endpoint; appending /mcp is forbidden")

    for path, text in surfaces.items():
        for number, line in enumerate(text.splitlines(), 1):
            sanctioned_default_expansion = (
                "${ZOTERO_MCP_URL:-" in line or "${ZOTERO_HTTP_URL:-" in line
            )
            if (
                "curl" in line
                and not sanctioned_default_expansion
                and BARE_DEFAULT_URL_PATTERN.search(line)
            ):
                violations.append(
                    f"{path}:{number}: bare production-default URL used as a curl target"
                )
            if "/mcp/mcp" in line:
                violations.append(f"{path}:{number}: double /mcp/mcp endpoint composition")

    agent_text = surfaces.get(CLEANER_AGENT_PATH, "")
    if CODEX_NATIVE_MCP_MARKER not in agent_text:
        violations.append(f"{CLEANER_AGENT_PATH}: Codex native-MCP-only hard rule was removed")

    return violations


def _read_repo_surfaces() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in CONTRACT_SURFACES}


def test_packaged_surfaces_follow_the_endpoint_contract():
    violations = endpoint_violations(_read_repo_surfaces())
    assert not violations, "endpoint contract violations:\n" + "\n".join(violations)


def test_active_callers_hold_default_literals_only_in_default_definitions():
    """Default literals in active callers appear only as the central/default
    definition; the final request URL must come from the runtime resolver."""
    new_session_lines = [
        line
        for line in NEW_SESSION_PATH.read_text(encoding="utf-8").splitlines()
        if BARE_DEFAULT_URL_PATTERN.search(line)
    ]
    assert len(new_session_lines) == 1, f"unexpected default literals in helper: {new_session_lines}"
    assert ":-" in new_session_lines[0]

    endpoints_lines = [
        line
        for line in ENDPOINTS_PATH.read_text(encoding="utf-8").splitlines()
        if BARE_DEFAULT_URL_PATTERN.search(line)
    ]
    assert endpoints_lines, "central default definition missing"
    assert all(
        "DEFAULT_ZOTERO_HTTP_URL" in line or "DEFAULT_ZOTERO_MCP_URL" in line
        for line in endpoints_lines
    )

    tagger_lines = [
        line
        for line in TAGGER_SCRIPT_PATH.read_text(encoding="utf-8").splitlines()
        if BARE_DEFAULT_URL_PATTERN.search(line)
    ]
    assert all(
        "DEFAULT_READ_BASE" in line or "DEFAULT_MCP_URL" in line for line in tagger_lines
    ), f"unexpected default literals in tagger: {tagger_lines}"

    assert not BARE_DEFAULT_URL_PATTERN.search(
        ITEM_EXPORT_PATH.read_text(encoding="utf-8")
    ), "item exporter must not carry its own default literal"


def test_gate_detects_reintroduced_hardcoded_callers():
    surfaces = _read_repo_surfaces()

    assert endpoint_violations(surfaces) == []

    surfaces[ITEM_EXPORT_PATH] += '\nMCP_URL = "http://127.0.0.1:23120/mcp"\n'
    assert any("independent MCP endpoint constant" in v for v in endpoint_violations(surfaces))

    surfaces = _read_repo_surfaces()
    surfaces[NEW_SESSION_PATH] += "curl -s -X POST http://127.0.0.1:23120/mcp\n"
    assert any("bare production-default URL" in v for v in endpoint_violations(surfaces))

    surfaces = _read_repo_surfaces()
    surfaces[READ_SKILL_PATH] += "curl -s --max-time 5 http://127.0.0.1:23119/connector/ping\n"
    assert any("bare production-default URL" in v for v in endpoint_violations(surfaces))

    surfaces = _read_repo_surfaces()
    surfaces[CLEANER_AGENT_PATH] = surfaces[CLEANER_AGENT_PATH].replace(CODEX_NATIVE_MCP_MARKER, "")
    assert any("native-MCP-only hard rule" in v for v in endpoint_violations(surfaces))

    surfaces = _read_repo_surfaces()
    surfaces[TAGGER_SCRIPT_PATH] = surfaces[TAGGER_SCRIPT_PATH].replace("ZOTERO_HTTP_URL", "")
    assert any("must honor ZOTERO_HTTP_URL" in v for v in endpoint_violations(surfaces))


def test_gate_detects_forbidden_mcp_recomposition():
    surfaces = _read_repo_surfaces()
    surfaces[READ_SKILL_PATH] += 'curl -s -X POST "$ZOTERO_MCP_URL/mcp" \\\n'
    assert any("/mcp/mcp" in v or "appending /mcp is forbidden" in v for v in endpoint_violations(surfaces))
