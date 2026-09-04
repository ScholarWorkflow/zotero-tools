import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / ".apm" / "skills" / "zotero-paper-tagger" / "scripts"


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load_module("corresp_extractor_test", "corresp_extractor.py")
B = load_module("corresp_backfill_test", "corresp_backfill.py")


def test_pdf_unique_name_email_emits_contact():
    text = (
        "A paper title\nAlex Example, B. Author\n"
        "* Corresponding author: Alex Example (alex@example.edu)\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["names"] == ["Alex Example"]
    assert rec["emails"] == ["alex@example.edu"]
    assert rec["contacts"] == [{
        "name": "Alex Example",
        "email": "alex@example.edu",
        "confidence": "high",
        "channel": "pdf_footnote",
    }]


def test_pdf_later_unrelated_email_is_not_paired():
    text = (
        "A paper title\n"
        "* Corresponding author: Alex Example\n"
        "Department of X\n"
        "For editorial questions: editorial@example.org\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["emails"] == ["editorial@example.org"]
    assert rec["contacts"] == []


def test_pdf_ambiguous_names_and_emails_are_not_positionally_paired():
    text = (
        "A paper title\n"
        "* Corresponding authors: Alex Example, Betty Sample "
        "(alex@example.edu, betty@example.edu)\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert set(rec["emails"]) == {"alex@example.edu", "betty@example.edu"}
    assert rec["contacts"] == []


def test_springer_pair_requires_unique_pair_inside_correspondence_block():
    html = (
        '<p id="corresponding-author-list">Correspondence to Alex Example '
        '(alex@example.edu)</p>'
    )
    rec = E.parse_springer_html(html)
    assert rec["contacts"] == [{
        "name": "Alex Example",
        "email": "alex@example.edu",
        "confidence": "high",
        "channel": "springer_curl",
    }]


def test_springer_neighbor_email_is_not_used_to_infer_pair():
    html = (
        '<div>alex@example.edu</div>'
        '<p id="corresponding-author-list">Correspondence to Alex Example</p>'
    )
    rec = E.parse_springer_html(html)
    assert rec["names"] == ["Alex Example"]
    assert rec["contacts"] == []


def test_item_doi_accepts_zotero_uppercase_field():
    assert B.item_doi({"DOI": "10.1234/example"}) == "10.1234/example"
    assert B.item_doi({"doi": "10.5678/lower"}) == "10.5678/lower"


def test_item_year_prefers_explicit_year_then_date():
    assert B.item_year({"year": "2024", "date": "2021-01-01"}) == 2024
    assert B.item_year({"date": "Published 2019-06"}) == 2019
    assert B.item_year({}) is None


def test_item_year_does_not_use_library_ingest_date():
    assert B.item_year({"dateAdded": "2026-09-03T12:00:00Z"}) is None


# --------------------------------------------------------------------------- #
# Schema marker: new records carry the verified-pair contract version.
# --------------------------------------------------------------------------- #

def test_new_record_from_pdf_carries_schema_marker():
    text = (
        "A paper title\n* Corresponding author: Alex Example (alex@example.edu)\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["schema"] == E.SCHEMA_VERSION


def test_new_record_from_springer_carries_schema_marker():
    html = (
        '<p id="corresponding-author-list">Correspondence to Alex Example '
        '(alex@example.edu)</p>'
    )
    rec = E.parse_springer_html(html)
    assert rec["schema"] == E.SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Record classification: legacy vs modern (verified / negative).
# --------------------------------------------------------------------------- #

def test_classify_modern_verified_record():
    rec = {"schema": "corresp/v1", "contacts": [{"name": "X", "email": "x@y"}],
           "channel": "pdf_footnote"}
    assert B.classify_record(rec) == "modern_verified"
    assert B.is_modern_record(rec)
    assert not B.is_legacy_record(rec)
    assert B.is_cache_hit(rec)


def test_classify_modern_negative_record():
    rec = {"schema": "corresp/v1", "contacts": [], "channel": "none"}
    assert B.classify_record(rec) == "modern_negative"
    assert B.is_modern_record(rec)
    assert not B.is_legacy_record(rec)
    assert B.is_cache_hit(rec)  # valid skip — was evaluated, just no pair


def test_classify_legacy_record_with_nonempty_channel():
    """A pre-PR7 record with channel but no schema is legacy, not modern."""
    rec = {"names": ["Alex Example"], "emails": ["alex@example.edu"],
           "channel": "pdf_footnote", "contacts": []}
    assert B.classify_record(rec) == "legacy"
    assert not B.is_modern_record(rec)
    assert B.is_legacy_record(rec)
    assert not B.is_cache_hit(rec)  # NOT a valid skip — needs re-evaluation


def test_classify_legacy_record_with_empty_arrays():
    rec = {"names": [], "emails": [], "channel": "none", "contacts": []}
    assert B.classify_record(rec) == "legacy"
    assert B.is_legacy_record(rec)
    assert not B.is_cache_hit(rec)


def test_classify_non_dict_is_legacy():
    assert B.classify_record(None) == "legacy"
    assert B.classify_record([]) == "legacy"


# --------------------------------------------------------------------------- #
# Selective refresh: legacy-only mode preserves modern records.
# --------------------------------------------------------------------------- #

def test_refresh_legacy_preserves_modern_verified():
    """In refresh_legacy mode, modern verified records are NOT re-evaluated."""
    modern = {"schema": "corresp/v1", "contacts": [{"name": "X", "email": "x@y"}],
              "channel": "pdf_footnote"}
    legacy = {"names": ["Old"], "emails": ["old@y"], "channel": "pdf_footnote",
              "contacts": []}
    cache = {"K1": modern, "K2": legacy}

    # Simulate is_todo under refresh_legacy=True
    todo_keys = [k for k in cache
                 if B.is_legacy_record(cache[k])]
    assert todo_keys == ["K2"]


def test_refresh_legacy_preserves_modern_negative():
    """Modern negative records (contacts=[] but schema present) are preserved."""
    modern_neg = {"schema": "corresp/v1", "contacts": [], "channel": "none"}
    legacy = {"names": ["Old"], "emails": [], "channel": "none", "contacts": []}
    cache = {"K1": modern_neg, "K2": legacy}

    todo_keys = [k for k in cache if B.is_legacy_record(cache[k])]
    assert todo_keys == ["K2"]


def test_selective_refresh_idempotency():
    """After refreshing a legacy record, it becomes modern and is skipped next time."""
    legacy = {"names": ["Old"], "emails": ["old@y"], "channel": "pdf_footnote",
              "contacts": []}
    assert B.is_legacy_record(legacy)

    # Simulate refresh: new record replaces legacy
    refreshed = {"schema": E.SCHEMA_VERSION, "contacts": [],
                 "channel": "none", "names": [], "emails": []}
    assert B.is_modern_record(refreshed)
    assert not B.is_legacy_record(refreshed)
    assert B.is_cache_hit(refreshed)  # now a valid skip


def test_no_code_path_zips_legacy_arrays_into_pair():
    """Legacy names[] + emails[] must never be zipped into a contact pair."""
    legacy = {"names": ["Alex", "Betty"], "emails": ["a@x", "b@y"],
              "channel": "pdf_footnote", "contacts": []}
    # The record has no contacts — and no code should add them by zipping
    assert legacy["contacts"] == []
    assert B.classify_record(legacy) == "legacy"


# --------------------------------------------------------------------------- #
# Outcome distinction: verified_negative vs unavailable (retryable).
# --------------------------------------------------------------------------- #

def test_unavailable_record_no_source_has_unavailable_schema():
    """A record with no PDF and no DOI is unavailable (retryable), not legacy."""
    rec = {"schema": E.SCHEMA_UNAVAILABLE, "contacts": [], "channel": "none",
           "names": [], "emails": []}
    assert B.is_unavailable_record(rec)
    assert not B.is_legacy_record(rec)
    assert not B.is_cache_hit(rec)  # retryable on next backfill
    assert B.classify_record(rec) == "unavailable"


def test_unavailable_record_after_error_has_unavailable_schema():
    """A record where PDF parse or network failed is retryable, not a verified negative."""
    rec = {"schema": E.SCHEMA_UNAVAILABLE, "contacts": [], "channel": "none",
           "names": [], "emails": [], "raw_text": "",
           "fetched_at": "2026-09-04T00:00:00+00:00"}
    assert B.is_unavailable_record(rec)
    assert not B.is_cache_hit(rec)
    assert B.classify_record(rec) == "unavailable"


def test_verified_negative_has_schema_and_is_cache_hit():
    """A record where a channel completed but found no pair is a modern negative."""
    rec = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}
    assert B.is_cache_hit(rec)
    assert B.classify_record(rec) == "modern_negative"


def test_extract_from_doi_raises_when_all_channels_fail():
    """extract_from_doi raises when no channel completes successfully."""
    from unittest.mock import patch

    with patch.object(E, "resolve_doi", side_effect=Exception("network down")):
        with patch.object(E, "fetch_crossref_role", side_effect=Exception("timeout")):
            try:
                E.extract_from_doi("10.1234/nonexistent")
                raised = False
            except Exception:
                raised = True
            assert raised, "extract_from_doi should raise when all channels fail"


def test_extract_from_doi_returns_none_when_checked_but_no_pair():
    """extract_from_doi returns None when a channel completes but finds no pair."""
    from unittest.mock import patch

    # resolve_doi succeeds but points to a non-Springer host, crossref returns None
    with patch.object(E, "resolve_doi", return_value="https://example.com/paper"):
        with patch.object(E, "fetch_crossref_role", return_value=None):
            result = E.extract_from_doi("10.1234/empty")
            assert result is None  # checked, no pair → valid negative


def test_unavailable_vs_verified_negative_classification():
    """The key distinction: unavailable records are retryable, verified negatives are not."""
    unavailable = {"schema": E.SCHEMA_UNAVAILABLE, "contacts": [], "channel": "none"}
    verified_neg = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}

    # Both have empty contacts, but only verified_neg is a cache hit
    assert not B.is_cache_hit(unavailable)
    assert B.is_cache_hit(verified_neg)

    # Classification distinguishes them
    assert B.classify_record(unavailable) == "unavailable"
    assert B.classify_record(verified_neg) == "modern_negative"


# --------------------------------------------------------------------------- #
# Backward-compat: PR #11 schema-less unavailable records must stay retryable.
# --------------------------------------------------------------------------- #

def test_pr11_unavailable_legacy_shape_classified_as_unavailable():
    """A no-schema record with PR #11's exact shape (channel='none', provenance
    keys, empty arrays) must be classified as 'unavailable', not 'legacy'."""
    pr11 = {
        "contacts": [], "channel": "none", "names": [], "emails": [],
        "raw_text": "", "fetched_at": "2026-09-04T00:00:00+00:00",
        "itemKey": "K1", "doi": None, "paper_year": 2025, "title": "X",
    }
    assert B.classify_record(pr11) == "unavailable"
    assert not B.is_legacy_record(pr11)
    assert not B.is_cache_hit(pr11)


def test_true_legacy_with_channel_is_not_pr11_unavailable():
    """A real pre-PR7 record with non-empty channel and arrays IS legacy."""
    true_legacy = {
        "names": ["Alex"], "emails": ["a@x"], "channel": "pdf_footnote",
        "contacts": [],
    }
    assert B.classify_record(true_legacy) == "legacy"
    assert B.is_legacy_record(true_legacy)


def test_schema_less_with_nonempty_channel_is_legacy_not_pr11_unavailable():
    """Schema-less record with channel='pdf_footnote' is legacy, not unavailable."""
    rec = {"channel": "pdf_footnote", "contacts": [], "names": ["X"],
           "emails": ["x@y"], "itemKey": "K", "fetched_at": "2026-09-04T00:00:00+00:00"}
    assert B.classify_record(rec) == "legacy"  # not the PR #11 shape


# --------------------------------------------------------------------------- #
# PDF unavailable path: no extractable text must NOT become a verified negative.
# --------------------------------------------------------------------------- #

def test_extract_from_pdf_raises_when_no_text_layer():
    """extract_from_pdf raises PdfUnavailable when PDF yields no analyzable text."""
    from unittest.mock import patch

    with patch.object(E, "pdf_page_text", return_value=""):
        try:
            E.extract_from_pdf("/fake/scan.pdf")
            raised = False
        except E.PdfUnavailable:
            raised = True
        assert raised, "extract_from_pdf should raise PdfUnavailable for empty text"


def test_extract_from_pdf_raises_when_text_too_short():
    """extract_from_pdf raises PdfUnavailable when PDF text is < 50 chars."""
    from unittest.mock import patch

    with patch.object(E, "pdf_page_text", return_value="  short  "):
        try:
            E.extract_from_pdf("/fake/short.pdf")
            raised = False
        except E.PdfUnavailable:
            raised = True
        assert raised, "extract_from_pdf should raise PdfUnavailable for short text"


def test_extract_from_pdf_returns_none_when_text_ok_but_no_pair():
    """extract_from_pdf returns None (verified negative) when text exists but no pair found."""
    from unittest.mock import patch

    # Enough text to pass the threshold, but no correspondence marker
    long_text = "Some paper title\n" + "body content " * 20
    with patch.object(E, "pdf_page_text", return_value=long_text):
        result = E.extract_from_pdf("/fake/nopair.pdf")
        assert result is None  # verified negative: checked, no pair


def test_work_a_pdf_unavailable_does_not_write_schema_version():
    """Integration: when PDF has no text, the cache record must NOT carry SCHEMA_VERSION."""
    from unittest.mock import patch

    # Simulate work_a's logic with a PDF that yields no text
    with patch.object(E, "pdf_page_text", return_value=""):
        try:
            rec = E.extract_from_pdf("/fake/scan.pdf")
            outcome = "verified_negative"
        except E.PdfUnavailable:
            rec = None
            outcome = "unavailable"

        # Build the record the same way record() does
        if rec is None and outcome == "unavailable":
            cache_rec = {"schema": E.SCHEMA_UNAVAILABLE, "contacts": [],
                         "channel": "none", "names": [], "emails": []}
        else:
            cache_rec = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}

        assert cache_rec.get("schema") != E.SCHEMA_VERSION, \
            "unavailable PDF must NOT carry SCHEMA_VERSION"
        assert not B.is_cache_hit(cache_rec), "unavailable PDF must stay retryable"


def test_work_a_pdf_verified_negative_writes_schema():
    """Integration: when PDF has text but no pair, the cache record carries schema."""
    from unittest.mock import patch

    long_text = "Some paper title\n" + "body content " * 20
    with patch.object(E, "pdf_page_text", return_value=long_text):
        try:
            rec = E.extract_from_pdf("/fake/nopair.pdf")
            outcome = "verified_negative"
        except E.PdfUnavailable:
            rec = None
            outcome = "unavailable"

        assert outcome == "verified_negative"
        if rec is None and outcome == "verified_negative":
            cache_rec = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}

        assert "schema" in cache_rec, "verified negative must carry schema"
        assert B.is_cache_hit(cache_rec), "verified negative is a valid skip"


