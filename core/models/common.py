"""Shared helpers for Sales OS repositories: ULIDs, UTC timestamps, SQLite coercion."""

from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel

# Crockford base32 (ULID spec). No I, L, O, U.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

T = TypeVar("T", bound=BaseModel)


def new_ulid() -> str:
    """Generate a 26-character ULID (48-bit timestamp + 80-bit randomness)."""
    timestamp_ms = time.time_ns() // 1_000_000
    if timestamp_ms >= (1 << 48):
        raise ValueError("timestamp out of ULID range")
    raw = timestamp_ms.to_bytes(6, "big") + os.urandom(10)
    n = int.from_bytes(raw, "big")
    chars = ["0"] * 26
    for i in range(25, -1, -1):
        chars[i] = _CROCKFORD[n & 31]
        n >>= 5
    return "".join(chars)


def is_ulid(value: str) -> bool:
    return bool(_ULID_RE.match(value))


def utcnow() -> str:
    """ISO-8601 UTC timestamp without microseconds, matching the schema convention."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ident(name: str) -> str:
    """Reject anything that is not a safe SQL identifier (table/column names)."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return name


def to_sql(value: Any) -> Any:
    """Coerce Python values to SQLite-bindable forms."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, Enum):
        return value.value
    return value


def row_to_model(row: sqlite3.Row, model_cls: type[T]) -> T:
    return model_cls.model_validate(dict(row))


def insert_row(conn: sqlite3.Connection, table: str, data: dict[str, Any]) -> None:
    table = ident(table)
    if not data:
        raise ValueError(f"no columns to insert into {table}")
    cols = [ident(c) for c in data]
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    conn.execute(sql, tuple(to_sql(data[c]) for c in cols))


def update_row(
    conn: sqlite3.Connection,
    table: str,
    data: dict[str, Any],
    *,
    where: dict[str, Any],
) -> None:
    table = ident(table)
    if not data:
        return
    if not where:
        raise ValueError("refusing unconstrained UPDATE")
    assignments = ", ".join(f"{ident(c)} = ?" for c in data)
    clause = " AND ".join(f"{ident(c)} = ?" for c in where)
    sql = f"UPDATE {table} SET {assignments} WHERE {clause}"
    params = tuple(to_sql(v) for v in data.values()) + tuple(
        to_sql(v) for v in where.values()
    )
    conn.execute(sql, params)


def fetch_one(
    conn: sqlite3.Connection,
    table: str,
    model_cls: type[T],
    *,
    where: dict[str, Any],
    order: str | None = None,
) -> T | None:
    table = ident(table)
    if not where:
        raise ValueError("refusing unconstrained SELECT")
    clause = " AND ".join(f"{ident(c)} = ?" for c in where)
    sql = f"SELECT * FROM {table} WHERE {clause}"
    if order:
        sql += f" ORDER BY {order}"
    sql += " LIMIT 1"
    row = conn.execute(sql, tuple(to_sql(v) for v in where.values())).fetchone()
    return row_to_model(row, model_cls) if row else None


def fetch_all(
    conn: sqlite3.Connection,
    table: str,
    model_cls: type[T],
    *,
    where: dict[str, Any] | None = None,
    order: str | None = None,
) -> list[T]:
    table = ident(table)
    sql = f"SELECT * FROM {table}"
    params: tuple[Any, ...] = ()
    if where:
        sql += " WHERE " + " AND ".join(f"{ident(c)} = ?" for c in where)
        params = tuple(to_sql(v) for v in where.values())
    if order:
        sql += f" ORDER BY {order}"
    return [row_to_model(r, model_cls) for r in conn.execute(sql, params)]


def save(
    conn: sqlite3.Connection,
    table: str,
    model_cls: type[T],
    incoming: T,
    *,
    existing: T | None,
    now: str | None = None,
    preserve: frozenset[str] = frozenset({"id", "created_at"}),
    always_touch: frozenset[str] = frozenset({"updated_at"}),
    lookup: dict[str, Any] | None = None,
) -> tuple[T, bool]:
    """Insert or update a row. Unset optional fields are not overwritten on update.

    Repositories do not commit; the caller owns the transaction.
    """
    now = now or utcnow()
    fields = model_cls.model_fields

    if existing is None:
        data = incoming.model_dump()
        for stamp in ("created_at", "updated_at", "first_seen_at", "last_seen_at"):
            if stamp in fields and stamp not in incoming.model_fields_set:
                data[stamp] = now
        insert_row(conn, table, data)
        where = lookup or {"id": data["id"]}
        saved = fetch_one(conn, table, model_cls, where=where)
        if saved is None:
            raise RuntimeError(f"insert into {table} did not round-trip")
        return saved, True

    incoming_data = incoming.model_dump(exclude_unset=True)
    for key in preserve:
        incoming_data.pop(key, None)
    for stamp in always_touch:
        if stamp in fields and stamp not in incoming.model_fields_set:
            incoming_data[stamp] = now
    where = lookup or {"id": existing.id}
    if incoming_data:
        update_row(conn, table, incoming_data, where=where)
    saved = fetch_one(conn, table, model_cls, where=where)
    if saved is None:
        raise RuntimeError(f"update of {table} did not round-trip")
    return saved, False
