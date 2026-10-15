"""Stable entry point for the existing Zotero MCP session helper."""

import os
import subprocess
from pathlib import Path


RESOURCE_ROOT_ENV = "ZOTERO_TOOLS_RESOURCE_ROOT"


def _session_helper() -> Path:
    resource_root = os.environ.get(RESOURCE_ROOT_ENV)
    if resource_root is None:
        skills_root = Path(__file__).resolve().parents[1] / ".apm" / "skills"
    elif not resource_root.strip():
        raise RuntimeError(
            f"{RESOURCE_ROOT_ENV} must name a directory containing "
            "zotero-paper-tagger and zotero-read"
        )
    else:
        skills_root = Path(resource_root).expanduser()

    helper = skills_root / "zotero-read" / "scripts" / "new-session.sh"
    if not helper.is_file():
        raise FileNotFoundError(f"Zotero session helper not found at: {helper}")
    return helper


def main() -> None:
    helper = _session_helper()
    raise SystemExit(subprocess.run(["bash", str(helper)], check=False).returncode)


if __name__ == "__main__":
    main()
