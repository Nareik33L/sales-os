# 01 — Architecture Review (Section 45 challenge)

This document challenges the V1 specification before code is written, as Section 45 asks. Each subsection states the question, the finding, and the **decision** carried into the rest of the design. Where the decision changes the original spec, it is listed again in the "Spec deltas" table at the end.

The review is guided by one test from Section 45: *does this reduce the amount of work I have to do?* Anything that adds machinery without removing work from the user's morning is pushed out of V1.

---

## 1. Architecture

### 1.1 Are the entities correct?

The spec's twelve tables are the right core. Four gaps appear once you trace the example flows end to end (email → memory → transcript → superseded memory → action):

| Gap | Why it matters | Decision |
|---|---|---|
| No place to record *who owes whom* on a commitment | "What do I owe Acme?" and "What are they waiting on internally?" are different questions over the same memory type | `memories.direction` (`USER_TO_CUSTOMER`, `CUSTOMER_TO_USER`, `CUSTOMER_INTERNAL`, `USER_INTERNAL`) |
| No supersession pointer | `valid_until` says *when* a belief stopped being true, not *what replaced it*. Deal detail needs "pricing was sent → now under review" as a chain | `memories.status` + `superseded_by_id` + `memory_evidence.relation` (`SUPPORTS`, `FULFILS`, `CONTRADICTS`, `SUPERSEDES`) |
| No change history for deals | "What changed since yesterday?" and "Recently changed deals" on Today cannot be answered from current state alone | `deal_changes` table populated by connector diffs |
| No queue for "ask me rather than guess" | Section 25 requires asking on low confidence; the spec has no entity for a pending question | `review_items` table, surfaced on Today as "N questions" |

Also added: `company_aliases` (how matching learns), `processed_files` (Section 34 hash tracking), `ai_calls` (Section 30 transparency), and a `RISK` memory type for Section 24's "risks / blockers".

### 1.2 Are the relationships correct?

The spec uses `source_evidence_ids` and `evidence_ids` as columns. In SQLite that means JSON arrays, which cannot be indexed or joined and make "Why do you think this?" a table scan. **Decision:** link tables (`memory_evidence`, `action_evidence`, `audit_log_evidence`). `memory_evidence` also carries the verbatim `quote`, which is the single most important anti-hallucination device in the system (see §5).

Contacts belong to companies, not to deals. Deal involvement is a memory (`RELATIONSHIP` type), because people move between deals and roles change; a fixed `deal_contacts` table would go stale. `contacts.role_in_deal` is kept only as a convenience label.

Prospecting rows are normalised into `prospecting_items` *and* produce one `actions` row each. Two tables for one thing is deliberate: `prospecting_items` mirrors the source (like `deals`), `actions` is the unified working list with user feedback attached. Deleting or completing the action must never mutate the sheet without approval.

### 1.3 Is the memory model sufficient?

The spec's type list is good. Two refinements:

- The spec distinguishes Fact vs Hypothesis in prose but the schema has only `type`. **Decision:** orthogonal `basis` column: `OBSERVED` (quote exists), `INFERRED` (AI/rule inference), `STATED_BY_USER`. A `DEAL_STATE` can be observed ("we're in procurement") or inferred (from a security questionnaire request). Rendering shows inferred beliefs with a visible "inferred" tag.
- `dedupe_key` (`type|deal_id|normalised subject`) so that a second email about "revised pricing" updates the existing commitment rather than creating a duplicate. Details in doc 04.

### 1.4 Is evidence provenance sufficient?

Nearly. Missing pieces: `content_hash` for dedupe across formats (the same email saved as `.msg` and `.eml`), `direction` (inbound/outbound decides whether "I'll send X" is *my* commitment or *theirs*), `participants_json`, and `match_confidence`/`match_method` so a wrongly matched piece of evidence can be found and corrected. All added.

### 1.5 Is SQLite appropriate?

Yes, without reservation. ~30 deals, one user, one process. Two additions that SQLite gives for free and that remove work elsewhere:

- **FTS5** on `evidence` answers "what did we agree on the last call?" with keyword search, which is what a person would actually type. This defers a vector database indefinitely (ADR-006).
- **WAL mode** so the Streamlit process and a file-drop processor can read concurrently.

Concurrency risk: Streamlit re-runs scripts on each interaction. All writes go through short transactions; no long-lived connections in session state.

---

## 2. Prioritisation

### 2.1 Are the ranking signals correct?

The seven signals are right. Two structural corrections:

