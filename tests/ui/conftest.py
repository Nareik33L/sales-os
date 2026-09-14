"""Shared Today-page fixtures. Fictional companies only."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.models import (
    SyncRun,
    SyncStatus,
    SyncTrigger,
    get_action,
    upsert_action,
    upsert_sync_run,
)
from core.prioritisation import recompute_all
from database.db import connect, migrate
from tests.prioritisation.helpers import NOW, TZ
from tests.seed import seed_fictional


def seed_today_db(path: Path) -> Path:
    """File-backed DB for AppTest (in-memory would not be shared with the app)."""
    conn = connect(path)
    try:
        migrate(conn)
        seed_fictional(conn)
        recompute_all(conn, now=NOW, tz=TZ)
        # Pin the Acme meeting-prep card to #1 so ordering tests can see
        # user_pinned_rank / user_priority_override beat a higher score.
        prep = get_action(conn, "ac_acme_prep")
        if prep is not None:
            upsert_action(
                conn,
                prep.model_copy(update={"user_priority_override": 1}),
            )
        upsert_sync_run(
            conn,
            SyncRun(
                source="hubspot",
                trigger=SyncTrigger.MANUAL,
                started_at="2026-09-14T07:50:00Z",
                finished_at="2026-09-14T07:51:00Z",
                status=SyncStatus.FAILED,
                message="Failed: simulated HubSpot outage",
                error_count=1,
            ),
        )
        upsert_sync_run(
            conn,
            SyncRun(
                source="excel",
                trigger=SyncTrigger.MANUAL,
                started_at="2026-09-14T07:52:00Z",
                finished_at="2026-09-14T07:52:30Z",
                status=SyncStatus.SUCCESS,
                message="Last sync 07:52",
                records_fetched=4,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def today_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frozen_now) -> Path:
    db_path = tmp_path / "today.db"
    monkeypatch.setenv("SALESOS_DB_PATH", str(db_path))
    monkeypatch.setenv("SALESOS_TIMEZONE", "Europe/London")
    seed_today_db(db_path)
    return db_path
