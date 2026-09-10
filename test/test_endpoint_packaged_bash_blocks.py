"""Regression gate for issue #21 independently executable packaged bash blocks.

A fenced bash block is an execution boundary for an agent or a user copying the
published skill instructions.  If that block curls an endpoint variable, it
must establish the frozen unset/default + trailing-slash-normalization contract
inside the same block rather than relying on shell-local state from a previous
fence.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MCP_VAR = "$ZOTERO_MCP_URL"
MCP_DEFAULT = "ZOTERO_MCP_URL:-http://127.0.0.1:23120/mcp"
MCP_NORMALIZER = 'ZOTERO_MCP_URL="${ZOTERO_MCP_URL%/}"'
HTTP_VAR = "$ZOTERO_HTTP_URL"
HTTP_DEFAULT = "ZOTERO_HTTP_URL:-http://127.0.0.1:23119"
HTTP_NORMALIZER = 'ZOTERO_HTTP_URL="${ZOTERO_HTTP_URL%/}"'

PACKAGED_MARKDOWN_SURFACES = (
    ROOT / ".apm/skills/zotero-read/SKILL.md",
    ROOT / ".apm/skills/zotero-collections/SKILL.md",
    ROOT / ".apm/skills/zotero-collection-cleaner/SKILL.md",
)


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\s*\n(.*?)```", text, flags=re.DOTALL)


def _block_violations(
    text: str,
    *,
    variable: str,
    default_marker: str,
    normalizer: str,
) -> list[str]:
    violations: list[str] = []
    for index, block in enumerate(_bash_blocks(text), 1):
        if "curl" not in block or variable not in block:
            continue

        first_curl = block.find("curl")
        default_at = block.find(default_marker)
        normalizer_at = block.find(normalizer)
        if not (0 <= default_at < normalizer_at < first_curl):
            violations.append(
                f"bash block #{index} curls {variable} without resolving its default "
                "and normalizing it first in the same block"
            )
    return violations


def test_each_packaged_bash_block_resolves_endpoint_before_curl():
    failures: list[str] = []
    for path in PACKAGED_MARKDOWN_SURFACES:
        text = path.read_text(encoding="utf-8")
        for violation in _block_violations(
            text,
            variable=MCP_VAR,
            default_marker=MCP_DEFAULT,
            normalizer=MCP_NORMALIZER,
        ):
            failures.append(f"{path.relative_to(ROOT)}: {violation}")
        for violation in _block_violations(
            text,
            variable=HTTP_VAR,
            default_marker=HTTP_DEFAULT,
            normalizer=HTTP_NORMALIZER,
        ):
            failures.append(f"{path.relative_to(ROOT)}: {violation}")

    assert not failures, "packaged bash block endpoint violations:\n" + "\n".join(failures)


def test_packaged_bash_block_gate_is_non_vacuous():
    bad = """```bash
curl -s --max-time 60 -X POST "$ZOTERO_MCP_URL"
```
"""
    assert _block_violations(
        bad,
        variable=MCP_VAR,
        default_marker=MCP_DEFAULT,
        normalizer=MCP_NORMALIZER,
    )

    good = """```bash
ZOTERO_MCP_URL="${ZOTERO_MCP_URL:-http://127.0.0.1:23120/mcp}"
ZOTERO_MCP_URL="${ZOTERO_MCP_URL%/}"
curl -s --max-time 60 -X POST "$ZOTERO_MCP_URL"
```
"""
    assert _block_violations(
        good,
        variable=MCP_VAR,
        default_marker=MCP_DEFAULT,
        normalizer=MCP_NORMALIZER,
    ) == []
