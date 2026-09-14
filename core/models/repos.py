"""SQLite repositories for Sales OS domain tables.

Callers pass a connection from ``database.db.connect`` (row_factory already
``sqlite3.Row``, foreign keys on). These functions do not commit.
"""

from __future__ import annotations

import json
import sqlite3
from enum import Enum
from typing import Any

from core.models.common import (
    fetch_all,
    fetch_one,
    insert_row,
    new_ulid,
    row_to_model,
    save,
    utcnow,
)
from core.models.schemas import (
    DEAL_TRACKED_FIELDS,
    Action,
    ActionEvidence,
    ActionStatus,
    AiCall,
    AuditLog,
    AuditLogEvidence,
    Company,
    CompanyAlias,
    Contact,
    Deal,
    DealChange,
    DealSource,
    DealUpsertResult,
    Evidence,
    FieldDiff,
    Meeting,
    MeetingSource,
    Memory,
    MemoryEvidence,
    MemoryRelation,
    ProcessedFile,
    ProspectingItem,
    ReviewItem,
    ReviewStatus,
    Setting,
    SyncRun,
    UserFeedback,
)

_DEAL_PRESERVE = frozenset({"id", "created_at", "first_seen_at"})
_DEAL_TOUCH = frozenset({"updated_at", "last_seen_at"})
_SEEN_TOUCH = frozenset({"updated_at", "last_seen_at"})


def _enum_val(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _as_change_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, ".12g")
    if isinstance(value, int):
        return str(value)
    return str(value)


def _values_equal(field: str, old: Any, new: Any) -> bool:
    if old is None and new is None:
        return True
    if field == "deal_value":
        if old is None or new is None:
            return False
        return float(old) == float(new)
    if field == "is_closed":
        return bool(old) == bool(new)
    return old == new


# ---------------------------------------------------------------------------
# companies / aliases / contacts
# ---------------------------------------------------------------------------


def _fill_normalised_name(company: Company) -> Company:
    if company.normalised_name:
        return company
    return company.model_copy(update={"normalised_name": company.name.strip().lower()})


def get_company(conn: sqlite3.Connection, company_id: str) -> Company | None:
    return fetch_one(conn, "companies", Company, where={"id": company_id})


def get_company_by_hubspot_id(conn: sqlite3.Connection, hubspot_id: str) -> Company | None:
    return fetch_one(conn, "companies", Company, where={"hubspot_id": hubspot_id})


def list_companies(conn: sqlite3.Connection) -> list[Company]:
    return fetch_all(conn, "companies", Company, order="name COLLATE NOCASE")


def upsert_company(
    conn: sqlite3.Connection, company: Company, *, now: str | None = None
) -> Company:
    existing = None
    if "id" in company.model_fields_set:
        existing = get_company(conn, company.id)
    if existing is None and company.hubspot_id:
        existing = get_company_by_hubspot_id(conn, company.hubspot_id)
    incoming = company if existing is not None else _fill_normalised_name(company)
    saved, _created = save(conn, "companies", Company, incoming, existing=existing, now=now)
    return saved


def get_company_alias(conn: sqlite3.Connection, alias_id: str) -> CompanyAlias | None:
    return fetch_one(conn, "company_aliases", CompanyAlias, where={"id": alias_id})


def list_company_aliases(
    conn: sqlite3.Connection, *, company_id: str | None = None
) -> list[CompanyAlias]:
    where = {"company_id": company_id} if company_id else None
    return fetch_all(conn, "company_aliases", CompanyAlias, where=where, order="value")


def upsert_company_alias(
    conn: sqlite3.Connection, alias: CompanyAlias, *, now: str | None = None
) -> CompanyAlias:
    existing = None
    if "id" in alias.model_fields_set:
        existing = get_company_alias(conn, alias.id)
    if existing is None:
        existing = fetch_one(
            conn,
            "company_aliases",
            CompanyAlias,
            where={"alias_type": alias.alias_type, "value": alias.value},
        )
    saved, _created = save(
        conn,
        "company_aliases",
        CompanyAlias,
        alias,
        existing=existing,
        now=now,
        always_touch=frozenset(),
    )
    return saved


