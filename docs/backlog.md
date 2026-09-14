# Backlog

Maintained by `salesos-lead`. One ticket per build-plan item (`docs/10-build-plan.md`). Status: `todo | in-progress | review | done | blocked`. Branch: `grok/SOS-nn-slug`.

## Phase 1 — Foundation

| ID | Item | Owner | Depends | Acceptance | Status |
|---|---|---|---|---|---|
| SOS-01 | SQLite database + migration runner | core | — | `pytest tests/test_schema.py` green; `run.py --migrate` idempotent | done |
| SOS-02 | Core data models + repositories | core | 01 | pydantic models for every table; `upsert_deal` returns diff and writes `deal_changes`; round-trip tests | done |
| SOS-03 | Evidence model + dedupe | core | 02 | insert by `(source, source_id)` or `content_hash` is idempotent; FTS searchable | done |
| SOS-04 | Memory model + lifecycle rules | core | 03 | doc 04 §3–7 rules as tests: dedupe-key update, corroboration maths, FULFILS, single-active supersede, conflict → review_item, commitment → action; rules extractor with 0.60 cap | done |
| SOS-05 | Action model + tiering | core | 02 | tier from type via `priority_weights.yaml`; `(source, source_id)` upsert | done |
| SOS-06 | Audit / approval gate | core | 02 | `execute_approved` refuses without APPROVED row; audit rows for propose/approve/reject/execute/config_change | done |
| SOS-06b | Config loaders + logging + `--demo` seed | qa | 01 | typed loaders for all `config/*.yaml` with validation (weights sum 1.0); rotating log under `data/logs`; `run.py --demo` seeds fictional data | done |
| SOS-06c | CI workflow + conftest fixtures | qa | 01 | `.github/workflows/ci.yml` runs ruff, pytest, migrate, config validation; fixtures `db`, `seeded_db`, `frozen_now`, `fake_provider` | done |

## Phase 2 — Vertical slice (HubSpot → prioritisation → Today)

| ID | Item | Owner | Depends | Acceptance | Status |
|---|---|---|---|---|---|
| SOS-07 | Connector base + refresh orchestrator | connectors | 02 | `BaseConnector.run()` records `sync_runs`; exceptions never escape; `NOT_CONFIGURED` on missing env; orchestrator continues past failures | done |
| SOS-08 | HubSpot connector | connectors | 07 | fixtures-based tests; deals/companies/contacts/engagements/tasks upserted; incremental cursor; `last_activity_at` recomputed; open tasks → `HUBSPOT_TASK` actions | done |
| SOS-09 | Prioritisation engine | core | 04, 05 | doc 03 fixture cases pass incl. Acme worked example (82.4 HIGH); breakdown stored; `explain()` bullets | todo |
| SOS-10 | Today page v0 | ui | 08, 09 | AppTest: ordering `tier, pinned, score`; Why bullets; Complete/Snooze/↑/↓/Dismiss write `user_feedback`; refresh button with per-connector status; renders with HubSpot ⚠ | todo |
| SOS-11 | Phase 2 release + manual test | qa | 10 | `salesos-release` checklist; `docs/manual-tests/phase-2.md` | todo |

## Phase 3 — Structured sources + Deals pages

| ID | Item | Owner | Depends | Acceptance | Status |
|---|---|---|---|---|---|
| SOS-12 | Excel importer | connectors | 07 | mapping-driven; synced path or drop folder; missing file → ⚠ with last data date; both products on Deals | todo |
| SOS-13 | Calendly connector | connectors | 07 | meetings upserted; `MEETING_PREP`/`FOLLOWUP` actions; proximity affects score | todo |
| SOS-14 | Google Sheets connector + CSV fallback | connectors | 07 | Today tab → tier-3 actions keyed by `row_key`; `Done` completes; CSV path identical | todo |
| SOS-15 | Deals page | ui | 12 | both products, filters, badges, sort by score | todo |
| SOS-16 | Deal detail (structured) | ui | 09, 15 | header, Why, next actions, recent evidence, changed since yesterday | todo |
| SOS-17 | Unified action list + deal cards | ui | 10, 13, 14 | all tiers; high-score deals without actions shown as cards | todo |
| SOS-18 | Phase 3 release + manual test | qa | 17 | — | todo |

## Phase 4 — Unstructured intelligence

| ID | Item | Owner | Depends | Acceptance | Status |
|---|---|---|---|---|---|
| SOS-19 | Entity matcher | core | 03 | doc 06 rule order and thresholds; review_items with candidates; alias learning | todo |
| SOS-20 | Inbox pipeline + email parsers | connectors | 07, 19 | `.msg/.eml/.txt/.pdf` → evidence with direction; move + hash; corrupt → FAILED | todo |
| SOS-21 | Transcript parser + calendar matching | connectors | 13, 20 | `.vtt/.txt`; ±90 min meeting match; unmatched → question | todo |
| SOS-22 | AI provider abstraction + validators | intelligence | 04 | Null/OpenAI/Local; quote verification; schema retry; `ai_calls`; prompt privacy test | todo |
| SOS-23 | Extraction step + rules fallback wiring | intelligence | 22, 20 | PENDING evidence → memories/actions; provider failure → rules | todo |
| SOS-24 | Deal summaries + brain panels | intelligence, core | 22, 16 | closed-world cited summary with templated fallback; you owe / they owe / waiting internally / last call panels | todo |
| SOS-25 | Inbox page (health, questions, approvals, processed, search) | ui | 19, 20, 22 | one page; answering a question re-runs extraction | todo |
| SOS-26 | Phase 4 release + manual test (end-to-end email → transcript → fulfilled) | qa | 25 | Section 2 example passes with fictional files | todo |

## Phase 5 — Learning (record only)

| ID | Item | Owner | Depends | Acceptance | Status |
|---|---|---|---|---|---|
| SOS-27 | Feedback capture completeness + context snapshot | core, ui | 10 | every control writes system/user priority + context_json | todo |
| SOS-28 | Overrides: pin, bounded boost, strategic flag | core, ui | 27 | visible in Why; bounds enforced | todo |
| SOS-29 | Behaviour views + Settings insight cards (≥ 30 events) | core, ui | 27 | read-only suggestions; "Apply" only pre-fills the weights form | todo |

## Phase 6 — Safety / polish

| ID | Item | Owner | Depends | Acceptance | Status |
|---|---|---|---|---|---|
| SOS-30 | Approval UI + gated writes (`complete_task`, `mark_done`) behind flags | connectors, ui | 06, 25 | flags default off; propose → approve → execute audit trail | todo |
| SOS-31 | Settings page (connectors, weights form w/ preview, aliases, Excel mapping, AI banner, data) | ui | 25 | YAML edits + CONFIG_CHANGE audit | todo |
| SOS-32 | Hardening pass: error handling, quarantine, logging review | connectors, qa | 26 | fault-injection suite green | todo |
| SOS-33 | README + per-connector setup docs + backup/restore | qa | 31 | a new laptop can be set up from docs alone | todo |
| SOS-34 | V1 release | qa | 33 | definition of done in `docs/10-build-plan.md` | todo |

## Phase 7 — Optional Microsoft

| ID | Item | Owner | Depends | Acceptance | Status |
|---|---|---|---|---|---|
| SOS-35 | Microsoft To-Do (Graph read + CSV fallback) | connectors | 07 | every failure → ⚠; `TODO_TASK` tier 2; dedupe vs HubSpot tasks | blocked (needs tenant permission) |
