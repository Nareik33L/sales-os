# Changelog

Sales OS versions follow `0.<phase>.<patch>`. There was no tagged 0.1.0
release; 0.2.0 is the first versioned cut (Phase 2 vertical slice).

## 0.2.0 — 2026-09-14

Phase 2 — HubSpot → deterministic prioritisation → Today.

### Added

- HubSpot connector: deals, companies, contacts, engagements and tasks; incremental cursor; `last_activity_at` recompute; open tasks become `HUBSPOT_TASK` actions. Missing token → `NOT_CONFIGURED` / ⚠, not a crash.
- Prioritisation engine (`core/prioritisation`): doc 03 fixtures including the Acme worked example at **82.4 HIGH**; stored breakdown; `explain()` Why bullets from structured data. Never calls the AI provider.
- Today page v0: START HERE ordered `tier ASC, user_pinned_rank NULLS LAST, priority_score DESC`; Why bullets; Complete / Snooze / ↑ / ↓ / Dismiss write `user_feedback`; ↻ Refresh with per-connector status (HubSpot ⚠ if not connected).
- Audit / approval gate (`core.audit.execute_approved`): external writes refuse without an APPROVED audit row. `writes.complete_task` stays `false`.
- Memory lifecycle (doc 04): dedupe-key update, corroboration, FULFILS, single-active supersede, conflict → review item, commitment → action.
- Connector base + refresh orchestrator: `sync_runs` for every run; exceptions never escape to a page; other connectors continue on failure.
- Config loaders for all `config/*.yaml` (weights must sum to 1.0); rotating log under `data/logs`; `python run.py --demo` seeds fictional Acme / Beta Corp / Gamma / Delta data and exits without Streamlit.
- CI: ruff, pytest, empty-DB migrate, YAML/JSON validation. Shared fixtures `db`, `seeded_db`, `frozen_now`, `fake_provider`.
- Phase 2 release fixture `tests/release/db_v0.2.0.sqlite` (fictional data) for migration-safety checks.

### Changed

- `python run.py` migrates then launches Streamlit Today at http://localhost:8501 (localhost only; ADR-008).

### Requires from you

- `HUBSPOT_ACCESS_TOKEN` — HubSpot private-app token for live data on Today. Copy `.env.example` to `.env`. Live steps are in [docs/manual-tests/phase-2.md](docs/manual-tests/phase-2.md).
- Optional and unused in Phase 2 (leave blank): `GOOGLE_SERVICE_ACCOUNT_FILE`, `GOOGLE_SHEETS_SPREADSHEET_ID`, `CALENDLY_ACCESS_TOKEN`, `EXCEL_SYNCED_FILE_PATH`. Those sources show ⚠ or –; the page still renders.

### Known gaps

- `writes.complete_task` and `writes.mark_done` remain `false`.
- Deals, Inbox and Settings are sidebar stubs (SOS-15 / SOS-25 / SOS-31).
- Excel, Calendly, Sheets, email/transcript inbox and AI extraction ship in Phase 3+.
