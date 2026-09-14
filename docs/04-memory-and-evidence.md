# 04 — Memory and Evidence Lifecycle

The brain is the `memories` table plus the rules in `core/memory/` that create, corroborate, supersede and retire rows. Everything in this document is deterministic; AI (when present) only proposes candidate memories, and every candidate passes through the same rules.

## 1. Evidence first

Nothing enters memory without an `evidence` row. The evidence pipeline:

```
raw item (API record / dropped file)
  → dedupe (source_id or content_hash) → evidence row (content stays local)
  → entity matching (doc 06) → company_id / deal_id / contact_id + confidence
  → extraction (AI or rules) → candidate memories + candidate actions
  → memory rules (this doc) → memories / memory_evidence / actions
  → deal.summary_stale = 1, deal.last_activity_at updated
  → prioritisation recompute
```

Structured evidence (`HUBSPOT_DEAL`, `EXCEL_DEAL`, `CALENDLY_MEETING`, `PROSPECTING_ACTIVITY`) gets `extraction_status = NOT_APPLICABLE`: it updates entities directly and needs no text extraction. Unstructured evidence (`EMAIL`, `ZOOM_TRANSCRIPT`, `HUBSPOT_ACTIVITY` notes/emails) is `PENDING` until extracted.

Evidence with `deal_id IS NULL` (unmatched) is still stored and searchable, but produces no memories until matched — creating memories on the wrong deal is worse than creating none.

## 2. Candidate memory

Whatever produces it (AI provider or rules extractor), a candidate has this shape (schema in `ai/prompts/schemas/memory_candidate.json`):

```json
{
  "type": "COMMITMENT",
  "subject": "Revised pricing",
  "content": "Sam will send revised pricing to Acme.",
  "direction": "USER_TO_CUSTOMER",
  "owner_label": "me",
  "due_text": "tomorrow",
  "quote": "I'll send the revised pricing tomorrow.",
  "extraction_confidence": 0.9,
  "relation_to_existing": null
}
```

Before it becomes a memory:

1. **Quote verification** — `quote` must be found in `evidence.content` (exact, or fuzzy ratio ≥ 0.92 for transcripts). Fail → candidate dropped, counted in `ai_calls.status = REJECTED_OUTPUT`. Rules extractor always produces exact quotes.
2. **Date resolution** — `due_text` → `due_date` with `dateparser`, relative to `evidence.occurred_at` (not "now"). "Friday" in an email sent on Monday 8 Sep resolves to 12 Sep. Unresolvable → `due_date NULL`, `due_text` kept.
3. **Direction sanity** — for `COMMITMENT`, if `evidence.direction = OUTBOUND` and the quote is first-person, direction is `USER_TO_CUSTOMER`; if `INBOUND` and first-person, `CUSTOMER_TO_USER`. The extractor proposes, this rule can overrule.
4. **Basis** — `OBSERVED` if the quote verified and the content is a restatement; `INFERRED` if the extractor flagged it as inference (e.g. deal state deduced from a security questionnaire request). AI candidates without a quote are only accepted as `INFERRED` with confidence capped at 0.5.

## 3. Dedupe key and create-or-update

```
dedupe_key = type | deal_id | normalise(subject)
normalise  = lowercase, strip punctuation, strip stop words, stem-ish (rapidfuzz token sort)
```

On arrival:

- **No ACTIVE memory with a matching key** (fuzzy ≥ 0.9 on the normalised subject within same type+deal) → create.
- **Match found** → update: link the new evidence with `SUPPORTS`, recompute confidence (§6), refresh `due_date` if the new evidence gives a later, explicit one, set `updated_at`. The content is *not* rewritten by AI; the newest verified quote is appended to the evidence panel.

Single-active types: `DEAL_STATE` and `NEXT_STEP` have at most one `ACTIVE` row per deal. A new observed one supersedes the old (§5).

## 4. Relations between evidence and memories

`memory_evidence.relation`:

| relation | meaning | effect |
|---|---|---|
| `SUPPORTS` | evidence says the same thing | confidence up (§6) |
| `FULFILS` | evidence shows the commitment happened | memory `status = FULFILLED`, `valid_until = occurred_at`; linked action offered for completion |
| `CONTRADICTS` | evidence says the opposite | see §5 conflict rule |
| `SUPERSEDES` | evidence establishes the replacement belief | old memory `SUPERSEDED`, `superseded_by_id` set |

The extractor emits `relation_to_existing` when the source clearly refers to an earlier belief ("we received the pricing" → `FULFILS` the "send revised pricing" commitment). Matching to the existing memory uses the same dedupe fuzzy match; if no candidate ≥ 0.8, the relation is ignored and the candidate is treated as a new `FACT` with a `CONFIRM_MEMORY` review item ("Does 'we received the pricing' mean 'Send revised pricing' is done?").

## 5. Supersession and conflict

