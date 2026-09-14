---
name: salesos-architecture-guardrails
description: The Sales OS invariants every PR must preserve, with how to check each one. Use when reviewing a PR, before merging, or when unsure whether a change is allowed by the architecture.
icon: shield
color: red
---

# Architecture guardrails

Source of truth: `docs/01-architecture-review.md`, ADRs in `docs/adr/`. If a PR needs to break one of these, it must add an ADR and the lead must flag it to the user.

| # | Invariant | How to check |
|---|---|---|
| 1 | Prioritisation is deterministic; `core/prioritisation` never imports `ai/` | `rg "from ai|import ai" core/prioritisation` returns nothing; fixtures pass |
| 2 | Prospecting (`tier 3`) never outranks tier 1/2 | test `test_prospecting_never_above_tier1`; Today query orders by `tier` first |
| 3 | External writes only via `core.audit.execute_approved()`; write flags default `false` | `rg "def write" connectors/` — each asserts `audit_id`; `sources.yaml` `writes.*: false` unchanged |
| 4 | AI extractions require a verified quote; inferred items capped at 0.5; summaries cite per sentence | validator tests with hallucinated-quote and uncited fixtures |
| 5 | Microsoft-managed sources are optional; failures are ⚠ statuses | unset env → `NOT_CONFIGURED`; no import of `msal`/Graph at module top level outside `connectors/todo` |
| 6 | No connector/parser exception reaches a page | `BaseConnector.run()` and inbox pipeline catch-all tests; page wrappers |
| 7 | Provenance via link tables with quotes, not JSON id arrays | no new `*_ids_json` columns in migrations |
| 8 | SQLite only; migrations append-only | no new DB drivers in `requirements.txt`; no edits to applied `NNN_*.sql` |
| 9 | Streamlit on localhost, stats off | `.streamlit/config.toml` unchanged; no `--server.address 0.0.0.0` anywhere |
| 10 | Secrets and data never in Git | `git diff main --name-only` contains no `.env`, `data/*` (except `.gitkeep`), `service_account*.json` |
| 11 | Prompts never contain deal values, phones, attachments | prompt-render test asserts absence |
| 12 | No V1 out-of-scope features | reject: email sending, autonomous CRM updates, Graph mail, ML training, forecasting/quota, multi-user, vector DB, drag-and-drop reorder |
| 13 | User adjustments bounded; system never changes weights itself | `max_boost_points` respected; weight edits only via Settings form + `CONFIG_CHANGE` audit row |
| 14 | Every high-priority item has Why bullets from structured data | `explain()` output used by cards; no AI text in Why |

## Review output format
```
Guardrails: 14/14 ✓   (or list the failing numbers with the file:line)
Tests: n added, suite green
Scope: within ticket area ✓ / touches <path> outside area
Decision: merge | request changes (bullets with concrete fixes) | escalate to user (reason from the autonomy contract)
```
