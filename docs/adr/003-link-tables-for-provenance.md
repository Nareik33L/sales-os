# ADR-003 — Provenance via link tables with verbatim quotes

**Context.** The spec suggests `source_evidence_ids` / `evidence_ids` columns. In SQLite these become JSON arrays that cannot be indexed or joined, making "why do you think this?" and "what does this evidence support?" expensive and fragile.

**Decision.** `memory_evidence`, `action_evidence`, `audit_log_evidence` link tables. `memory_evidence` carries `quote` (verbatim span, code-verified) and `relation` (`SUPPORTS`, `FULFILS`, `CONTRADICTS`, `SUPERSEDES`).

**Consequences.**
- Provenance is queryable in both directions with indexes.
- Quotes make the evidence panel show the exact passage, and double as the hallucination check (ADR-009).
- One more join on the deal-detail page; negligible at this scale.