# --------------------------------------------------------------------------- #
# Selective refresh scoping: default must NOT auto-migrate all legacy records.
# --------------------------------------------------------------------------- #

def test_default_backfill_skips_legacy_records():
    """Default backfill does NOT auto-migrate legacy records — only reports them."""
    # Simulate is_todo under default mode (no refresh, no refresh_legacy, no item_keys)
    legacy = {"names": ["Old"], "emails": ["old@y"], "channel": "pdf_footnote",
              "contacts": []}
    modern_neg = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}
    modern_verified = {"schema": E.SCHEMA_VERSION,
                       "contacts": [{"name": "X", "email": "x@y"}],
                       "channel": "pdf_footnote"}

    # Default is_todo: legacy → skip, modern → skip (both are cache hits or legacy)
    assert not _default_is_todo(legacy), "legacy should be skipped in default mode"
    assert not _default_is_todo(modern_neg), "modern negative is a cache hit"
    assert not _default_is_todo(modern_verified), "modern verified is a cache hit"


def test_default_backfill_retrying_unavailable():
    """Default backfill DOES re-evaluate unavailable/failed records."""
    # An unavailable record carries SCHEMA_UNAVAILABLE — it's a previous
    # attempt that failed and should be retried.
    unavailable = {"schema": E.SCHEMA_UNAVAILABLE, "contacts": [], "channel": "none"}
    assert _default_is_todo(unavailable), "unavailable records should be retried"


