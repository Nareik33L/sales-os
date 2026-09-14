"""Offline tests for BaseConnector.run() — no network, fictional data only."""

from __future__ import annotations

import json

import pytest

from connectors.base import BaseConnector, ConnectorSpec, SaveStats, error_item
from connectors.errors import (
    ConnectorAuthError,
    ConnectorNotConfigured,
    ConnectorTransientError,
)
from database.db import connect, migrate
from tests.connectors.fakes import FakeConnector


@pytest.fixture
def conn():
    c = connect(":memory:")
    migrate(c)
    yield c
    c.close()


def test_missing_env_not_configured_no_exception(conn, monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    connector = FakeConnector(name="hubspot", required_env=["HUBSPOT_ACCESS_TOKEN"])
    result = connector.run("MANUAL", conn=conn)
    assert result.status == "NOT_CONFIGURED"
    assert result.message == "Not connected — set HUBSPOT_ACCESS_TOKEN"
    row = conn.execute("SELECT * FROM sync_runs WHERE source = 'hubspot'").fetchone()
    assert row is not None
    assert row["status"] == "NOT_CONFIGURED"
    assert row["finished_at"] is not None
    assert row["message"] == "Not connected — set HUBSPOT_ACCESS_TOKEN"


def test_missing_env_on_base_connector_without_subclass_fetch(conn, monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    connector = BaseConnector(
        ConnectorSpec(name="hubspot", required_env=["HUBSPOT_ACCESS_TOKEN"])
    )
    result = connector.run("STARTUP", conn=conn)
    assert result.status == "NOT_CONFIGURED"
    assert result.trigger == "STARTUP"


def test_empty_env_value_is_not_configured(conn, monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "   ")
    connector = FakeConnector(name="hubspot", required_env=["HUBSPOT_ACCESS_TOKEN"])
    result = connector.run("MANUAL", conn=conn)
    assert result.status == "NOT_CONFIGURED"


def test_fetch_raise_failed_exception_does_not_escape(conn):
    connector = FakeConnector(
        name="hubspot",
        fetch_exc=RuntimeError("simulated HubSpot outage"),
    )
    result = connector.run("MANUAL", conn=conn)
    assert result.status == "FAILED"
    assert "simulated HubSpot outage" in (result.message or "")
    row = conn.execute("SELECT * FROM sync_runs WHERE id = ?", (result.id,)).fetchone()
    assert row["status"] == "FAILED"
    assert row["error_count"] == 1
    errors = json.loads(row["errors_json"])
    assert errors[0]["message"] == "simulated HubSpot outage"
    assert row["finished_at"] is not None


def test_auth_error_is_failed(conn):
    connector = FakeConnector(
        name="hubspot",
        auth_exc=ConnectorAuthError("401 unauthorized"),
    )
    result = connector.run("MANUAL", conn=conn)
    assert result.status == "FAILED"
    assert "401 unauthorized" in (result.message or "")


def test_transient_error_is_failed(conn):
    connector = FakeConnector(
        name="calendly",
        fetch_exc=ConnectorTransientError("429 retry later"),
    )
    result = connector.run("MORNING", conn=conn)
    assert result.status == "FAILED"
    assert result.trigger == "MORNING"


def test_connect_not_configured_uses_human_message(conn):
    connector = FakeConnector(
        name="hubspot",
        connect_exc=ConnectorNotConfigured(env_vars=["HUBSPOT_ACCESS_TOKEN"]),
    )
    result = connector.run("MANUAL", conn=conn)
    assert result.status == "NOT_CONFIGURED"
    assert result.message == "Not connected — set HUBSPOT_ACCESS_TOKEN"


def test_successful_run_records_success_and_counts(conn, monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "fictional-test-token")
    records = [
        {"id": "acme-1", "company": "Acme Ltd"},
        {"id": "beta-1", "company": "Beta Corp"},
        {"id": "gamma-1", "company": "Gamma"},
    ]
    connector = FakeConnector(
        name="hubspot",
        required_env=["HUBSPOT_ACCESS_TOKEN"],
        fetch_records=records,
        fetch_cursor={"hs_lastmodifieddate": "2026-09-14T08:00:00Z"},
        save_stats=SaveStats(created=2, changed=1, unchanged=0),
    )
    result = connector.run("MANUAL", conn=conn)
    assert result.status == "SUCCESS"
    assert result.records_fetched == 3
    assert result.records_created == 2
    assert result.records_changed == 1
    assert result.cursor == {"hs_lastmodifieddate": "2026-09-14T08:00:00Z"}
    row = conn.execute("SELECT * FROM sync_runs WHERE id = ?", (result.id,)).fetchone()
    assert row["status"] == "SUCCESS"
    assert row["records_fetched"] == 3
    assert row["records_created"] == 2
    assert row["records_changed"] == 1
    assert json.loads(row["cursor_json"])["hs_lastmodifieddate"].startswith("2026-09-14")
    assert "3 checked" in row["message"]
    assert "1 changed" in row["message"]


def test_partial_when_fetch_returns_errors(conn):
    connector = FakeConnector(
        name="excel",
        fetch_records=[{"id": "row-1"}],
        fetch_errors=[error_item("malformed row", "row-2")],
        save_stats=SaveStats(created=1, changed=0, unchanged=0),
    )
    result = connector.run("FILE_DROP", conn=conn)
    assert result.status == "PARTIAL"
    assert result.error_count == 1
    assert result.trigger == "FILE_DROP"


def test_disabled_is_skipped(conn):
    connector = FakeConnector(name="todo", mode="disabled", enabled=False)
    result = connector.run("MANUAL", conn=conn)
    assert result.status == "SKIPPED"
    assert result.message == "Disabled in sources.yaml"
    assert connector.fetch_calls == 0


def test_next_run_receives_previous_cursor(conn):
    connector = FakeConnector(
        name="hubspot",
        fetch_cursor={"page": 1},
        save_stats=SaveStats(created=1, changed=0, unchanged=0),
    )
    first = connector.run("MANUAL", conn=conn)
    assert first.status == "SUCCESS"
    assert connector.last_cursor is None
    second = connector.run("MANUAL", conn=conn)
    assert second.status == "SUCCESS"
    assert connector.last_cursor == {"page": 1}


def test_invalid_trigger_coerced_to_manual(conn):
    connector = FakeConnector(name="hubspot")
    result = connector.run("not-a-real-trigger", conn=conn)
    assert result.trigger == "MANUAL"
    row = conn.execute("SELECT trigger FROM sync_runs WHERE id = ?", (result.id,)).fetchone()
    assert row["trigger"] == "MANUAL"