1. **Prospecting must be a tier, not a weight.** If prospecting is merely down-weighted, a very overdue prospecting row will eventually outrank a deal action. The spec says it must *always* rank below deal work. **Decision:** `actions.tier` (1 deal work, 2 follow-ups/admin, 3 prospecting) is the primary sort key; score sorts within a tier.
2. **Deal score and action score are different things.** The Today list shows actions, but value/close/staleness are deal properties. **Decision:** compute a deal score, then an action score = weighted(inherited deal score, own due-date signal). A deal with no actions but a high score still appears on Today as a "deal needs attention" card so it is not invisible.

### 2.2 Is the weighting model sensible?

Additive weighted sum of 0–100 signals is right: explainable, tunable, and every component maps to a "Why" bullet. Raw deal value must be log-scaled; otherwise one £150k deal is permanently #1 regardless of anything else. Initial weights (value .30, close .30, stale .15, commitment .15, meeting .10) encode the spec's "value + close date are strongest".

### 2.3 How should stale activity be calculated?

Define `last_activity_at` precisely or the signal is noise:

- **Counts as activity:** HubSpot calls, meetings, notes, logged emails, completed tasks; local email evidence (either direction); processed transcripts; Calendly meetings that have occurred.
- **Does not count:** syncs, deal property edits without engagement, the user viewing the deal, future meetings, open tasks.
- `last_activity_at = max(source activity timestamp, local evidence occurred_at)`.

Conflict rule: a stale deal closing in six months is not urgent. Stale signal is capped at 50 when `close_date` is more than 60 days out. Both numbers are in `priority_weights.yaml`.

### 2.4 How should conflicting signals be handled?

Do not try to resolve them; expose them. Every component's contribution is stored in `priority_breakdown_json`, and the "Why" panel shows the top contributors. Two specific conflicts get rules:

- **Close date in the past:** treated as maximum urgency *and* a `DATA_HYGIENE` action "Update close date for X" is created, because usually the CRM is wrong, not the deal.
- **Customer owes me something and the deal is stale:** these are the same signal seen twice (they are waiting on themselves). Customer-side overdue commitments feed a follow-up action (score 40), not a deal alarm.

---

## 3. Data ingestion

### 3.1 HubSpot

Can provide everything in Section 4. Notes for the connector (doc 05):

- Private App token is the right auth for a single-user tool; no OAuth dance.
- Engagements are CRM objects (`calls`, `meetings`, `notes`, `emails`, `tasks`) fetched with `associations=deals`. Logged email bodies may be truncated or absent depending on how they were logged; treat `HUBSPOT_ACTIVITY` evidence as lower-fidelity than a saved `.msg`.
- "Last activity" is a computed property (`notes_last_updated`) that lags; the connector recomputes from engagements it fetched rather than trusting it.
- Rate limits are comfortably above what 30 deals need, but the search API has its own lower limit; use plain list/`hs_lastmodifieddate` filtering for incremental sync.
- Stage ids are opaque; pipelines endpoint provides labels. Store both.

### 3.2 Google Sheets

Direct connection is likely but not certain: a service account needs the sheet shared with it, and some Workspace tenants block sharing outside the domain. **Decision:** connector supports API mode and a file fallback (`data/inbox/prospecting/*.csv`, exported from the Today tab). Same normaliser for both.

Row identity is the real problem: the "Today" tab is a working view and rows move. **Decision:** `row_key = hash(Sequence ID | Company | Contact | Step)`; row number is informational only. If the sheet gains a stable ID column, switch the key columns in `sources.yaml`.

### 3.3 Calendly

Personal Access Token against v2 is straightforward. Invitee email requires a second call per event; volume is small. Company is inferred from invitee email domain (never from freemail), falling back to event name and then to a review item. Cancellations are reported and mark meetings `CANCELLED` rather than deleting them (the cancelled meeting is itself context).

### 3.4 Local Excel import

Two modes, one normaliser: a synced path (OneDrive client) or the newest file in `data/inbox/excel/`. The sync client sometimes locks the workbook; copy to temp before opening. Column mapping, sheet names, product, and stable-key columns all live in `excel_mapping.yaml`. If the file is missing or unreadable the connector returns `NOT_CONFIGURED`/`FAILED` with the last successful import date, and existing Excel deals are kept with their `last_seen_at` unchanged; the UI shows "⚠ Not connected — last data 14 Sep".

### 3.5 .msg parsing

`extract-msg` handles Outlook `.msg` (sender, recipients, date, subject, body, attachments). `.eml` via the stdlib `email` package. `.pdf` via `pypdf` text extraction with header heuristics (From/To/Sent/Subject lines). `.txt` with the same heuristics. Dedupe by Message-ID when present, else SHA-256 of normalised body. Direction is decided by comparing sender to `user_email_addresses` in `sources.yaml`; this is what turns "I'll send X" into a *user* commitment.

