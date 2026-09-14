# ADR-006 — SQLite FTS5 for search; no vector database in V1

**Context.** Brain questions like "what did we agree on the last call?" need search over evidence. The spec lists a vector database as out of scope unless necessary.

**Decision.** FTS5 external-content table over `evidence(title, content, summary)` kept in sync by triggers. Deal-scoped keyword search on Inbox and deal detail. Structured questions (what do I owe, what changed) are answered by SQL over memories, not search.

**Consequences.**
- No embeddings pipeline, no extra service, no data sent anywhere for indexing.
- Synonym/semantic recall is weaker than vectors; acceptable because the user knows the vocabulary of their own deals and memories already capture the important semantics.
- If needed later, an embeddings table keyed by `evidence.id` can be added without touching the model.
