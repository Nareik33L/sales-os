# ADR-005 — Every external write passes through an approved audit row

**Context.** The spec's hard rule: AI recommendation → proposed action → user approval → external write. Never silently modify CRM, tasks, sheets or send email.

**Decision.** Connector `write()` methods are callable only from `core.audit.execute_approved(audit_id)`, which asserts an `audit_log` row with `approval_status = APPROVED` and records execution result. Write capabilities are additionally gated by `sources.yaml` flags defaulting to `false`. Proposals, approvals, rejections, executions and config changes are all audit rows.

**Consequences.**
- No code path can write externally without a user click and a durable record.
- Slightly more ceremony for the two V1 writes (complete HubSpot task, mark sheet row done); that is the point.
- The audit log doubles as the change history for "what did I approve last week?".