### 3.6 Zoom transcript identification/matching

Zoom exports `.vtt` (timestamped, speaker-labelled) or `.txt`. Filenames usually contain the meeting topic and date. Matching order: (1) meeting time from the file/filename within ±90 minutes of a known `meetings` row → inherit its company/deal (0.85); (2) speaker names against contacts (0.70); (3) company names mentioned in the first minutes (fuzzy). Anything under threshold goes to `review_items` — a transcript attached to the wrong deal would poison memory, so this is the one place the matcher is deliberately conservative.

---

## 4. Microsoft restrictions

Assumed to fail: Graph permissions, SharePoint access, To-Do access. The design has **no code path where a Microsoft failure propagates**:

- Excel is read from disk, never from SharePoint APIs.
- Outlook is read from files the user saves.
- To-Do is Tier 2, `mode: disabled` by default in `sources.yaml`, and the internal `actions` model never depends on it. If it connects, To-Do items become `TODO_TASK` actions (tier 2). If it does not, the Sales OS *is* the task list, which is the spec's stated fallback.
- The connector framework catches all exceptions per connector and records a `sync_runs` row with status `FAILED`/`NOT_CONFIGURED`; the refresh continues with the next source.

---

## 5. AI

### 5.1 Is the abstraction sufficient?

The four-method interface is right for callers; underneath it one generic `complete_json(task, prompt, schema)` keeps providers thin. Add `NullProvider` so the "no AI" path is a normal provider, not a special case scattered through the code. Add `answer_question` for Brain Q&A.

### 5.2 What should deterministic code handle vs AI?

| Deterministic (always) | AI (optional, validated) |
|---|---|
| Sync, diffing, `deal_changes` | Extracting commitments/next steps/state/risks from email and transcript text |
| Matching by id, domain, alias, fuzzy name, calendar | Tie-breaking a match *only* by proposing candidates for the review queue, never by linking |
| Prioritisation and "Why" bullets | Short per-evidence summaries |
| Action creation from structured sources (HubSpot tasks, sheet rows, meetings) | Deal "current situation" paragraph, built only from supplied memories |
| Memory dedupe, supersession, expiry | Phrasing answers to Brain questions from deterministic query results |
| Audit and approval | — (AI never writes externally) |

### 5.3 How should hallucinations be prevented?

Three mechanical controls, all enforced in code rather than by prompt wording:

1. **Quote verification.** Every extracted memory/action must include a verbatim `quote`. Code checks the quote exists in the source text (fuzzy ratio ≥ 0.92 to survive transcript punctuation). Items without a verified quote are dropped and counted in `ai_calls.status = REJECTED_OUTPUT`.
2. **Schema validation.** Outputs are JSON validated against schemas in `ai/prompts/schemas/`. Free text is never parsed.
3. **Closed-world summaries.** `generate_deal_summary` receives only memories and evidence for that deal and must cite an id per sentence; uncited sentences are removed. The AI explains, it does not discover.

### 5.4 How should confidence be represented?

A single 0–1 float on memories, composed as `source_reliability × extraction_confidence × match_confidence`, corroborated upward by additional supporting evidence. Displayed as three bands (High ≥ 0.8, Medium ≥ 0.5, Low), never as a raw number in the main UI. Rule-based extraction is capped at 0.60 so it always reads as "medium" and invites confirmation. Details in doc 04.

### 5.5 What happens when AI is unavailable?

The rules extractor runs (commitment phrases + `dateparser` for date phrases), summaries are templated from structured data, and Brain Q&A returns the deterministic query result as a list. Evidence is marked `extraction_provider = rules` so it can be re-extracted later when a provider is configured (`Reprocess` button on Inbox).

---

## 6. Memory

Summary of the lifecycle rules (full detail in doc 04):

- **Creation:** extraction produces candidates → dedupe by `dedupe_key` → new row or update existing (confidence corroborated, evidence linked).
- **Update:** new evidence linked with `SUPPORTS` raises confidence; `CONTRADICTS` on a high-confidence memory opens a `CONFLICTING_MEMORY` review item rather than flipping state silently.
- **Supersession:** `DEAL_STATE` and `NEXT_STEP` are single-active per deal; the newest observed one supersedes the previous (pointer kept). Commitments are `FULFILLED` when evidence indicates the thing happened (`FULFILS` link).
- **User statements:** the user typing "Pricing was sent yesterday" on a deal creates `USER_INPUT` evidence and a `STATED_BY_USER` memory with confidence 1.0; it can fulfil or retract other memories.
- **Expiry:** commitments past due stay `ACTIVE` and flagged overdue (that is exactly when they matter). After a configurable 30 days overdue with no fulfilment, a `STALE_COMMITMENT` review item asks the user; unanswered items expire after 60 days.
- **Confidence calculation:** see §5.4; never decays with time for commitments, decays for `INFERRED` hypotheses lacking corroboration.

