# ADR-004 — Microsoft-managed sources are read from local files; Graph is Tier 2

**Context.** Microsoft Graph, SharePoint and To-Do access on a corporate tenant may be blocked by admin consent, conditional access or device policy. The spec forbids designing around the assumption these work and forbids bypassing IT.

**Decision.** Outlook emails and Zoom transcripts are read from `data/inbox/` folders the user populates. Excel is read from a locally synced file or a dropped copy. Microsoft To-Do is a Tier 2 connector, `mode: disabled` by default, with a CSV fallback; the internal `actions` table is the task list regardless.

**Consequences.**
- No Microsoft failure can break the application; each surfaces as ⚠ with a message.
- A small manual step (saving emails/transcripts to a folder) replaces an integration that might never be approved.
- If Graph is later permitted, connectors slot into the same interface without changing the model.
