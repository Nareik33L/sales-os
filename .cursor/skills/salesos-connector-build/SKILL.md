---
name: salesos-connector-build
description: Step-by-step recipe for building or changing a Sales OS connector so it follows the common interface, records sync health, never crashes the app, and is testable offline. Use when working in connectors/ or core/ingestion.
icon: terminal
color: green
paths: connectors/**, core/ingestion/**
---

# Building a connector

Reference: `docs/05-connectors.md`. Config: `config/sources.yaml` (and `config/excel_mapping.yaml` for Excel).

## Layout
```
connectors/<name>/
  __init__.py
  connector.py     # class <Name>Connector(BaseConnector)
  client.py        # thin HTTP/file access; no business logic
  normalise.py     # raw -> NormalisedBatch (Deal/Company/Contact/Meeting/Evidence/Action rows)
  fixtures/        # fictional recorded responses / sample files for tests
tests/connectors/test_<name>.py
```

## Steps
1. **Declare** the connector in `config/sources.yaml` (tier, mode, `required_env`, fallback). `is_configured()` reads that list; missing → `NOT_CONFIGURED`, message "Not connected — set HUBSPOT_ACCESS_TOKEN".
2. **Client**: pagination, rate-limit backoff (respect `Retry-After`), timeouts from `refresh.connector_timeout_seconds`. Return raw dicts; never raise on "no data".
3. **Fetch** takes the previous `cursor_json` (e.g. `hs_lastmodifieddate` watermark) and returns `(records, next_cursor)`. First run uses `lookback_days_on_first_sync`.
4. **Normalise** into internal rows: set `source`, `external_id`, `product` (from `sources.yaml`), `deal_value_gbp` via `currency.rates_to_gbp`, timestamps UTC ISO, dates local ISO. Every normalised record also yields an `evidence` row of the appropriate structured type where doc 05 says so.
5. **Save** via `core.models` repositories only: `upsert_*` returns `created|changed|unchanged` plus field diffs → `deal_changes`. Update `last_seen_at`. Never delete.
6. **Health**: `BaseConnector.run()` does the bookkeeping; your job is to raise typed errors (`ConnectorNotConfigured`, `ConnectorAuthError`, `ConnectorTransientError`) so status is accurate.
7. **Writes** (only if doc 05 lists one): method `write(capability, payload, *, audit_id)`; assert `core.audit.is_approved(audit_id)`; flag in `sources.yaml` stays `false`.
8. **Tests** (offline): configured/not-configured, first sync, incremental sync with a changed record → one `deal_changes` row, malformed record → `PARTIAL` with `errors_json`, auth failure → `FAILED` and no exception.
9. **File connectors** additionally: hash dedupe, partial-file skip, move to `data/processed/<kind>/<yyyy-mm>/`, corrupt file → `processed_files.status = FAILED`.

## Don'ts
- No SQL in connectors. No secrets or bodies in INFO logs. No deletes. No calling AI. No enabling write flags.
