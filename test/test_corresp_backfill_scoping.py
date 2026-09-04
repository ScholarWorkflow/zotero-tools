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


def test_default_backfill_skips_pr11_unavailable_record_until_explicit_refresh(tmp_path):
    """A no-schema record written by PR #11 stays legacy until explicitly scoped.

    The shape fingerprint of PR #11 transient unavailable writes collides with
    pre-PR11 legacy empty records, so a default backfill cannot safely
    auto-retry them — that would re-introduce broad re-fetching.  Callers
    who genuinely want to retry a PR #11 transient must opt in via
    --item-key or --refresh-legacy, after which the record is rewritten with
    the new SCHEMA_UNAVAILABLE marker and becomes retryable.
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
    before = dict(pr11_unavailable)

    with patch.object(B, "collect_items", return_value=(real, {})), \
            patch.object(B, "load_cache", return_value={"K1": dict(pr11_unavailable)}), \
            patch.object(B, "save_cache"):
        result = B.backfill_root(None, tmp_path, workers=1)

    # Default backfill: legacy record is reported but not retried.
    assert result["stats"]["no_source"] == 0
    assert result["stats"]["legacy_needs_refresh"] == 1
    assert result["cache"]["K1"] == before  # byte-for-byte unchanged


def test_explicit_item_key_migrates_pr11_unavailable(tmp_path):
    """With --item-key, a PR #11 transient unavailable is rewritten with SCHEMA_UNAVAILABLE."""
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
        result = B.backfill_root(
            None, tmp_path, workers=1, item_keys=["K1"])

    # With explicit --item-key, the record is retried and the new
    # SCHEMA_UNAVAILABLE marker is written (preserving retryability for
    # future default backfills).
    assert result["stats"]["no_source"] == 1
    assert result["cache"]["K1"]["schema"] == B.E.SCHEMA_UNAVAILABLE


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
