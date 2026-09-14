"""The schema is the architecture artifact — make sure it actually applies and
encodes the invariants the docs promise."""

import sqlite3

import pytest

from database.db import migrate, table_names

EXPECTED_TABLES = {
    "companies", "company_aliases", "contacts", "deals", "deal_changes",
    "evidence", "evidence_fts", "memories", "memory_evidence",
    "actions", "action_evidence", "meetings", "prospecting_items",
    "sync_runs", "processed_files", "review_items",
    "audit_log", "audit_log_evidence", "ai_calls",
    "user_feedback", "settings", "schema_migrations",
}


def test_all_planned_tables_exist(db):
    names = set(table_names(db))
    missing = EXPECTED_TABLES - names
    assert not missing, f"missing tables: {missing}"


def test_migrate_is_idempotent(db):
    assert migrate(db) == []
    assert db.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1


def _now():
    return "2026-09-14T08:00:00Z"


def _insert_company(db, cid="c1"):
    db.execute(
        "INSERT INTO companies(id, name, normalised_name, created_at, updated_at) VALUES (?,?,?,?,?)",
        (cid, "Acme Ltd", "acme", _now(), _now()),
    )


def _insert_deal(db, did="d1", cid="c1"):
    db.execute(
        """INSERT INTO deals(id, external_id, source, product, name, company_id, deal_value, currency,
                              first_seen_at, last_seen_at, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (did, "hs-1", "HUBSPOT", "XODO_SIGN", "Acme — Xodo Sign", cid, 75000, "GBP", _now(), _now(), _now(), _now()),
    )


def test_enums_are_enforced(db):
    _insert_company(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO deals(id, external_id, source, product, name, first_seen_at, last_seen_at, created_at, updated_at)
               VALUES ('d2','x','SALESFORCE','XODO_SIGN','bad', ?, ?, ?, ?)""",
            (_now(), _now(), _now(), _now()),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO memories(id, type, subject, content, confidence, valid_from, created_by, created_at, updated_at)
               VALUES ('m1','GUESS','s','c',0.5,?, 'rules', ?, ?)""",
            (_now(), _now(), _now()),
        )


def test_confidence_bounds(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO memories(id, type, subject, content, confidence, valid_from, created_by, created_at, updated_at)
               VALUES ('m1','FACT','s','c',1.5,?, 'rules', ?, ?)""",
            (_now(), _now(), _now()),
        )


def test_evidence_memory_provenance_roundtrip(db):
    _insert_company(db)
    _insert_deal(db)
    db.execute(
        """INSERT INTO evidence(id, type, source, source_id, company_id, deal_id, occurred_at, title, content, created_at)
           VALUES ('e1','EMAIL','email_files','<msg-1>','c1','d1',?, 'Re: pricing',
                   'Thanks Sam. I will send the revised pricing tomorrow.', ?)""",
        (_now(), _now()),
    )
    db.execute(
        """INSERT INTO memories(id, type, basis, subject, content, deal_id, direction, due_date, confidence,
                                valid_from, created_by, created_at, updated_at)
           VALUES ('m1','COMMITMENT','OBSERVED','Revised pricing','Send revised pricing to Acme','d1',
                   'USER_TO_CUSTOMER','2026-09-15',0.85,?, 'rules', ?, ?)""",
        (_now(), _now(), _now()),
    )
    db.execute(
        "INSERT INTO memory_evidence(memory_id, evidence_id, quote, created_at) VALUES ('m1','e1',?,?)",
        ("I will send the revised pricing tomorrow.", _now()),
    )
    row = db.execute(
        """SELECT e.title, me.quote FROM memories m
           JOIN memory_evidence me ON me.memory_id = m.id
           JOIN evidence e ON e.id = me.evidence_id WHERE m.id = 'm1'"""
    ).fetchone()
    assert row["title"] == "Re: pricing"
    assert "revised pricing" in row["quote"]


def test_evidence_full_text_search(db):
    db.execute(
        """INSERT INTO evidence(id, type, source, source_id, occurred_at, title, content, created_at)
           VALUES ('e1','ZOOM_TRANSCRIPT','transcripts','acme-2026-09-13',?, 'Acme call',
                   'We received the pricing and are reviewing internally with procurement.', ?)""",
        (_now(), _now()),
    )
    hits = db.execute(
        "SELECT rowid FROM evidence_fts WHERE evidence_fts MATCH 'procurement'"
    ).fetchall()
    assert len(hits) == 1


def test_foreign_keys_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO actions(id, title, type, source, deal_id, created_at, updated_at)
               VALUES ('a1','Send pricing','COMMITMENT','memory','does-not-exist',?,?)""",
            (_now(), _now()),
        )


def test_action_dedupe_by_source(db):
    db.execute(
        """INSERT INTO actions(id, title, type, source, source_id, created_at, updated_at)
           VALUES ('a1','Row 1','PROSPECTING','google_sheets','row-abc',?,?)""",
        (_now(), _now()),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO actions(id, title, type, source, source_id, created_at, updated_at)
               VALUES ('a2','Row 1 again','PROSPECTING','google_sheets','row-abc',?,?)""",
            (_now(), _now()),
        )
