"""SQLite connection and migration runner.

Usage:
    from database.db import connect, migrate
    conn = connect()          # uses SALESOS_DB_PATH, default data/salesos.db
    migrate(conn)             # applies database/migrations/*.sql in order, idempotently

Migrations are plain SQL files named NNN_description.sql. Each is applied once
inside a transaction and recorded in schema_migrations. No ORM: the schema is
the architecture artifact and stays readable as SQL.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")


def default_db_path() -> Path:
    return Path(os.environ.get("SALESOS_DB_PATH", "data/salesos.db"))


def connect(path: str | os.PathLike | None = None) -> sqlite3.Connection:
    """Open a connection with the pragmas the application relies on."""
    db_path = Path(path) if path is not None else default_db_path()
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), detect_types=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_migrations(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, str, Path]]:
    found = []
    for file in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.match(file.name)
        if not match:
            raise ValueError(f"Migration file name not in NNN_name.sql form: {file.name}")
        found.append((int(match.group(1)), match.group(2), file))
    versions = [v for v, _, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError("Duplicate migration version numbers")
    return found


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not exists:
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def migrate(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[int]:
    """Apply pending migrations. Returns the versions applied in this call."""
    done = applied_versions(conn)
    applied: list[int] = []
    for version, name, file in list_migrations(directory):
        if version in done:
            continue
        sql = file.read_text(encoding="utf-8")
        try:
            conn.execute("BEGIN")
            conn.executescript(sql)  # executescript commits first; we re-open a transaction for bookkeeping
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, _utcnow()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        applied.append(version)
    return applied


def table_names(conn: sqlite3.Connection) -> Iterable[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r[0] for r in rows]