- **Newer observed beats older observed** for single-active types (`DEAL_STATE`, `NEXT_STEP`). The old row is kept with `SUPERSEDED` so the deal timeline reads "Proposal → Procurement → Legal".
- **Contradiction on a high-confidence memory** (≥ 0.8) does *not* flip silently. Both stay `ACTIVE`, a `CONFLICTING_MEMORY` review item is opened with both quotes, and the deal summary shows "⚠ conflicting information about X". The user resolves; the loser becomes `REJECTED` or `SUPERSEDED`.
- **Contradiction on a low/medium-confidence memory** (< 0.8) → the newer evidence supersedes if its own confidence is higher; otherwise conflict item as above.
- **User statement wins.** A `STATED_BY_USER` memory (confidence 1.0) supersedes any conflicting non-user memory immediately and retracts nothing else.

## 6. Confidence

```
confidence = source_reliability × extraction_confidence × match_confidence
```

| factor | values |
|---|---|
| source_reliability | HubSpot structured 1.0 · user input 1.0 · saved `.msg/.eml` 0.95 · transcript 0.85 · HubSpot logged email/note 0.8 · `.pdf/.txt` email 0.8 |
| extraction_confidence | AI-reported (0–1), or 0.60 cap for the rules extractor |
| match_confidence | from doc 06 (auto-link ≥ 0.9, provisional ≥ 0.6) |

Corroboration by a second independent evidence item: `c = 1 − (1 − c₁)(1 − c₂)`. Two medium beliefs make a high one; a hundred weak ones cannot exceed 1.

Decay: **commitments never decay** — an overdue commitment is more important, not less. `INFERRED` memories with a single evidence item decay 0.05 per week without corroboration and expire at < 0.3. `OBSERVED` facts do not decay.

Display bands: High ≥ 0.8 · Medium ≥ 0.5 · Low < 0.5. The raw number is visible on the memory's detail popover only.

## 7. Commitment lifecycle

```
ACTIVE (due in future) → ACTIVE (overdue, flagged) → FULFILLED | SUPERSEDED | RETRACTED
                                     │
                                     └─ 30 days overdue → STALE_COMMITMENT review item
                                              └─ unanswered 60 days → EXPIRED
```

- Every `USER_TO_CUSTOMER` commitment creates one `COMMITMENT` action (tier 1) via `origin_memory_id`. Completing the action prompts "Mark commitment as fulfilled?" — yes → `FULFILLED` with a `USER_INPUT` evidence row; no → action completed, memory stays (e.g. partially done).
- `CUSTOMER_TO_USER` commitments create no action until overdue, then create "Chase {contact} for {subject}" (tier 1, signal 40 in prioritisation).
- `CUSTOMER_INTERNAL` ("speak to procurement") never create actions; they appear in "They are waiting on internally" on deal detail.

## 8. User statements as evidence

Deal detail has a single text input: *"Tell the brain something"*. Submitting creates `evidence(type = USER_INPUT, direction = INTERNAL, content = text)` and runs the same extraction. Additionally, simple imperative forms are handled deterministically without AI:

- "pricing sent" / "sent the pricing" → offers to `FULFIL` the matching commitment
- "close date is 30 Sep" → `DATA_HYGIENE` proposal (not a CRM write)
- anything else → `FACT`, `STATED_BY_USER`, 1.0

## 9. What the deal detail page reads

All panels are simple queries over `ACTIVE` memories for the deal:

| panel | query |
|---|---|
| Current situation | `deals.summary` (doc 07 §4) or templated from the rows below |
| You owe | `COMMITMENT`, `direction = USER_TO_CUSTOMER` |
| They owe you | `COMMITMENT`, `direction = CUSTOMER_TO_USER` |
| Waiting on internally | `COMMITMENT`, `direction = CUSTOMER_INTERNAL` + `DEAL_STATE` |
| Signals & risks | `BUYING_SIGNAL`, `OBJECTION`, `RISK` |
| People | `RELATIONSHIP` + contacts |
| Preferences | `CUSTOMER_PREFERENCE` |
| Changed since yesterday | `deal_changes` + memories with `updated_at ≥ yesterday` + evidence `occurred_at ≥ yesterday` |
| Recent evidence | `evidence` by `occurred_at DESC`, each expandable to full content and its memories |

Clicking any memory shows its quotes and evidence — the "Why do you think this?" answer.

## 10. Rules extractor (no-AI fallback)

Deterministic, confidence capped at 0.60, exact quotes by construction:

- Commitment phrases: `I'll|I will|we'll|we will|I can|let me` + verb → `COMMITMENT`, direction from evidence direction.
- Request phrases: `could you|can you|please send|we need` → `COMMITMENT` in the opposite direction.
- Date phrases: `dateparser.search.search_dates` within the same sentence → `due_text/due_date`.
- State keywords: `procurement|legal|security review|infosec|approval|signature|redlines` → `DEAL_STATE` (`INFERRED`).
- Objection keywords: `too expensive|budget|competitor|not a priority` → `OBJECTION` (`INFERRED`, 0.4).

It will miss things. It will not invent things. That trade is correct for a fallback.
