"""Demo seed inserts the fictional Acme/Beta/Gamma/Delta dataset."""

from __future__ import annotations

from pathlib import Path

from database.db import connect, migrate
from database.seed import COMPANY_NAMES, seed_demo
from run import main


def _seeded_conn():
    conn = connect(":memory:")
    migrate(conn)
    seed_demo(conn)
    return conn


def test_seed_inserts_fictional_companies_contacts_and_deals():
    conn = _seeded_conn()
    names = {row["name"] for row in conn.execute("SELECT name FROM companies")}
    assert names == set(COMPANY_NAMES)

    emails = [row["email"] for row in conn.execute("SELECT email FROM contacts")]
    assert len(emails) == 4
    assert any(e.endswith("@acme-example.test") for e in emails)
    assert any(e.endswith("@beta-example.test") for e in emails)
    assert all(e.endswith("-example.test") for e in emails)

    products = {row["product"] for row in conn.execute("SELECT product FROM deals")}
    assert products == {"XODO_SIGN", "PRODUCT_B"}
    assert conn.execute("SELECT count(*) FROM deals").fetchone()[0] == 4


def test_seed_inserts_memories_meetings_and_actions():
    conn = _seeded_conn()
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] >= 3
    assert conn.execute("SELECT count(*) FROM meetings").fetchone()[0] >= 2
    assert conn.execute("SELECT count(*) FROM actions").fetchone()[0] >= 4
    assert conn.execute("SELECT count(*) FROM evidence").fetchone()[0] >= 2
    tiers = {
        row["tier"]
        for row in conn.execute("SELECT DISTINCT tier FROM actions")
    }
    assert 1 in tiers and 3 in tiers
    quote = conn.execute(
        "SELECT quote FROM memory_evidence WHERE memory_id = 'demo-memory-acme-pricing'"
    ).fetchone()["quote"]
    assert "revised pricing" in quote.lower()


def test_seed_is_idempotent():
    conn = connect(":memory:")
    migrate(conn)
    seed_demo(conn)
    seed_demo(conn)
    assert conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 4
    assert conn.execute("SELECT count(*) FROM deals").fetchone()[0] == 4


def test_run_demo_cli_seeds_and_skips_streamlit(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "salesos.db"
    monkeypatch.setenv("SALESOS_DB_PATH", str(db_path))
    monkeypatch.setenv("SALESOS_DATA_DIR", str(tmp_path))
    assert main(["--demo"]) == 0
    conn = connect(db_path)
    names = {row["name"] for row in conn.execute("SELECT name FROM companies")}
    assert names == set(COMPANY_NAMES)
    assert (tmp_path / "logs" / "salesos.log").is_file()


def test_run_migrate_does_not_seed(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "salesos.db"
    monkeypatch.setenv("SALESOS_DB_PATH", str(db_path))
    monkeypatch.setenv("SALESOS_DATA_DIR", str(tmp_path))
    assert main(["--migrate"]) == 0
    conn = connect(db_path)
    assert conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 0
