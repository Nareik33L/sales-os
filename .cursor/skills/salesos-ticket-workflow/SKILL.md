---
name: salesos-ticket-workflow
description: How a Sales OS engineer picks up, implements, verifies and submits a backlog ticket end-to-end without asking the user. Use whenever starting or finishing a SOS-nn ticket.
icon: code
color: blue
---

# Ticket workflow

## 1. Pick up
- Read `docs/backlog.md`; take the lowest-numbered `todo` ticket in your area whose dependencies are `done`. Set it to `in-progress` with your agent name.
- Read the governing docs listed on the ticket and the acceptance criteria. If the criteria are vague, sharpen them in the ticket *before* coding.

## 2. Branch
```bash
git fetch origin main && git checkout -b grok/SOS-nn-short-slug origin/main
```

## 3. Implement
- Test first from the doc's worked example or acceptance criterion.
- Stay inside your area's directories. Needing something from another area → add a minimal interface stub + TODO with the owning agent's name, or ask the lead to dispatch it.
- Decisions the docs do not make: choose the simplest option, list it under "Decisions" in the PR body.

## 4. Verify locally
```bash
pip install -r requirements.txt
ruff check . && pytest -q
python run.py --migrate            # migrations still apply on an empty DB
```
Fault check for anything touching connectors/parsers: make it fail on purpose; confirm a `sync_runs`/`processed_files` row, not a traceback.

## 5. Commit and PR
- Conventional commits, one logical change per commit, `#SOS-nn` in the message.
- `git push -u origin grok/SOS-nn-short-slug`; open a PR to `main` with body:
```
## SOS-nn — <title>
What: …
Why (doc refs): docs/03-prioritisation.md §2.3 …
Verified: pytest (n new tests), ruff, migrate, fault check …
Decisions: …
User must: <nothing | add env var X | run manual test step Y>
```
- Set ticket to `review`; mention `salesos-lead` and `salesos-qa-release-engineer`.

## 6. After review
- Address every comment with a commit, never a force-push. When merged, set the ticket to `done` and delete the branch.
