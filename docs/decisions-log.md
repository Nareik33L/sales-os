# Decisions log

Routine decisions the docs did not make, recorded by the lead so they never need re-asking. Format: date · ticket · decision · why.

| Date | Ticket | Decision | Why |
|---|---|---|---|
| 2026-09-14 | SOS-06b | Typed YAML loaders live in `config/loaders.py` next to the files they validate; rotating logging is `core/logging_setup.py`; demo rows are `database/seed.py`. | Simplest split that stays in QA/shared infra and leaves `core/models/` for SOS-02. SOS-06c should reuse `seed_demo()` for `seeded_db`. |
| 2026-09-14 | SOS-06b | `python run.py --demo` migrates, validates config, seeds fictional data, and does **not** start Streamlit. | App UI is not built yet; seed stays testable and scriptable. Launch with `python run.py` against the same DB after seeding. |
| 2026-09-14 | SOS-11 | First versioned cut is **0.2.0**. No `db_v0.1.0` fixture — Phase 1 never shipped a populated-DB baseline. Phase 2 fixture is `tests/release/db_v0.2.0.sqlite` (demo seed). | Ticket: create VERSION/CHANGELOG; first release fixture. |
| 2026-09-14 | SOS-11 | Annotated tag `v0.2.0` is **not** pushed on this PR. Lead cuts the tag on `main` after merge. | Avoids tagging a branch tip that is not yet `main`. |
