"""Persist a `NormalisedBatch` through `core.models` repositories.

Connectors must not embed SQL. Per-record failures are isolated with
savepoints so one bad row becomes `SaveStats.errors` (PARTIAL), not a
run-level exception.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from connectors.base import NormalisedBatch, SaveStats, error_item
from core.models import (
    Action,
    Company,
    Contact,
    Deal,
    Evidence,
    Meeting,
    ProspectingItem,
    get_action,
    get_action_by_source_id,
    get_company,
    get_company_by_hubspot_id,
    get_contact,
    get_contact_by_email,
    get_contact_by_hubspot_id,
    get_evidence,
    get_evidence_by_source_id,
    get_meeting,
    get_meeting_by_source_id,
    get_prospecting_item,
    get_prospecting_item_by_row_key,
    upsert_action,
    upsert_company,
    upsert_contact,
    upsert_deal,
    upsert_evidence,
    upsert_meeting,
    upsert_prospecting_item,
)

T = TypeVar("T", bound=BaseModel)

_TIMESTAMP_FIELDS = frozenset(
    {"id", "created_at", "updated_at", "first_seen_at", "last_seen_at"}
)


def save_normalised_batch(
    batch: NormalisedBatch,
    conn: sqlite3.Connection,
    sync_run_id: str,
) -> SaveStats:
    """Upsert every entity in `batch`. Never deletes. Does not commit."""
    stats = SaveStats()
    if not conn.in_transaction:
        conn.execute("BEGIN")
    sp = 0

    def run(item: Any, handler: Callable[[Any], str]) -> None:
        nonlocal sp
        sp += 1
        ref = _record_ref(item)
        try:
            kind = _with_savepoint(conn, sp, lambda: handler(item))
        except Exception as exc:
            stats.errors.append(error_item(_safe_message(exc), ref))
            return
        _tally(stats, kind)

    for item in batch.companies:
        run(item, lambda raw: _save_company(conn, raw))
    for item in batch.contacts:
        run(item, lambda raw: _save_contact(conn, raw))
    for item in batch.deals:
        run(item, lambda raw: _save_deal(conn, raw, sync_run_id))
    for item in batch.meetings:
        run(item, lambda raw: _save_meeting(conn, raw))
    for item in batch.evidence:
        run(item, lambda raw: _save_evidence(conn, raw))
    for item in batch.actions:
        run(item, lambda raw: _save_action(conn, raw))
    for item in batch.prospecting_items:
        run(item, lambda raw: _save_prospecting(conn, raw))
    return stats


def _with_savepoint(conn: sqlite3.Connection, index: int, fn: Callable[[], str]) -> str:
    name = f"sp_{index}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        kind = fn()
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {name}")
    return kind


def _tally(stats: SaveStats, kind: str) -> None:
    if kind == "created":
        stats.created += 1
    elif kind == "changed":
        stats.changed += 1
    else:
        stats.unchanged += 1


def _save_company(conn: sqlite3.Connection, raw: Any) -> str:
    company = _coerce(raw, Company)
    existing = _existing_company(conn, company)
    saved = upsert_company(conn, company)
    return _classify(existing, saved)


def _save_contact(conn: sqlite3.Connection, raw: Any) -> str:
    contact = _coerce(raw, Contact)
    existing = _existing_contact(conn, contact)
    saved = upsert_contact(conn, contact)
    return _classify(existing, saved)


def _save_deal(conn: sqlite3.Connection, raw: Any, sync_run_id: str) -> str:
    deal = _coerce(raw, Deal)
    result = upsert_deal(conn, deal, sync_run_id=sync_run_id)
    if result.created:
        return "created"
    if result.diff:
        return "changed"
    return "unchanged"


def _save_meeting(conn: sqlite3.Connection, raw: Any) -> str:
    meeting = _coerce(raw, Meeting)
    existing = _existing_meeting(conn, meeting)
    saved = upsert_meeting(conn, meeting)
    return _classify(existing, saved)


def _save_evidence(conn: sqlite3.Connection, raw: Any) -> str:
    evidence = _coerce(raw, Evidence)
    existing = _existing_evidence(conn, evidence)
    saved = upsert_evidence(conn, evidence)
    return _classify(existing, saved)


def _save_action(conn: sqlite3.Connection, raw: Any) -> str:
    action = _coerce(raw, Action)
    existing = _existing_action(conn, action)
    saved = upsert_action(conn, action)
    return _classify(existing, saved)


def _save_prospecting(conn: sqlite3.Connection, raw: Any) -> str:
    item = _coerce(raw, ProspectingItem)
    existing = _existing_prospecting(conn, item)
    saved = upsert_prospecting_item(conn, item)
    return _classify(existing, saved)


def _existing_company(conn: sqlite3.Connection, company: Company) -> Company | None:
    if "id" in company.model_fields_set:
        found = get_company(conn, company.id)
        if found is not None:
            return found
    if company.hubspot_id:
        return get_company_by_hubspot_id(conn, company.hubspot_id)
    return None


def _existing_contact(conn: sqlite3.Connection, contact: Contact) -> Contact | None:
    if "id" in contact.model_fields_set:
        found = get_contact(conn, contact.id)
        if found is not None:
            return found
    if contact.hubspot_id:
        found = get_contact_by_hubspot_id(conn, contact.hubspot_id)
        if found is not None:
            return found
    if contact.email:
        return get_contact_by_email(conn, contact.email)
    return None


def _existing_meeting(conn: sqlite3.Connection, meeting: Meeting) -> Meeting | None:
    if "id" in meeting.model_fields_set:
        found = get_meeting(conn, meeting.id)
        if found is not None:
            return found
    if meeting.external_id is not None:
        return get_meeting_by_source_id(conn, meeting.source, meeting.external_id)
    return None


def _existing_evidence(conn: sqlite3.Connection, evidence: Evidence) -> Evidence | None:
    if "id" in evidence.model_fields_set:
        found = get_evidence(conn, evidence.id)
        if found is not None:
            return found
    if evidence.source_id is not None:
        return get_evidence_by_source_id(conn, evidence.source, evidence.source_id)
    return None


def _existing_action(conn: sqlite3.Connection, action: Action) -> Action | None:
    if "id" in action.model_fields_set:
        found = get_action(conn, action.id)
        if found is not None:
            return found
    if action.source_id is not None:
        return get_action_by_source_id(conn, action.source, action.source_id)
    return None


def _existing_prospecting(
    conn: sqlite3.Connection, item: ProspectingItem
) -> ProspectingItem | None:
    if "id" in item.model_fields_set:
        found = get_prospecting_item(conn, item.id)
        if found is not None:
            return found
    return get_prospecting_item_by_row_key(conn, item.row_key)


def _classify(existing: BaseModel | None, saved: BaseModel) -> str:
    if existing is None:
        return "created"
    if _business_changed(existing, saved):
        return "changed"
    return "unchanged"


def _business_changed(before: BaseModel, after: BaseModel) -> bool:
    old = before.model_dump()
    new = after.model_dump()
    keys = (set(old) | set(new)) - _TIMESTAMP_FIELDS
    return any(old.get(key) != new.get(key) for key in keys)


def _coerce(raw: Any, model_cls: type[T]) -> T:
    if isinstance(raw, model_cls):
        return raw
    if isinstance(raw, dict):
        return model_cls.model_validate(_stringify_json_fields(raw))
    raise TypeError(f"expected {model_cls.__name__} or dict, got {type(raw).__name__}")


def _stringify_json_fields(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key.endswith("_json") and value is not None and not isinstance(value, str):
            out[key] = json.dumps(value, default=str)
        else:
            out[key] = value
    return out


def _record_ref(item: Any) -> str | None:
    for key in (
        "external_id",
        "source_id",
        "hubspot_id",
        "email",
        "row_key",
        "name",
        "title",
        "id",
    ):
        if isinstance(item, dict):
            value = item.get(key)
        else:
            value = getattr(item, key, None)
        if value:
            return str(value)
    return None


def _safe_message(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    if len(text) > 500:
        return text[:497] + "..."
    return text
