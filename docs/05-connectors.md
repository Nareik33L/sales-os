# 05 — Connectors

Every connector turns an external source into the internal model and reports its own health. The rest of the application never imports a connector directly; it calls the refresh orchestrator and reads tables.

## 1. Common interface

```python
class Connector(Protocol):
    name: str                      # "hubspot", "excel", …  (key in sources.yaml)
    tier: int
    mode: Literal["api", "file", "disabled"]

    def is_configured(self) -> bool: ...          # required env present / file path readable
    def connect(self) -> None: ...                # build client; raise ConnectorNotConfigured / ConnectorAuthError
    def authenticate(self) -> None: ...           # cheap auth probe (e.g. GET /owners); used by health check
    def fetch(self, cursor: dict | None) -> FetchResult: ...   # raw records + next cursor
    def normalise(self, raw) -> NormalisedBatch: ...           # -> Deal / Company / Contact / Meeting / Evidence / Action rows
    def save(self, batch, conn, sync_run_id) -> SaveStats: ... # upsert + diff -> deal_changes; never deletes

    # Optional, approval-gated. Only callable by core.audit.execute_approved().
    write_capabilities: set[str]                  # {"complete_task"} for HubSpot, {"mark_done"} for Sheets
    def write(self, capability: str, payload: dict) -> WriteResult: ...
```

`BaseConnector` implements the orchestration around these: opens a `sync_runs` row, wraps each step in try/except, records counts and errors, sets status (`SUCCESS` / `PARTIAL` / `FAILED` / `NOT_CONFIGURED` / `SKIPPED`), and **never lets an exception escape** to the orchestrator. `records_changed` comes from `save()` diffing, so "123 checked, 4 changed" is real.

### Refresh orchestrator (`core/ingestion/refresh.py`)

```
for connector in enabled_connectors(sources.yaml):     # Tier 1 first
    run = connector.run(trigger)                         # isolated; always returns a sync_runs row
process_inbox_folders()                                  # emails, transcripts, excel, prospecting csv
recompute_activity_dates()
run_extraction_for_pending_evidence()                    # AI or rules
recompute_priorities()
```

Triggers: `STARTUP` (app opened, no run today, after `morning_refresh_hour_local`), `MANUAL` (↻ button), `FILE_DROP` (user clicked "Process inbox"). No daemon, no scheduler.

### Health display

| status | icon | message |
|---|---|---|
| SUCCESS | ✓ | "Last sync 08:42 · 123 checked · 4 changed" |
| PARTIAL | ✓⚠ | "… · 2 errors (view)" |
| FAILED | ⚠ | "Failed: <first error> · last good data 13 Sep" |
| NOT_CONFIGURED | ⚠ | "Not connected · last available data 14 Sep" |
| SKIPPED / disabled | – | "Disabled in sources.yaml" |

## 2. HubSpot (Tier 1, API)

**Auth:** Private App access token (`HUBSPOT_ACCESS_TOKEN`). Read scopes: `crm.objects.deals.read`, `crm.objects.companies.read`, `crm.objects.contacts.read`, `crm.objects.owners.read`, `crm.schemas.deals.read`; `sales-email-read` only if logged email bodies are wanted.

**Fetch (v3 CRM):**

| object | endpoint | notes |
|---|---|---|
| pipelines/stages | `GET /crm/v3/pipelines/deals` | labels for stage ids; `closedwon`/`closedlost` metadata gives `is_closed/is_won` |
| owners | `GET /crm/v3/owners` | id → name |
| deals | `GET /crm/v3/objects/deals` with `properties=dealname,amount,deal_currency_code,dealstage,pipeline,closedate,hubspot_owner_id,createdate,hs_lastmodifieddate,notes_last_updated&associations=companies,contacts` | incremental via search `hs_lastmodifieddate > cursor` on subsequent runs; closed deals older than `include_closed_deals_days` skipped |
| companies | `GET /crm/v3/objects/companies` for associated ids | `name, domain, industry` → company + `DOMAIN` alias |
| contacts | associated ids | `firstname, lastname, email, phone, jobtitle` |
| engagements | `GET /crm/v3/objects/{calls,meetings,notes,emails,tasks}` with `associations=deals` | one `evidence` row each (`HUBSPOT_ACTIVITY`); open tasks → `actions(type = HUBSPOT_TASK)`; completed tasks feed `last_activity_at` |

**Normalise:** `deals.source = HUBSPOT`, `product = XODO_SIGN` (from `sources.yaml` product whose `source_of_truth = HUBSPOT`), `deal_value_gbp` via static rates. `last_activity_at` is recomputed from fetched engagements rather than trusting `notes_last_updated`.

