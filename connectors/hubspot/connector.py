"""HubSpot CRM connector — Private App token, fixtures-testable, no deletes."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from connectors.base import (
    BaseConnector,
    ConnectorSpec,
    FetchResult,
    NormalisedBatch,
    SaveStats,
    WriteResult,
    error_item,
)
from connectors.errors import ConnectorError, ConnectorNotConfigured
from connectors.hubspot.client import (
    COMPANY_PROPERTIES,
    CONTACT_PROPERTIES,
    DEAL_PROPERTIES,
    DEFAULT_TIMEOUT_SECONDS,
    ENGAGEMENT_PROPERTIES,
    HubSpotClient,
)
from connectors.hubspot.normalise import (
    HubSpotBatch,
    HubSpotNormaliseConfig,
    normalise_snapshot,
    parse_hs_datetime,
    parse_hs_datetime_ms,
    product_for_hubspot,
    rates_from_sources,
)
from core.models import (
    AliasType,
    CompanyAlias,
    get_company_by_hubspot_id,
    get_deal_by_source_id,
    upsert_company_alias,
)

logger = logging.getLogger("salesos.connectors.hubspot")

DEFAULT_ENGAGEMENTS = ("calls", "meetings", "notes", "emails", "tasks")


class HubSpotConnector(BaseConnector):
    """Tier-1 HubSpot source. Writes stay gated; ``writes.complete_task`` stays false."""

    name = "hubspot"
    tier = 1
    mode = "api"
    required_env = ("HUBSPOT_ACCESS_TOKEN",)
    write_capabilities = frozenset({"complete_task"})

    def __init__(
        self,
        spec: ConnectorSpec | None = None,
        *,
        client: HubSpotClient | None = None,
        sources_config: dict[str, Any] | None = None,
        now: datetime | None = None,
        **overrides: Any,
    ) -> None:
        super().__init__(spec, **overrides)
        self._client = client
        self._sources_config = sources_config
        self._now = now
        self._snapshot: dict[str, Any] | None = None
        cfg = (spec.config if spec is not None else {}) or {}
        sync = cfg.get("sync") or {}
        self.lookback_days = int(sync.get("lookback_days_on_first_sync") or 365)
        self.include_closed_deals_days = int(sync.get("include_closed_deals_days") or 90)
        self.incremental = bool(sync.get("incremental", True))
        engagements = sync.get("engagements") or list(DEFAULT_ENGAGEMENTS)
        self.engagement_types = tuple(str(item) for item in engagements)

    def connect(self) -> None:
        if self._client is not None:
            return
        token = os.environ.get("HUBSPOT_ACCESS_TOKEN", "").strip()
        if not token:
            raise ConnectorNotConfigured(env_vars=["HUBSPOT_ACCESS_TOKEN"])
        timeout = self.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        self._client = HubSpotClient(token, timeout_seconds=int(timeout))

    def authenticate(self) -> None:
        client = self._require_client()
        client.get_owners()

    def fetch(self, cursor: dict[str, Any] | None) -> FetchResult:
        client = self._require_client()
        now = self._now or datetime.now(timezone.utc)
        errors: list[dict[str, Any]] = []
        since_ms = self._since_ms(cursor, now)
        logger.info(
            "hubspot fetch starting incremental=%s since_ms=%s",
            bool(cursor),
            since_ms,
        )

        pipelines = client.get_pipelines()
        owners = client.get_owners()

        deals = client.search_objects(
            "deals",
            since_ms=since_ms,
            properties=DEAL_PROPERTIES,
            associations=["companies", "contacts"],
        )
        engagements: dict[str, list[dict[str, Any]]] = {}
        for kind in self.engagement_types:
            try:
                engagements[kind] = client.search_objects(
                    kind,
                    since_ms=since_ms,
                    properties=ENGAGEMENT_PROPERTIES.get(kind, ["hs_lastmodifieddate"]),
                    associations=["deals"],
                )
            except Exception as exc:
                logger.debug("hubspot engagement fetch failed for %s", kind, exc_info=True)
                errors.append(error_item(str(exc), kind))
                engagements[kind] = []

        deal_ids = {str(row["id"]) for row in deals if row.get("id")}
        for rows in engagements.values():
            for row in rows:
                for assoc in _assoc_ids(row, "deals"):
                    deal_ids.add(assoc)
        missing = [did for did in deal_ids if did not in {str(d.get("id")) for d in deals}]
        if missing:
            extra = client.read_objects(
                "deals",
                missing,
                properties=DEAL_PROPERTIES,
                associations=["companies", "contacts"],
            )
            deals.extend(extra)

        company_ids: list[str] = []
        contact_ids: list[str] = []
        for deal in deals:
            company_ids.extend(_assoc_ids(deal, "companies"))
            contact_ids.extend(_assoc_ids(deal, "contacts"))
        companies = client.read_objects(
            "companies",
            company_ids,
            properties=COMPANY_PROPERTIES,
        )
        contacts = client.read_objects(
            "contacts",
            contact_ids,
            properties=CONTACT_PROPERTIES,
            associations=["companies"],
        )

        next_cursor = _next_cursor(cursor, deals, companies, contacts, engagements)
        snapshot = {
            "pipelines": pipelines,
            "owners": owners,
            "deals": deals,
            "companies": companies,
            "contacts": contacts,
            "engagements": engagements,
            "cursor": next_cursor,
            "errors": errors,
        }
        self._snapshot = snapshot
        records = list(deals) + list(companies) + list(contacts)
        for rows in engagements.values():
            records.extend(rows)
        logger.info(
            "hubspot fetched deals=%s companies=%s contacts=%s engagements=%s",
            len(deals),
            len(companies),
            len(contacts),
            sum(len(v) for v in engagements.values()),
        )
        return FetchResult(records=records, cursor=next_cursor, errors=errors)

    def normalise(self, raw: Any) -> NormalisedBatch:
        snapshot = self._snapshot
        if snapshot is None and isinstance(raw, dict) and "deals" in raw:
            snapshot = raw
        if snapshot is None and isinstance(raw, list) and raw and isinstance(raw[0], dict) and "deals" in raw[0]:
            snapshot = raw[0]
        if snapshot is None:
            return NormalisedBatch(errors=[error_item("hubspot normalise missing snapshot")])
        sources = self._load_sources()
        products = sources.get("products") if sources else None
        currency = sources.get("currency") if sources else None
        pipeline_ids = _pipeline_id_filter()
        cfg = HubSpotNormaliseConfig(
            product=product_for_hubspot(products),
            rates_to_gbp=rates_from_sources(currency),
            include_closed_deals_days=self.include_closed_deals_days,
            now=self._now,
            user_timezone=os.environ.get("SALESOS_TIMEZONE") or "Europe/London",
            pipeline_ids=pipeline_ids,
        )
        return normalise_snapshot(snapshot, config=cfg)

    def save(
        self,
        batch: NormalisedBatch,
        conn: Any,
        sync_run_id: str,
    ) -> SaveStats:
        from core.ingestion.persist import save_normalised_batch

        hub = _as_hubspot_batch(batch)
        stats = SaveStats()

        def merge(other: SaveStats) -> None:
            stats.created += other.created
            stats.changed += other.changed
            stats.unchanged += other.unchanged
            stats.errors.extend(other.errors)

        merge(
            save_normalised_batch(
                NormalisedBatch(companies=list(hub.companies)), conn, sync_run_id
            )
        )
        company_map = _company_id_map(conn, hub)
        contacts = _attach_company_id(hub.contacts, hub.contact_company_hs, company_map, "hubspot_id")
        deals = _attach_deal_company(conn, hub.deals, hub.deal_company_hs, company_map)
        merge(
            save_normalised_batch(
                NormalisedBatch(contacts=contacts, deals=deals), conn, sync_run_id
            )
        )
        linked = _link_after_deals(
            conn,
            HubSpotBatch(
                deals=deals,
                meetings=list(hub.meetings),
                evidence=list(hub.evidence),
                actions=list(hub.actions),
                evidence_deal_hs=hub.evidence_deal_hs,
                action_deal_hs=hub.action_deal_hs,
                meeting_deal_hs=hub.meeting_deal_hs,
                company_domains=hub.company_domains,
            ),
        )
        merge(
            save_normalised_batch(
                NormalisedBatch(
                    meetings=linked.meetings,
                    evidence=linked.evidence,
                    actions=linked.actions,
                ),
                conn,
                sync_run_id,
            )
        )
        _upsert_domain_aliases(conn, hub)
        return stats

    def write(self, capability: str, payload: dict[str, Any], *, audit_id: str) -> WriteResult:
        if not audit_id:
            raise ConnectorError("write requires an approved audit_id")
        if capability not in self.write_capabilities:
            raise ConnectorError(
                f"unsupported write capability {capability!r} on {self.name}"
            )
        writes = (self.spec.config or {}).get("writes") or {}
        if capability == "complete_task" and not writes.get("complete_task"):
            raise ConnectorError("writes.complete_task is disabled in sources.yaml")
        # TODO(salesos-core-engineer): SOS-06 — assert core.audit.is_approved(audit_id)
        if capability != "complete_task":
            raise ConnectorError(f"write capability {capability!r} is not implemented")
        task_id = str(payload.get("task_id") or payload.get("id") or "").strip()
        if not task_id:
            raise ConnectorError("complete_task requires payload.task_id")
        self.connect()
        self._require_client().complete_task(task_id)
        return WriteResult(ok=True, message="task completed", payload={"id": task_id})

    def _require_client(self) -> HubSpotClient:
        if self._client is None:
            raise ConnectorNotConfigured(env_vars=list(self.required_env))
        return self._client

    def _since_ms(self, cursor: dict[str, Any] | None, now: datetime) -> int | None:
        if cursor and self.incremental:
            watermark = None
            watermarks = cursor.get("watermarks") if isinstance(cursor.get("watermarks"), dict) else {}
            watermark = watermarks.get("deals") or cursor.get("hs_lastmodifieddate")
            ms = parse_hs_datetime_ms(watermark) if watermark else None
            if ms is not None:
                return ms
        lookback = now - timedelta(days=self.lookback_days)
        return int(lookback.timestamp() * 1000)

    def _load_sources(self) -> dict[str, Any]:
        if self._sources_config is not None:
            return self._sources_config
        try:
            from config.loaders import load_sources

            loaded = load_sources()
            return loaded.model_dump()
        except Exception:
            logger.debug("could not load sources.yaml for hubspot", exc_info=True)
            return {}


def _as_hubspot_batch(batch: NormalisedBatch) -> HubSpotBatch:
    if isinstance(batch, HubSpotBatch):
        return batch
    return HubSpotBatch(
        deals=list(batch.deals),
        companies=list(batch.companies),
        contacts=list(batch.contacts),
        meetings=list(batch.meetings),
        evidence=list(batch.evidence),
        actions=list(batch.actions),
        prospecting_items=list(batch.prospecting_items),
        errors=list(batch.errors),
    )


def _company_id_map(conn: Any, hub: HubSpotBatch) -> dict[str, str]:
    needed: set[str] = set()
    for item in hub.companies:
        hs_id = _get(item, "hubspot_id")
        if hs_id:
            needed.add(str(hs_id))
    needed.update(hub.deal_company_hs.values())
    needed.update(hub.contact_company_hs.values())
    mapping: dict[str, str] = {}
    for hs_id in needed:
        found = get_company_by_hubspot_id(conn, hs_id)
        if found is not None:
            mapping[hs_id] = found.id
    return mapping


def _attach_company_id(
    items: list[Any],
    hs_map: dict[str, str],
    company_map: dict[str, str],
    id_field: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        data = _as_dict(item)
        key = str(data.get(id_field) or "")
        company_hs = hs_map.get(key)
        if company_hs and company_hs in company_map:
            data["company_id"] = company_map[company_hs]
        out.append(data)
    return out


def _attach_deal_company(
    conn: Any,
    deals: list[Any],
    deal_company_hs: dict[str, str],
    company_map: dict[str, str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in deals:
        data = _as_dict(item)
        ext_id = str(data.get("external_id") or "")
        company_hs = deal_company_hs.get(ext_id)
        if company_hs and company_hs in company_map:
            data["company_id"] = company_map[company_hs]
            if not data.get("company_name"):
                found = get_company_by_hubspot_id(conn, company_hs)
                if found is not None:
                    data["company_name"] = found.name
        out.append(data)
    return out


def _link_after_deals(conn: Any, batch: HubSpotBatch) -> HubSpotBatch:
    deal_map: dict[str, str] = {}
    needed = set(batch.evidence_deal_hs.values())
    needed.update(batch.action_deal_hs.values())
    needed.update(batch.meeting_deal_hs.values())
    for item in batch.deals:
        ext_id = _get(item, "external_id")
        if ext_id:
            needed.add(str(ext_id))
    company_by_deal: dict[str, str] = {}
    for ext_id in needed:
        found = get_deal_by_source_id(conn, "HUBSPOT", ext_id)
        if found is not None:
            deal_map[ext_id] = found.id
            if found.company_id:
                company_by_deal[ext_id] = found.company_id

    evidence = []
    for item in batch.evidence:
        data = _as_dict(item)
        source_id = str(data.get("source_id") or "")
        deal_hs = batch.evidence_deal_hs.get(source_id)
        if deal_hs and deal_hs in deal_map:
            data["deal_id"] = deal_map[deal_hs]
            if deal_hs in company_by_deal:
                data["company_id"] = company_by_deal[deal_hs]
        evidence.append(data)

    actions = []
    for item in batch.actions:
        data = _as_dict(item)
        source_id = str(data.get("source_id") or "")
        deal_hs = batch.action_deal_hs.get(source_id)
        if deal_hs and deal_hs in deal_map:
            data["deal_id"] = deal_map[deal_hs]
            if deal_hs in company_by_deal:
                data["company_id"] = company_by_deal[deal_hs]
        actions.append(data)

    meetings = []
    for item in batch.meetings:
        data = _as_dict(item)
        ext_id = str(data.get("external_id") or "")
        deal_hs = batch.meeting_deal_hs.get(ext_id)
        if deal_hs and deal_hs in deal_map:
            data["deal_id"] = deal_map[deal_hs]
            if deal_hs in company_by_deal:
                data["company_id"] = company_by_deal[deal_hs]
        meetings.append(data)

    return HubSpotBatch(
        companies=list(batch.companies),
        contacts=list(batch.contacts),
        deals=list(batch.deals),
        meetings=meetings,
        evidence=evidence,
        actions=actions,
        errors=list(batch.errors),
        deal_company_hs=batch.deal_company_hs,
        contact_company_hs=batch.contact_company_hs,
        evidence_deal_hs=batch.evidence_deal_hs,
        action_deal_hs=batch.action_deal_hs,
        meeting_deal_hs=batch.meeting_deal_hs,
        company_domains=batch.company_domains,
    )


def _upsert_domain_aliases(conn: Any, batch: NormalisedBatch) -> None:
    hub = batch if isinstance(batch, HubSpotBatch) else None
    domains = hub.company_domains if hub else {}
    if not domains:
        for item in batch.companies:
            hs_id = _get(item, "hubspot_id")
            domain = _get(item, "primary_domain")
            if hs_id and domain:
                domains[str(hs_id)] = str(domain)
    for hs_id, domain in domains.items():
        company = get_company_by_hubspot_id(conn, hs_id)
        if company is None or not domain:
            continue
        upsert_company_alias(
            conn,
            CompanyAlias(
                company_id=company.id,
                alias_type=AliasType.DOMAIN,
                value=str(domain).strip().lower(),
                source="HUBSPOT",
            ),
        )


def _get(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(item)


def _assoc_ids(raw: dict[str, Any], object_type: str) -> list[str]:
    associations = raw.get("associations") or {}
    block = associations.get(object_type) or {}
    results = block.get("results") if isinstance(block, dict) else block
    ids: list[str] = []
    for item in results or []:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
    return ids


def _next_cursor(
    previous: dict[str, Any] | None,
    deals: list[dict[str, Any]],
    companies: list[dict[str, Any]],
    contacts: list[dict[str, Any]],
    engagements: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    watermarks: dict[str, str] = {}
    if isinstance(previous, dict) and isinstance(previous.get("watermarks"), dict):
        watermarks.update({str(k): str(v) for k, v in previous["watermarks"].items()})

    def bump(key: str, records: list[dict[str, Any]]) -> None:
        latest = _latest_modified(records)
        if latest and (key not in watermarks or latest > watermarks[key]):
            watermarks[key] = latest

    bump("deals", deals)
    bump("companies", companies)
    bump("contacts", contacts)
    for kind, rows in engagements.items():
        bump(kind, rows)
    values = [v for v in watermarks.values() if v]
    global_max = max(values) if values else None
    if global_max is None and isinstance(previous, dict):
        global_max = previous.get("hs_lastmodifieddate")
    cursor: dict[str, Any] = {"watermarks": watermarks}
    if global_max:
        cursor["hs_lastmodifieddate"] = global_max
    return cursor


def _latest_modified(records: list[dict[str, Any]]) -> str | None:
    latest: str | None = None
    for row in records:
        props = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        iso = parse_hs_datetime(props.get("hs_lastmodifieddate") or row.get("updatedAt"))
        if iso and (latest is None or iso > latest):
            latest = iso
    return latest


def _pipeline_id_filter() -> frozenset[str] | None:
    raw = os.environ.get("HUBSPOT_PIPELINE_IDS", "").strip()
    if not raw:
        return None
    values = {part.strip() for part in raw.split(",") if part.strip()}
    return frozenset(values) or None
