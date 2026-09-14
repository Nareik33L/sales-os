# sales-os

Personal Sales Operating System — a local-first working layer over HubSpot, Excel, Google Sheets, Calendly, Zoom transcripts and saved Outlook emails. One user, one laptop, one screen in the morning.

> Read broadly. Remember intelligently. Prioritise clearly. Write cautiously.

## Status

**Phase 2 — 0.2.0.** HubSpot → deterministic prioritisation → Today. `python run.py` opens http://localhost:8501. Version in `VERSION`; history in [CHANGELOG.md](CHANGELOG.md). Next: Excel / Sheets / Calendly and the Deals pages ([docs/10-build-plan.md](docs/10-build-plan.md)).

## What it does (V1)

- Reads deals, tasks and activity from HubSpot; deals from a local Excel workbook; prospecting rows from a Google Sheet; meetings from Calendly; emails and Zoom transcripts from local drop folders.
- Keeps **evidence** for everything, builds **memory** (commitments, deal state, signals, risks) with quotes and confidence, and turns it into one **tiered, deterministically prioritised action list** with a "why" for every item.
- Never writes to an external system without an explicit approval recorded in an audit log.
- Works fully without AI; an optional provider adds extraction and cited summaries, with every call logged.
- Treats every Microsoft-managed source as optional: if Excel, Outlook or To-Do cannot connect, the rest keeps working.

## Documentation

Start at [docs/00-overview.md](docs/00-overview.md). The Section 45 review with all decisions is [docs/01-architecture-review.md](docs/01-architecture-review.md). Decision records are in [docs/adr/](docs/adr/).

## Quick start (Phase 2)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # HUBSPOT_ACCESS_TOKEN for live HubSpot; rest can stay blank
python run.py --migrate                                # creates data/salesos.db
python run.py --demo                                   # fictional seed (Acme / Beta Corp); does not start the UI
python run.py                                          # Today at http://localhost:8501
```

Needs Python 3.11 or 3.12. Logs rotate under `data/logs/salesos.log`. Manual check after a pull: [docs/manual-tests/phase-2.md](docs/manual-tests/phase-2.md).

## Layout

```
app/          Streamlit UI (Today, Deals, Deal detail, Inbox, Settings)
core/         models, prioritisation, matching, memory, summarisation, audit, ingestion, brain
connectors/   hubspot, google_sheets, calendly, excel, email_files, transcripts, todo
ai/           provider abstraction, prompts + JSON schemas, providers (null, openai, local)
database/     db.py + SQL migrations (the schema is the architecture artifact)
config/       sources, priority weights, excel mapping, matching, ai — all editable YAML
data/         inbox/ (drop files here), processed/, exports/ — gitignored, stays on this machine
docs/         architecture package and ADRs
tests/        including tests/release/db_v0.2.0.sqlite (fictional)
VERSION, CHANGELOG.md, run.py, requirements.txt
```

## Safety rules

- `.env` and `data/` are gitignored and must never be committed.
- Streamlit is pinned to `localhost` in `.streamlit/config.toml`. Do not run with `--server.address 0.0.0.0`.
- `AI_PROVIDER=none` by default; nothing leaves the machine until you configure a provider, and then every call is logged in `ai_calls`.
- All write capabilities (`complete_task`, `mark_done`) are off in `config/sources.yaml` and, when on, require a per-action approval.
