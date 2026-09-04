# Paper-side correspondence evidence schema

`_corresp_cache.json` remains a JSON object keyed by Zotero item key. Existing consumers may continue reading `names[]`, `emails[]`, `channel`, `confidence`, `raw_text`, and `fetched_at`.

Newly backfilled records also expose structured pairs and paper provenance:

```json
{
  "ITEMKEY": {
    "contacts": [
      {
        "name": "Alex Example",
        "email": "alex@example.edu",
        "confidence": "high",
        "channel": "pdf_footnote"
      }
    ],
    "names": ["Alex Example"],
    "emails": ["alex@example.edu"],
    "channel": "pdf_footnote",
    "confidence": "high",
    "itemKey": "ITEMKEY",
    "doi": "10.1234/example",
    "paper_year": 2025,
    "title": "Paper title",
    "raw_text": "Corresponding author: Alex Example (alex@example.edu)",
    "fetched_at": "2026-09-03T12:00:00+00:00"
  }
}
```

## Pairing invariant

`contacts[]` is stronger evidence than the legacy arrays. A contact is emitted only when one source structure proves that a specific name belongs with a specific email. The implementation deliberately does **not** zip, index-match, or otherwise positionally pair independent `names[]` and `emails[]` arrays.

Examples:

- one PDF correspondence-marker line containing exactly one detected name and one email: pair allowed;
- a PDF marker line with one name followed immediately by explicit email-field lines (a labeled `E-mail:`/`Email:`/`メール:` line, or a line holding only an email address): the bounded block is the marker line plus those consecutive email-field lines, and exactly one name plus one email inside it yields one pair — e.g. `* Corresponding author: Taro Yamada` + `E-mail: taro@example.ac.jp`;
- the bounded block ends at the first line that is not an explicit email field (blank line, affiliation, editorial/funding prose): an email in such a later unrelated block stays unpaired, even though it may remain in legacy `emails[]`;
- a PDF marker line containing a name while an email appears only on a later non-field line (editorial notes, affiliation text): `contacts: []`;
- one Springer `#corresponding-author-list` block containing exactly one detected name and one email: pair allowed, including when the container binds the name and email across child elements such as `<br>`;
- two names plus two emails in one ambiguous block: `contacts: []`, while all names/emails remain in the compatibility arrays;
- Crossref `corresponding-author` role with a name but no email: `contacts: []`;
- an email found in neighboring HTML outside the corresponding-author block: it may remain in `emails[]`, but it is not paired into `contacts[]`.

For a future `browser_dom` producer, the same rule applies: populate `contacts[]` only when the DOM structure itself establishes the relation (for example a single author card containing that author's name and email). Do not pair two separately collected lists.

## Scope

These records are paper evidence only. They are not statements about a professor's current official contact address or recruitment eligibility. Recruitment/faculty-list reconciliation and final outreach address selection belong to higher-level workflows.
