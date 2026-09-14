# ADR-007 — Prospecting is a hard tier below deal work

**Context.** The spec: "Prospecting should always rank below active deal management." Encoding this as a low weight fails eventually — an overdue prospecting row with a high sheet priority will surpass a mid-score deal action.

**Decision.** `actions.tier` (1 deal work, 2 follow-ups/admin, 3 prospecting) is the primary sort key; score orders within a tier. Tier is assigned from action type via config.

**Consequences.**
- The guarantee holds by construction and is trivially testable.
- Within tier 3 the sheet's own Priority/Due date ordering survives.
- If the user ever wants a prospecting item above deal work, pinning does it explicitly and is recorded as feedback.
