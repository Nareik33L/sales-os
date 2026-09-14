"""Offline HubSpot connector tests. Fixtures only — no network, no secrets."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

from connectors.base import ConnectorSpec, registered_connectors
from connectors.errors import ConnectorAuthError, ConnectorError, ConnectorTransientError
from connectors.hubspot.client import HubSpotClient
from connectors.hubspot.connector import HubSpotConnector
from connectors.hubspot.normalise import parse_hs_datetime
from core.ingestion.refresh import build_connectors, load_sources_config, recompute_activity_dates
from core.models import (
    ActionStatus,
    ActionType,
    DealSource,
    EvidenceType,
    MeetingSource,
    get_action_by_source_id,
    get_company_by_hubspot_id,
    get_contact_by_hubspot_id,
    get_deal_by_source_id,
    list_actions,
    list_company_aliases,
    list_deal_changes,
    list_evidence,
    list_meetings,
    upsert_deal,
)
from tests.connectors.hubspot_fake import FakeHubSpotClient

NOW = datetime(2026, 9, 14, 8, 0, 0, tzinfo=timezone.utc)
FICTIONAL_TOKEN = "fictional-test-token"


def _spec() -> ConnectorSpec:
    return ConnectorSpec(
        name="hubspot",
        tier=1,
        mode="api",
        enabled=True,
        required_env=["HUBSPOT_ACCESS_TOKEN"],
        label="HubSpot",
        config={
            "writes": {"complete_task": False},
            "sync": {
                "incremental": True,
                "lookback_days_on_first_sync": 365,
                "include_closed_deals_days": 90,
                "engagements": ["calls", "meetings", "notes", "emails", "tasks"],
            },
        },
    )


def _connector(monkeypatch: pytest.MonkeyPatch, client: FakeHubSpotClient | None = None) -> HubSpotConnector:
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", FICTIONAL_TOKEN)
    monkeypatch.setenv("SALESOS_TIMEZONE", "Europe/London")
    return HubSpotConnector(spec=_spec(), client=client or FakeHubSpotClient(), now=NOW)


def test_not_configured_returns_not_configured(db, monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    connector = HubSpotConnector(spec=_spec(), now=NOW)
    result = connector.run("MANUAL", conn=db)
    assert result.status == "NOT_CONFIGURED"
    assert result.message == "Not connected — set HUBSPOT_ACCESS_TOKEN"
    assert db.execute("SELECT count(*) FROM deals").fetchone()[0] == 0


def test_first_sync_upserts_deals_companies_contacts_engagements_tasks(
    db, monkeypatch, frozen_now
):
    client = FakeHubSpotClient()
    result = _connector(monkeypatch, client).run("MANUAL", conn=db)
    assert result.status == "SUCCESS"
    assert result.records_created >= 1
    assert result.cursor is not None
    assert "hs_lastmodifieddate" in result.cursor

    acme_co = get_company_by_hubspot_id(db, "1001")
    assert acme_co is not None
    assert acme_co.name == "Acme Ltd"
    assert acme_co.primary_domain == "acme-example.test"
    aliases = list_company_aliases(db, company_id=acme_co.id)
    assert any(a.alias_type == "DOMAIN" and a.value == "acme-example.test" for a in aliases)

    ada = get_contact_by_hubspot_id(db, "2001")
    assert ada is not None
    assert ada.email == "ada@acme-example.test"
    assert ada.company_id == acme_co.id

    acme = get_deal_by_source_id(db, "HUBSPOT", "3001")
    assert acme is not None
    assert acme.product == "XODO_SIGN"
    assert acme.source == DealSource.HUBSPOT
    assert acme.stage == "Proposal"
    assert acme.stage_key == "presentationscheduled"
    assert acme.deal_value == 75000
    assert acme.deal_value_gbp == 75000
    assert acme.owner == "Sam Taylor"
    assert acme.company_id == acme_co.id
    assert acme.is_closed is False

    gamma = get_deal_by_source_id(db, "HUBSPOT", "3005")
    assert gamma is not None
    assert gamma.currency == "USD"
    assert gamma.deal_value == 10000
    assert gamma.deal_value_gbp == 7800

    assert get_deal_by_source_id(db, "HUBSPOT", "3003") is None  # closed > 90 days ago
    closed_lost = get_deal_by_source_id(db, "HUBSPOT", "3004")
    assert closed_lost is not None
    assert closed_lost.is_closed is True
    assert closed_lost.is_won is False

    evidence = list_evidence(db)
    kinds = {row.source_id.split(":", 1)[0] for row in evidence if row.source_id}
    assert kinds >= {"calls", "meetings", "notes", "emails", "tasks"}
    assert all(row.type == EvidenceType.HUBSPOT_ACTIVITY for row in evidence)
    assert all(row.source == "hubspot" for row in evidence)

    meetings = list_meetings(db)
    assert any(m.external_id == "4002" and m.source == MeetingSource.HUBSPOT for m in meetings)

    open_task = get_action_by_source_id(db, "hubspot", "5001")
    assert open_task is not None
    assert open_task.type == ActionType.HUBSPOT_TASK
    assert open_task.status == ActionStatus.OPEN
    assert open_task.tier == 1
    assert open_task.deal_id == acme.id

    done_task = get_action_by_source_id(db, "hubspot", "5002")
    assert done_task is not None
    assert done_task.status == ActionStatus.COMPLETED


def test_last_activity_at_recomputed_from_engagements_not_notes_last_updated(
    db, monkeypatch, frozen_now
):
    _connector(monkeypatch).run("MANUAL", conn=db)
    acme = get_deal_by_source_id(db, "HUBSPOT", "3001")
    assert acme is not None
    # Call on 5 Sep is the latest *activity*; notes_last_updated is 14 Sep 07:00Z
    # and the 14 Sep 09:30Z meeting is still in the future at frozen_now.
    assert acme.last_activity_at == "2026-09-05T08:00:00Z"
    assert acme.source_updated_at == "2026-09-13T12:00:00Z"


def test_open_task_becomes_hubspot_task_action(db, monkeypatch, frozen_now):
    _connector(monkeypatch).run("MANUAL", conn=db)
    actions = [a for a in list_actions(db) if a.type == ActionType.HUBSPOT_TASK]
    open_ones = [a for a in actions if a.status == ActionStatus.OPEN]
    assert len(open_ones) == 1
    assert open_ones[0].source_id == "5001"
    assert "revised pricing" in (open_ones[0].title or "").lower()


def test_incremental_sync_writes_deal_changes(db, monkeypatch, frozen_now):
    client = FakeHubSpotClient()
    connector = _connector(monkeypatch, client)
    first = connector.run("MANUAL", conn=db)
    assert first.status == "SUCCESS"
    acme = get_deal_by_source_id(db, "HUBSPOT", "3001")
    assert acme is not None
    assert list_deal_changes(db, deal_id=acme.id) == []

    client.mutate_deal(
        "3001",
        amount="82000",
        dealstage="decisionmakerboughtin",
        hs_lastmodifieddate="2026-09-14T08:00:00.000Z",
    )
    second = connector.run("MANUAL", conn=db)
    assert second.status == "SUCCESS"
    assert second.records_changed >= 1
    assert any(kind == "deals" and since is not None for kind, since in client.search_calls[-6:])

    updated = get_deal_by_source_id(db, "HUBSPOT", "3001")
    assert updated is not None
    assert updated.id == acme.id
    assert updated.deal_value == 82000
    assert updated.stage == "Negotiation"
    fields = {row.field for row in list_deal_changes(db, deal_id=acme.id)}
    assert "deal_value" in fields
    assert "stage" in fields


def test_auth_failure_is_failed_and_does_not_escape(db, monkeypatch):
    client = FakeHubSpotClient(auth_error=True)
    result = _connector(monkeypatch, client).run("MANUAL", conn=db)
    assert result.status == "FAILED"
    assert "401" in (result.message or "")
    assert db.execute("SELECT count(*) FROM deals").fetchone()[0] == 0


def test_transient_failure_is_failed_and_does_not_escape(db, monkeypatch):
    client = FakeHubSpotClient(transient_error=True)
    result = _connector(monkeypatch, client).run("STARTUP", conn=db)
    assert result.status == "FAILED"
    assert result.trigger == "STARTUP"
    assert db.execute("SELECT status FROM sync_runs").fetchone()[0] == "FAILED"


def test_engagement_outage_is_partial(db, monkeypatch, frozen_now):
    client = FakeHubSpotClient(engagement_error="notes")
    result = _connector(monkeypatch, client).run("MANUAL", conn=db)
    assert result.status == "PARTIAL"
    assert result.error_count >= 1
    assert get_deal_by_source_id(db, "HUBSPOT", "3001") is not None


def test_malformed_deal_is_partial(db, monkeypatch, frozen_now):
    client = FakeHubSpotClient()
    client.add_deal(
        {
            "id": "3999",
            "properties": {"amount": "1", "hs_lastmodifieddate": "2026-09-13T12:00:00.000Z"},
            "updatedAt": "2026-09-13T12:00:00.000Z",
        }
    )
    result = _connector(monkeypatch, client).run("MANUAL", conn=db)
    assert result.status == "PARTIAL"
    assert get_deal_by_source_id(db, "HUBSPOT", "3001") is not None
    assert get_deal_by_source_id(db, "HUBSPOT", "3999") is None


def test_write_complete_task_stays_disabled_without_flag(db, monkeypatch):
    client = FakeHubSpotClient()
    connector = _connector(monkeypatch, client)
    with pytest.raises(ConnectorError, match="disabled"):
        connector.write("complete_task", {"task_id": "5001"}, audit_id="audit-1")
    assert client.completed_tasks == []
    with pytest.raises(ConnectorError, match="audit_id"):
        connector.write("complete_task", {"task_id": "5001"}, audit_id="")


def test_write_complete_task_when_flag_enabled(monkeypatch):
    client = FakeHubSpotClient()
    monkeypatch.setenv("HUBSPOT_ACCESS_TOKEN", FICTIONAL_TOKEN)
    spec = _spec()
    spec.config["writes"] = {"complete_task": True}
    connector = HubSpotConnector(spec=spec, client=client, now=NOW)
    result = connector.write("complete_task", {"task_id": "5001"}, audit_id="audit-approved")
    assert result.ok is True
    assert client.completed_tasks == ["5001"]


def test_sources_yaml_write_flag_unchanged():
    sources = load_sources_config()
    assert sources["connectors"]["hubspot"]["writes"]["complete_task"] is False


def test_hubspot_registered_for_orchestrator():
    from connectors import load_builtin_connectors

    load_builtin_connectors()
    assert "hubspot" in registered_connectors()
    built = build_connectors(load_sources_config())
    names = [c.name for c in built]
    assert "hubspot" in names
    hs = next(c for c in built if c.name == "hubspot")
    assert hs.timeout_seconds == 60
    assert "complete_task" in hs.write_capabilities


def test_recompute_activity_dates_ignores_open_tasks_and_future_meetings(
    db, monkeypatch, frozen_now
):
    _connector(monkeypatch).run("MANUAL", conn=db)
    acme = get_deal_by_source_id(db, "HUBSPOT", "3001")
    assert acme is not None
    acme.last_activity_at = "2026-09-14T07:00:00Z"
    upsert_deal(db, acme)
    recompute_activity_dates(db)
    refreshed = get_deal_by_source_id(db, "HUBSPOT", "3001")
    assert refreshed is not None
    assert refreshed.last_activity_at == "2026-09-05T08:00:00Z"


def test_client_retries_after_retry_after_header():
    sleeps: list[float] = []

    class ScriptedSession:
        def __init__(self) -> None:
            self.calls = 0

        def request(self, method, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return _HttpResponse(429, headers={"Retry-After": "2"})
            return _HttpResponse(200, json_data={"results": []})

    session = ScriptedSession()
    client = HubSpotClient(
        FICTIONAL_TOKEN,
        timeout_seconds=10,
        session=session,  # type: ignore[arg-type]
        sleep=sleeps.append,
    )
    assert client.get_pipelines() == []
    assert session.calls == 2
    assert sleeps == [2.0]


def test_client_auth_error_on_401():
    class Once:
        def request(self, method, url, **kwargs):
            return _HttpResponse(401, json_data={"message": "expired token", "category": "EXPIRED"})

    client = HubSpotClient(FICTIONAL_TOKEN, session=Once(), sleep=lambda _: None)  # type: ignore[arg-type]
    with pytest.raises(ConnectorAuthError):
        client.get_owners()


def test_client_timeout_is_transient():
    class Boom:
        def request(self, method, url, **kwargs):
            raise requests.Timeout("simulated")

    client = HubSpotClient(FICTIONAL_TOKEN, session=Boom(), sleep=lambda _: None)  # type: ignore[arg-type]
    with pytest.raises(ConnectorTransientError):
        client.get_owners()


def test_parse_hs_datetime_accepts_millis():
    assert parse_hs_datetime("1694678400000") is not None
    assert parse_hs_datetime("2026-09-05T08:00:00.000Z") == "2026-09-05T08:00:00Z"


class _HttpResponse:
    def __init__(
        self,
        status: int,
        *,
        json_data: dict | None = None,
        headers: dict | None = None,
        content: bytes | None = None,
    ) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._json = json_data
        self.content = content if content is not None else (b"{}" if json_data is not None else b"")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json
