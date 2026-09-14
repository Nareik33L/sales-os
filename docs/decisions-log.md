# Decisions log

Routine decisions the docs did not make, recorded by the lead so they never need re-asking. Format: date · ticket · decision · why.

| Date | Ticket | Decision | Why |
|---|---|---|---|
| 2026-09-14 | SOS-06b | Typed YAML loaders live in `config/loaders.py` next to the files they validate; rotating logging is `core/logging_setup.py`; demo rows are `database/seed.py`. | Simplest split that stays in QA/shared infra and leaves `core/models/` for SOS-02. SOS-06c should reuse `seed_demo()` for `seeded_db`. |
| 2026-09-14 | SOS-06b | `python run.py --demo` migrates, validates config, seeds fictional data, and does **not** start Streamlit. | App UI is not built yet; seed stays testable and scriptable. Launch with `python run.py` against the same DB after seeding. |
