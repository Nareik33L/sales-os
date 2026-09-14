"""Offline tests for BaseConnector.run() — no network, fictional data only."""

from __future__ import annotations

import json

from connectors.base import BaseConnector, ConnectorSpec, SaveStats, error_item
from connectors.errors import (
    ConnectorAuthError,
    ConnectorNotConfigured,
    ConnectorTransientError,
)
from core.models import (
    get_company_by_hubspot_id,
    get_deal_by_source_id,
    is_ulid,
    list_deal_changes,
)
from tests.connectors.fakes import FakeConnector, SavingConnector, acme_deal_payload


def test_missing_env_not_configured_no_exception(db, monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    connector = FakeConnector(name="hubspot", required_env=["HUBSPOT_ACCESS_TOKEN"])
    result = connector.run("MANUAL", conn=db)
    assert result.status == "NOT_CONFIGURED"
    assert result.message == "Not connected — set HUBSPOT_ACCESS_TOKEN"
    row = db.execute("SELECT * FROM sync_runs WHERE source = 'hubspot'").fetchone()
    assert row is not None
    assert row["status"] == "NOT_CONFIGURED"
    assert row["finished_at"] is not None
    assert row["message"] == "Not connected — set HUBSPOT_ACCESS_TOKEN"


def test_missing_env_on_base_connector_without_subclass_fetch(db, monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    connector = BaseConnector(
        ConnectorSpec(name="hubspot", required_env=["HUBSPOT_ACCESS_TOKEN"])
    )
    result = connector.run("STARTUP", conn=db)
    assert result.status == "NOT_CONFIGURED"
    assert result.trigger == "STARTUP"


def test_empty_env_value_is_not_configured(db, monkeypatch):
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", "   ")
    connector = FakeConnector(name="hubspot", required_env=["HUBSPOT_ACCESS_TOKEN"])
    result = connector.run("MANUAL", conn=db)
    assert result.status == "NOT_CONFIGURED"


def test_fetch_raise_failed_exception_does_not_escape(db):
    connector = FakeConnector(
        name="hubspot",
        fetch_exc=RuntimeError("simulated HubSpot outage"),
    )
    result = connector.run("MANUAL", conn=db)
    assert result.status == "FAILED"
    assert "simulated HubSpot outage" in (result.message or "")
    row = db.execute("SELECT * FROM sync_runs WHERE id = ?", (result.id,)).fetchone()
    assert row["status"] == "FAILED"
    assert row["error_count"] == 1
    errors = json.loads(row["errors_json"])
    assert errors[0]["message"] == "simulated HubSpot outage"
    assert row["finished_at"] is not None


def test_save_raise_failed_exception_does_not_escape(db):
    connector = FakeConnector(
        name="hubspot",
        save_exc=RuntimeError("simulated save failure"),
    )
    result = connector.run("MANUAL", conn=db)
    assert result.status == "FAILED"
    assert "simulated save failure" in (result.message or "")
    assert db.execute("SELECT count(*) FROM deals").fetchone()[0] == 0


def test_auth_error_is_failed(db):
    connector = FakeConnector(
        name="hubspot",
        auth_exc=ConnectorAuthError("401 unauthorized"),
    )
    result = connector.run("MANUAL", conn=db)
    assert result.status == "FAILED"
    assert "401 unauthorized" in (result.message or "")


def test_transient_error_is_failed(db):
    connector = FakeConnector(
        name="calendly",
        fetch_exc=ConnectorTransientError("429 retry later"),
    )
    result = connector.run("MORNING", conn=db)
    assert result.status == "FAILED"
    assert result.trigger == "MORNING"


def test_connect_not_configured_uses_human_message(db):
    connector = FakeConnector(
        name="hubspot",
        connect_exc=ConnectorNotConfigured(env_vars=["HUBSPOT_ACCESS_TOKEN"]),
    )
    result = connector.run("MANUAL", conn=db)
    assert result.status == "NOT_CONFIGURED"
    assert result.message == "Not connected — set HUBSPOT_ACCESS_TOKEN"


def test_successful_run_records_success_and_counts(db, monkeypatch):
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
    result = connector.run("MANUAL", conn=db)
    assert result.status == "SUCCESS"
    assert result.records_fetched == 3
    assert result.records_created == 2
    assert result.records_changed == 1
    assert result.cursor == {"hs_lastmodifieddate": "2026-09-14T08:00:00Z"}
    row = db.execute("SELECT * FROM sync_runs WHERE id = ?", (result.id,)).fetchone()
    assert row["status"] == "SUCCESS"
    assert row["records_fetched"] == 3
    assert row["records_created"] == 2
    assert row["records_changed"] == 1
    assert json.loads(row["cursor_json"])["hs_lastmodifieddate"].startswith("2026-09-14")
    assert "3 checked" in row["message"]
    assert "1 changed" in row["message"]
    assert is_ulid(result.id)


def test_partial_when_fetch_returns_errors(db):
    connector = FakeConnector(
        name="excel",
        fetch_records=[{"id": "row-1"}],
        fetch_errors=[error_item("malformed row", "row-2")],
        save_stats=SaveStats(created=1, changed=0, unchanged=0),
    )
    result = connector.run("FILE_DROP", conn=db)
    assert result.status == "PARTIAL"
    assert result.error_count == 1
    assert result.trigger == "FILE_DROP"


def test_disabled_is_skipped(db):
    connector = FakeConnector(name="todo", mode="disabled", enabled=False)
    result = connector.run("MANUAL", conn=db)
    assert result.status == "SKIPPED"
    assert result.message == "Disabled in sources.yaml"
    assert connector.fetch_calls == 0


def test_next_run_receives_previous_cursor(db):
    connector = FakeConnector(
        name="hubspot",
        fetch_cursor={"page": 1},
        save_stats=SaveStats(created=1, changed=0, unchanged=0),
    )
    first = connector.run("MANUAL", conn=db)
    assert first.status == "SUCCESS"
    assert connector.last_cursor is None
    second = connector.run("MANUAL", conn=db)
    assert second.status == "SUCCESS"
    assert connector.last_cursor == {"page": 1}


def test_invalid_trigger_coerced_to_manual(db):
    connector = FakeConnector(name="hubspot")
    result = connector.run("not-a-real-trigger", conn=db)
    assert result.trigger == "MANUAL"
    row = db.execute("SELECT trigger FROM sync_runs WHERE id = ?", (result.id,)).fetchone()
    assert row["trigger"] == "MANUAL"


def test_save_upserts_deal_and_writes_deal_changes(db):
    payload = acme_deal_payload()
    first = SavingConnector(deals=[payload]).run("MANUAL", conn=db)
    assert first.status == "SUCCESS"
    assert first.records_created == 1
    assert first.records_changed == 0
    deal = get_deal_by_source_id(db, "HUBSPOT", "hs-deal-acme-1")
    assert deal is not None
    assert deal.name == "Acme — Xodo Sign"
    assert deal.deal_value == 75000
    assert list_deal_changes(db, deal_id=deal.id) == []

    changed = acme_deal_payload(stage="Negotiation", deal_value=82000, deal_value_gbp=82000)
    second = SavingConnector(deals=[changed]).run("MANUAL", conn=db)
    assert second.status == "SUCCESS"
    assert second.records_created == 0
    assert second.records_changed == 1
    updated = get_deal_by_source_id(db, "HUBSPOT", "hs-deal-acme-1")
    assert updated is not None
    assert updated.id == deal.id
    assert updated.stage == "Negotiation"
    assert updated.deal_value == 82000
    rows = list_deal_changes(db, deal_id=deal.id)
    assert {r.field for r in rows} == {"stage", "deal_value"}
    assert all(r.sync_run_id == second.id for r in rows)

    third = SavingConnector(deals=[changed]).run("MANUAL", conn=db)
    assert third.status == "SUCCESS"
    assert third.records_created == 0
    assert third.records_changed == 0
    assert third.records_unchanged == 1
    assert len(list_deal_changes(db, deal_id=deal.id)) == 2


def test_save_malformed_deal_is_partial_and_does_not_escape(db):
    connector = SavingConnector(
        deals=[
            {"name": "not a deal"},
            acme_deal_payload(external_id="hs-deal-beta-1", name="Beta Corp — Xodo Sign"),
        ]
    )
    result = connector.run("MANUAL", conn=db)
    assert result.status == "PARTIAL"
    assert result.records_created == 1
    assert result.error_count >= 1
    assert get_deal_by_source_id(db, "HUBSPOT", "hs-deal-beta-1") is not None
    assert get_deal_by_source_id(db, "HUBSPOT", "hs-deal-acme-1") is None


def test_save_upserts_company_then_deal(db):
    connector = SavingConnector(
        companies=[
            {
                "name": "Acme Ltd",
                "hubspot_id": "hs-co-acme",
                "primary_domain": "acme-example.test",
            }
        ],
        deals=[acme_deal_payload()],
    )
    result = connector.run("MANUAL", conn=db)
    assert result.status == "SUCCESS"
    assert result.records_created == 2
    company = get_company_by_hubspot_id(db, "hs-co-acme")
    assert company is not None
    assert company.name == "Acme Ltd"
    deal = get_deal_by_source_id(db, "HUBSPOT", "hs-deal-acme-1")
    assert deal is not None


def test_save_invalid_fk_is_partial_not_an_exception(db):
    connector = SavingConnector(
        deals=[acme_deal_payload(company_id="does-not-exist")]
    )
    result = connector.run("MANUAL", conn=db)
    assert result.status == "PARTIAL"
    assert result.records_created == 0
    assert result.error_count >= 1
    assert get_deal_by_source_id(db, "HUBSPOT", "hs-deal-acme-1") is None
