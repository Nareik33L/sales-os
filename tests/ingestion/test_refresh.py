"""Offline tests for the refresh orchestrator. No network."""

from __future__ import annotations

from connectors.base import SaveStats
from connectors.errors import ConnectorTransientError
from core.ingestion.refresh import (
    build_connectors,
    enabled_connector_specs,
    load_sources_config,
    refresh,
)
from tests.connectors.fakes import FakeConnector


def test_orchestrator_continues_when_one_connector_fails(db):
    failing = FakeConnector(
        name="hubspot",
        tier=1,
        fetch_exc=RuntimeError("simulated HubSpot outage"),
    )
    ok = FakeConnector(
        name="excel",
        tier=1,
        fetch_records=[{"id": "acme-excel-1", "company": "Acme Ltd"}],
        save_stats=SaveStats(created=1, changed=0, unchanged=0),
    )
    result = refresh("MANUAL", conn=db, connectors=[failing, ok])
    assert [r.source for r in result.runs] == ["hubspot", "excel"]
    assert result.runs[0].status == "FAILED"
    assert result.runs[1].status == "SUCCESS"
    assert result.runs[1].records_created == 1
    rows = {
        row["source"]: row["status"]
        for row in db.execute("SELECT source, status FROM sync_runs")
    }
    assert rows["hubspot"] == "FAILED"
    assert rows["excel"] == "SUCCESS"


def test_orchestrator_stops_when_continue_on_failure_is_false(db):
    failing = FakeConnector(
        name="hubspot",
        fetch_exc=ConnectorTransientError("timeout"),
    )
    later = FakeConnector(name="excel")
    result = refresh(
        "MANUAL",
        conn=db,
        connectors=[failing, later],
        continue_on_connector_failure=False,
    )
    assert [r.source for r in result.runs] == ["hubspot"]
    assert later.fetch_calls == 0
    sources = [row["source"] for row in db.execute("SELECT source FROM sync_runs")]
    assert sources == ["hubspot"]


def test_refresh_loads_enabled_connectors_tier_1_first(db, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        """
version: 1
connectors:
  todo:
    tier: 2
    mode: api
    enabled: true
    required_env: []
  hubspot:
    tier: 1
    mode: api
    enabled: true
    required_env: [HUBSPOT_ACCESS_TOKEN]
  excel:
    tier: 1
    mode: file
    enabled: true
  disabled_one:
    tier: 1
    mode: disabled
    enabled: false
refresh:
  continue_on_connector_failure: true
  connector_timeout_seconds: 60
""",
        encoding="utf-8",
    )
    order: list[str] = []

    def factory_for(name: str):
        def _make(spec):
            connector = FakeConnector(
                name=spec.name,
                tier=spec.tier,
                mode=spec.mode,
                enabled=spec.enabled,
                required_env=list(spec.required_env),
            )
            original_run = connector.run

            def tracking_run(trigger, *, conn=None):
                order.append(spec.name)
                return original_run(trigger, conn=conn)

            connector.run = tracking_run  # type: ignore[method-assign]
            return connector

        return _make

    factories = {
        "hubspot": factory_for("hubspot"),
        "excel": factory_for("excel"),
        "todo": factory_for("todo"),
        "disabled_one": factory_for("disabled_one"),
    }
    result = refresh(
        "STARTUP",
        conn=db,
        sources_path=sources,
        factories=factories,
    )
    assert "disabled_one" not in order
    assert order[0] in {"excel", "hubspot"}  # both tier 1, name-sorted: excel then hubspot
    assert order == ["excel", "hubspot", "todo"]
    assert {r.source for r in result.runs} == {"excel", "hubspot", "todo"}


def test_enabled_specs_from_repo_sources_yaml():
    config = load_sources_config()
    specs = enabled_connector_specs(config)
    names = [s.name for s in specs]
    assert "hubspot" in names
    assert "todo" not in names
    tiers = [s.tier for s in specs]
    assert tiers == sorted(tiers)
    writes = config["connectors"]["hubspot"]["writes"]["complete_task"]
    assert writes is False
    assert config["connectors"]["google_sheets"]["writes"]["mark_done"] is False


def test_build_connectors_skips_unregistered_sources():
    config = load_sources_config()
    built = build_connectors(config, factories={})
    assert built == []


def test_refresh_with_real_sources_yaml_empty_registry_does_not_crash(db):
    result = refresh("FILE_DROP", conn=db, factories={})
    assert result.runs == []
    assert result.trigger == "FILE_DROP"
    count = db.execute("SELECT count(*) FROM sync_runs").fetchone()[0]
    assert count == 0


def test_not_configured_connector_does_not_stop_the_rest(db, monkeypatch):
    monkeypatch.delenv("HUBSPOT_ACCESS_TOKEN", raising=False)
    hubspot = FakeConnector(name="hubspot", required_env=["HUBSPOT_ACCESS_TOKEN"])
    excel = FakeConnector(name="excel", fetch_records=[{"id": "x1"}])
    result = refresh("MANUAL", conn=db, connectors=[hubspot, excel])
    assert result.runs[0].status == "NOT_CONFIGURED"
    assert result.runs[1].status == "SUCCESS"