def get_contact(conn: sqlite3.Connection, contact_id: str) -> Contact | None:
    return fetch_one(conn, "contacts", Contact, where={"id": contact_id})


def get_contact_by_email(conn: sqlite3.Connection, email: str) -> Contact | None:
    return fetch_one(conn, "contacts", Contact, where={"email": email.strip().lower()})


def get_contact_by_hubspot_id(conn: sqlite3.Connection, hubspot_id: str) -> Contact | None:
    return fetch_one(conn, "contacts", Contact, where={"hubspot_id": hubspot_id})


def list_contacts(
    conn: sqlite3.Connection, *, company_id: str | None = None
) -> list[Contact]:
    where = {"company_id": company_id} if company_id else None
    return fetch_all(conn, "contacts", Contact, where=where, order="full_name COLLATE NOCASE")


def upsert_contact(
    conn: sqlite3.Connection, contact: Contact, *, now: str | None = None
) -> Contact:
    existing = None
    if "id" in contact.model_fields_set:
        existing = get_contact(conn, contact.id)
    if existing is None and contact.hubspot_id:
        existing = get_contact_by_hubspot_id(conn, contact.hubspot_id)
    if existing is None and contact.email:
        existing = get_contact_by_email(conn, contact.email)
    saved, _created = save(conn, "contacts", Contact, contact, existing=existing, now=now)
    return saved


# ---------------------------------------------------------------------------
# deals + deal_changes
# ---------------------------------------------------------------------------


def get_deal(conn: sqlite3.Connection, deal_id: str) -> Deal | None:
    return fetch_one(conn, "deals", Deal, where={"id": deal_id})


def get_deal_by_source_id(
    conn: sqlite3.Connection, source: DealSource | str, external_id: str
) -> Deal | None:
    return fetch_one(
        conn,
        "deals",
        Deal,
        where={"source": _enum_val(source), "external_id": external_id},
    )


def list_deals(
    conn: sqlite3.Connection, *, is_closed: bool | None = None
) -> list[Deal]:
    where = None if is_closed is None else {"is_closed": is_closed}
    return fetch_all(
        conn, "deals", Deal, where=where, order="is_closed ASC, priority_score DESC"
    )


def get_deal_change(conn: sqlite3.Connection, change_id: str) -> DealChange | None:
    return fetch_one(conn, "deal_changes", DealChange, where={"id": change_id})


def list_deal_changes(
    conn: sqlite3.Connection,
    *,
    deal_id: str | None = None,
    since: str | None = None,
) -> list[DealChange]:
    if deal_id is None and since is None:
        return fetch_all(conn, "deal_changes", DealChange, order="changed_at DESC")
    sql = "SELECT * FROM deal_changes WHERE 1=1"
    params: list[Any] = []
    if deal_id is not None:
        sql += " AND deal_id = ?"
        params.append(deal_id)
    if since is not None:
        sql += " AND changed_at >= ?"
        params.append(since)
    sql += " ORDER BY changed_at DESC"
    return [row_to_model(r, DealChange) for r in conn.execute(sql, params)]