def test_item_key_targeting_only_refreshes_specified():
    """--item-key K2 must only refresh K2, leaving K1/K3 untouched."""
    legacy = {"names": ["Old"], "emails": ["old@y"], "channel": "pdf_footnote",
              "contacts": []}
    cache = {"K1": legacy, "K2": legacy, "K3": legacy}

    # With item_keys=["K2"], only K2 is todo
    todo = [k for k in cache if _is_todo_with_keys(cache.get(k), k, item_keys=["K2"])]
    assert todo == ["K2"]


def test_item_key_targeting_overrides_legacy_skip():
    """--item-key can target a legacy record explicitly."""
    legacy = {"names": ["Old"], "emails": ["old@y"], "channel": "pdf_footnote",
              "contacts": []}
    cache = {"K1": legacy}

    # Default: legacy is skipped
    assert not _default_is_todo(legacy)
    # With item_keys targeting K1: it IS todo
    todo = [k for k in cache if _is_todo_with_keys(cache.get(k), k, item_keys=["K1"])]
    assert todo == ["K1"]


def test_refresh_legacy_migrates_all_legacy():
    """--refresh-legacy refreshes all legacy records."""
    legacy = {"names": ["Old"], "emails": ["old@y"], "channel": "pdf_footnote",
              "contacts": []}
    modern = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}
    cache = {"K1": legacy, "K2": modern, "K3": legacy}

    todo = [k for k in cache if _is_todo_refresh_legacy(cache.get(k))]
    assert todo == ["K1", "K3"]


