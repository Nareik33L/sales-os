# Architecture Decision Records

Short records of decisions that would be expensive to reverse or that someone will later ask "why?" about. Format: context, decision, consequences. Superseding an ADR means adding a new one, not editing the old.

| # | decision |
|---|---|
| [001](001-sqlite-single-file.md) | SQLite single-file database, no ORM |
| [002](002-deterministic-prioritisation.md) | Prioritisation is deterministic; AI never ranks |
| [003](003-link-tables-for-provenance.md) | Provenance via link tables with verbatim quotes, not JSON id arrays |
| [004](004-file-inbox-for-microsoft-sources.md) | Microsoft-managed sources are read from local files; Graph is Tier 2 |
| [005](005-approval-gated-writes.md) | Every external write passes through an approved audit row |
| [006](006-fts5-not-vector-db.md) | SQLite FTS5 for search; no vector database in V1 |
| [007](007-tiered-action-ordering.md) | Prospecting is a hard tier below deal work |
| [008](008-streamlit-local-ui.md) | Streamlit bound to localhost; no auth layer, no encryption layer in V1 |
| [009](009-quote-verified-extraction.md) | AI extractions accepted only with a verified verbatim quote |
