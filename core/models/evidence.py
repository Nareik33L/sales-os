"""Evidence hash, file-sourced dedupe helpers, and FTS search.

docs/02-data-model.md: ``(source, source_id)`` is unique for API-sourced items;
file-sourced items (null ``source_id``) dedupe on ``content_hash``.
docs/04-memory-and-evidence.md §1: dedupe by source_id or content_hash before
the evidence row is created. Search is FTS5 over title/content/summary
(ADR-006), not a vector index.

Memory lifecycle (create/corroborate/supersede) is SOS-04 — not this module.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3

from core.models.common import row_to_model
from core.models.schemas import Evidence

# FTS5 MATCH is a mini-language; only pass alphanumeric tokens so a user
# query like "SSO?" cannot inject operators or fail the statement.
_FTS_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_DEFAULT_SEARCH_LIMIT = 50


def hash_content(content: str) -> str:
    """SHA-256 hex digest of UTF-8 ``content`` (the evidence body, not the file)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalise_source_id(source_id: str | None) -> str | None:
    """Treat missing or blank ``source_id`` as absent (file-sourced path)."""
    if source_id is None:
        return None
    stripped = source_id.strip()
    return stripped or None


def ensure_content_hash(evidence: Evidence) -> Evidence:
    """Fill ``content_hash`` from ``content`` when the caller omitted it.

    A caller-supplied hash is left alone: inbox pipelines may hash raw file
    bytes, which can differ from the extracted text stored in ``content``.
    """
    if evidence.content_hash:
        return evidence
    if not evidence.content:
        return evidence
    return evidence.model_copy(update={"content_hash": hash_content(evidence.content)})


def fts_match_query(query: str) -> str | None:
    """Turn a user string into a safe FTS5 MATCH expression, or None if empty."""
    tokens = _FTS_TOKEN.findall(query)
    if not tokens:
        return None
    return " AND ".join(f'"{token}"' for token in tokens)


def search_evidence(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = _DEFAULT_SEARCH_LIMIT,
    deal_id: str | None = None,
) -> list[Evidence]:
    """Return evidence rows matching ``query`` via ``evidence_fts``.

    Ordered by FTS5 bm25 (more relevant first), then ``occurred_at`` descending
    so a tie prefers the more recent item. Empty / operator-only queries
    return no rows rather than raising.
    """
    match = fts_match_query(query)
    if match is None or limit <= 0:
        return []

    sql = """
        SELECT e.*
        FROM evidence e
        JOIN evidence_fts ON evidence_fts.rowid = e.rowid
        WHERE evidence_fts MATCH ?
    """
    params: list[object] = [match]
    if deal_id is not None:
        sql += " AND e.deal_id = ?"
        params.append(deal_id)
    sql += " ORDER BY bm25(evidence_fts) ASC, e.occurred_at DESC LIMIT ?"
    params.append(limit)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [row_to_model(row, Evidence) for row in rows]