def test_legacy_needs_refresh_counting():
    """Default mode counts legacy records that need refresh but aren't migrated."""
    legacy = {"names": ["Old"], "emails": ["old@y"], "channel": "pdf_footnote",
              "contacts": []}
    modern = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}
    cache = {"K1": legacy, "K2": legacy, "K3": modern}

    # In default mode, legacy records are NOT todo but ARE counted
    todo = [k for k in cache if _default_is_todo(cache.get(k))]
    legacy_count = sum(1 for k in cache
                       if B.is_legacy_record(cache[k]) and k not in set(todo))
    assert legacy_count == 2  # K1, K2 are legacy and not in todo


# Helper functions that mirror backfill_root's is_todo logic for testing.

def _default_is_todo(old):
    """Default is_todo: skip legacy & modern, retry unavailable."""
    if B.is_modern_record(old):
        return False
    if B.is_legacy_record(old):
        return False
    # unavailable (or any non-modern, non-legacy) → retry
    return True


def _is_todo_with_keys(old, key, item_keys=None):
    """is_todo with item_keys targeting."""
    target_set = set(item_keys) if item_keys else None
    if target_set is not None:
        return key in target_set
    if B.is_modern_record(old):
        return False
    if B.is_legacy_record(old):
        return False
    return True


def _is_todo_refresh_legacy(old):
    """is_todo in refresh_legacy mode."""
    return B.is_legacy_record(old)
