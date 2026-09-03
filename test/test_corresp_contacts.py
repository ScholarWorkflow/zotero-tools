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
    assert "Alex Example" in rec["names"]
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
