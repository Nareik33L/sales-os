# ADR-001 — SQLite single-file database, no ORM

**Context.** One user, ~30 active deals, low thousands of evidence rows, one Streamlit process on a corporate laptop with no admin rights. The spec forbids cloud databases, Docker and distributed components.

**Decision.** SQLite in `data/salesos.db`, WAL mode, foreign keys on. Schema is plain SQL migrations applied by `database/db.py`. Access through thin repository functions; pydantic models for validation in Python, no ORM.

**Consequences.**
- Zero install, one file to back up, trivially inspectable with any SQLite tool.
- Schema is the readable architecture artifact; CHECK constraints make enums fail loudly.
- SQLite `ALTER TABLE` is limited; destructive migrations use create-copy-drop.
- Concurrency limited to one writer; acceptable because refresh is synchronous and user-triggered.
