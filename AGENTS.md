# AGENTS.md — Sales OS

Personal Sales Operating System: local-first Streamlit + SQLite working layer over HubSpot, Excel, Google Sheets, Calendly, Zoom transcripts and saved Outlook emails. One user. The specification is `docs/`; start with `docs/00-overview.md`.

## Team

This repository is built by Grok 4.6 subagents defined in `.cursor/agents/` under the charter in `.cursor/rules/salesos-team.mdc`. Roster, workflow and how to start them: `docs/11-team.md`. Ticket board: `docs/backlog.md`.

## Rules that apply to every agent

- Grok 4.6 only. Do not use or spawn other models.
- Work autonomously. Ask the user only for: a missing secret; enabling an external write; deleting user data; an architecture deviation (propose an ADR); or a phase-gate manual test (`docs/manual-tests/phase-N.md`).
- Invariants (checked by skill `salesos-architecture-guardrails`): deterministic prioritisation, prospecting is tier 3, external writes only via `core.audit.execute_approved()`, AI extractions need verified quotes, Microsoft sources are optional, SQLite only, Streamlit on localhost.
- `.env` and `data/` never enter Git. Fixtures use fictional companies only.
- Conventional commits; branch `grok/SOS-nn-slug`; one PR per ticket; PR body: what, why (doc refs), verified, decisions, user must.

## Commands

```bash
pip install -r requirements.txt
ruff check . && pytest -q
python run.py --migrate      # apply migrations
python run.py --demo         # migrate + seed fictional data (does not start Streamlit)
python run.py                # launch UI on http://localhost:8501
```

## Cursor Cloud specific instructions

- No secrets are needed to build or test; every connector has offline fixtures. If a ticket needs a real credential, name the exact env var and continue with other work.
- Never run Streamlit with `--server.address 0.0.0.0`.
- Do not modify `config/sources.yaml` write flags, `.streamlit/config.toml`, or applied migrations.
