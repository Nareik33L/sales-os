# 02 — Data Model

Executable form: `database/migrations/001_initial.sql`. Applied by `database/db.py`. Verified by `tests/test_schema.py`.

## Conventions

- **IDs** are ULIDs stored as TEXT. Sortable by creation time, generated in Python, no coupling to autoincrement.
- **Timestamps** are ISO-8601 UTC (`2026-09-14T08:42:00Z`). **Dates** (`close_date`, `due_date`) are ISO dates in the user's timezone (`SALESOS_TIMEZONE`).
- **Enums** are `CHECK` constraints. Bad data fails at insert time, not on the dashboard.
- **`*_json`** columns hold metadata only. Anything that must be joined or filtered is a column or a link table.
- **Foreign keys** are on (`PRAGMA foreign_keys = ON`). Deletion of an entity nulls references from evidence/memories/actions rather than cascading, because provenance must outlive a bad merge.

## Entity map

```
companies ──< company_aliases
    │
    ├──< contacts
    │
    └──< deals ──< deal_changes
            │
            ├──< evidence >── evidence_fts (FTS5 shadow)
            │        │
            │        ├──< memory_evidence >── memories ──(superseded_by)──> memories
            │        ├──< action_evidence >── actions
            │        └──< audit_log_evidence >── audit_log
            │
            ├──< meetings ──(transcript_evidence_id)──> evidence
            │
            └──< actions ──< user_feedback

prospecting_items ──(row_key = actions.source_id)──> actions
sync_runs, processed_files, review_items, ai_calls, settings, schema_migrations
```

## Tables

### companies, company_aliases

`companies.normalised_name` is the matching key (lowercase, legal suffixes stripped — rules in `config/matching.yaml`). `is_strategic` is a user-set flag that feeds prioritisation as an explicit, visible adjustment; the system never sets it.

`company_aliases` is how matching learns without retraining anything. Every user confirmation in the review queue writes an alias (`source = USER`, confidence 1.0 next time). Connectors add domains and labels (`source = HUBSPOT|EXCEL`). Unique on `(alias_type, value)` so one label cannot point at two companies.

### contacts

Email is the primary identity (unique when present). `company_id` is nullable: a contact seen only in a transcript may not yet have a company. `role_in_deal` is a convenience label; real relationship knowledge is a `RELATIONSHIP` memory with evidence.

### deals, deal_changes

One row per external deal; `(source, external_id)` is unique. Both products land here (`product` from `sources.yaml`) so the Deals page is a single query.

Key derived columns and who owns them:

| Column | Owner | Notes |
|---|---|---|
| `deal_value_gbp` | connector | static rates from `sources.yaml`; ranking only |
| `last_activity_at` | activity aggregator | `max(source engagement, local evidence)`; definition in doc 03 §3 |
| `priority_score`, `priority_breakdown_json`, `attention_status` | prioritisation engine | recomputed after every refresh and every feedback event |
| `summary`, `summary_updated_at`, `summary_stale` | summariser | `summary_stale = 1` whenever new evidence or memory touches the deal; regenerated lazily when viewed |
| `user_pinned_rank`, `user_boost` | user via feedback controls | bounded by config |
| `last_seen_at` | connector | if a deal disappears from the source it is not deleted; the UI shows "not seen since" |

`deal_changes` is written by the connector diff for a fixed field list (`stage`, `close_date`, `deal_value`, `owner`, `is_closed`). It powers "Recently changed" on Today and "Changed since yesterday" on deal detail. Excel changes appear here too, so the Excel product gets change awareness it never had.

### evidence, evidence_fts

The provenance layer. Every row is a thing that happened, with the full text kept locally. `(source, source_id)` is unique for API-sourced items; file-sourced items dedupe on `content_hash`.

`direction` matters more than it looks: it is what decides whether "I'll send the pricing tomorrow" is a `USER_TO_CUSTOMER` commitment or a `CUSTOMER_TO_USER` one. Connectors set it from `user_email_addresses` / `user_speaker_names` in `sources.yaml`.

`extraction_status` / `extraction_provider` let the Inbox page show what has been processed by what, and let the user re-run extraction after enabling an AI provider.

`evidence_fts` is an FTS5 external-content table kept in sync by triggers. Search over `title`, `content`, `summary`.

### memories, memory_evidence

Full lifecycle rules in doc 04. Schema-level invariants:

