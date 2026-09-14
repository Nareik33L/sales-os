---
name: salesos-release
description: Cut a Sales OS phase release — for this project "deploy" means it installs and runs cleanly on the user's laptop from git pull. Covers clean-venv install, migration safety on a populated DB, demo mode, versioning, changelog, tag and release note. Use at the end of every phase.
icon: rocket
color: orange
---

# Release a phase

There is no server. A release is a tagged `main` that a person can run with `git pull && python run.py`.

## Checklist
1. **Green main**: `ruff check . && pytest -q` on `main`.
2. **Clean install** (Python 3.11 and 3.12):
   ```bash
   python -m venv /tmp/sos-venv && source /tmp/sos-venv/bin/activate
   pip install -r requirements.txt && python run.py --migrate && pytest -q
   ```
3. **Migration safety**: copy the previous release's `data/salesos.db` fixture (kept in `tests/release/db_v0.N-1.sqlite`, fictional data) → `python run.py --migrate` → row counts unchanged, new tables present. Save the migrated file as the next fixture.
4. **Demo mode**: `python run.py --demo` seeds fictional data into a temp DB and opens the UI; click through Today, Deals, a deal, Inbox, Settings. Fix anything that errors; screenshots into the release PR.
5. **No-credentials run**: with an empty `.env`, `python run.py` starts and every connector shows ⚠ Not connected. Nothing crashes.
6. **Version**: bump `VERSION` (`0.<phase>.<patch>`), update `CHANGELOG.md`:
   ```
   ## 0.N.0 — <date>
   ### Added / Changed / Fixed
   ### Requires from you
   - add HUBSPOT_ACCESS_TOKEN (see .env.example) …
   ```
7. **Tag**: `git tag -a v0.N.0 -m "Phase N: <name>" && git push origin v0.N.0`.
8. **Manual test**: write `docs/manual-tests/phase-N.md` (skill `salesos-manual-test-request`).
9. **Release note** to the lead (≤ 15 lines): what changed, how to run, env vars needed, link to the manual test, known gaps.

## Rules
- No release with a red test, a skipped migration check, or a page that errors in demo mode.
- Never include real data in release fixtures or screenshots.
- Do not change write flags in `config/sources.yaml` as part of a release.
