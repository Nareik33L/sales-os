---
name: salesos-test-and-verify
description: Sales OS testing conventions — fixtures, fictional data, fault injection, prioritisation fixture format, Streamlit AppTest, and the commands to run before any PR. Use when writing or reviewing tests.
icon: beaker
color: purple
---

# Test and verify

## Commands (all must pass before a PR)
```bash
ruff check .
pytest -q
python run.py --migrate
python -c "import yaml,json,glob; [yaml.safe_load(open(f)) for f in glob.glob('config/*.yaml')]; [json.load(open(f)) for f in glob.glob('ai/prompts/schemas/*.json')]"
```

## Fixtures (`tests/conftest.py`)
- `db` — in-memory SQLite with all migrations applied.
- `seeded_db` — fictional dataset only: companies Acme, Beta Corp, Gamma, Delta; contacts with `@acme-example.test` style domains; deals across both products; a few memories, meetings, actions.
- `frozen_now` — `2026-09-14T08:00:00Z`, timezone Europe/London.
- `fake_provider` — returns canned JSON per purpose; variants: valid, schema-invalid, hallucinated quote, uncited summary sentence.
- Never use real customer, colleague or company names. Never copy real emails/transcripts into `tests/`.

## Prioritisation fixtures (`tests/prioritisation/cases/*.json`)
```json
{ "name": "acme_worked_example",
  "deal": {...}, "memories": [...], "meetings": [...], "config": "default",
  "expect": { "score_between": [80, 85], "attention": "HIGH",
              "bullets_include": ["£75k deal", "Closing in 4 days"], "tier_order_holds": true } }
```
Required cases: log scaling, close date passed, stale-but-far cap, commitment max-not-sum, prospecting never above tier 1, boost bound, pinned rank, unknown value/close date bullets.

## Fault injection (connectors, parsers, pages)
- Unset each `required_env` → refresh completes, status `NOT_CONFIGURED`, page renders.
- Raise inside `fetch()` → `FAILED`, other connectors still run.
- Corrupt `.msg`, `.vtt`, `.xlsx` in inbox → `processed_files.status = FAILED`, file quarantined, no traceback.
- Provider raises / returns garbage → rules fallback, `ai_calls.status` recorded.

## Streamlit pages
Use `streamlit.testing.v1.AppTest` against `seeded_db`: page renders, Today ordering `tier, pinned, score`, clicking Complete writes `user_feedback` and `actions.status`, empty states show text not errors.

## Review checklist for tests
- Would the test fail if the feature were deleted?
- Does it assert on behaviour (rows, order, status), not on log text or pixels?
- Is it under a second? (Whole suite < 60 s.)