**Limitations to design around:**
- Logged email bodies are often truncated or HTML; `HUBSPOT_ACTIVITY` evidence has `source_reliability 0.8`. A saved `.msg` of the same email supersedes it by `content_hash`/subject+date match.
- Search API has a lower rate limit than list endpoints; volume here is tiny, but keep to one search call per object type per run.
- Associations v4 are needed for association *labels* (e.g. "decision maker"); v1 does not need labels.

**Write (gated):** `complete_task` → `PATCH /crm/v3/objects/tasks/{id}` `hs_task_status = COMPLETED`. Only via `core.audit.execute_approved()`. Disabled in `sources.yaml` until the user turns it on.

## 3. Google Sheets (Tier 1, API with file fallback)

**Auth:** service account JSON (`GOOGLE_SERVICE_ACCOUNT_FILE`); the sheet is shared with the SA email (viewer). If the Workspace tenant blocks external sharing, an OAuth installed-app flow is a second option; if both are blocked, **file mode**.

**Fetch:** `spreadsheets.values.get` on `{TAB}!A:Z` once per refresh. Header row → column map by header text (the columns in Section 6). Unknown columns are kept in `raw_row_json`.

**Row identity:** `row_key = sha1(normalise(Sequence ID) | normalise(Company) | normalise(Contact) | normalise(Step))` (columns configurable). Rows that disappear from the tab are not deleted; `last_seen_at` stops advancing and their action is auto-completed with `dismissed_reason = "row left Today tab"` after 3 days unseen — the user moved it, so Sales OS follows.

**Normalise:** `prospecting_items` row + one `actions` row: `type = PROSPECTING`, `tier 3`, `title = "{Company} — {Step} ({Channel})"`, `description = Subject`, `due_date = Due date`, `source_id = row_key`. `Done = TRUE` → action `COMPLETED`. `Outcome`/`Notes` (when present) become `PROSPECTING_ACTIVITY` evidence on the company if the company matches an existing one (prospects usually will not; that is fine).

**File fallback:** `data/inbox/prospecting/*.csv` exported from the Today tab; identical normaliser; `processed_files` tracks the hash.

**Write (gated):** `mark_done` → `values.update` of the `Done` cell for the row found by `row_key` at write time (re-locate the row; never trust the stored row number). Off by default.

## 4. Calendly (Tier 1, API)

**Auth:** Personal Access Token (`CALENDLY_ACCESS_TOKEN`), v2 API.

**Fetch:** `GET /users/me` → user uri; `GET /scheduled_events?user={uri}&min_start_time={now − past_days}&max_start_time={now + future_days}&status=active|canceled`; for each event `GET /scheduled_events/{uuid}/invitees` for name/email; `event_type` name from the event.

**Normalise:** `meetings(source = CALENDLY)`, `status` from Calendly (`active` → `SCHEDULED`, past end → `HELD`, `canceled` → `CANCELLED`). Company via invitee email domain (doc 06) → `company_id/deal_id`. One `CALENDLY_MEETING` evidence row per event; held meetings count as activity.

**Derived actions:** meeting today → `MEETING_PREP`; meeting held with no follow-up after 24h → `MEETING_FOLLOWUP` (both tier 1, dedupe on `source_id = meeting id + kind`).

**Limitations:** invitee company is not a first-class field; custom questions ("Company?") are read if present. Freemail invitees go to the review queue only if the event is within 7 days (otherwise noise).

## 5. Excel (Tier 1, file)

**Read order:** `EXCEL_SYNCED_FILE_PATH` → `excel_mapping.yaml: file.synced_path` → newest `*.xlsx` in `data/inbox/excel/`. If the source is a synced path, copy to a temp file first (`copy_before_open`) to avoid OneDrive locks. If nothing is readable → `NOT_CONFIGURED`, existing Excel deals untouched, UI shows last data date.

**Parse:** `pandas.read_excel(..., sheet_name=…, header=header_row − 1, engine="openpyxl")`; columns mapped by `excel_mapping.yaml: columns` (case-insensitive header match); missing mapped columns warn once per run and leave NULLs; rows with empty `skip_rows_where_empty` columns skipped; values cleaned with `value_strip_chars`; dates parsed with the listed formats.

**Identity:** `external_id = sha1(normalised stable_key_columns)`. If the workbook gains an ID column, set `stable_key_columns: ["ID"]`.

**Normalise:** `deals(source = EXCEL, product = mapping.product)`; `company` created/matched by name (`EXCEL_LABEL` alias recorded). Closed sheet rows → `is_closed = 1`, `is_won` from `won_column`. Diff → `deal_changes`, so Excel deals get change tracking.

