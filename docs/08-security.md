# 08 — Security and Privacy

A personal tool on a company laptop holding customer names, deal values, email bodies and transcripts. The posture is: everything stays on disk, nothing listens on the network, every outbound byte to an AI provider is logged, and no external system is modified without an approved audit row.

## 1. Local storage

| item | location | notes |
|---|---|---|
| database | `data/salesos.db` (+ `-wal`, `-shm`) | SQLite, WAL mode |
| inbox | `data/inbox/{emails,transcripts,excel,prospecting,todo}/` | user drops files here |
| processed | `data/processed/<kind>/<yyyy-mm>/` | moved after processing; attachments under `emails/<hash>/` |
| exports | `data/exports/` | CSV exports the user asks for |
| logs | `data/logs/salesos.log` | rotating; no evidence bodies in logs |

`data/` is entirely gitignored (`.gitkeep` files excepted). Backups are the user's responsibility; the Settings page shows the DB path and size and offers "Export database copy" to `data/exports/`.

Disk encryption is assumed from corporate device policy; the tool does not add its own encryption layer in V1 (ADR-008 notes the option of SQLCipher later).

## 2. Credentials

- Only in `.env` (loaded by `python-dotenv`) or the OS environment. `.env.example` documents every key with its scope.
- Service-account JSON and token caches are gitignored by pattern (`service_account*.json`, `token*.json`).
- Never logged, never stored in `settings`, never shown on the UI beyond "configured: yes/no".
- Recommended: a pre-commit hook running `git diff --cached --name-only | grep -E '^\.env$|^data/'` to block accidents; documented in README.

## 3. Network surface

- Streamlit bound to `localhost` (`server.address = "localhost"`, `server.headless = true`), usage stats off (`browser.gatherUsageStats = false`) via `.streamlit/config.toml` (committed; contains no secrets).
- Outbound only: HubSpot, Google, Calendly, optional Microsoft Graph, optional AI provider. All honour `HTTPS_PROXY`/`NO_PROXY` so corporate proxies work without special code.
- No telemetry, no update checks, no crash reporting.

## 4. AI data transmission

Covered in doc 07 §5. Summary of guarantees:

- Default is `none`; nothing leaves the machine until the user configures a provider.
- `ai_calls` records each call; the Settings banner shows provider, model, endpoint host and today's volume.
- Deal values, phone numbers and attachments are never included in prompts. Email addresses optionally redacted.
- Local-provider mode exists for tenants that forbid external AI.

## 5. Approval gate and audit

The only path to an external write:

```
proposal (system or user)  → audit_log(event=PROPOSE_EXTERNAL_WRITE, approval_status=PENDING, proposed_change_json)
user clicks Approve        → audit_log(approval_status=APPROVED, approved_at)
core.audit.execute_approved(audit_id)
    → asserts APPROVED, loads connector, calls connector.write(capability, payload)
    → audit_log(approval_status=EXECUTED|FAILED, executed_at, result_json)
```

Connector `write()` methods are not exported anywhere else and check for a valid audit id argument. `sources.yaml` `writes.*` flags default to `false`, so even the proposal step is off until enabled. Pending proposals are listed on Inbox with Approve/Reject and the evidence that motivated them.

Also audited: `CONFIG_CHANGE` (weights, mappings edited through the UI), `USER_EDIT` (manual deal/memory edits), `SYNC` summaries.

## 6. File handling

- Only whitelisted extensions are parsed; others recorded as `UNSUPPORTED` and moved aside.
- `.msg`/`.eml` parsing is offline via libraries; no macros, no rendering, no link fetching. HTML bodies are converted to text; images/remote content are dropped.
- Attachments are saved with their hash-prefixed names and never executed or opened by the tool.
- Path handling uses `pathlib` and refuses paths that escape `data/`.
- Files are moved within the same filesystem (`os.replace`) to avoid partial copies.

## 7. Git safety

- `.gitignore` covers `.env*` (except example), `data/`, service-account/token files, `config/*.local.yaml` (for machine-specific overrides).
- README instructs: never commit `data/` or `.env`; use `config/*.local.yaml` for anything containing customer names.
- No customer data in tests: fixtures use fictional companies.

## 8. Corporate-device assumptions

| assumption | consequence |
|---|---|
| No admin rights | `pip install --user` / venv; no services, no drivers |
| Endpoint protection may flag unusual binaries | pure-Python dependencies only |
| Proxies / SSL inspection | `requests` honours env proxies and `REQUESTS_CA_BUNDLE` |
| DLP may watch file exports | the tool reads what the user already saved; it does not pull mail or SharePoint content programmatically |
| Microsoft Graph blocked | Tier 2 disabled by default; never a dependency |
| Device could be wiped/replaced | `data/` is the only state; documented backup/restore |

The tool never attempts to work around IT controls. Every Microsoft touchpoint is a file the user chose to save.

## 9. Threats explicitly out of scope

Multi-user access control, network exposure, encryption at rest beyond OS policy, malicious files crafted to exploit parsers (mitigated by whitelisting and library choice, not eliminated).
