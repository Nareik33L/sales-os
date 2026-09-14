"""Helpers for phase-release SQLite fixtures (fictional data only)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from database.db import connect, migrate
from database.seed import seed_demo

RELEASE_DIR = Path(__file__).resolve().parent
FIXTURE_V020 = RELEASE_DIR / "db_v0.2.0.sqlite"

# User tables whose row counts must survive an already-current migrate.
COUNTED_TABLES = (
    "companies",
    "contacts",
    "deals",
    "deal_changes",
    "memories",
    "memory_evidence",
    "meetings",
    "actions",
    "evidence",
    "prospecting_items",
    "schema_migrations",
    "settings",
)

FICTIONAL_COMPANIES = frozenset({"Acme", "Beta Corp", "Gamma", "Delta"})


def row_counts(conn: sqlite3.Connection, tables: tuple[str, ...] = COUNTED_TABLES) -> dict[str, int]:
    return {
        name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]  # noqa: S608
        for name in tables
    }


def copy_fixture(dest: Path, source: Path = FIXTURE_V020) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(source.read_bytes())
    return dest


def checkpoint_and_vacuum(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()


def build_v020_fixture(dest: Path | None = None) -> Path:
    """Seed a Phase 2 baseline DB (demo rows) and write a WAL-free sqlite file."""
    dest = dest or FIXTURE_V020
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src = connect(":memory:")
    try:
        migrate(src)
        seed_demo(src)
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
            out.execute("VACUUM")
            out.commit()
        finally:
            out.close()
    finally:
        src.close()
    checkpoint_and_vacuum(dest)
    return dest