def upsert_deal(
    conn: sqlite3.Connection,
    deal: Deal,
    *,
    sync_run_id: str | None = None,
    now: str | None = None,
) -> DealUpsertResult:
    """Insert or update a deal.

    On update, compare tracked fields (stage, close_date, deal_value, owner,
    is_closed), write ``deal_changes`` rows for actual changes, and return the
    field-level diff. Unset fields are not overwritten, so connector upserts
    cannot clobber prioritisation / user-override columns.
    """
    now = now or utcnow()
    existing = None
    if "id" in deal.model_fields_set:
        existing = get_deal(conn, deal.id)
    if existing is None:
        existing = get_deal_by_source_id(conn, deal.source, deal.external_id)

    if existing is None:
        saved, _ = save(
            conn,
            "deals",
            Deal,
            deal,
            existing=None,
            now=now,
            preserve=_DEAL_PRESERVE,
            always_touch=_DEAL_TOUCH,
        )
        return DealUpsertResult(deal=saved, created=True, diff=[])

    incoming = deal.model_dump(exclude_unset=True)
    diff: list[FieldDiff] = []
    for field in DEAL_TRACKED_FIELDS:
        if field not in incoming:
            continue
        old = getattr(existing, field)
        new = incoming[field]
        if _values_equal(field, old, new):
            continue
        diff.append(
            FieldDiff(
                field=field,
                old_value=_as_change_text(old),
                new_value=_as_change_text(new),
            )
        )

    saved, _ = save(
        conn,
        "deals",
        Deal,
        deal,
        existing=existing,
        now=now,
        preserve=_DEAL_PRESERVE,
        always_touch=_DEAL_TOUCH,
    )
    for change in diff:
        insert_row(
            conn,
            "deal_changes",
            {
                "id": new_ulid(),
                "deal_id": saved.id,
                "sync_run_id": sync_run_id,
                "field": change.field,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "changed_at": now,
            },
        )
    return DealUpsertResult(deal=saved, created=False, diff=diff)


# ---------------------------------------------------------------------------
# evidence / memories / actions / meetings / prospecting
# ---------------------------------------------------------------------------


def get_evidence(conn: sqlite3.Connection, evidence_id: str) -> Evidence | None:
    return fetch_one(conn, "evidence", Evidence, where={"id": evidence_id})


def get_evidence_by_source_id(
    conn: sqlite3.Connection, source: str, source_id: str
) -> Evidence | None:
    return fetch_one(
        conn, "evidence", Evidence, where={"source": source, "source_id": source_id}
    )


def list_evidence(
    conn: sqlite3.Connection, *, deal_id: str | None = None, company_id: str | None = None
) -> list[Evidence]:
    where: dict[str, Any] | None = None
    if deal_id is not None:
        where = {"deal_id": deal_id}
    elif company_id is not None:
        where = {"company_id": company_id}
    return fetch_all(conn, "evidence", Evidence, where=where, order="occurred_at DESC")


def upsert_evidence(
    conn: sqlite3.Connection, evidence: Evidence, *, now: str | None = None
) -> Evidence:
    existing = None
    if "id" in evidence.model_fields_set:
        existing = get_evidence(conn, evidence.id)
    if existing is None and evidence.source_id is not None:
        existing = get_evidence_by_source_id(conn, evidence.source, evidence.source_id)
    saved, _ = save(
        conn,
        "evidence",
        Evidence,
        evidence,
        existing=existing,
        now=now,
        always_touch=frozenset(),
    )
    return saved


def get_memory(conn: sqlite3.Connection, memory_id: str) -> Memory | None:
    return fetch_one(conn, "memories", Memory, where={"id": memory_id})


def list_memories(
    conn: sqlite3.Connection,
    *,
    deal_id: str | None = None,
    company_id: str | None = None,
    status: str | None = None,
) -> list[Memory]:
    where: dict[str, Any] = {}
    if deal_id is not None:
        where["deal_id"] = deal_id
    if company_id is not None:
        where["company_id"] = company_id
    if status is not None:
        where["status"] = status
    return fetch_all(
        conn,
        "memories",
        Memory,
        where=where or None,
        order="valid_from DESC",
    )


def upsert_memory(
    conn: sqlite3.Connection, memory: Memory, *, now: str | None = None
) -> Memory:
    existing = None
    if "id" in memory.model_fields_set:
        existing = get_memory(conn, memory.id)
    saved, _ = save(conn, "memories", Memory, memory, existing=existing, now=now)
    return saved


