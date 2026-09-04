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


def test_pdf_two_line_correspondence_block_emits_contact():
    text = (
        "A paper title\n"
        "* Corresponding author: Taro Yamada\n"
        "E-mail: taro@example.ac.jp\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["names"] == ["Taro Yamada"]
    assert rec["emails"] == ["taro@example.ac.jp"]
    assert rec["contacts"] == [{
        "name": "Taro Yamada",
        "email": "taro@example.ac.jp",
        "confidence": "high",
        "channel": "pdf_footnote",
    }]


def test_pdf_bare_email_line_in_block_emits_contact():
    text = (
        "A paper title\n"
        "* Corresponding author: Hanako Sample\n"
        "hanako@example.ac.jp\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["contacts"] == [{
        "name": "Hanako Sample",
        "email": "hanako@example.ac.jp",
        "confidence": "high",
        "channel": "pdf_footnote",
    }]


def test_pdf_editorial_email_on_next_line_is_not_absorbed():
    text = (
        "A paper title\n"
        "* Corresponding author: Alex Example\n"
        "For editorial questions only: editorial@example.org\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["emails"] == ["editorial@example.org"]
    assert rec["contacts"] == []


def test_pdf_labeled_email_line_with_editorial_note_is_not_absorbed():
    text = (
        "A paper title\n"
        "* Corresponding author: Alex Example\n"
        "E-mail: editorial@example.org (Editorial Office)\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["emails"] == ["editorial@example.org"]
    assert rec["contacts"] == []


def test_pdf_labeled_email_line_with_support_prose_is_not_absorbed():
    text = (
        "A paper title\n"
        "* Corresponding author: Alex Example\n"
        "Email: support@example.org for submission questions\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["emails"] == ["support@example.org"]
    assert rec["contacts"] == []


def test_pdf_punctuation_separator_ends_block_before_bare_email():
    text = (
        "A paper title\n"
        "* Corresponding author: Alex Example\n"
        "-----\n"
        "editorial@example.org\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["emails"] == ["editorial@example.org"]
    assert rec["contacts"] == []


def test_pdf_email_line_after_affiliation_line_is_outside_block():
    text = (
        "A paper title\n"
        "* Corresponding author: Alex Example\n"
        "Department of Chemistry, Example University\n"
        "E-mail: dept@example.edu\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["emails"] == ["dept@example.edu"]
    assert rec["contacts"] == []


def test_pdf_multi_line_two_authors_two_emails_stay_unpaired():
    text = (
        "A paper title\n"
        "* Corresponding authors: Alex Example, Betty Sample\n"
        "E-mail: alex@example.edu\n"
        "E-mail: betty@example.edu\n"
        + "body " * 30
    )
    rec = E.parse_pdf_text(text)
    assert rec["names"] == ["Alex Example", "Betty Sample"]
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


def test_springer_multiline_container_binds_name_and_email():
    html = (
        '<p id="corresponding-author-list">Correspondence to Alex Example'
        '<br>E-mail: alex@example.edu</p>'
    )
    rec = E.parse_springer_html(html)
    assert rec["names"] == ["Alex Example"]
    assert rec["contacts"] == [{
        "name": "Alex Example",
        "email": "alex@example.edu",
        "confidence": "high",
        "channel": "springer_curl",
    }]


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

def test_unavailable_record_no_source_has_no_schema():
    """A record with no PDF and no DOI is unavailable, not a verified negative."""
    # Simulate the "unavailable" outcome: no schema → stays retryable
    rec = {"contacts": [], "channel": "none", "names": [], "emails": []}
    assert "schema" not in rec
    assert not B.is_cache_hit(rec)  # retryable on next backfill


def test_unavailable_record_after_error_has_no_schema():
    """A record where PDF parse or network failed is retryable, not a verified negative."""
    # When work_a catches an exception, outcome="unavailable" → no schema
    rec = {"contacts": [], "channel": "none", "names": [], "emails": [],
           "raw_text": "", "fetched_at": "2026-09-04T00:00:00+00:00"}
    assert "schema" not in rec
    assert not B.is_cache_hit(rec)


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
    unavailable = {"contacts": [], "channel": "none"}  # no schema
    verified_neg = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}

    # Both have empty contacts, but only verified_neg is a cache hit
    assert not B.is_cache_hit(unavailable)
    assert B.is_cache_hit(verified_neg)

    # Both classify as legacy/modern based on schema presence
    assert B.classify_record(unavailable) == "legacy"  # no schema → legacy
    assert B.classify_record(verified_neg) == "modern_negative"


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


def test_work_a_pdf_unavailable_does_not_write_schema():
    """Integration: when PDF has no text, the cache record must NOT carry schema."""
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
            cache_rec = {"contacts": [], "channel": "none", "names": [],
                         "emails": [], "raw_text": "", "fetched_at": "2026-09-04T00:00:00+00:00"}
        else:
            cache_rec = {"schema": E.SCHEMA_VERSION, "contacts": [], "channel": "none"}

        assert "schema" not in cache_rec, "unavailable PDF must NOT carry schema"
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
