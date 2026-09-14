# 06 — Entity Matching

Goal from Section 25: the user should never have to say which deal an email or transcript belongs to. Corollary from the same section: when the system is not sure, it asks rather than guesses. Matching is deterministic, rule-ordered and learns through `company_aliases`.

## 1. Inputs and outputs

Input: an `evidence` row (participants, title, content, occurred_at, source) or a source record (Excel company name, Calendly invitee, sheet company).

Output: `company_id`, `deal_id`, `contact_id` (each nullable), `match_confidence`, `match_method`, and zero or more `review_items`.

## 2. Rule order (first sufficient rule wins; all rules run to collect candidates)

| # | rule | method | confidence |
|---|---|---|---|
| 1 | External id already linked (HubSpot engagement → deal association; Calendly event → meeting) | `EXTERNAL_ID` | 1.00 |
| 2 | Identifier in `company_aliases` with `source = USER` | `ALIAS` | 1.00 |
| 3 | Participant email domain = `companies.primary_domain` or `DOMAIN` alias (freemail excluded) | `DOMAIN` | 0.95 |
| 4 | Participant email = `contacts.email` | `CONTACT` | 0.95 |
| 5 | Transcript time within window of a matched meeting, ≥1 speaker name overlaps invitees | `CALENDAR` | 0.85 |
| 6 | Normalised company name exact = `normalised_name` or `NAME` alias | `NAME_EXACT` | 0.90 |
| 7 | Fuzzy company name (rapidfuzz `token_set_ratio`) ≥ 92 / ≥ 85 | `NAME_FUZZY` | 0.75 / 0.55 |
| 8 | Speaker/participant full name = `contacts.full_name` | `CONTACT_NAME` | 0.70 |
| 9 | Content mentions a subject unique to one deal's active memories (e.g. "the Xodo Sign pilot pricing") | `MEMORY` | 0.60 |

Thresholds (`config/matching.yaml`): **≥ 0.90 auto-link**, **0.60–0.89 provisional link + `CONFIRM` review item**, **< 0.60 no link + `MATCH_*` review item with ranked candidates**.

Provisional links are real links (memories get created against them) but are flagged; correcting one re-points all evidence, memories and actions and records `MATCH_CORRECTED`.

## 3. Company → deal disambiguation

Most companies have one open deal per product; some have two. Given a company:

1. Open deals only (`is_closed = 0`), unless the evidence predates the close.
2. Product hint: content matches `product_hints` in `matching.yaml` → prefer that product's deal.
3. Thread continuity: email `In-Reply-To` chain already linked → same deal.
4. Most recent `last_activity_at`.
5. If the top two candidates are within 0.10 → **ask** (`MATCH_DEAL` review item). Do not pick.

If the company has no open deal, link company only, leave `deal_id NULL`, and create a `MATCH_DEAL` review item only if the evidence looks commercial (mentions pricing/proposal/contract); otherwise it is just context on the company.

## 4. Company name normalisation

Lowercase → strip punctuation → strip legal suffixes (`ltd, limited, plc, inc, llc, gmbh, corp, group, holdings…`) → collapse whitespace. "ACME Holdings Ltd." and "Acme" normalise identically. The suffix list is configuration.

## 5. Learning

Every review resolution writes a `company_aliases` row:

| resolved from | alias_type |
|---|---|
| email domain the user confirmed | `DOMAIN` |
| Excel company label | `EXCEL_LABEL` |
| sheet company label | `SHEET_LABEL` |
| Calendly event/invitee label | `CALENDLY_LABEL` |
| transcript company mention / filename fragment | `TRANSCRIPT_LABEL` |
| any other name variant | `NAME` |

Next time, rule 2 matches at 1.00 and the question never comes back. This is the whole learning mechanism for matching: no model, fully inspectable, editable on Settings.

Contacts learn the same way: confirming "this speaker is Jane at Acme" creates/updates a `contacts` row.

## 6. Review queue UX

Shown on Today as "❓ 2 questions" and on Inbox in full:

```
Transcript "Acme call 13 Sep" — which deal?
  ○ Acme — Xodo Sign (£75k, Proposal)        likely: 2 speakers match contacts
  ○ Acme — Product B (£20k, Discovery)        possible: company only
  ○ Somewhere else…  [search]
  ○ Not a deal — keep as company context
[Confirm]
```

Answering is one click; the system then runs extraction for that evidence immediately.

## 7. Failure modes and how they are contained

| failure | containment |
|---|---|
| Wrong auto-link at 0.95 (shared domain across subsidiaries) | `match_method` visible on every evidence row; "Move to another deal" action re-points and adds an alias; memories created from it are re-parented |
| Freemail customer | never inferred; asked once; alias by email address (`contacts.email`) thereafter |
| Company renamed in HubSpot | old name kept as `NAME` alias by the connector diff |
| Two companies fuzzy-match each other ("Acme" / "Acme Foods") | fuzzy ≥ 92 only when a single candidate clears it; ties ask |
