"""In-memory HubSpot client backed by recorded fictional fixtures. No network."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from connectors.errors import ConnectorAuthError, ConnectorTransientError
from connectors.hubspot.normalise import parse_hs_datetime_ms

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "connectors" / "hubspot" / "fixtures"

OBJECT_FILES = {
    "deals": "deals.json",
    "companies": "companies.json",
    "contacts": "contacts.json",
    "calls": "calls.json",
    "meetings": "meetings.json",
    "notes": "notes.json",
    "emails": "emails.json",
    "tasks": "tasks.json",
}


def load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


class FakeHubSpotClient:
    """Duck-types HubSpotClient. All data is fictional (Acme / Beta / Gamma)."""

    def __init__(
        self,
        *,
        auth_error: bool = False,
        transient_error: bool = False,
        engagement_error: str | None = None,
    ) -> None:
        self.auth_error = auth_error
        self.transient_error = transient_error
        self.engagement_error = engagement_error
        self.search_calls: list[tuple[str, int | None]] = []
        self.completed_tasks: list[str] = []
        self._store: dict[str, list[dict[str, Any]]] = {
            key: copy.deepcopy(load_fixture(filename).get("results") or [])
            for key, filename in OBJECT_FILES.items()
        }
        self._pipelines = copy.deepcopy(load_fixture("pipelines.json").get("results") or [])
        self._owners = copy.deepcopy(load_fixture("owners.json").get("results") or [])

    def get_pipelines(self) -> list[dict[str, Any]]:
        self._maybe_fail()
        return copy.deepcopy(self._pipelines)

    def get_owners(self) -> list[dict[str, Any]]:
        self._maybe_fail()
        return copy.deepcopy(self._owners)

    def search_objects(
        self,
        object_type: str,
        *,
        since_ms: int | None,
        properties: list[str],
        associations: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.search_calls.append((object_type, since_ms))
        self._maybe_fail()
        if self.engagement_error and object_type == self.engagement_error:
            raise ConnectorTransientError(f"simulated {object_type} outage")
        return self.read_objects(
            object_type,
            [row["id"] for row in self._filter(object_type, since_ms)],
            properties=properties,
            associations=associations,
        )

    def read_objects(
        self,
        object_type: str,
        ids: list[str],
        *,
        properties: list[str],
        associations: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        wanted = {str(i) for i in ids}
        records = [
            copy.deepcopy(row)
            for row in self._store.get(object_type, [])
            if str(row.get("id")) in wanted
        ]
        return records

    def complete_task(self, task_id: str) -> dict[str, Any]:
        self._maybe_fail()
        self.completed_tasks.append(str(task_id))
        return {"id": str(task_id), "properties": {"hs_task_status": "COMPLETED"}}

    def mutate_deal(self, deal_id: str, **properties: Any) -> None:
        for row in self._store["deals"]:
            if str(row.get("id")) == str(deal_id):
                row.setdefault("properties", {}).update(properties)
                if "hs_lastmodifieddate" in properties:
                    row["updatedAt"] = properties["hs_lastmodifieddate"]
                return
        raise KeyError(deal_id)

    def add_deal(self, record: dict[str, Any]) -> None:
        self._store["deals"].append(copy.deepcopy(record))

    def _filter(self, object_type: str, since_ms: int | None) -> list[dict[str, Any]]:
        rows = self._store.get(object_type, [])
        if since_ms is None:
            return rows
        kept: list[dict[str, Any]] = []
        for row in rows:
            props = row.get("properties") if isinstance(row.get("properties"), dict) else {}
            ms = parse_hs_datetime_ms(props.get("hs_lastmodifieddate") or row.get("updatedAt"))
            if ms is None or ms >= since_ms:
                kept.append(row)
        return kept

    def _maybe_fail(self) -> None:
        if self.auth_error:
            raise ConnectorAuthError("401 unauthorized")
        if self.transient_error:
            raise ConnectorTransientError("429 retry later")
