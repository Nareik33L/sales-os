---
name: salesos-manual-test-request
description: How to write the short manual test checklist the user runs at each Sales OS phase gate — the only routine thing the human does. Use when a phase completes or when a feature can only be verified against real HubSpot, Excel, Sheets, Calendly, emails or transcripts.
icon: bug
color: yellow
---

# Manual test request

The user's time is the scarcest resource in this project. A manual test asks only for what a machine cannot verify: real data appearing, real files matching the right deal, the screen feeling right.

## File
`docs/manual-tests/phase-N.md`, one per phase. Keep the previous ones; they double as regression scripts.

## Template
```markdown
# Phase N manual test — <name>            est. <10–15> min

## Before you start
- git pull && python run.py           (opens http://localhost:8501)
- Env vars needed for this phase: HUBSPOT_ACCESS_TOKEN (see .env.example)   ← only if new

## Steps
| # | Do | Expect | ✓/✗ + note |
|---|----|--------|------------|
| 1 | Click ↻ Refresh on Today | HubSpot ✓ with "n checked", Excel ⚠ "Not connected", page still renders | |
| 2 | Look at #1 on Today | It is a deal you would also put first; Why bullets are true | |
| 3 | Drop one real .msg into data/inbox/emails, click Process inbox | File moves to data/processed; Inbox shows it matched to the right deal (or asks you) | |
| … | | | |

## Tell us
- Anything that was wrong or surprising (one line each).
- Any bullet in "Why" that was untrue.
- Anything the tool asked you that it should have known.

## Only you can decide
- <e.g. Is the second product's name "Product B" in config/sources.yaml correct?>
```

## Rules
- 5–12 steps. Each step: one action, one observable result.
- Never ask the user to inspect the database, read logs or run pytest — that is the team's job.
- Never ask for approval of routine engineering decisions; list them under "Decisions" in the release note instead.
- Include the "Only you can decide" section only when there is a genuine item; otherwise omit it.
- After the user responds, the lead turns every ✗ into a `fix:` ticket at the top of the backlog.