- `confidence` in [0, 1].
- `status` is the lifecycle: `ACTIVE → FULFILLED | SUPERSEDED | EXPIRED | RETRACTED | REJECTED`. Only `ACTIVE` memories drive prioritisation and summaries; the others remain for history and "why did this change".
- `basis` is orthogonal to `type`: an `OBSERVED` `DEAL_STATE` has a quote; an `INFERRED` one does not and is rendered with an "inferred" tag.
- `direction`, `owner_label`, `due_date`, `due_text` are populated for `COMMITMENT` and `NEXT_STEP`. `due_text` keeps the original phrase ("Friday") so the resolved date can be re-derived if the evidence date was wrong.
- `superseded_by_id` gives the chain; `memory_evidence.relation` says how a piece of evidence relates (`SUPPORTS`, `FULFILS`, `CONTRADICTS`, `SUPERSEDES`).
- `memory_evidence.quote` is the verbatim span. Verified by code against `evidence.content` before insert (doc 07 §3).

### actions, action_evidence

The unified working list. `(source, source_id)` is unique so re-syncing a HubSpot task or a sheet row updates rather than duplicates.

- `tier` is the primary sort key (1 deal work, 2 follow-ups/admin, 3 prospecting). Assigned from `type` via `priority_weights.yaml`.
- `origin_memory_id` links a `COMMITMENT` action to its memory; completing the action offers to mark the memory `FULFILLED` (user confirms).
- `external_write_status` tracks approval-gated writes (`PROPOSED → APPROVED → WRITTEN`). `NOT_APPLICABLE` for internal-only actions. The gate itself is `audit_log`.
- `system_rank` is the position the system assigned at last computation; `user_feedback` compares it with what the user did.

### meetings

Calendly is the primary source; HubSpot meetings and transcripts can also create rows. `transcript_evidence_id` links a held meeting to its transcript, which is how a transcript inherits company/deal. `followup_action_id` lets prioritisation see "meeting held yesterday, no follow-up yet".

### prospecting_items

Normalised sheet rows. `row_key` is the stable identity (columns configured in `sources.yaml`). `sheet_row_number` is kept only to help the user find the row. Each open row yields one `actions` row (`type = PROSPECTING`, `source = google_sheets`, `source_id = row_key`). `done = 1` in the sheet completes the action; completing the action in Sales OS does **not** tick the sheet unless the approval-gated write is enabled.

### sync_runs

One row per connector per refresh. `status` distinguishes `NOT_CONFIGURED` (no credentials — expected for Excel/To-Do) from `FAILED` (credentials present, call failed) so the UI can show ⚠ with the right message. `cursor_json` stores incremental watermarks (HubSpot `hs_lastmodifieddate`).

### processed_files

Hash registry for the inbox folders. `DUPLICATE` rows record that a re-dropped file was recognised and skipped. `stored_path` points into `data/processed/`. "Reprocess" resets `evidence.extraction_status`, not this table.

### review_items

The "ask me rather than guess" queue. `kind` covers matching (`MATCH_COMPANY|DEAL|CONTACT`), memory (`CONFLICTING_MEMORY`, `CONFIRM_MEMORY`, `STALE_COMMITMENT`) and data hygiene (`CLOSE_DATE_PASSED`). `candidates_json` holds ranked options with reasons; `resolution_json` holds the choice. Resolving a match writes a `company_aliases` row and records `MATCH_CONFIRMED|CORRECTED` in `user_feedback`.

### audit_log, audit_log_evidence

Every proposal to change an external system, every approval/rejection, every execution, and every config change. `proposed_change_json` is the exact payload. Invariant enforced in `core/audit`: a connector write method requires an `audit_log` row with `approval_status = APPROVED` for that action; there is no other entry point.

### ai_calls

One row per provider call: purpose, evidence/deal touched, characters in/out, redaction flag, status (`REJECTED_OUTPUT` when validation dropped the result). Settings shows a daily total so the user knows what left the machine.

### user_feedback

Behavioural signals only. `system_priority` vs `user_priority` plus a `context_json` snapshot (value, days to close, staleness, tier, `is_strategic`) is enough to detect the patterns in Section 16 later with plain SQL — no model.

### settings

Key/JSON store for UI state and small preferences (`last_morning_refresh`, `today_greeting_name`). Weights live in YAML, not here, so they are diffable in Git.

## Indexes worth noting

- `deals(is_closed, priority_score DESC)` — Today and Deals pages.
- `actions(status, tier, priority_score DESC)` — the Today list.
- `memories(deal_id, status, type)` — "you owe / they owe / state" panels.
- `evidence(deal_id, occurred_at DESC)` — recent evidence on deal detail.
- `deal_changes(changed_at DESC)` — recently changed.

## Migration policy

Plain SQL files `NNN_name.sql`, applied once in order, recorded in `schema_migrations`. No ORM migrations. Destructive changes (drop/rename) get a new file that copies data; SQLite's limited `ALTER TABLE` is worked around with create-copy-drop.
