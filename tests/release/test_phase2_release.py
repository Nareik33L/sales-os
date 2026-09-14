"""Phase 2 release checks: version, fixture, migrate safety, no-credentials."""

from __future__ import annotations

from pathlib import Path

import yaml

from core.ingestion.refresh import refresh
from database.db import connect, migrate, table_names
from database.seed import COMPANY_NAMES
from run import main
from tests.release.helpers import (
    FIXTURE_V020,
    FICTIONAL_COMPANIES,
    copy_fixture,
    row_counts,
)
from tests.test_schema import EXPECTED_TABLES

ROOT = Path(__file__).resolve().parents[2]


def test_version_is_phase_2():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.2.0"


def test_changelog_covers_phase_2():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## 0.2.0 — 2026-09-14" in text
    assert "HubSpot" in text
    assert "82.4" in text
    assert "HUBSPOT_ACCESS_TOKEN" in text
    assert "writes.complete_task" in text


def test_manual_test_checklist_exists():
    path = ROOT / "docs" / "manual-tests" / "phase-2.md"
    text = path.read_text(encoding="utf-8")
    assert "Phase 2 manual test" in text
    assert "HUBSPOT_ACCESS_TOKEN" in text
    assert "python run.py" in text
    assert "pytest" not in text.lower()


def test_write_flags_remain_off():
    sources = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    assert sources["connectors"]["hubspot"]["writes"]["complete_task"] is False
    assert sources["connectors"]["google_sheets"]["writes"]["mark_done"] is False


def test_phase2_fixture_is_fictional():
    assert FIXTURE_V020.is_file()
    conn = connect(FIXTURE_V020)
    try:
        names = {row["name"] for row in conn.execute("SELECT name FROM companies")}
        assert names == FICTIONAL_COMPANIES == set(COMPANY_NAMES)
        emails = [row["email"] for row in conn.execute("SELECT email FROM contacts")]
        assert emails
        assert all(e.endswith("-example.test") for e in emails)
        assert conn.execute("SELECT count(*) FROM deals").fetchone()[0] == 4
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        assert applied == {1}
    finally:
        conn.close()


def test_migrate_on_fixture_copy_is_idempotent(tmp_path: Path):
    dest = copy_fixture(tmp_path / "copy.sqlite")
    conn = connect(dest)
    try:
        before = row_counts(conn)
        assert migrate(conn) == []
        after = row_counts(conn)
        assert after == before
        assert migrate(conn) == []
        assert row_counts(conn) == before
        missing = EXPECTED_TABLES - set(table_names(conn))
        assert not missing, f"missing tables: {missing}"
    finally:
        conn.close()


def test_run_migrate_cli_on_fixture_copy_is_safe(tmp_path: Path, monkeypatch):
    dest = copy_fixture(tmp_path / "cli.sqlite")
    before_conn = connect(dest)
    try:
        before = row_counts(before_conn)
    finally:
        before_conn.close()

    monkeypatch.setenv("SALESOS_DB_PATH", str(dest))
    monkeypatch.setenv("SALESOS_DATA_DIR", str(tmp_path))
    assert main(["--migrate"]) == 0

    after_conn = connect(dest)
    try:
        assert row_counts(after_conn) == before
    finally:
        after_conn.close()


def test_refresh_without_hubspot_token_is_not_configured(db, monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "")
    result = refresh("MANUAL", conn=db)
    hubspot = [run for run in result.runs if run.source == "hubspot"]
    assert hubspot, "HubSpot connector must run even without a token"
    assert hubspot[0].status == "NOT_CONFIGURED"
    assert "HUBSPOT_ACCESS_TOKEN" in (hubspot[0].message or "")
    assert all(run.status != "FAILED" for run in result.runs)
    row = db.execute(
        "SELECT status, message FROM sync_runs WHERE source = 'hubspot'"
    ).fetchone()
    assert row["status"] == "NOT_CONFIGURED"
