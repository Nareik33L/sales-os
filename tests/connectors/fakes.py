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


def acme_deal_payload(**overrides: Any) -> dict[str, Any]:
    """Minimal fictional HubSpot-shaped deal for `BaseConnector.save()` tests."""
    payload: dict[str, Any] = {
        "external_id": "hs-deal-acme-1",
        "source": "HUBSPOT",
        "product": "XODO_SIGN",
        "name": "Acme — Xodo Sign",
        "company_name": "Acme Ltd",
        "deal_value": 75000,
        "currency": "GBP",
        "deal_value_gbp": 75000,
        "stage": "Proposal",
        "stage_key": "presentationscheduled",
        "is_closed": False,
        "close_date": "2026-09-18",
        "owner": "Sam Taylor",
    }
    payload.update(overrides)
    return payload


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
        save_exc: BaseException | None = None,
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
        self.save_exc = save_exc
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
        return NormalisedBatch(
            deals=[{"external_id": r.get("id"), **r} for r in records if isinstance(r, dict)]
        )

    def save(self, batch: NormalisedBatch, conn: Any, sync_run_id: str) -> SaveStats:
        if self.save_exc is not None:
            raise self.save_exc
        if self.save_stats is not None:
            return self.save_stats
        n = len(batch.deals)
        return SaveStats(created=n, changed=0, unchanged=0)


class SavingConnector(BaseConnector):
    """Uses inherited `save()` against `core.models`. Fictional fixtures only."""

    def __init__(
        self,
        name: str = "hubspot",
        *,
        deals: list[Any] | None = None,
        companies: list[Any] | None = None,
        contacts: list[Any] | None = None,
        meetings: list[Any] | None = None,
        evidence: list[Any] | None = None,
        actions: list[Any] | None = None,
        prospecting_items: list[Any] | None = None,
        required_env: list[str] | None = None,
    ) -> None:
        super().__init__(
            ConnectorSpec(
                name=name,
                tier=1,
                mode="api",
                enabled=True,
                required_env=list(required_env or []),
                label=name,
            )
        )
        self._deals = list(deals or [])
        self._companies = list(companies or [])
        self._contacts = list(contacts or [])
        self._meetings = list(meetings or [])
        self._evidence = list(evidence or [])
        self._actions = list(actions or [])
        self._prospecting_items = list(prospecting_items or [])

    def fetch(self, cursor: dict[str, Any] | None) -> FetchResult:
        records = (
            list(self._deals)
            or list(self._companies)
            or list(self._contacts)
            or [{}]
        )
        return FetchResult(
            records=records, cursor={"watermark": "2026-09-14T08:00:00Z"}
        )

    def normalise(self, raw: Any) -> NormalisedBatch:
        return NormalisedBatch(
            deals=list(self._deals),
            companies=list(self._companies),
            contacts=list(self._contacts),
            meetings=list(self._meetings),
            evidence=list(self._evidence),
            actions=list(self._actions),
            prospecting_items=list(self._prospecting_items),
        )