---

## 7. Security

| Concern | Decision |
|---|---|
| Local storage | `data/` holds the SQLite file, processed files, exports; whole directory gitignored |
| Credentials | `.env` only; `.env.example` documents keys; no credentials in `config/` |
| AI data transmission | Every call logged in `ai_calls`; deal values and phone numbers never included in prompts; optional email-address redaction; Settings shows the provider and today's volume |
| Audit logs | `audit_log` records proposals, approvals, executions and config changes; external writes are impossible without an `APPROVED` audit row |
| File handling | Inbox files are moved (not copied) to `data/processed/<kind>/<yyyy-mm>/` after processing; `.msg` parsing is offline; attachments are stored but never executed or opened |
| Git safety | `.gitignore` covers `.env*`, `data/`, service-account JSON, tokens; pre-commit hook recommended (doc 08) |
| Corporate device | No admin rights needed, no service/daemon, no inbound ports (Streamlit bound to `localhost`), no telemetry (`gatherUsageStats=false`), proxy respected via standard env vars. The tool never bypasses IT controls; it reads files the user already has |

---

## 8. UX — does this reduce work?

Applying the test to spec features:

| Feature | Verdict |
|---|---|
| Today page with tiers, Why bullets, ↑↓/Snooze/Complete/Dismiss | Core. Replaces opening six tools |
| Deals page + detail | Core. Replaces HubSpot + Excel cross-referencing |
| Inbox page (source health, processed files, questions, pending approvals) | Core, but keep it one page. It is where the user drops files and answers questions |
| Settings (weights, mappings, AI provider) | Needed, minimal: edit YAML through a form |
| Brain Q&A free-text | **Deferred to late V1.** The ten questions in Section 39 are covered by deterministic panels on deal detail ("You owe", "They owe", "State", "People", "Last call", "Changed since yesterday") plus FTS search. A chat box adds surface area without removing work |
| Separate "Brain" page | Out of V1, as the spec suggests |
| Manual reordering by drag-and-drop | Out. Streamlit makes it awkward; ↑/↓ + pin captures the same signal |
| Suggested weight adjustments | Late V1: a read-only insight card on Settings once ≥ 30 feedback events exist. Never applied automatically |

---

## 9. Build sequence challenge

The spec builds all connectors (Phase 2) before any dashboard (Phase 3). That delays the first useful morning by four connectors. **Recommendation:** build a thin vertical slice first — schema → HubSpot → prioritisation → Today page — then widen. The phases in doc 10 keep the spec's numbering but reorder the first two into a slice. Every phase ends with the app runnable and the Today page showing more than before.

---

## Spec deltas

| # | Original spec | Change | Reason |
|---|---|---|---|
| 1 | `memories.source_evidence_ids`, `actions.evidence_ids` columns | Link tables with quotes | Queryable provenance; quote verification |
| 2 | Memory has `valid_from/valid_until` only | + `status`, `superseded_by_id`, `basis`, `direction`, `dedupe_key`, `due_text` | Supersession chain, owner of commitment, fact vs hypothesis |
| 3 | Twelve tables | + `company_aliases`, `deal_changes`, `processed_files`, `review_items`, `ai_calls`, link tables | Learning matcher, change history, hash tracking, ask-don't-guess, AI transparency |
| 4 | Action types list | + `MEETING_PREP`, `MEETING_FOLLOWUP`, `COMMITMENT`, `DATA_HYGIENE`, `REVIEW`; `MEETING` split into prep/follow-up | Distinct behaviours and tiers |
| 5 | Prospecting "ranks below" via weights | Hard `tier` sort key | Weights cannot guarantee ordering |
| 6 | Single priority score | Deal score + derived action score, breakdown stored | Today shows actions; value/close are deal properties |
| 7 | Memory types | + `RISK` | Section 24 asks for risks/blockers |
| 8 | Evidence types | + `TODO_TASK` | Tier 2 connector needs a type |
| 9 | Build: all connectors then dashboard | Vertical slice first | Earlier usefulness, earlier feedback on weights |
| 10 | Brain Q&A | Deterministic panels first; free-text Q&A late V1 | Reduces work test |
| 11 | Repo layout `app/pages/*.py` | Same, plus `core/ingestion/` for the inbox pipeline and `core/brain/` for the query layer | Section 8/9/34 pipeline needs a home that is not a connector |
