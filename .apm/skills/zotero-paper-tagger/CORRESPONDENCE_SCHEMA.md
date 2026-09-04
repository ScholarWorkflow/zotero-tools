# Paper-side correspondence evidence schema

`_corresp_cache.json` remains a JSON object keyed by Zotero item key. Existing consumers may continue reading `names[]`, `emails[]`, `channel`, `confidence`, `raw_text`, and `fetched_at`.

Newly backfilled records also expose structured pairs and paper provenance:

```json
{
  "ITEMKEY": {
    "schema": "corresp/v1",
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

## Schema marker and record classification

New records carry a `schema` field (`"corresp/v1"`) that marks them as evaluated under the verified-pair contract. This field distinguishes three record kinds:

| Kind | `schema` | `contacts` | Meaning |
|------|----------|------------|---------|
| modern_verified | present | non-empty | A verified name/email pair was found. |
| modern_negative | present | empty | A channel completed successfully but found no verified pair. Safe to skip on later backfills. |
| legacy | absent | empty | Record predates the verified-pair contract; independent `names[]`/`emails[]` may need re-evaluation. |

Records produced under `channel: "none"` **do not** carry `schema` when the absence of a pair was not the result of a successful check — for example when no source was available (no PDF, no DOI) or when a channel failed (PDF parse error, network error). These stay retryable so a later backfill can re-attempt once the source or network is restored.

Downstream reconciliation can therefore tell "verified no pair" (`schema` present, `contacts: []`) from "old cache never evaluated under the contract" (`schema` absent).

## Pairing invariant

`contacts[]` is stronger evidence than the legacy arrays. A contact is emitted only when one source structure proves that a specific name belongs with a specific email. The implementation deliberately does **not** zip, index-match, or otherwise positionally pair independent `names[]` and `emails[]` arrays.

Examples:

- one PDF correspondence-marker line containing exactly one detected name and one email: pair allowed;
- a PDF marker line containing a name while an email appears only on a later line: `contacts: []`, even though the email may remain in legacy `emails[]`;
- one Springer `#corresponding-author-list` block containing exactly one detected name and one email: pair allowed;
- two names plus two emails in one ambiguous block: `contacts: []`, while all names/emails remain in the compatibility arrays;
- Crossref `corresponding-author` role with a name but no email: `contacts: []`;
- an email found in neighboring HTML outside the corresponding-author block: it may remain in `emails[]`, but it is not paired into `contacts[]`.

For a future `browser_dom` producer, the same rule applies: populate `contacts[]` only when the DOM structure itself establishes the relation (for example a single author card containing that author's name and email). Do not pair two separately collected lists.

## Scope

These records are paper evidence only. They are not statements about a professor's current official contact address or recruitment eligibility. Recruitment/faculty-list reconciliation and final outreach address selection belong to higher-level workflows.
