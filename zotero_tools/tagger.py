"""Load the canonical tagger without depending on the checkout path."""

import importlib.util
import os
from pathlib import Path


RESOURCE_ROOT_ENV = "ZOTERO_TOOLS_RESOURCE_ROOT"


def _tagger_source() -> Path:
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

    source = skills_root / "zotero-paper-tagger" / "scripts" / "tagger.py"
    if not source.is_file():
        raise FileNotFoundError(f"canonical tagger script not found at: {source}")
    return source


def main() -> None:
    source = _tagger_source()
    spec = importlib.util.spec_from_file_location("zotero_paper_tagger_canonical", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load canonical tagger: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


if __name__ == "__main__":
    main()