def add_memory_evidence(
    conn: sqlite3.Connection,
    memory_id: str,
    evidence_id: str,
    *,
    quote: str | None = None,
    relation: MemoryRelation | str = MemoryRelation.SUPPORTS,
    created_at: str | None = None,
) -> MemoryEvidence:
    link = MemoryEvidence(
        memory_id=memory_id,
        evidence_id=evidence_id,
        quote=quote,
        relation=MemoryRelation(relation),
        created_at=created_at or utcnow(),
    )
    insert_row(conn, "memory_evidence", link.model_dump())
    return link


def list_memory_evidence(
    conn: sqlite3.Connection, *, memory_id: str | None = None, evidence_id: str | None = None
) -> list[MemoryEvidence]:
    where: dict[str, Any] = {}
    if memory_id is not None:
        where["memory_id"] = memory_id
    if evidence_id is not None:
        where["evidence_id"] = evidence_id
    return fetch_all(conn, "memory_evidence", MemoryEvidence, where=where or None)


def get_action(conn: sqlite3.Connection, action_id: str) -> Action | None:
    return fetch_one(conn, "actions", Action, where={"id": action_id})


def get_action_by_source_id(
    conn: sqlite3.Connection, source: str, source_id: str
) -> Action | None:
    return fetch_one(
        conn, "actions", Action, where={"source": source, "source_id": source_id}
    )


def list_actions(
    conn: sqlite3.Connection,
    *,
    status: ActionStatus | str | None = None,
    deal_id: str | None = None,
) -> list[Action]:
    where: dict[str, Any] = {}
    if status is not None:
        where["status"] = _enum_val(status)
    if deal_id is not None:
        where["deal_id"] = deal_id
    return fetch_all(
        conn,
        "actions",
        Action,
        where=where or None,
        order="tier ASC, priority_score DESC",
    )


def upsert_action(
    conn: sqlite3.Connection, action: Action, *, now: str | None = None
) -> Action:
    existing = None
    if "id" in action.model_fields_set:
        existing = get_action(conn, action.id)
    if existing is None and action.source_id is not None:
        existing = get_action_by_source_id(conn, action.source, action.source_id)
    saved, _ = save(conn, "actions", Action, action, existing=existing, now=now)
    return saved


def add_action_evidence(
    conn: sqlite3.Connection, action_id: str, evidence_id: str
) -> ActionEvidence:
    link = ActionEvidence(action_id=action_id, evidence_id=evidence_id)
    insert_row(conn, "action_evidence", link.model_dump())
    return link


def list_action_evidence(
    conn: sqlite3.Connection, *, action_id: str | None = None
) -> list[ActionEvidence]:
    where = {"action_id": action_id} if action_id else None
    return fetch_all(conn, "action_evidence", ActionEvidence, where=where)


def get_meeting(conn: sqlite3.Connection, meeting_id: str) -> Meeting | None:
    return fetch_one(conn, "meetings", Meeting, where={"id": meeting_id})


def get_meeting_by_source_id(
    conn: sqlite3.Connection, source: MeetingSource | str, external_id: str
) -> Meeting | None:
    return fetch_one(
        conn,
        "meetings",
        Meeting,
        where={"source": _enum_val(source), "external_id": external_id},
    )


def list_meetings(
    conn: sqlite3.Connection, *, deal_id: str | None = None
) -> list[Meeting]:
    where = {"deal_id": deal_id} if deal_id else None
    return fetch_all(conn, "meetings", Meeting, where=where, order="start_at DESC")


def upsert_meeting(
    conn: sqlite3.Connection, meeting: Meeting, *, now: str | None = None
) -> Meeting:
    existing = None
    if "id" in meeting.model_fields_set:
        existing = get_meeting(conn, meeting.id)
    if existing is None and meeting.external_id is not None:
        existing = get_meeting_by_source_id(conn, meeting.source, meeting.external_id)
    saved, _ = save(conn, "meetings", Meeting, meeting, existing=existing, now=now)
    return saved


def get_prospecting_item(conn: sqlite3.Connection, item_id: str) -> ProspectingItem | None:
    return fetch_one(conn, "prospecting_items", ProspectingItem, where={"id": item_id})


