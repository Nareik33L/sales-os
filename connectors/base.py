"""Connector protocol and BaseConnector orchestration.

See `docs/05-connectors.md` §1. Concrete sources (HubSpot, Excel, …) subclass
`BaseConnector` and implement the hooks; `run()` owns `sync_runs` bookkeeping
and **never** lets an exception escape to the orchestrator or a Streamlit page.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from connectors.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNotConfigured,
    ConnectorTransientError,
    not_configured_message,
)

logger = logging.getLogger("salesos.connectors")

Trigger = Literal["STARTUP", "MANUAL", "FILE_DROP", "MORNING"]
SyncStatus = Literal[
    "RUNNING", "SUCCESS", "PARTIAL", "FAILED", "SKIPPED", "NOT_CONFIGURED"
]
ConnectorMode = Literal["api", "file", "disabled"]

ALLOWED_TRIGGERS: frozenset[str] = frozenset(
    {"STARTUP", "MANUAL", "FILE_DROP", "MORNING"}
)
ERROR_CAP = 50

ConnectorFactory = Callable[["ConnectorSpec"], "Connector"]

_FACTORIES: dict[str, ConnectorFactory] = {}


def register_connector(name: str, factory: ConnectorFactory) -> None:
    """Register a factory used by the refresh orchestrator to build a source."""
    _FACTORIES[name] = factory


def registered_connectors() -> dict[str, ConnectorFactory]:
    return dict(_FACTORIES)


@dataclass
class ConnectorSpec:
    """Declared shape of one entry under `config/sources.yaml` `connectors:`."""

    name: str
    tier: int = 1
    mode: str = "api"
    enabled: bool = True
    required_env: list[str] = field(default_factory=list)
    label: str = ""
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    """Raw records plus the incremental cursor for the next run."""

    records: list[Any] = field(default_factory=list)
    cursor: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class NormalisedBatch:
    """Internal rows for `save()` — `core.models` instances or coercible dicts."""

    deals: list[Any] = field(default_factory=list)
    companies: list[Any] = field(default_factory=list)
    contacts: list[Any] = field(default_factory=list)
    meetings: list[Any] = field(default_factory=list)
    evidence: list[Any] = field(default_factory=list)
    actions: list[Any] = field(default_factory=list)
    prospecting_items: list[Any] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def record_count(self) -> int:
        return (
            len(self.deals)
            + len(self.companies)
            + len(self.contacts)
            + len(self.meetings)
            + len(self.evidence)
            + len(self.actions)
            + len(self.prospecting_items)
        )


@dataclass
class SaveStats:
    """Outcome of `save()`: upsert diffs, never deletes."""

    created: int = 0
    changed: int = 0
    unchanged: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class WriteResult:
    ok: bool
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncRunResult:
    """In-memory view of a `sync_runs` row returned by `BaseConnector.run()`."""

    id: str
    source: str
    trigger: str
    started_at: str
    finished_at: str | None
    status: str
    records_fetched: int = 0
    records_created: int = 0
    records_changed: int = 0
    records_unchanged: int = 0
    error_count: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    message: str | None = None
    cursor: dict[str, Any] | None = None


def error_item(message: str, record_ref: str | None = None) -> dict[str, Any]:
    return {"message": message, "record_ref": record_ref}


def cap_errors(errors: list[dict[str, Any]], limit: int = ERROR_CAP) -> list[dict[str, Any]]:
    if len(errors) <= limit:
        return list(errors)
    extra = len(errors) - limit
    capped = list(errors[:limit])
    capped.append(error_item(f"{extra} more error(s) omitted"))
    return capped


def coerce_trigger(trigger: str) -> str:
    value = (trigger or "MANUAL").strip().upper()
    if value in ALLOWED_TRIGGERS:
        return value
    return "MANUAL"


@runtime_checkable
class Connector(Protocol):
    name: str
    tier: int
    mode: str

    def is_configured(self) -> bool: ...
    def connect(self) -> None: ...
    def authenticate(self) -> None: ...
    def fetch(self, cursor: dict[str, Any] | None) -> FetchResult: ...
    def normalise(self, raw: Any) -> NormalisedBatch: ...
    def save(
        self, batch: NormalisedBatch, conn: sqlite3.Connection, sync_run_id: str
    ) -> SaveStats: ...
    def run(self, trigger: str, *, conn: sqlite3.Connection | None = None) -> SyncRunResult: ...


class BaseConnector:
    """Shared run orchestration. Subclasses implement the hooks for one source."""

    name: str = ""
    tier: int = 1
    mode: str = "api"
    enabled: bool = True
    required_env: tuple[str, ...] = ()
    label: str = ""
    write_capabilities: frozenset[str] = frozenset()
    timeout_seconds: int | None = None

    def __init__(self, spec: ConnectorSpec | None = None, **overrides: Any) -> None:
        if spec is not None:
            self.name = spec.name
            self.tier = spec.tier
            self.mode = spec.mode
            self.enabled = spec.enabled
            self.required_env = list(spec.required_env)
            self.label = spec.label or spec.name
            self.spec = spec
        else:
            self.required_env = list(self.required_env)
            self.spec = ConnectorSpec(
                name=self.name,
                tier=self.tier,
                mode=self.mode,
                enabled=self.enabled,
                required_env=list(self.required_env),
                label=self.label or self.name,
            )
        self.write_capabilities = set(self.write_capabilities)
        for key, value in overrides.items():
            setattr(self, key, value)

    def missing_env_vars(self) -> list[str]:
        missing: list[str] = []
        for var in self.required_env:
            value = os.environ.get(var, "")
            if not str(value).strip():
                missing.append(var)
        return missing

    def is_configured(self) -> bool:
        """True when every `required_env` name is present and non-empty."""
        return not self.missing_env_vars()

    def connect(self) -> None:
        """Build the HTTP/file client. Raise ConnectorNotConfigured / ConnectorAuthError."""

    def authenticate(self) -> None:
        """Cheap auth probe used by health checks. No-op by default."""

    def fetch(self, cursor: dict[str, Any] | None) -> FetchResult:
        raise NotImplementedError(f"{type(self).__name__}.fetch is not implemented")

    def normalise(self, raw: Any) -> NormalisedBatch:
        raise NotImplementedError(f"{type(self).__name__}.normalise is not implemented")

    def save(
        self,
        batch: NormalisedBatch,
        conn: sqlite3.Connection,
        sync_run_id: str,
    ) -> SaveStats:
        """Persist a normalised batch via `core.models` upserts.

        Deals use `upsert_deal(..., sync_run_id=)` so tracked-field diffs land
        in `deal_changes`. Does not commit — `finish_run` owns the commit.
        Never deletes; disappearing source rows simply stop advancing
        `last_seen_at`.
        """
        from core.ingestion.persist import save_normalised_batch

        return save_normalised_batch(batch, conn, sync_run_id)

    def write(self, capability: str, payload: dict[str, Any], *, audit_id: str) -> WriteResult:
        """Approval-gated external write. Only reachable via `core.audit.execute_approved()`.

        Do not enable `writes.*` flags in `config/sources.yaml`.
        TODO(salesos-core-engineer): SOS-06 — assert `core.audit.is_approved(audit_id)`.
        """
        if not audit_id:
            raise ConnectorError("write requires an approved audit_id")
        if capability not in self.write_capabilities:
            raise ConnectorError(
                f"unsupported write capability {capability!r} on {self.name}"
            )
        raise ConnectorError(f"write capability {capability!r} is not implemented")

    def run(self, trigger: str, *, conn: sqlite3.Connection | None = None) -> SyncRunResult:
        """Open a `sync_runs` row, run hooks, record status. Never re-raises."""
        from core.ingestion.sync_runs import finish_run, latest_cursor, open_run

        trigger = coerce_trigger(trigger)
        owns_conn = conn is None
        if owns_conn:
            from database.db import connect as db_connect

            try:
                conn = db_connect()
            except Exception as exc:
                logger.debug("could not open db for %s", self.name, exc_info=True)
                return SyncRunResult(
                    id="",
                    source=self.name,
                    trigger=trigger,
                    started_at="",
                    finished_at=None,
                    status="FAILED",
                    error_count=1,
                    errors=[error_item(_safe_message(exc))],
                    message=f"Failed: {_safe_message(exc)}",
                )
        run_id = ""
        try:
            run_id = open_run(conn, source=self.name, trigger=trigger)
            return self._execute(conn, run_id, trigger, latest_cursor, finish_run)
        except Exception as exc:
            logger.debug("connector %s run() outer failure", self.name, exc_info=True)
            _safe_rollback(conn)
            if run_id:
                try:
                    return finish_run(
                        conn,
                        run_id,
                        status="FAILED",
                        errors=[error_item(_safe_message(exc))],
                        message=f"Failed: {_safe_message(exc)}",
                    )
                except Exception:
                    logger.debug("finish_run failed for %s", self.name, exc_info=True)
            return SyncRunResult(
                id=run_id or "",
                source=self.name,
                trigger=trigger,
                started_at="",
                finished_at=None,
                status="FAILED",
                error_count=1,
                errors=[error_item(_safe_message(exc))],
                message=f"Failed: {_safe_message(exc)}",
            )
        finally:
            if owns_conn:
                conn.close()

    def _execute(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        trigger: str,
        latest_cursor: Any,
        finish_run: Any,
    ) -> SyncRunResult:
        try:
            if not self.enabled or self.mode == "disabled":
                return finish_run(
                    conn,
                    run_id,
                    status="SKIPPED",
                    message="Disabled in sources.yaml",
                )
            if not self.is_configured():
                message = not_configured_message(self.missing_env_vars())
                return finish_run(
                    conn,
                    run_id,
                    status="NOT_CONFIGURED",
                    message=message,
                )

            self.connect()
            self.authenticate()
            previous = latest_cursor(conn, self.name)
            fetched = self.fetch(previous)
            if not isinstance(fetched, FetchResult):
                fetched = FetchResult(records=list(fetched or []))
            batch = self.normalise(fetched.records)
            if not isinstance(batch, NormalisedBatch):
                batch = NormalisedBatch(errors=[error_item("normalise() returned an invalid batch")])
            stats = self.save(batch, conn, run_id)
            if not isinstance(stats, SaveStats):
                stats = SaveStats(errors=[error_item("save() returned invalid stats")])

            errors = cap_errors(
                list(fetched.errors) + list(batch.errors) + list(stats.errors)
            )
            fetched_count = len(fetched.records)
            if errors:
                status: SyncStatus = "PARTIAL"
                message = (
                    f"{fetched_count} checked · {stats.changed} changed · "
                    f"{len(errors)} errors"
                )
            else:
                status = "SUCCESS"
                message = f"{fetched_count} checked · {stats.changed} changed"
            return finish_run(
                conn,
                run_id,
                status=status,
                records_fetched=fetched_count,
                records_created=stats.created,
                records_changed=stats.changed,
                records_unchanged=stats.unchanged,
                errors=errors,
                message=message,
                cursor=fetched.cursor,
            )
        except ConnectorNotConfigured as exc:
            logger.debug("connector %s not configured", self.name, exc_info=True)
            _safe_rollback(conn)
            message = str(exc) or not_configured_message(exc.env_vars or self.missing_env_vars())
            return finish_run(
                conn,
                run_id,
                status="NOT_CONFIGURED",
                message=message,
            )
        except (ConnectorAuthError, ConnectorTransientError, Exception) as exc:
            logger.debug("connector %s failed during run", self.name, exc_info=True)
            _safe_rollback(conn)
            item = error_item(_safe_message(exc))
            status = "FAILED"
            return finish_run(
                conn,
                run_id,
                status=status,
                errors=[item],
                message=f"Failed: {_safe_message(exc)}",
            )


def _safe_rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.rollback()
    except sqlite3.Error:
        logger.debug("sqlite rollback failed", exc_info=True)


def _safe_message(exc: BaseException) -> str:
    """Exception text for `sync_runs.message`. Never include secrets or bodies."""
    text = str(exc).strip() or type(exc).__name__
    lowered = text.lower()
    for needle in ("bearer ", "token=", "api_key=", "authorization:"):
        if needle in lowered:
            return type(exc).__name__
    if len(text) > 500:
        return text[:497] + "..."
    return text
