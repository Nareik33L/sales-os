# ADR-002 — Prioritisation is deterministic; AI never ranks

**Context.** The spec requires explainable ranking, configurable weights, and a system that works without AI. LLM ranking is non-reproducible, cannot be tuned by editing a number, and cannot produce a faithful "why".

**Decision.** `core/prioritisation` is pure functions over structured rows using `config/priority_weights.yaml`. A deal score and a derived action score, each with a stored per-component breakdown. "Why" bullets are templated from the breakdown. The AI provider has no entry point into this module.

**Consequences.**
- Same inputs always give the same order; fixture tests are possible.
- Tuning is a YAML edit with an audit row; the system can only *suggest* changes.
- Signals not representable as structured data (e.g. tone of an email) do not affect ranking unless first turned into a memory (e.g. `RISK`), which then does.