**Inbox behaviour:** a workbook dropped into `data/inbox/excel/` is processed then moved to `data/processed/excel/<yyyy-mm>/`; hash recorded; re-dropping the same file is a no-op.

## 6. Email files (Tier 1, file)

**Folder:** `data/inbox/emails/`. Formats: `.msg` (extract-msg), `.eml` (stdlib `email`), `.pdf` (pypdf text + header heuristics), `.txt` (header heuristics).

**Parse → evidence:**

| field | source |
|---|---|
| `source_id` | Message-ID header when present, else `sha256(normalised body + date + subject)` |
| `occurred_at` | Date header (tz-aware) |
| `direction` | sender ∈ `user_email_addresses` → OUTBOUND else INBOUND |
| `participants_json` | from/to/cc with names |
| `title` | subject (`Re:`/`Fwd:` stripped for matching, kept for display) |
| `content` | plain-text body; HTML converted; quoted history below the reply marker kept but tagged so extraction weights the top |
| attachments | saved under `data/processed/emails/<yyyy-mm>/<hash>/`, listed in `metadata_json`; never opened |

Matching: recipient/sender domains → company (doc 06). Multiple non-freemail external domains → best match auto-links if it maps to an open deal, otherwise review item.

Thread handling: `In-Reply-To`/`References` headers stored in `metadata_json`; later used to attach a reply to the same deal automatically.

## 7. Zoom transcripts (Tier 1, file)

**Folder:** `data/inbox/transcripts/`. Formats: `.vtt` (webvtt-py: timestamps + `Speaker: text`), `.txt` (Zoom's plain export: `[HH:MM:SS] Speaker: text` or `Speaker: text`).

**Parse → evidence:** `type = ZOOM_TRANSCRIPT`, `occurred_at` from the filename date pattern (`GMT20260913-143000_Recording…` or `Acme call 2026-09-13`) else file mtime; `participants_json` = distinct speakers; `direction = UNKNOWN`; `content` = `Speaker: text` lines joined (timestamps dropped for FTS quality but kept in `metadata_json`).

**Matching (conservative):**
1. Held `meetings` row within ±`match_to_meeting_window_minutes` of `occurred_at` → inherit company/deal (0.85); set `meetings.transcript_evidence_id`.
2. Speaker names vs `contacts.full_name` (0.70).
3. Company names in the first ~5 minutes of text vs aliases (fuzzy).
4. Below threshold → `MATCH_DEAL` review item. Memories are not created until matched.

`user_speaker_names` decides which speaker is "me" so first-person commitments get the right direction.

## 8. Microsoft To-Do (Tier 2, optional)

Default `mode: disabled`. If enabled with `MS_GRAPH_CLIENT_ID/TENANT_ID`: MSAL device-code flow, `Tasks.Read` delegated scope, `GET /me/todo/lists` → `GET /me/todo/lists/{id}/tasks`. Every failure mode here (admin consent required, conditional access, token cache blocked) is expected and returns `NOT_CONFIGURED` with the Graph error text in `message`.

File fallback: `data/inbox/todo/*.csv` (title, due, list, status). Either way tasks become `actions(type = TODO_TASK, tier 2)`; HubSpot-originated To-Do items are deduped against `HUBSPOT_TASK` actions by title + due date.

No write path in V1.

## 9. Inbox processing pipeline (`core/ingestion/inbox.py`)

```
for kind, folder in inbox folders:
    for file in folder (skip hidden/partial: ~$, .tmp, size changing):
        sha = sha256(file)
        if sha in processed_files: move to processed/…/duplicates, record DUPLICATE, continue
        try:
            evidence = parser[kind](file)         # may return several (multi-email PDF)
            match(evidence)
            move file → data/processed/<kind>/<yyyy-mm>/<sha8>_<name>
            record PROCESSED with stored_path + evidence_id
        except UnsupportedFormat:  record UNSUPPORTED, move to processed/<kind>/unsupported/
        except Exception as e:     record FAILED with error; leave file in place for one retry, then move to failed/
```

Files are moved, not copied, so the inbox is always "what has not been processed yet" — which is what a person expects a folder called inbox to mean.

## 10. Connector build order

1. HubSpot (structured, source of truth, biggest immediate payoff)
2. Excel (unified deal view needs both products)
3. Calendly (meetings feed prioritisation)
4. Google Sheets (prospecting tier)
5. Email files, 6. Transcripts (unstructured intelligence, after matching exists)
7. To-Do (only if permissions allow; never a blocker)
