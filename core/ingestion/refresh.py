"""Refresh orchestrator — the only entry point the rest of the app should call.

Loads enabled connectors from `config/sources.yaml` (Tier 1 first), runs each
`connector.run(trigger)` in isolation, and continues past connector failures
when `refresh.continue_on_connector_failure` is true (the default).

Post-connector steps are stubbed until later tickets: inbox, activity dates,
extraction, prioritisation.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from connectors.base import (
    Connector,
    ConnectorFactory,
    ConnectorSpec,
    SyncRunResult,
    coerce_trigger,
    error_item,
    registered_connectors,
)

logger = logging.getLogger("salesos.ingestion")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES_PATH = REPO_ROOT / "config" / "sources.yaml"


@dataclass
class RefreshResult:
    trigger: str
    runs: list[SyncRunResult] = field(default_factory=list)

    @property
    def failed_sources(self) -> list[str]:
        return [r.source for r in self.runs if r.status == "FAILED"]


def default_sources_path() -> Path:
    return DEFAULT_SOURCES_PATH


def load_sources_config(path: str | Path | None = None) -> dict[str, Any]:
    """Parse `config/sources.yaml`. Does not mutate write flags."""
    config_path = Path(path) if path is not None else default_sources_path()
    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise TypeError(f"{config_path} must contain a mapping")
    return data


def connector_specs(config: Mapping[str, Any]) -> list[ConnectorSpec]:
    raw_connectors = config.get("connectors") or {}
    specs: list[ConnectorSpec] = []
    for name, raw in raw_connectors.items():
        if not isinstance(raw, dict):
            raw = {}
        specs.append(
            ConnectorSpec(
                name=str(name),
                tier=int(raw.get("tier", 99)),
                mode=str(raw.get("mode", "disabled")),
                enabled=bool(raw.get("enabled", False)),
                required_env=[str(v) for v in (raw.get("required_env") or [])],
                label=str(raw.get("label") or name),
                config=dict(raw),
            )
        )
    specs.sort(key=lambda spec: (spec.tier, spec.name))
    return specs


def enabled_connector_specs(config: Mapping[str, Any]) -> list[ConnectorSpec]:
    """Enabled, non-disabled connectors, Tier 1 first."""
    return [
        spec
        for spec in connector_specs(config)
        if spec.enabled and spec.mode != "disabled"
    ]


def build_connectors(
    config: Mapping[str, Any],
    factories: Mapping[str, ConnectorFactory] | None = None,
) -> list[Connector]:
    """Instantiate registered implementations for enabled sources.

    Sources that are enabled in YAML but have no factory yet (HubSpot lands in
    SOS-08) are logged and skipped — they do not write SKIPPED `sync_runs` rows
    so the UI is not spammed before those tickets exist.
    """
    factories = dict(factories) if factories is not None else registered_connectors()
    timeout = (config.get("refresh") or {}).get("connector_timeout_seconds")
    built: list[Connector] = []
    for spec in enabled_connector_specs(config):
        factory = factories.get(spec.name)
        if factory is None:
            logger.info(
                "Skipping %s: no connector implementation registered yet", spec.name
            )
            continue
        connector = factory(spec)
        if timeout is not None and getattr(connector, "timeout_seconds", None) is None:
            try:
                connector.timeout_seconds = int(timeout)
            except (TypeError, ValueError, AttributeError):
                logger.debug("could not set timeout on %s", spec.name, exc_info=True)
        built.append(connector)
    return built


def process_inbox_folders(conn: sqlite3.Connection) -> None:
    """Parse `data/inbox/*` then move files to `data/processed/`.

    TODO(salesos-connector-engineer): SOS-20 inbox pipeline (`core/ingestion/inbox.py`).
    """


def recompute_activity_dates(conn: sqlite3.Connection) -> None:
    """Recompute `deals.last_activity_at` from engagements + local evidence.

    TODO(salesos-core-engineer): SOS-02 activity aggregator.
    """


def run_extraction_for_pending_evidence(conn: sqlite3.Connection) -> None:
    """Run AI/rules extraction for `evidence.extraction_status = PENDING`.

    TODO(salesos-intelligence-engineer): SOS-23 extraction step.
    """


def recompute_priorities(conn: sqlite3.Connection) -> None:
    """Recompute deterministic priority scores after ingestion.

    TODO(salesos-core-engineer): SOS-09 prioritisation engine.
    """


def refresh(
    trigger: str,
    *,
    conn: sqlite3.Connection | None = None,
    connectors: Sequence[Connector] | None = None,
    sources_path: str | Path | None = None,
    factories: Mapping[str, ConnectorFactory] | None = None,
    continue_on_connector_failure: bool | None = None,
    config: Mapping[str, Any] | None = None,
) -> RefreshResult:
    """Run enabled connectors then post-steps. Isolated per connector.

    `trigger` must match `sync_runs.trigger`: STARTUP | MANUAL | FILE_DROP | MORNING.
    Invalid values are coerced to MANUAL so the row can still be inserted.
    """
    trigger = coerce_trigger(trigger)
    if config is None:
        config = load_sources_config(sources_path)
    refresh_cfg = config.get("refresh") or {}
    if continue_on_connector_failure is None:
        continue_on_connector_failure = bool(
            refresh_cfg.get("continue_on_connector_failure", True)
        )

    owns_conn = conn is None
    if owns_conn:
        from database.db import connect as db_connect

        conn = db_connect()

    try:
        to_run: Iterable[Connector]
        if connectors is None:
            to_run = build_connectors(config, factories)
        else:
            to_run = list(connectors)

        runs: list[SyncRunResult] = []
        for connector in to_run:
            result = _run_isolated(connector, trigger, conn)
            runs.append(result)
            if result.status == "FAILED" and not continue_on_connector_failure:
                logger.info(
                    "Stopping remaining connectors after %s FAILED "
                    "(continue_on_connector_failure=false)",
                    result.source,
                )
                break

        _run_post_steps(conn)
        return RefreshResult(trigger=trigger, runs=runs)
    finally:
        if owns_conn:
            conn.close()


def _run_isolated(
    connector: Connector, trigger: str, conn: sqlite3.Connection
) -> SyncRunResult:
    """Call `connector.run()`; if it still raises, record FAILED here."""
    name = getattr(connector, "name", type(connector).__name__)
    try:
        return connector.run(trigger, conn=conn)
    except Exception as exc:
        logger.debug("connector %s raised past run(); isolating", name, exc_info=True)
        return _record_escaped_failure(conn, name, trigger, exc)


def _record_escaped_failure(
    conn: sqlite3.Connection,
    source: str,
    trigger: str,
    exc: BaseException,
) -> SyncRunResult:
    from core.ingestion.sync_runs import finish_run, open_run

    message = f"Failed: {type(exc).__name__}"
    try:
        try:
            conn.rollback()
        except sqlite3.Error:
            logger.debug("sqlite rollback failed while isolating %s", source, exc_info=True)
        run_id = open_run(conn, source=source, trigger=trigger)
        return finish_run(
            conn,
            run_id,
            status="FAILED",
            errors=[error_item(message)],
            message=message,
        )
    except Exception:
        logger.debug("could not record escaped failure for %s", source, exc_info=True)
        return SyncRunResult(
            id="",
            source=source,
            trigger=trigger,
            started_at="",
            finished_at=None,
            status="FAILED",
            error_count=1,
            errors=[error_item(message)],
            message=message,
        )


def _run_post_steps(conn: sqlite3.Connection) -> None:
    for step in (
        process_inbox_folders,
        recompute_activity_dates,
        run_extraction_for_pending_evidence,
        recompute_priorities,
    ):
        try:
            step(conn)
        except Exception:
            logger.debug("post-step %s failed", step.__name__, exc_info=True)
