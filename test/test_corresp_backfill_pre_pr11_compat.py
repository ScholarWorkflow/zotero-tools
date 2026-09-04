import importlib.util
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / ".apm" / "skills" / "zotero-paper-tagger" / "scripts"


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = load_module("corresp_backfill_pre_pr11_test", "corresp_backfill.py")


def _item(title):
    return {
        "data": {
            "itemType": "journalArticle",
            "title": title,
            "DOI": "",
            "date": "2025",
        }
    }


def test_pre_pr11_schema_less_negative_is_not_auto_retried(tmp_path):
    """A historical pre-PR11 empty record must remain legacy, not become retryable.

    Before PR #11, corresp_backfill.record() already wrote schema-less empty
    records with channel='none', itemKey, fetched_at and provenance for any
    no-result path.  That shape is therefore not unique to PR #11 unavailable
    writes.  A record timestamped before PR #11 existed must not be silently
    reclassified as unavailable and auto-refetched by an ordinary backfill.
    """
    real = {"K1": _item("Historical empty result")}
    historical = {
        "contacts": [],
        "channel": "none",
        "names": [],
        "emails": [],
        "raw_text": "",
        # Deliberately predates PR #11, so this cannot be a PR #11 transient write.
        "fetched_at": "2026-09-03T00:00:00+00:00",
        "itemKey": "K1",
        "doi": None,
        "paper_year": 2025,
        "title": "Historical empty result",
    }
    before = dict(historical)

    with patch.object(B, "collect_items", return_value=(real, {})), \
            patch.object(B, "load_cache", return_value={"K1": dict(historical)}), \
            patch.object(B, "save_cache"):
        result = B.backfill_root(None, tmp_path, workers=1)

    assert result["stats"]["no_source"] == 0
    assert result["stats"]["legacy_needs_refresh"] == 1
    assert result["cache"]["K1"] == before
    assert B.classify_record(before) == "legacy"
