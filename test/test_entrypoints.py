import os
import subprocess
import sys
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_module(module, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=Path("/tmp"),
        env=env,
        capture_output=True,
        text=True,
    )


def test_tagger_help_is_available_from_any_cwd():
    result = run_module("zotero_tools.tagger", "--help")
    assert result.returncode == 0
    assert "zotero-paper-tagger" in result.stdout


def test_tagger_rejects_unknown_arguments():
    result = run_module("zotero_tools.tagger", "--not-a-real-option")
    assert result.returncode != 0


def test_backfill_uses_configured_storage_root(tmp_path, monkeypatch):
    source = ROOT / ".apm/skills/zotero-paper-tagger/scripts/corresp_backfill.py"
    spec = importlib.util.spec_from_file_location("backfill_under_test", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    storage = tmp_path / "storage"
    monkeypatch.setenv("ZOTERO_STORAGE_ROOT", str(storage))
    item = {"key": "ITEM1234", "data": {"itemType": "attachment",
            "parentItem": "PARENT01", "contentType": "application/pdf",
            "filename": "paper.pdf"}}
    module.T.fetch_collection_items = lambda key: {item["key"]: item}
    module.T.get_subcollections = lambda mcp, key: []
    mapping_dir = tmp_path / "教授研究"
    mapping_dir.mkdir()
    (mapping_dir / module.T.MAPPING_NAME).write_text(
        '{"professors":{"Professor A":["University A/Program A/Professor A"]},'
        '"collections":{"University A/Program A/Professor A":{"key":"COLL1234"}}}',
        encoding="utf-8")

    result = module.collect_items(object(), tmp_path)
    assert result[1]["PARENT01"] == storage / "ITEM1234" / "paper.pdf"


def test_backfill_defaults_to_home_zotero_storage(tmp_path, monkeypatch):
    source = ROOT / ".apm/skills/zotero-paper-tagger/scripts/corresp_backfill.py"
    spec = importlib.util.spec_from_file_location("backfill_default_under_test", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.delenv("ZOTERO_STORAGE_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    item = {"key": "ITEM1234", "data": {"itemType": "attachment",
            "parentItem": "PARENT01", "contentType": "application/pdf",
            "filename": "paper.pdf"}}
    module.T.fetch_collection_items = lambda key: {item["key"]: item}
    module.T.get_subcollections = lambda mcp, key: []
    mapping_dir = tmp_path / "program" / "教授研究"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / module.T.MAPPING_NAME).write_text(
        '{"professors":{"Professor A":["University A/Program A/Professor A"]},'
        '"collections":{"University A/Program A/Professor A":{"key":"COLL1234"}}}',
        encoding="utf-8")

    result = module.collect_items(object(), tmp_path / "program")
    assert result[1]["PARENT01"] == tmp_path / "Zotero" / "storage" / "ITEM1234" / "paper.pdf"
