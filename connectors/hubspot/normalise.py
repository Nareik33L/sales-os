"""HubSpot CRM records → NormalisedBatch (Deal / Company / Contact / Evidence / Action)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from connectors.base import NormalisedBatch, error_item
from core.models.schemas import (
    ActionStatus,
    ActionType,
    DealSource,
    EvidenceDirection,
    EvidenceType,
    ExtractionStatus,
    MeetingSource,
    MeetingStatus,
)

SOURCE = "hubspot"
DEAL_SOURCE = DealSource.HUBSPOT
ACTIVITY_RELIABILITY = 0.8
OPEN_TASK_STATUSES = frozenset({"NOT_STARTED", "WAITING", "DEFERRED", "IN_PROGRESS"})
COMPLETED_TASK_STATUSES = frozenset({"COMPLETED"})


@dataclass
class HubSpotBatch(NormalisedBatch):
    """Normalised batch plus HubSpot id maps used to resolve internal FKs on save."""

    deal_company_hs: dict[str, str] = field(default_factory=dict)
    contact_company_hs: dict[str, str] = field(default_factory=dict)
    evidence_deal_hs: dict[str, str] = field(default_factory=dict)
    action_deal_hs: dict[str, str] = field(default_factory=dict)
    meeting_deal_hs: dict[str, str] = field(default_factory=dict)
    company_domains: dict[str, str] = field(default_factory=dict)


@dataclass
class HubSpotNormaliseConfig:
    product: str = "XODO_SIGN"
    rates_to_gbp: dict[str, float] = field(default_factory=lambda: {"GBP": 1.0})
    include_closed_deals_days: int = 90
    now: datetime | None = None
    user_timezone: str = "Europe/London"
    pipeline_ids: frozenset[str] | None = None


def product_for_hubspot(products: Mapping[str, Any] | None) -> str:
    if not products:
        return "XODO_SIGN"
    for key, entry in products.items():
        source = entry.get("source_of_truth") if isinstance(entry, dict) else getattr(
            entry, "source_of_truth", None
        )
        if str(source) == "HUBSPOT":
            return str(key)
    return "XODO_SIGN"


def rates_from_sources(currency: Mapping[str, Any] | None) -> dict[str, float]:
    if not currency:
        return {"GBP": 1.0}
    rates = currency.get("rates_to_gbp") if isinstance(currency, dict) else getattr(
        currency, "rates_to_gbp", None
    )
    if not rates:
        return {"GBP": 1.0}
    return {str(k).upper(): float(v) for k, v in dict(rates).items()}


def normalise_snapshot(
    snapshot: Mapping[str, Any],
    *,
    config: HubSpotNormaliseConfig | None = None,
) -> HubSpotBatch:
    """Turn a fetched HubSpot snapshot into internal rows. Never raises on a bad record."""
    cfg = config or HubSpotNormaliseConfig()
    now = cfg.now or datetime.now(timezone.utc)
    batch = HubSpotBatch()
    stages = _stage_index(snapshot.get("pipelines") or [])
    owners = _owner_index(snapshot.get("owners") or [])
    closed_cutoff = (now - timedelta(days=cfg.include_closed_deals_days)).date()

    company_names: dict[str, str] = {}
    for raw in snapshot.get("companies") or []:
        try:
            company = _normalise_company(raw)
        except Exception as exc:
            batch.errors.append(error_item(str(exc), _record_id(raw)))
            continue
        if company is None:
            batch.errors.append(error_item("company missing name", _record_id(raw)))
            continue
        hs_id = str(company["hubspot_id"])
        company_names[hs_id] = str(company["name"])
        if company.get("primary_domain"):
            batch.company_domains[hs_id] = str(company["primary_domain"])
        batch.companies.append(company)

    for raw in snapshot.get("contacts") or []:
        try:
            contact, company_hs = _normalise_contact(raw)
        except Exception as exc:
            batch.errors.append(error_item(str(exc), _record_id(raw)))
            continue
        if contact is None:
            batch.errors.append(error_item("contact missing identity", _record_id(raw)))
            continue
        if company_hs:
            batch.contact_company_hs[str(contact["hubspot_id"])] = company_hs
        batch.contacts.append(contact)

    kept_deal_ids: set[str] = set()
    for raw in snapshot.get("deals") or []:
        try:
            deal, company_hs = _normalise_deal(
                raw,
                stages=stages,
                owners=owners,
                company_names=company_names,
                config=cfg,
                closed_cutoff=closed_cutoff,
            )
        except Exception as ext:
            batch.errors.append(error_item(str(ext), _record_id(raw)))
            continue
        if deal is None:
            continue
        ext_id = str(deal["external_id"])
        kept_deal_ids.add(ext_id)
        if company_hs:
            batch.deal_company_hs[ext_id] = company_hs
        batch.deals.append(deal)

    engagement_times: dict[str, list[str]] = {}
    engagements = snapshot.get("engagements") or {}
    for kind, rows in engagements.items():
        for raw in rows or []:
            try:
                evidence, action, meeting, deal_hs, occurred = _normalise_engagement(
                    kind, raw, now=now
                )
            except Exception as exc:
                batch.errors.append(error_item(str(exc), _record_id(raw)))
                continue
            if evidence is None:
                batch.errors.append(error_item("engagement missing timestamp", _record_id(raw)))
                continue
            source_id = str(evidence["source_id"])
            if deal_hs:
                batch.evidence_deal_hs[source_id] = deal_hs
                if _counts_as_activity(kind, raw, now=now) and occurred:
                    engagement_times.setdefault(deal_hs, []).append(occurred)
            batch.evidence.append(evidence)
            if action is not None:
                if deal_hs:
                    batch.action_deal_hs[str(action["source_id"])] = deal_hs
                batch.actions.append(action)
            if meeting is not None:
                if deal_hs:
                    batch.meeting_deal_hs[str(meeting.get("external_id"))] = deal_hs
                batch.meetings.append(meeting)

    for deal in batch.deals:
        ext_id = str(deal["external_id"])
        times = engagement_times.get(ext_id) or []
        if times:
            deal["last_activity_at"] = max(times)
        # Never fall back to notes_last_updated.

    # Drop association maps for skipped (old closed) deals — FKs would not resolve.
    batch.deal_company_hs = {
        k: v for k, v in batch.deal_company_hs.items() if k in kept_deal_ids
    }
    return batch


def _stage_index(pipelines: Sequence[Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for pipe in pipelines:
        if not isinstance(pipe, dict):
            continue
        for stage in pipe.get("stages") or []:
            if not isinstance(stage, dict) or not stage.get("id"):
                continue
            meta = stage.get("metadata") or {}
            is_closed = _truthy(meta.get("isClosed"))
            try:
                probability = float(meta.get("probability") or 0)
            except (TypeError, ValueError):
                probability = 0.0
            index[str(stage["id"])] = {
                "label": stage.get("label") or stage["id"],
                "is_closed": is_closed,
                "is_won": is_closed and probability >= 1.0,
                "pipeline_id": str(pipe.get("id") or ""),
            }
    return index


def _owner_index(owners: Sequence[Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for owner in owners:
        if not isinstance(owner, dict) or not owner.get("id"):
            continue
        first = str(owner.get("firstName") or owner.get("first_name") or "").strip()
        last = str(owner.get("lastName") or owner.get("last_name") or "").strip()
        name = " ".join(part for part in (first, last) if part)
        if not name:
            name = str(owner.get("email") or owner["id"])
        index[str(owner["id"])] = name
    return index


def _normalise_company(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    props = _props(raw)
    hs_id = str(raw.get("id") or "")
    name = str(props.get("name") or "").strip()
    if not hs_id or not name:
        return None
    domain = str(props.get("domain") or "").strip().lower() or None
    industry = str(props.get("industry") or "").strip() or None
    return {
        "name": name,
        "hubspot_id": hs_id,
        "primary_domain": domain,
        "industry": industry,
    }


def _normalise_contact(raw: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    props = _props(raw)
    hs_id = str(raw.get("id") or "")
    first = str(props.get("firstname") or "").strip() or None
    last = str(props.get("lastname") or "").strip() or None
    email = str(props.get("email") or "").strip().lower() or None
    full = " ".join(part for part in (first, last) if part).strip()
    if not full:
        full = email or ""
    if not hs_id or not full:
        return None, None
    company_hs = _first_associated_id(raw, "companies")
    return (
        {
            "hubspot_id": hs_id,
            "first_name": first,
            "last_name": last,
            "full_name": full,
            "email": email,
            "phone": str(props.get("phone") or "").strip() or None,
            "title": str(props.get("jobtitle") or "").strip() or None,
        },
        company_hs,
    )


def _normalise_deal(
    raw: Mapping[str, Any],
    *,
    stages: Mapping[str, Mapping[str, Any]],
    owners: Mapping[str, str],
    company_names: Mapping[str, str],
    config: HubSpotNormaliseConfig,
    closed_cutoff,
) -> tuple[dict[str, Any] | None, str | None]:
    props = _props(raw)
    ext_id = str(raw.get("id") or "")
    name = str(props.get("dealname") or "").strip()
    if not ext_id or not name:
        raise ValueError("deal missing id or dealname")
    if config.pipeline_ids:
        pipeline = str(props.get("pipeline") or "")
        if pipeline and pipeline not in config.pipeline_ids:
            return None, None

    stage_key = str(props.get("dealstage") or "") or None
    stage_meta = stages.get(stage_key or "") or {}
    is_closed = bool(stage_meta.get("is_closed"))
    is_won = bool(stage_meta.get("is_won")) if is_closed else None
    close_date = parse_hs_date(props.get("closedate"), tz_name=config.user_timezone)
    if is_closed and close_date:
        try:
            close = datetime.strptime(close_date, "%Y-%m-%d").date()
        except ValueError:
            close = None
        if close is not None and close < closed_cutoff:
            return None, None

    currency = str(props.get("deal_currency_code") or "GBP").strip().upper() or "GBP"
    amount = _parse_float(props.get("amount"))
    rate = config.rates_to_gbp.get(currency, 1.0)
    deal_value_gbp = None if amount is None else round(amount * float(rate), 2)
    company_hs = _first_associated_id(raw, "companies")
    owner_id = str(props.get("hubspot_owner_id") or "")
    compact = {
        "id": ext_id,
        "properties": {
            key: props.get(key)
            for key in (
                "dealname",
                "amount",
                "deal_currency_code",
                "dealstage",
                "pipeline",
                "closedate",
                "hubspot_owner_id",
                "hs_lastmodifieddate",
                "notes_last_updated",
            )
        },
        "associations": {
            "companies": [_assoc_ids(raw, "companies")],
            "contacts": [_assoc_ids(raw, "contacts")],
        },
    }
    deal = {
        "external_id": ext_id,
        "source": DEAL_SOURCE,
        "product": config.product,
        "name": name,
        "company_name": company_names.get(company_hs or "") if company_hs else None,
        "deal_value": amount,
        "currency": currency,
        "deal_value_gbp": deal_value_gbp,
        "stage": stage_meta.get("label") or stage_key,
        "stage_key": stage_key,
        "is_closed": is_closed,
        "is_won": is_won,
        "close_date": close_date,
        "owner": owners.get(owner_id) or (owner_id or None),
        "source_created_at": parse_hs_datetime(props.get("createdate")),
        "source_updated_at": parse_hs_datetime(props.get("hs_lastmodifieddate")),
        "source_record_json": json.dumps(compact, default=str),
    }
    return deal, company_hs


def _normalise_engagement(
    kind: str,
    raw: Mapping[str, Any],
    *,
    now: datetime,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, str | None, str | None]:
    props = _props(raw)
    hs_id = str(raw.get("id") or "")
    if not hs_id:
        return None, None, None, None, None
    occurred = parse_hs_datetime(
        props.get("hs_timestamp")
        or props.get("hs_meeting_start_time")
        or props.get("hs_task_completion_date")
        or raw.get("createdAt")
    )
    if not occurred:
        return None, None, None, None, None
    deal_hs = _first_associated_id(raw, "deals")
    title, content, direction = _engagement_text(kind, props)
    task_status = str(props.get("hs_task_status") or "").upper() or None
    end_at = parse_hs_datetime(props.get("hs_meeting_end_time"))
    meta = {
        "engagement_type": kind,
        "hubspot_id": hs_id,
        "source_reliability": ACTIVITY_RELIABILITY,
        "task_status": task_status,
        "end_at": end_at,
    }
    has_text = bool(content)
    unstructured = kind in {"notes", "emails"} or (kind in {"calls", "meetings"} and has_text)
    evidence = {
        "type": EvidenceType.HUBSPOT_ACTIVITY,
        "source": SOURCE,
        "source_id": f"{kind}:{hs_id}",
        "occurred_at": occurred,
        "direction": direction,
        "title": title,
        "content": content,
        "metadata_json": json.dumps({k: v for k, v in meta.items() if v is not None}),
        "extraction_status": (
            ExtractionStatus.PENDING if unstructured and has_text else ExtractionStatus.NOT_APPLICABLE
        ),
        "match_confidence": ACTIVITY_RELIABILITY,
        "match_method": "hubspot_association",
    }
    action = None
    if kind == "tasks":
        action = {
            "title": title or f"HubSpot task {hs_id}",
            "description": content,
            "type": ActionType.HUBSPOT_TASK,
            "status": (
                ActionStatus.COMPLETED
                if task_status in COMPLETED_TASK_STATUSES
                else ActionStatus.OPEN
            ),
            "source": SOURCE,
            "source_id": hs_id,
            "due_date": parse_hs_date(props.get("hs_timestamp")),
            "completed_at": parse_hs_datetime(props.get("hs_task_completion_date")),
        }
    meeting = None
    if kind == "meetings":
        start_at = parse_hs_datetime(props.get("hs_meeting_start_time")) or occurred
        outcome = str(props.get("hs_meeting_outcome") or "").upper()
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        end = end_at or start_at
        if outcome in {"CANCELED", "CANCELLED"}:
            status = MeetingStatus.CANCELLED
        elif end and end <= now_iso:
            status = MeetingStatus.HELD
        else:
            status = MeetingStatus.SCHEDULED
        meeting = {
            "source": MeetingSource.HUBSPOT,
            "external_id": hs_id,
            "title": title,
            "start_at": start_at,
            "end_at": end_at,
            "status": status,
        }
    return evidence, action, meeting, deal_hs, occurred


def _engagement_text(
    kind: str, props: Mapping[str, Any]
) -> tuple[str | None, str | None, EvidenceDirection]:
    if kind == "calls":
        title = str(props.get("hs_call_title") or "").strip() or "Call"
        content = str(props.get("hs_call_body") or "").strip() or None
        return title, content, _direction(props.get("hs_call_direction"))
    if kind == "meetings":
        title = str(props.get("hs_meeting_title") or "").strip() or "Meeting"
        content = str(props.get("hs_meeting_body") or "").strip() or None
        return title, content, EvidenceDirection.UNKNOWN
    if kind == "notes":
        content = str(props.get("hs_note_body") or "").strip() or None
        return "Note", content, EvidenceDirection.UNKNOWN
    if kind == "emails":
        title = str(props.get("hs_email_subject") or "").strip() or "Email"
        content = str(props.get("hs_email_text") or "").strip() or None
        return title, content, _direction(props.get("hs_email_direction"))
    if kind == "tasks":
        title = str(props.get("hs_task_subject") or "").strip() or "Task"
        content = str(props.get("hs_task_body") or "").strip() or None
        return title, content, EvidenceDirection.UNKNOWN
    return kind, None, EvidenceDirection.UNKNOWN


def _counts_as_activity(kind: str, raw: Mapping[str, Any], *, now: datetime) -> bool:
    """docs/03 §2.3: calls, meetings (past), notes, emails, completed tasks. Not open tasks."""
    props = _props(raw)
    if kind == "tasks":
        return str(props.get("hs_task_status") or "").upper() in COMPLETED_TASK_STATUSES
    if kind == "meetings":
        end = parse_hs_datetime(props.get("hs_meeting_end_time")) or parse_hs_datetime(
            props.get("hs_meeting_start_time")
        )
        if not end:
            return False
        return end <= now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return kind in {"calls", "notes", "emails"}


def _direction(value: Any) -> EvidenceDirection:
    text = str(value or "").strip().upper()
    if text in {"INBOUND", "INCOMING"}:
        return EvidenceDirection.INBOUND
    if text in {"OUTBOUND", "OUTGOING"}:
        return EvidenceDirection.OUTBOUND
    if text in {"INTERNAL", "FORWARDED"}:
        return EvidenceDirection.INTERNAL
    return EvidenceDirection.UNKNOWN


def _props(raw: Mapping[str, Any]) -> dict[str, Any]:
    props = raw.get("properties")
    return dict(props) if isinstance(props, dict) else {}


def _first_associated_id(raw: Mapping[str, Any], object_type: str) -> str | None:
    ids = _assoc_ids(raw, object_type)
    return ids[0] if ids else None


def _assoc_ids(raw: Mapping[str, Any], object_type: str) -> list[str]:
    associations = raw.get("associations") or {}
    block = associations.get(object_type) or {}
    results = block.get("results") if isinstance(block, dict) else block
    ids: list[str] = []
    for item in results or []:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
        elif isinstance(item, str):
            ids.append(item)
    return ids


def _record_id(raw: Any) -> str | None:
    if isinstance(raw, dict) and raw.get("id"):
        return str(raw["id"])
    return None


def _parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def parse_hs_datetime(value: Any) -> str | None:
    """HubSpot datetime (ISO or epoch ms) → ``YYYY-MM-DDTHH:MM:SSZ``."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        ms = int(value)
        if ms > 10_000_000_000:
            seconds = ms / 1000.0
        else:
            seconds = float(ms)
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_hs_date(value: Any, *, tz_name: str | None = None) -> str | None:
    """HubSpot date → ``YYYY-MM-DD`` in the user's timezone when possible."""
    iso = parse_hs_datetime(value)
    if iso:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        tz = tz_name or os.environ.get("SALESOS_TIMEZONE") or "Europe/London"
        try:
            local = dt.astimezone(ZoneInfo(tz))
        except Exception:
            local = dt
        return local.date().isoformat()
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def parse_hs_datetime_ms(value: Any) -> int | None:
    iso = parse_hs_datetime(value)
    if not iso:
        return None
    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)
