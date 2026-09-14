# 10 — Build Plan

Keeps the spec's numbering (1–32) but reorders Phases 1–3 into a vertical slice so the Today page exists after the first connector. Each phase ends with the app runnable and the Today page showing more than before. Phases are not time estimates; they are dependency-ordered increments.

## Phase 1 — Foundation *(this package delivers items 1–6 as schema + docs)*

| # | item | deliverable | acceptance |
|---|---|---|---|
| 1 | SQLite database | `database/db.py`, `001_initial.sql` | `pytest tests/test_schema.py` passes ✔ |
| 2 | Core data models | `core/models/` pydantic models mirroring tables; repositories with upsert+diff | round-trip tests; `deal_changes` written on diff |
| 3 | Evidence model | `core/models/evidence.py`, hash + dedupe | duplicate insert is a no-op |
| 4 | Memory model | `core/memory/` create-or-update, relations, confidence maths | fixture tests from doc 04 §3–6 |
| 5 | Action model | `core/models/action.py`, tier assignment | tier from type via config |
| 6 | Audit model | `core/audit/` propose/approve/execute gate | write without APPROVED row raises |

Also: `run.py` (migrate + launch Streamlit), `config/` loaders with validation, logging setup, `.streamlit/config.toml`.

## Phase 2 — Vertical slice: HubSpot → prioritisation → Today

| # | item | acceptance |
|---|---|---|
| 7 | HubSpot connector | deals/companies/contacts/engagements/tasks land; `sync_runs` row; second run is incremental; `last_activity_at` recomputed |
| 15 | Prioritisation engine | doc 03 fixtures pass; breakdown stored; Why bullets rendered |
| 11 | Today page (v0) | opens at 08:00 with HubSpot tasks tiered and scored, Why bullets, Complete/Snooze/↑/↓/Dismiss writing `user_feedback` |
| 27 | Connector health (v0) | failed HubSpot token shows ⚠ and the page still renders |

**Exit:** the user can replace "open HubSpot, review tasks, review deals" with Today.

## Phase 3 — Remaining structured sources + Deals pages

| # | item | acceptance |
|---|---|---|
| 10 | Local Excel importer | mapping-driven; missing file → ⚠ with last data date; both products on Deals |
| 9 | Calendly connector | meetings on Today; `MEETING_PREP`/`FOLLOWUP` actions; meeting proximity affects score |
| 8 | Google Sheets connector | Today tab → tier-3 actions; `Done` completes; CSV fallback works identically |
| 12 | Deals page | both products, filters, badges |
| 13 | Deal detail (structured) | header, Why, next actions, recent evidence, changed since yesterday (from `deal_changes`) |
| 14 | Unified action list | all tiers on Today; deal cards for high-score deals without actions |

**Exit:** Excel, Sheets and Calendly no longer need opening in the morning.

## Phase 4 — Unstructured intelligence

| # | item | acceptance |
|---|---|---|
| 18 | Entity matching | doc 06 rules; thresholds from config; review queue on Today/Inbox; aliases learned |
| 16 | Email file ingestion | `.msg/.eml/.txt/.pdf` → evidence with direction; moved to processed; hashes tracked |
| 17 | Zoom transcript ingestion | `.vtt/.txt` → evidence; calendar-correlated matching; unmatched → question |
| 19 | AI extraction | provider abstraction; Null/OpenAI/Local; quote verification; `ai_calls`; rules fallback |
| 20 | Memory updates | commitments, fulfilment, supersession, conflict items; commitment → action |
| 21 | Deal summaries | closed-world, cited, templated fallback; "You owe / They owe / Waiting on internally" panels |

**Exit:** the Section 2 example works end to end — email creates a commitment and an action; a later transcript fulfils it; the Today card disappears; the deal timeline shows it.

## Phase 5 — Learning (record only)

| # | item | acceptance |
|---|---|---|
| 22 | User feedback | all controls write `user_feedback` with system/user priority and context snapshot |
| 23 | Manual priority overrides | pin, bounded boost, strategic flag; visible in Why |
| 24 | Behaviour tracking | SQL views: agreement rate, boost distribution by context |
| 25 | Suggested adjustments | Settings insight cards after ≥ 30 events; never auto-applied |

## Phase 6 — Safety / polish

| # | item | acceptance |
|---|---|---|
| 26 | Audit/approval framework (UI) | Inbox approvals section; HubSpot `complete_task` and Sheets `mark_done` behind flags; audit rows for every step |
| 27 | Connector health monitoring | full health table; errors viewable; last-good-data dates |
| 28 | Error handling | no connector or parser exception reaches the page; failed files retried once then quarantined |
| 29 | Tests | schema, prioritisation fixtures, memory rules, matcher rules, parsers with fictional fixtures, audit gate |
| 30 | Documentation | README quick start, per-connector setup, backup/restore, "what leaves this machine" |

## Phase 7 — Optional Microsoft

| # | item | acceptance |
|---|---|---|
| 31 | Microsoft To-Do | Graph read if consent exists; CSV fallback; every failure → ⚠ not error |
| 32 | Other Microsoft | only with explicit permission; file-based first |

## Definition of done for V1

- Morning: open `localhost:8501`, one refresh, Today shows all tiers with Why bullets; at least HubSpot + Excel + Sheets + Calendly + emails + transcripts feeding it.
- Any connector can be unconfigured or failing and the page still renders with ⚠.
- No external write is possible without an approved audit row; write flags default off.
- `AI_PROVIDER=none` gives a fully working system; enabling a provider adds extraction and summaries with every call logged.
- Tests pass; `.env` and `data/` cannot be committed by accident.

## Repository layout (final)

```
sales-os/
├── app/                 main.py, pages/{today,deals,deal_detail,inbox,settings}.py, components/
├── core/                models/, prioritisation/, matching/, memory/, summarisation/, audit/, ingestion/, brain/
├── connectors/          base.py, hubspot/, google_sheets/, calendly/, excel/, email_files/, transcripts/, todo/
├── ai/                  provider.py, providers/{null,openai,local}_provider.py, prompts/ (+ schemas/)
├── database/            db.py, migrations/NNN_*.sql
├── config/              sources.yaml, priority_weights.yaml, excel_mapping.yaml, matching.yaml, ai.yaml
├── data/                inbox/{emails,transcripts,excel,prospecting,todo}/, processed/, exports/   (gitignored)
├── docs/                this package + adr/
├── tests/
├── requirements.txt, .env.example, .gitignore, README.md, run.py
```

`core/ingestion/` (inbox pipeline, refresh orchestrator) and `core/brain/` (deterministic question queries) are additions to the spec's layout (doc 01 delta 11).