def get_prospecting_item_by_row_key(
    conn: sqlite3.Connection, row_key: str
) -> ProspectingItem | None:
    return fetch_one(conn, "prospecting_items", ProspectingItem, where={"row_key": row_key})


def list_prospecting_items(
    conn: sqlite3.Connection, *, done: bool | None = None
) -> list[ProspectingItem]:
    where = None if done is None else {"done": done}
    return fetch_all(
        conn, "prospecting_items", ProspectingItem, where=where, order="due_date ASC"
    )


def upsert_prospecting_item(
    conn: sqlite3.Connection, item: ProspectingItem, *, now: str | None = None
) -> ProspectingItem:
    existing = None
    if "id" in item.model_fields_set:
        existing = get_prospecting_item(conn, item.id)
    if existing is None:
        existing = get_prospecting_item_by_row_key(conn, item.row_key)
    saved, _ = save(
        conn,
        "prospecting_items",
        ProspectingItem,
        item,
        existing=existing,
        now=now,
        preserve=frozenset({"id", "created_at", "first_seen_at"}),
        always_touch=_SEEN_TOUCH,
    )
    return saved


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------


def get_sync_run(conn: sqlite3.Connection, run_id: str) -> SyncRun | None:
    return fetch_one(conn, "sync_runs", SyncRun, where={"id": run_id})


def list_sync_runs(
    conn: sqlite3.Connection, *, source: str | None = None
) -> list[SyncRun]:
    where = {"source": source} if source else None
    return fetch_all(conn, "sync_runs", SyncRun, where=where, order="started_at DESC")


def upsert_sync_run(
    conn: sqlite3.Connection, run: SyncRun, *, now: str | None = None
) -> SyncRun:
    existing = None
    if "id" in run.model_fields_set:
        existing = get_sync_run(conn, run.id)
    saved, _ = save(
        conn, "sync_runs", SyncRun, run, existing=existing, now=now, always_touch=frozenset()
    )
    return saved


def get_processed_file(conn: sqlite3.Connection, file_id: str) -> ProcessedFile | None:
    return fetch_one(conn, "processed_files", ProcessedFile, where={"id": file_id})


def get_processed_file_by_sha256(
    conn: sqlite3.Connection, sha256: str
) -> ProcessedFile | None:
    return fetch_one(conn, "processed_files", ProcessedFile, where={"sha256": sha256})


def list_processed_files(conn: sqlite3.Connection) -> list[ProcessedFile]:
    return fetch_all(conn, "processed_files", ProcessedFile, order="processed_at DESC")


def upsert_processed_file(
    conn: sqlite3.Connection, item: ProcessedFile, *, now: str | None = None
) -> ProcessedFile:
    existing = None
    if "id" in item.model_fields_set:
        existing = get_processed_file(conn, item.id)
    if existing is None:
        existing = get_processed_file_by_sha256(conn, item.sha256)
    saved, _ = save(
        conn,
        "processed_files",
        ProcessedFile,
        item,
        existing=existing,
        now=now,
        always_touch=frozenset(),
    )
    return saved


def get_review_item(conn: sqlite3.Connection, item_id: str) -> ReviewItem | None:
    return fetch_one(conn, "review_items", ReviewItem, where={"id": item_id})


def list_review_items(
    conn: sqlite3.Connection, *, status: ReviewStatus | str | None = None
) -> list[ReviewItem]:
    where = None if status is None else {"status": _enum_val(status)}
    return fetch_all(conn, "review_items", ReviewItem, where=where, order="created_at ASC")


def upsert_review_item(
    conn: sqlite3.Connection, item: ReviewItem, *, now: str | None = None
) -> ReviewItem:
    existing = None
    if "id" in item.model_fields_set:
        existing = get_review_item(conn, item.id)
    saved, _ = save(
        conn,
        "review_items",
        ReviewItem,
        item,
        existing=existing,
        now=now,
        always_touch=frozenset(),
    )
    return saved


# ---------------------------------------------------------------------------
# safety / learning / settings
# ---------------------------------------------------------------------------


