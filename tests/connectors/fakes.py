"""Test doubles for connector tests. Fictional data only — no network."""

from __future__ import annotations

from typing import Any

from connectors.base import (
    BaseConnector,
    ConnectorSpec,
    FetchResult,
    NormalisedBatch,
    SaveStats,
)


class FakeConnector(BaseConnector):
    """Configurable subclass used by offline BaseConnector / refresh tests."""

    def __init__(
        self,
        name: str = "fake",
        *,
        tier: int = 1,
        mode: str = "api",
        enabled: bool = True,
        required_env: list[str] | None = None,
        fetch_records: list[Any] | None = None,
        fetch_cursor: dict[str, Any] | None = None,
        fetch_errors: list[dict[str, Any]] | None = None,
        fetch_exc: BaseException | None = None,
        save_stats: SaveStats | None = None,
        connect_exc: BaseException | None = None,
        auth_exc: BaseException | None = None,
        label: str = "",
    ) -> None:
        super().__init__(
            ConnectorSpec(
                name=name,
                tier=tier,
                mode=mode,
                enabled=enabled,
                required_env=list(required_env or []),
                label=label or name,
            )
        )
        self.fetch_records = (
            fetch_records
            if fetch_records is not None
            else [{"id": "acme-1", "company": "Acme Ltd"}]
        )
        self.fetch_cursor = fetch_cursor if fetch_cursor is not None else {"watermark": "2026-09-14"}
        self.fetch_errors = list(fetch_errors or [])
        self.fetch_exc = fetch_exc
        self.save_stats = save_stats
        self.connect_exc = connect_exc
        self.auth_exc = auth_exc
        self.last_cursor: dict[str, Any] | None = None
        self.fetch_calls = 0

    def connect(self) -> None:
        if self.connect_exc is not None:
            raise self.connect_exc

    def authenticate(self) -> None:
        if self.auth_exc is not None:
            raise self.auth_exc

    def fetch(self, cursor: dict[str, Any] | None) -> FetchResult:
        self.fetch_calls += 1
        self.last_cursor = cursor
        if self.fetch_exc is not None:
            raise self.fetch_exc
        return FetchResult(
            records=list(self.fetch_records),
            cursor=self.fetch_cursor,
            errors=list(self.fetch_errors),
        )

    def normalise(self, raw: Any) -> NormalisedBatch:
        records = list(raw) if raw is not None else []
        return NormalisedBatch(deals=[{"external_id": r.get("id"), **r} for r in records if isinstance(r, dict)])

    def save(self, batch: NormalisedBatch, conn: Any, sync_run_id: str) -> SaveStats:
        if self.save_stats is not None:
            return self.save_stats
        n = len(batch.deals)
        return SaveStats(created=n, changed=0, unchanged=0)
