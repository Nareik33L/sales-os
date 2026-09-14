# 00 — Overview

Personal Sales Operating System (Sales OS) — V1 architecture package.

## Principle

> Read broadly. Remember intelligently. Prioritise clearly. Write cautiously.

A local-first working layer over HubSpot, Excel, Google Sheets, Calendly, Zoom transcripts and saved Outlook emails. One user, one laptop, one screen in the morning. It does not replace any of those tools and never writes to them without explicit approval.

## Conceptual architecture

```
Sources ──► Evidence ──► Memory ──► Intelligence ──► Actions ──► Today screen
   ▲                                                                 │
   └──────────────── user feedback / behaviour ◄─────────────────────┘
```

| Layer | Owns | Lives in |
|---|---|---|
| Sources / connectors | Fetch, normalise, diff, record sync health | `connectors/` |
| Evidence | Provenance for everything: the raw thing that happened, with content and participants | `evidence`, `evidence_fts`, `processed_files` |
| Memory | What the brain currently believes, with status, confidence and evidence links | `memories`, `memory_evidence`, `company_aliases` |
| Intelligence | Deterministic prioritisation, matching, change detection; optional AI extraction and summaries | `core/prioritisation`, `core/matching`, `core/memory`, `ai/` |
| Actions | The single working list, tiered and scored, with user feedback | `actions`, `user_feedback` |
| Safety | Approval gate, audit trail, AI transmission log | `audit_log`, `ai_calls` |
| UI | Today, Deals, Deal detail, Inbox, Settings | `app/` (Streamlit) |

## Documents

| Doc | Content |
|---|---|
| [01 Architecture review](01-architecture-review.md) | Section 45 challenge: findings, decisions, spec deltas |
| [02 Data model](02-data-model.md) | Every table, why it exists, key invariants. Executable form: `database/migrations/001_initial.sql` |
| [03 Prioritisation](03-prioritisation.md) | Deterministic scoring, tiers, explanations, conflict rules, learning signals |
| [04 Memory and evidence](04-memory-and-evidence.md) | Lifecycle: creation, dedupe, corroboration, supersession, expiry, confidence |
| [05 Connectors](05-connectors.md) | Common interface, per-source design, API limits, fallbacks, inbox pipeline |
| [06 Entity matching](06-entity-matching.md) | Rule order, thresholds, review queue, how the matcher learns |
| [07 AI boundaries](07-ai-boundaries.md) | Provider abstraction, task contracts, hallucination controls, no-AI mode |
| [08 Security](08-security.md) | Local storage, credentials, AI transmission, audit, corporate device assumptions |
| [09 UI spec](09-ui-spec.md) | Page-by-page layout and controls |
| [10 Build plan](10-build-plan.md) | Phases with acceptance criteria |
| [ADRs](adr/) | Decision records |

## Configuration surface

| File | Purpose |
|---|---|
| `.env` (from `.env.example`) | Credentials and paths. Never committed |
| `config/sources.yaml` | Products, currency rates, connector modes/tiers/fallbacks, refresh policy |
| `config/priority_weights.yaml` | All prioritisation weights, curves, thresholds |
| `config/excel_mapping.yaml` | Excel sheets, columns, stable key |
| `config/matching.yaml` | Matching rule confidences and thresholds |
| `config/ai.yaml` | AI task permissions, validation, privacy |

## Non-goals (V1)

CRM replacement, automated email sending, autonomous CRM updates, direct Outlook/Graph integration, ML models, forecasting, quota, team or multi-user features, mobile, vector database, proposal generation, autonomous prospecting.
