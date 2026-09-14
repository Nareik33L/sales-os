# ADR-009 — AI extractions accepted only with a verified verbatim quote

**Context.** The most damaging failure of an AI-assisted sales brain is a confident false memory ("customer agreed to £60k") that then drives prioritisation and summaries. Prompt instructions alone do not prevent this.

**Decision.** Every `memory_candidate` / `action_candidate` must include `quote`. Code verifies the quote exists in the source (exact, or fuzzy ≥ 0.92 for transcripts). Unverified items are dropped and counted. Items accepted without a quote are only allowed as `basis = INFERRED` with confidence capped at 0.5 and are rendered with an "inferred" tag. Deal summaries must cite memory/evidence ids per sentence; uncited sentences are removed.

**Consequences.**
- The system can under-extract (miss things) but cannot invent an observed fact.
- Quotes give the UI its "why do you think this?" panel for free.
- Slightly larger prompts/outputs; negligible at this volume.
