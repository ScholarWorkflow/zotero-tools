"""Stable entry point for the existing Zotero MCP session helper."""

import subprocess
from pathlib import Path


def main() -> None:
    helper = Path(__file__).resolve().parents[1] / ".apm/skills/zotero-read/scripts/new-session.sh"
    raise SystemExit(subprocess.run(["bash", str(helper)], check=False).returncode)


if __name__ == "__main__":
    main()
