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


B = load_module("corresp_backfill_scope_test", "corresp_backfill.py")


def _item(title):
    return {
        "data": {
            "itemType": "journalArticle",
            "title": title,
            "DOI": "",
            "date": "2025",
        }
    }


def test_default_backfill_retries_pr11_unavailable_record(tmp_path):
    """A no-schema unavailable record written by PR #11 must not become stuck as legacy.

    PR #11 deliberately wrote failed/no-source attempts without a schema so the
    ordinary next backfill would retry them.  PR #12 adds SCHEMA_UNAVAILABLE,
    but an upgrade must also preserve retry behavior for records already written
    by PR #11.
    """
    real = {"K1": _item("Unavailable paper")}
    pr11_unavailable = {
        "contacts": [],
        "channel": "none",
        "names": [],
        "emails": [],
        "raw_text": "",
        "fetched_at": "2026-09-04T00:00:00+00:00",
        "itemKey": "K1",
        "doi": None,
        "paper_year": 2025,
        "title": "Unavailable paper",
    }

    with patch.object(B, "collect_items", return_value=(real, {})), \
            patch.object(B, "load_cache", return_value={"K1": dict(pr11_unavailable)}), \
            patch.object(B, "save_cache"):
        result = B.backfill_root(None, tmp_path, workers=1)

    # The previous unavailable attempt should be retried. With no source still
    # available in this fixture, the retry writes the new explicit unavailable
    # marker rather than leaving the old no-schema record permanently skipped.
    assert result["stats"]["no_source"] == 1
    assert result["cache"]["K1"]["schema"] == B.E.SCHEMA_UNAVAILABLE
    assert result["stats"]["legacy_needs_refresh"] == 0


def test_item_key_scope_wins_over_global_refresh(tmp_path):
    """Explicit item-key targeting must never expand into unrelated refresh work.

    `--item-key K2` promises a deterministic target list.  Even if a caller also
    supplies the broad refresh flag, K1/K3 must remain byte-for-byte equivalent
    cache records and only K2 may be re-evaluated.
    """
    real = {
        "K1": _item("Paper one"),
        "K2": _item("Paper two"),
        "K3": _item("Paper three"),
    }
    cache = {
        "K1": {"schema": B.E.SCHEMA_VERSION, "contacts": [], "channel": "none",
               "sentinel": "keep-k1"},
        "K2": {"schema": B.E.SCHEMA_VERSION, "contacts": [], "channel": "none",
               "sentinel": "replace-k2"},
        "K3": {"schema": B.E.SCHEMA_VERSION, "contacts": [], "channel": "none",
               "sentinel": "keep-k3"},
    }
    before_k1 = dict(cache["K1"])
    before_k3 = dict(cache["K3"])

    with patch.object(B, "collect_items", return_value=(real, {})), \
            patch.object(B, "load_cache", return_value=cache), \
            patch.object(B, "save_cache"):
        result = B.backfill_root(
            None,
            tmp_path,
            workers=1,
            refresh=True,
            item_keys=["K2"],
        )

    assert result["cache"]["K1"] == before_k1
    assert result["cache"]["K3"] == before_k3
    assert result["cache"]["K2"]["schema"] == B.E.SCHEMA_UNAVAILABLE
    assert "sentinel" not in result["cache"]["K2"]
    assert result["stats"]["no_source"] == 1
