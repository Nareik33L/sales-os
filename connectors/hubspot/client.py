"""Thin HubSpot CRM v3 HTTP client.

Pagination, Retry-After backoff, and timeouts only — no normalisation.
The connector injects this (or a fake) so tests never hit the network.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Any
from urllib.parse import urljoin

import requests

from connectors.errors import ConnectorAuthError, ConnectorTransientError

logger = logging.getLogger("salesos.connectors.hubspot")

DEFAULT_BASE_URL = "https://api.hubapi.com"
DEFAULT_TIMEOUT_SECONDS = 60
MAX_RETRIES = 3
PAGE_LIMIT = 100
BATCH_LIMIT = 100
MAX_PAGES = 100

DEAL_PROPERTIES = [
    "dealname",
    "amount",
    "deal_currency_code",
    "dealstage",
    "pipeline",
    "closedate",
    "hubspot_owner_id",
    "createdate",
    "hs_lastmodifieddate",
    "notes_last_updated",
]
COMPANY_PROPERTIES = ["name", "domain", "industry", "hs_lastmodifieddate"]
CONTACT_PROPERTIES = [
    "firstname",
    "lastname",
    "email",
    "phone",
    "jobtitle",
    "hs_lastmodifieddate",
]
ENGAGEMENT_PROPERTIES: dict[str, list[str]] = {
    "calls": [
        "hs_call_title",
        "hs_call_body",
        "hs_call_direction",
        "hs_timestamp",
        "hs_lastmodifieddate",
    ],
    "meetings": [
        "hs_meeting_title",
        "hs_meeting_body",
        "hs_meeting_start_time",
        "hs_meeting_end_time",
        "hs_meeting_outcome",
        "hs_timestamp",
        "hs_lastmodifieddate",
    ],
    "notes": ["hs_note_body", "hs_timestamp", "hs_lastmodifieddate"],
    "emails": [
        "hs_email_subject",
        "hs_email_text",
        "hs_email_direction",
        "hs_email_from_email",
        "hs_email_to_email",
        "hs_timestamp",
        "hs_lastmodifieddate",
    ],
    "tasks": [
        "hs_task_subject",
        "hs_task_body",
        "hs_task_status",
        "hs_task_priority",
        "hs_timestamp",
        "hs_task_completion_date",
        "hs_lastmodifieddate",
        "hubspot_owner_id",
    ],
}


class HubSpotClient:
    """Bearer-token CRM client. Never logs the token or response bodies."""

    def __init__(
        self,
        token: str,
        *,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        base_url: str = DEFAULT_BASE_URL,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = token
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.base_url = base_url.rstrip("/") + "/"
        self.session = session or requests.Session()
        self._sleep = sleep

    def get_pipelines(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/crm/v3/pipelines/deals")
        return list(data.get("results") or [])

    def get_owners(self) -> list[dict[str, Any]]:
        return self._paginate_get("/crm/v3/owners")

    def search_objects(
        self,
        object_type: str,
        *,
        since_ms: int | None,
        properties: Sequence[str],
        associations: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """One search query (paginated) per object type, then hydrate associations."""
        ids = [row["id"] for row in self._search_pages(object_type, since_ms) if row.get("id")]
        if not ids:
            return []
        return self.read_objects(
            object_type,
            ids,
            properties=properties,
            associations=associations,
        )

    def read_objects(
        self,
        object_type: str,
        ids: Iterable[str],
        *,
        properties: Sequence[str],
        associations: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(str(i) for i in ids if i))
        if not unique_ids:
            return []
        records: list[dict[str, Any]] = []
        for chunk in _chunks(unique_ids, BATCH_LIMIT):
            body = {
                "properties": list(properties),
                "inputs": [{"id": item} for item in chunk],
            }
            data = self._request(
                "POST", f"/crm/v3/objects/{object_type}/batch/read", json_body=body
            )
            records.extend(data.get("results") or [])
        if associations:
            self._merge_associations(object_type, records, associations)
        return records

    def complete_task(self, task_id: str) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/crm/v3/objects/tasks/{task_id}",
            json_body={"properties": {"hs_task_status": "COMPLETED"}},
        )

    def _search_pages(self, object_type: str, since_ms: int | None) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        if since_ms is not None:
            filters.append(
                {
                    "propertyName": "hs_lastmodifieddate",
                    "operator": "GTE",
                    "value": str(int(since_ms)),
                }
            )
        body: dict[str, Any] = {
            "filterGroups": [{"filters": filters}] if filters else [{"filters": []}],
            "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}],
            "properties": ["hs_lastmodifieddate"],
            "limit": PAGE_LIMIT,
        }
        results: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(MAX_PAGES):
            if after is not None:
                body["after"] = after
            data = self._request(
                "POST", f"/crm/v3/objects/{object_type}/search", json_body=body
            )
            results.extend(data.get("results") or [])
            after = _next_after(data)
            if not after:
                break
        return results

    def _paginate_get(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        after: str | None = None
        query = dict(params or {})
        query.setdefault("limit", PAGE_LIMIT)
        for _ in range(MAX_PAGES):
            if after is not None:
                query["after"] = after
            data = self._request("GET", path, params=query)
            results.extend(data.get("results") or [])
            after = _next_after(data)
            if not after:
                break
        return results

    def _merge_associations(
        self,
        object_type: str,
        records: list[dict[str, Any]],
        associations: Sequence[str],
    ) -> None:
        ids = [str(row.get("id")) for row in records if row.get("id")]
        if not ids:
            return
        by_id = {str(row["id"]): row for row in records if row.get("id")}
        for assoc in associations:
            mapping: dict[str, list[dict[str, Any]]] = {}
            try:
                for chunk in _chunks(ids, BATCH_LIMIT):
                    data = self._request(
                        "POST",
                        f"/crm/v4/associations/{object_type}/{assoc}/batch/read",
                        json_body={"inputs": [{"id": item} for item in chunk]},
                    )
                    for row in data.get("results") or []:
                        from_id = str(
                            (row.get("from") or {}).get("id") or row.get("fromObjectId") or ""
                        )
                        if not from_id:
                            continue
                        tos = row.get("to") or row.get("toObjectIds") or []
                        mapped: list[dict[str, Any]] = []
                        for target in tos:
                            if isinstance(target, dict):
                                tid = target.get("toObjectId") or target.get("id")
                                if tid is not None:
                                    mapped.append({"id": str(tid), "type": f"{object_type}_to_{assoc}"})
                            else:
                                mapped.append({"id": str(target), "type": f"{object_type}_to_{assoc}"})
                        mapping.setdefault(from_id, []).extend(mapped)
            except ConnectorTransientError:
                logger.debug("associations batch read failed for %s/%s", object_type, assoc)
                continue
            except ConnectorAuthError:
                raise
            except Exception:
                logger.debug(
                    "associations batch read failed for %s/%s", object_type, assoc, exc_info=True
                )
                continue
            for from_id, targets in mapping.items():
                record = by_id.get(from_id)
                if record is None:
                    continue
                assoc_block = record.setdefault("associations", {})
                existing = (assoc_block.get(assoc) or {}).get("results") or []
                seen = {str(item.get("id")) for item in existing if isinstance(item, dict)}
                merged = list(existing)
                for target in targets:
                    if target["id"] not in seen:
                        merged.append(target)
                        seen.add(target["id"])
                assoc_block[assoc] = {"results": merged}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = urljoin(self.base_url, path.lstrip("/"))
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=self.timeout_seconds,
                )
            except requests.Timeout as exc:
                last_error = ConnectorTransientError("HubSpot request timed out")
                logger.debug("hubspot timeout on %s %s", method, path, exc_info=True)
                if attempt + 1 >= MAX_RETRIES:
                    raise last_error from exc
                self._sleep(min(2 ** attempt, self.timeout_seconds))
                continue
            except requests.RequestException as exc:
                last_error = ConnectorTransientError("HubSpot request failed")
                logger.debug("hubspot transport error on %s %s", method, path, exc_info=True)
                if attempt + 1 >= MAX_RETRIES:
                    raise last_error from exc
                self._sleep(min(2 ** attempt, self.timeout_seconds))
                continue

            status = response.status_code
            if status in {401, 403}:
                raise ConnectorAuthError(_safe_hubspot_message(response, default="HubSpot auth failed"))
            if status == 429 or status >= 500:
                retry_after = _retry_after_seconds(response, fallback=2 ** attempt)
                retry_after = min(retry_after, float(self.timeout_seconds))
                last_error = ConnectorTransientError(
                    _safe_hubspot_message(response, default=f"HubSpot HTTP {status}")
                )
                if attempt + 1 >= MAX_RETRIES:
                    raise last_error
                logger.debug("hubspot HTTP %s on %s %s; retrying", status, method, path)
                self._sleep(retry_after)
                continue
            if status >= 400:
                raise ConnectorTransientError(
                    _safe_hubspot_message(response, default=f"HubSpot HTTP {status}")
                )
            if not response.content:
                return {}
            try:
                payload = response.json()
            except ValueError as exc:
                raise ConnectorTransientError("HubSpot returned non-JSON") from exc
            if not isinstance(payload, dict):
                return {"results": payload if isinstance(payload, list) else []}
            return payload
        raise last_error or ConnectorTransientError("HubSpot request failed")


def _chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(values), size):
        yield list(values[i : i + size])


def _next_after(data: dict[str, Any]) -> str | None:
    paging = data.get("paging") or {}
    nxt = paging.get("next") or {}
    after = nxt.get("after")
    return str(after) if after else None


def _retry_after_seconds(response: requests.Response, *, fallback: float) -> float:
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if not raw:
        return max(1.0, float(fallback))
    try:
        return max(1.0, float(raw))
    except ValueError:
        return max(1.0, float(fallback))


def _safe_hubspot_message(response: requests.Response, *, default: str) -> str:
    """Error text for sync_runs. Never include tokens or bodies."""
    try:
        payload = response.json()
    except ValueError:
        return default
    if not isinstance(payload, dict):
        return default
    message = str(payload.get("message") or payload.get("category") or default)
    lowered = message.lower()
    for needle in ("bearer ", "token=", "authorization:"):
        if needle in lowered:
            return default
    return message[:500]
