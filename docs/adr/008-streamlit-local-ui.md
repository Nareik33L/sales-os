# ADR-008 — Streamlit bound to localhost; no auth layer, no app-level encryption in V1

**Context.** Single user on a corporate laptop with OS-level login and disk encryption policy. The spec chooses Streamlit and forbids public exposure.

**Decision.** Streamlit with `server.address = localhost`, `headless = true`, usage stats off. No login screen, no app-level encryption. Data at rest relies on corporate disk encryption.

**Consequences.**
- Zero friction in the morning; the OS session is the authentication boundary.
- Must never be run with `--server.address 0.0.0.0`; README says so and `.streamlit/config.toml` pins it.
- If the laptop policy changes or data is moved to unencrypted media, SQLCipher or an encrypted volume is the upgrade path; the schema is unaffected.
