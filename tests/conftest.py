"""Shared pytest fixtures for Sales OS.

Names are part of the SOS-06c contract (skill ``salesos-test-and-verify``):

* ``db`` — in-memory SQLite with every migration applied.
* ``seeded_db`` — ``db`` plus the fictional Acme / Beta Corp / Gamma / Delta dataset.
* ``frozen_now`` — wall clock frozen at ``2026-09-14T08:00:00Z`` (09:00 Europe/London).
* ``fake_provider`` — canned JSON per AI purpose; variants for validator tests.

Fictional data only. Never put real customer, colleague or company names here.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from database.db import connect, migrate
from tests.fakes import FakeProvider
from tests.seed import seed_fictional

FROZEN_NOW_UTC = datetime(2026, 9, 14, 8, 0, 0, tzinfo=timezone.utc)
USER_TZ = ZoneInfo("Europe/London")


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    """In-memory SQLite with all migrations applied. Closed when the test ends."""
    conn = connect(":memory:")
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture
def seeded_db(db: sqlite3.Connection) -> sqlite3.Connection:
    """``db`` populated with the canonical fictional companies and related rows."""
    seed_fictional(db)
    return db


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> Iterator[datetime]:
    """Freeze wall-clock time to 2026-09-14T08:00:00Z.

    Request this fixture in any test that depends on "now". freezegun patches
    ``datetime.datetime.now`` / ``utcnow`` and ``time.time`` for the duration of
    the test, including in modules that already did ``from datetime import datetime``.

    Also sets ``SALESOS_TIMEZONE=Europe/London``. Local civil time is BST on this
    date::

        frozen_now.astimezone(USER_TZ)
        # datetime.datetime(2026, 9, 14, 9, 0, tzinfo=zoneinfo.ZoneInfo(key='Europe/London'))

    Tests that only need the timestamp string for SQL inserts can use
    ``frozen_now.strftime("%Y-%m-%dT%H:%M:%SZ")`` → ``2026-09-14T08:00:00Z``.
    """
    monkeypatch.setenv("SALESOS_TIMEZONE", str(USER_TZ))
    with freeze_time(FROZEN_NOW_UTC):
        yield FROZEN_NOW_UTC


@pytest.fixture
def fake_provider() -> FakeProvider:
    """Canned-JSON provider. Default variant is ``valid``.

    Switch variant with ``fake_provider.with_variant("schema-invalid")`` or
    ``fake_provider.payload("extract_memory", "hallucinated-quote")``.
    Variants: ``valid``, ``schema-invalid``, ``hallucinated-quote``,
    ``uncited-summary-sentence``.
    """
    return FakeProvider(variant="valid")
