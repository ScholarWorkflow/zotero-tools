"""Load the canonical tagger without depending on the checkout path."""

import importlib.util
from pathlib import Path


def main() -> None:
    source = Path(__file__).resolve().parents[1] / ".apm/skills/zotero-paper-tagger/scripts/tagger.py"
    spec = importlib.util.spec_from_file_location("zotero_paper_tagger_canonical", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load canonical tagger: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


if __name__ == "__main__":
    main()