def get_audit_log(conn: sqlite3.Connection, audit_id: str) -> AuditLog | None:
    return fetch_one(conn, "audit_log", AuditLog, where={"id": audit_id})


def list_audit_log(
    conn: sqlite3.Connection, *, approval_status: str | None = None
) -> list[AuditLog]:
    where = None if approval_status is None else {"approval_status": approval_status}
    return fetch_all(conn, "audit_log", AuditLog, where=where, order="timestamp DESC")


def upsert_audit_log(
    conn: sqlite3.Connection, entry: AuditLog, *, now: str | None = None
) -> AuditLog:
    existing = None
    if "id" in entry.model_fields_set:
        existing = get_audit_log(conn, entry.id)
    saved, _ = save(
        conn, "audit_log", AuditLog, entry, existing=existing, now=now, always_touch=frozenset()
    )
    return saved


def add_audit_log_evidence(
    conn: sqlite3.Connection, audit_id: str, evidence_id: str
) -> AuditLogEvidence:
    link = AuditLogEvidence(audit_id=audit_id, evidence_id=evidence_id)
    insert_row(conn, "audit_log_evidence", link.model_dump())
    return link


def list_audit_log_evidence(
    conn: sqlite3.Connection, *, audit_id: str | None = None
) -> list[AuditLogEvidence]:
    where = {"audit_id": audit_id} if audit_id else None
    return fetch_all(conn, "audit_log_evidence", AuditLogEvidence, where=where)


def get_ai_call(conn: sqlite3.Connection, call_id: str) -> AiCall | None:
    return fetch_one(conn, "ai_calls", AiCall, where={"id": call_id})


def list_ai_calls(conn: sqlite3.Connection) -> list[AiCall]:
    return fetch_all(conn, "ai_calls", AiCall, order="timestamp DESC")


def upsert_ai_call(
    conn: sqlite3.Connection, call: AiCall, *, now: str | None = None
) -> AiCall:
    existing = None
    if "id" in call.model_fields_set:
        existing = get_ai_call(conn, call.id)
    saved, _ = save(
        conn, "ai_calls", AiCall, call, existing=existing, now=now, always_touch=frozenset()
    )
    return saved


def get_user_feedback(conn: sqlite3.Connection, feedback_id: str) -> UserFeedback | None:
    return fetch_one(conn, "user_feedback", UserFeedback, where={"id": feedback_id})


def list_user_feedback(conn: sqlite3.Connection) -> list[UserFeedback]:
    return fetch_all(conn, "user_feedback", UserFeedback, order="timestamp DESC")


def upsert_user_feedback(
    conn: sqlite3.Connection, feedback: UserFeedback, *, now: str | None = None
) -> UserFeedback:
    existing = None
    if "id" in feedback.model_fields_set:
        existing = get_user_feedback(conn, feedback.id)
    saved, _ = save(
        conn,
        "user_feedback",
        UserFeedback,
        feedback,
        existing=existing,
        now=now,
        always_touch=frozenset(),
    )
    return saved


def get_setting(conn: sqlite3.Connection, key: str) -> Setting | None:
    return fetch_one(conn, "settings", Setting, where={"key": key})


def get_setting_value(conn: sqlite3.Connection, key: str) -> Any:
    row = get_setting(conn, key)
    if row is None:
        return None
    return json.loads(row.value_json)


def list_settings(conn: sqlite3.Connection) -> list[Setting]:
    return fetch_all(conn, "settings", Setting, order="key")


def set_setting(
    conn: sqlite3.Connection,
    key: str,
    value: Any,
    *,
    now: str | None = None,
) -> Setting:
    now = now or utcnow()
    payload = json.dumps(value)
    existing = get_setting(conn, key)
    incoming = Setting(key=key, value_json=payload, updated_at=now)
    saved, _ = save(
        conn,
        "settings",
        Setting,
        incoming,
        existing=existing,
        now=now,
        preserve=frozenset(),
        always_touch=frozenset({"updated_at"}),
        lookup={"key": key},
    )
    return saved
