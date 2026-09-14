"""Short-lived DB sessions and Today bootstrap (refresh / recompute).

Connections are opened per run and closed before Streamlit reruns. They are
never stored in ``st.session_state`` (UI engineer charter).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import streamlit as st

from config.loaders import load_sources
from core.ingestion import refresh as run_refresh
from core.models import get_setting_value, list_deals, list_sync_runs
from core.prioritisation import recompute_all
from core.prioritisation.engine import local_date_of, parse_timestamp, utc_now, user_timezone
from database.db import connect

log = logging.getLogger("salesos.app")

STALE_MINUTES = 15
DEFAULT_GREETING_NAME = "Sam"


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection, commit on success, always close."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            log.debug("rollback failed", exc_info=True)
        raise
    finally:
        conn.close()


def configure_page(*, title: str = "Sales OS") -> None:
    try:
        st.set_page_config(page_title=title, layout="wide")
    except st.errors.StreamlitAPIException:
        # Already set by app/main.py when a page is imported as a helper.
        pass


def greeting_name(conn: sqlite3.Connection) -> str:
    value = get_setting_value(conn, "today_greeting_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_GREETING_NAME


def should_startup_refresh(conn: sqlite3.Connection, now: datetime | None = None) -> bool:
    """True when no connector has run today and local time is past the morning hour."""
    sources = load_sources()
    moment = utc_now(now)
    local = moment.astimezone(user_timezone())
    if local.hour < sources.refresh.morning_refresh_hour_local:
        return False
    today = local.date()
    for run in list_sync_runs(conn):
        stamp = run.finished_at or run.started_at
        if stamp and local_date_of(stamp) == today:
            return False
    return True


def scores_are_stale(conn: sqlite3.Connection, now: datetime | None = None) -> bool:
    latest: datetime | None = None
    for deal in list_deals(conn):
        parsed = parse_timestamp(deal.priority_computed_at)
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    if latest is None:
        return True
    return utc_now(now) - latest > timedelta(minutes=STALE_MINUTES)


def prepare_today(conn: sqlite3.Connection, *, now: datetime | None = None) -> None:
    """First-load refresh (if none today) then a cheap recompute if scores are stale."""
    if should_startup_refresh(conn, now):
        with st.spinner("Refreshing sources…"):
            try:
                run_refresh("STARTUP", conn=conn)
            except Exception:
                log.exception("startup refresh failed")
                st.warning("Refresh did not finish. Today is using the last saved data.")
        return
    if scores_are_stale(conn, now):
        recompute_all(conn, now=now)


def trigger_manual_refresh(conn: sqlite3.Connection) -> None:
    """↻ Refresh — isolated per connector; failures become sync_runs rows."""
    run_refresh("MANUAL", conn=conn)


def utc_stamp(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
