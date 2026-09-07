"""Shared APM projection helpers for the issue #14 compatibility gates.

These helpers drive the *installed* APM CLI against a copy of the current worktree
source and deploy it into a throwaway consumer directory. APM is a pinned test/dev
tool (not a runtime dependency): the projection gates only run against the verified
converter version and skip otherwise, so the merge gate never rides on a moving
"latest".
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / ".apm" / "agents" / "zotero-collection-cleaner.agent.md"
SKILL_PATH = ROOT / ".apm" / "skills" / "zotero-collection-cleaner" / "SKILL.md"

#: The APM CLI version whose Codex/OpenCode conversion behaviour was measured
#: for these gates (see test_apm_codex_projection / test_apm_opencode_projection).
VERIFIED_APM_VERSION = "0.29.0"

_COPY_IGNORE = shutil.ignore_patterns(
    ".venv",
    ".git",
    "__pycache__",
    "*.egg-info",
    ".pytest_cache",
    "apm_modules",
)


def _installed_apm_version() -> str | None:
    try:
        result = subprocess.run(
            ["apm", "--version"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"version (\S+)", result.stdout)
    return match.group(1) if match else None


def require_verified_apm() -> None:
    """Skip unless the installed APM CLI is the verified converter version."""
    version = _installed_apm_version()
    if version is None:
        pytest.skip(f"APM CLI not installed; projection gates need apm {VERIFIED_APM_VERSION}")
    if version != VERIFIED_APM_VERSION:
        pytest.skip(
            f"APM {version} is not the verified converter {VERIFIED_APM_VERSION}; "
            "re-measure the conversion before gating on it"
        )


def canonical_agent_text() -> str:
    return AGENT_PATH.read_text(encoding="utf-8")


def canonical_agent_body() -> str:
    lines = canonical_agent_text().splitlines()
    closing = lines.index("---", 1)
    return "\n".join(lines[closing + 1 :])


def canonical_agent_description() -> str:
    lines = canonical_agent_text().splitlines()
    closing = lines.index("---", 1)
    for line in lines[1:closing]:
        if line.startswith("description:"):
            value = line.split(":", 1)[1].strip()
            assert len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"
            return value[1:-1]
    raise AssertionError("canonical agent has no description frontmatter field")


def project_to_consumer(
    tmp_path: Path,
    target: str,
    mutate: Callable[[Path], None] | None = None,
) -> Path:
    """Deploy the current worktree source into a fresh consumer for ``target``."""
    require_verified_apm()

    producer = tmp_path / "producer"
    shutil.copytree(ROOT, producer, ignore=_COPY_IGNORE)
    if mutate is not None:
        mutate(producer)

    consumer = tmp_path / f"consumer-{target}"
    consumer.mkdir()
    subprocess.run(
        ["apm", "install", str(producer), "--target", target],
        cwd=consumer,
        check=True,
        capture_output=True,
        text=True,
    )
    return consumer
