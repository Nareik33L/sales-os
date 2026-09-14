"""Thin `sync_runs` persistence helper.

Temporary until `salesos-core-engineer` ships `SyncRunRepository` in SOS-02.
Uses the existing `database.db` connection (sqlite3, row factory, FK on).
Connectors must not embed this SQL themselves — they call `open_run` / `finish_run`.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from connectors.base import SyncRunResult, cap_errors

# TODO(salesos-core-engineer): SOS-02 — replace this module with SyncRunRepository
# (open/finish/latest_cursor) and a shared ULID id helper. Callers in
# connectors.base and core.ingestion.refresh should then depend on core.models.


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    """Unique TEXT primary key. UUID4 until the shared ULID helper lands."""
    return str(uuid.uuid4())


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str, separators=(",", ":"))


def _load_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def open_run(conn: sqlite3.Connection, *, source: str, trigger: str) -> str:
    """Insert a RUNNING `sync_runs` row and return its id."""
    run_id = new_id()
    started_at = _utcnow()
    conn.execute(
        """
        INSERT INTO sync_runs (
            id, source, trigger, started_at, finished_at, status,
            records_fetched, records_created, records_changed, records_unchanged,
            error_count, errors_json, message, cursor_json
        ) VALUES (?, ?, ?, ?, NULL, 'RUNNING', 0, 0, 0, 0, 0, NULL, NULL, NULL)
        """,
        (run_id, source, trigger, started_at),
    )
    conn.commit()
    return run_id


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    records_fetched: int = 0,
    records_created: int = 0,
    records_changed: int = 0,
    records_unchanged: int = 0,
    errors: list[dict[str, Any]] | None = None,
    message: str | None = None,
    cursor: dict[str, Any] | None = None,
) -> SyncRunResult:
    """Set terminal status, counts, errors, message, cursor, and `finished_at`."""
    errors = cap_errors(list(errors or []))
    finished_at = _utcnow()
    conn.execute(
        """
        UPDATE sync_runs SET
            finished_at = ?,
            status = ?,
            records_fetched = ?,
            records_created = ?,
            records_changed = ?,
            records_unchanged = ?,
            error_count = ?,
            errors_json = ?,
            message = ?,
            cursor_json = ?
        WHERE id = ?
        """,
        (
            finished_at,
            status,
            records_fetched,
            records_created,
            records_changed,
            records_unchanged,
            len(errors),
            _dump_json(errors) if errors else None,
            message,
            _dump_json(cursor),
            run_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sync_runs WHERE id = ?", (run_id,)).fetchone()
    return _row_to_result(row)


def latest_cursor(conn: sqlite3.Connection, source: str) -> dict[str, Any] | None:
    """Most recent incremental cursor from a successful or partial run of `source`."""
    row = conn.execute(
        """
        SELECT cursor_json FROM sync_runs
        WHERE source = ?
          AND status IN ('SUCCESS', 'PARTIAL')
          AND cursor_json IS NOT NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (source,),
    ).fetchone()
    if row is None:
        return None
    loaded = _load_json(row["cursor_json"])
    return loaded if isinstance(loaded, dict) else None


def get_run(conn: sqlite3.Connection, run_id: str) -> SyncRunResult | None:
    row = conn.execute("SELECT * FROM sync_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return _row_to_result(row)


def _row_to_result(row: sqlite3.Row) -> SyncRunResult:
    errors = _load_json(row["errors_json"]) or []
    if not isinstance(errors, list):
        errors = []
    cursor = _load_json(row["cursor_json"])
    if cursor is not None and not isinstance(cursor, dict):
        cursor = None
    return SyncRunResult(
        id=row["id"],
        source=row["source"],
        trigger=row["trigger"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status=row["status"],
        records_fetched=row["records_fetched"] or 0,
        records_created=row["records_created"] or 0,
        records_changed=row["records_changed"] or 0,
        records_unchanged=row["records_unchanged"] or 0,
        error_count=row["error_count"] or 0,
        errors=errors,
        message=row["message"],
        cursor=cursor,
    )
