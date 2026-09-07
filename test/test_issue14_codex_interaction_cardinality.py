"""Regression gate for issue #14 Codex interaction cardinality.

The Codex ``needs_input`` bridge must preserve the selection semantics of the
canonical OpenCode interactions. Root selection is multi-select; canonical
Tie-break and plan confirmation are single-select.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / ".apm" / "agents" / "zotero-collection-cleaner.agent.md"


def _compatibility_section() -> str:
    text = AGENT_PATH.read_text(encoding="utf-8")
    marker = "## Runtime compatibility (Codex)"
    assert marker in text, "missing Codex compatibility section"
    return text.split(marker, 1)[1]


def _declares_cardinality(section: str, category: str, expected: str) -> bool:
    pattern = rf"{re.escape(category)}.{{0,200}}multiple.{{0,40}}{expected}"
    return re.search(pattern, section, flags=re.IGNORECASE | re.DOTALL) is not None


def test_codex_needs_input_preserves_interaction_selection_cardinality() -> None:
    section = _compatibility_section()

    assert _declares_cardinality(section, "root_selection", "true"), (
        "Codex root_selection must remain multi-select (multiple=true); "
        "a generic needs_input example with multiple=false changes the existing interaction contract"
    )
    assert _declares_cardinality(section, "canonical_tie_break", "false"), (
        "Codex canonical_tie_break must remain single-select (multiple=false)"
    )
    assert _declares_cardinality(section, "plan_confirmation", "false"), (
        "Codex plan_confirmation must remain single-select (multiple=false)"
    )
