"""`sync_runs` open/finish/cursor helpers on top of `core.models`.

`upsert_sync_run` / `get_sync_run` / `list_sync_runs` are the repository API
(SOS-02). This module keeps the connector-facing lifecycle: insert RUNNING,
finish with counts, read the latest incremental cursor. Repositories do not
commit; `open_run` / `finish_run` do so a RUNNING row is visible and a
terminal status is durable.
"""

from __future__ import annotations

import json
import sqlite3
from enum import Enum
from typing import Any

from connectors.base import SyncRunResult, cap_errors
from core.models import (
    SyncRun,
    SyncStatus,
    SyncTrigger,
    get_sync_run,
    list_sync_runs,
    upsert_sync_run,
    utcnow,
)

_CURSOR_STATUSES = {SyncStatus.SUCCESS, SyncStatus.PARTIAL, "SUCCESS", "PARTIAL"}


def _enum_val(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


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
    run = upsert_sync_run(
        conn,
        SyncRun(
            source=source,
            trigger=SyncTrigger(trigger),
            started_at=utcnow(),
            status=SyncStatus.RUNNING,
        ),
    )
    conn.commit()
    return run.id


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
    finished_at = utcnow()
    existing = get_sync_run(conn, run_id)
    incoming = SyncRun(
        id=run_id,
        source=existing.source if existing is not None else "",
        trigger=(
            existing.trigger if existing is not None else SyncTrigger.MANUAL
        ),
        started_at=existing.started_at if existing is not None else finished_at,
        finished_at=finished_at,
        status=SyncStatus(status),
        records_fetched=records_fetched,
        records_created=records_created,
        records_changed=records_changed,
        records_unchanged=records_unchanged,
        error_count=len(errors),
        errors_json=_dump_json(errors) if errors else None,
        message=message,
        cursor_json=_dump_json(cursor),
    )
    saved = upsert_sync_run(conn, incoming)
    conn.commit()
    return _model_to_result(saved)


def latest_cursor(conn: sqlite3.Connection, source: str) -> dict[str, Any] | None:
    """Most recent incremental cursor from a successful or partial run of `source`."""
    for run in list_sync_runs(conn, source=source):
        if run.status not in _CURSOR_STATUSES:
            continue
        loaded = _load_json(run.cursor_json)
        if isinstance(loaded, dict):
            return loaded
    return None


def get_run(conn: sqlite3.Connection, run_id: str) -> SyncRunResult | None:
    run = get_sync_run(conn, run_id)
    if run is None:
        return None
    return _model_to_result(run)


def _model_to_result(run: SyncRun) -> SyncRunResult:
    errors = _load_json(run.errors_json) or []
    if not isinstance(errors, list):
        errors = []
    cursor = _load_json(run.cursor_json)
    if cursor is not None and not isinstance(cursor, dict):
        cursor = None
    return SyncRunResult(
        id=run.id,
        source=run.source,
        trigger=_enum_val(run.trigger),
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=_enum_val(run.status),
        records_fetched=run.records_fetched or 0,
        records_created=run.records_created or 0,
        records_changed=run.records_changed or 0,
        records_unchanged=run.records_unchanged or 0,
        error_count=run.error_count or 0,
        errors=errors,
        message=run.message,
        cursor=cursor,
    )
