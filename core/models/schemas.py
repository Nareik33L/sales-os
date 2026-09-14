"""Pydantic models mirroring every domain table in database/migrations/001_initial.sql.

FTS shadow tables and schema_migrations are plumbing and are not modelled.
Column names match the SQL 1:1 so sqlite3.Row dicts validate directly.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from core.models.common import new_ulid, utcnow


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
    return value


def _coerce_bool(value: Any) -> bool:
    coerced = _coerce_optional_bool(value)
    return bool(coerced) if coerced is not None else False


SqliteBool = Annotated[bool, BeforeValidator(_coerce_bool)]
OptionalSqliteBool = Annotated[bool | None, BeforeValidator(_coerce_optional_bool)]


class TableModel(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True, use_enum_values=False)


# ---------------------------------------------------------------------------
# Enums matching CHECK constraints
# ---------------------------------------------------------------------------


class AliasType(StrEnum):
    DOMAIN = "DOMAIN"
    NAME = "NAME"
    EXCEL_LABEL = "EXCEL_LABEL"
    SHEET_LABEL = "SHEET_LABEL"
    CALENDLY_LABEL = "CALENDLY_LABEL"
    TRANSCRIPT_LABEL = "TRANSCRIPT_LABEL"


class DealSource(StrEnum):
    HUBSPOT = "HUBSPOT"
    EXCEL = "EXCEL"
    MANUAL = "MANUAL"


class AttentionStatus(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class EvidenceType(StrEnum):
    EMAIL = "EMAIL"
    ZOOM_TRANSCRIPT = "ZOOM_TRANSCRIPT"
    HUBSPOT_ACTIVITY = "HUBSPOT_ACTIVITY"
    HUBSPOT_DEAL = "HUBSPOT_DEAL"
    EXCEL_DEAL = "EXCEL_DEAL"
    PROSPECTING_ACTIVITY = "PROSPECTING_ACTIVITY"
    CALENDLY_MEETING = "CALENDLY_MEETING"
    TODO_TASK = "TODO_TASK"
    USER_INPUT = "USER_INPUT"


class EvidenceDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    INTERNAL = "INTERNAL"
    UNKNOWN = "UNKNOWN"


class ExtractionStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MemoryType(StrEnum):
    FACT = "FACT"
    COMMITMENT = "COMMITMENT"
    CUSTOMER_PREFERENCE = "CUSTOMER_PREFERENCE"
    OBJECTION = "OBJECTION"
    BUYING_SIGNAL = "BUYING_SIGNAL"
    RELATIONSHIP = "RELATIONSHIP"
    DEAL_STATE = "DEAL_STATE"
    NEXT_STEP = "NEXT_STEP"
    RISK = "RISK"
    USER_PREFERENCE = "USER_PREFERENCE"
    LEARNED_PATTERN = "LEARNED_PATTERN"


class MemoryBasis(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    STATED_BY_USER = "STATED_BY_USER"


class MemoryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    RETRACTED = "RETRACTED"
    REJECTED = "REJECTED"


class MemoryDirection(StrEnum):
    USER_TO_CUSTOMER = "USER_TO_CUSTOMER"
    CUSTOMER_TO_USER = "CUSTOMER_TO_USER"
    CUSTOMER_INTERNAL = "CUSTOMER_INTERNAL"
    USER_INTERNAL = "USER_INTERNAL"


class MemoryRelation(StrEnum):
    SUPPORTS = "SUPPORTS"
    FULFILS = "FULFILS"
    CONTRADICTS = "CONTRADICTS"
    SUPERSEDES = "SUPERSEDES"


class ActionType(StrEnum):
    HUBSPOT_TASK = "HUBSPOT_TASK"
    TODO_TASK = "TODO_TASK"
    PROSPECTING = "PROSPECTING"
    EMAIL_FOLLOWUP = "EMAIL_FOLLOWUP"
    TRANSCRIPT_ACTION = "TRANSCRIPT_ACTION"
    MEETING_PREP = "MEETING_PREP"
    MEETING_FOLLOWUP = "MEETING_FOLLOWUP"
    COMMITMENT = "COMMITMENT"
    DATA_HYGIENE = "DATA_HYGIENE"
    REVIEW = "REVIEW"
    MANUAL = "MANUAL"


class ActionStatus(StrEnum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    DISMISSED = "DISMISSED"
    SNOOZED = "SNOOZED"


class ExternalWriteStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    WRITTEN = "WRITTEN"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class MeetingSource(StrEnum):
    CALENDLY = "CALENDLY"
    HUBSPOT = "HUBSPOT"
    TRANSCRIPT = "TRANSCRIPT"
    MANUAL = "MANUAL"


class MeetingStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class InboxKind(StrEnum):
    EMAIL = "EMAIL"
    TRANSCRIPT = "TRANSCRIPT"
    EXCEL = "EXCEL"
    PROSPECTING_CSV = "PROSPECTING_CSV"
    TODO_EXPORT = "TODO_EXPORT"


class ProcessedFileStatus(StrEnum):
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"
    UNSUPPORTED = "UNSUPPORTED"


class SyncTrigger(StrEnum):
    MORNING = "MORNING"
    MANUAL = "MANUAL"
    STARTUP = "STARTUP"
    FILE_DROP = "FILE_DROP"


class SyncStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class ReviewKind(StrEnum):
    MATCH_COMPANY = "MATCH_COMPANY"
    MATCH_DEAL = "MATCH_DEAL"
    MATCH_CONTACT = "MATCH_CONTACT"
    CONFLICTING_MEMORY = "CONFLICTING_MEMORY"
    CONFIRM_MEMORY = "CONFIRM_MEMORY"
    STALE_COMMITMENT = "STALE_COMMITMENT"
    CLOSE_DATE_PASSED = "CLOSE_DATE_PASSED"


class ReviewStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    NOT_REQUIRED = "NOT_REQUIRED"


class AiCallStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    REJECTED_OUTPUT = "REJECTED_OUTPUT"


class FeedbackEvent(StrEnum):
    COMPLETED = "COMPLETED"
    IGNORED = "IGNORED"
    SNOOZED = "SNOOZED"
    DISMISSED = "DISMISSED"
    BOOST_UP = "BOOST_UP"
    BOOST_DOWN = "BOOST_DOWN"
    PINNED = "PINNED"
    UNPINNED = "UNPINNED"
    REORDERED = "REORDERED"
    MEMORY_CONFIRMED = "MEMORY_CONFIRMED"
    MEMORY_REJECTED = "MEMORY_REJECTED"
    MATCH_CONFIRMED = "MATCH_CONFIRMED"
    MATCH_CORRECTED = "MATCH_CORRECTED"


# Fields the connector diff writes to deal_changes (docs/02-data-model.md).
DEAL_TRACKED_FIELDS: tuple[str, ...] = (
    "stage",
    "close_date",
    "deal_value",
    "owner",
    "is_closed",
)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class Company(TableModel):
    id: str = Field(default_factory=new_ulid)
    name: str
    normalised_name: str = ""
    hubspot_id: str | None = None
    primary_domain: str | None = None
    industry: str | None = None
    is_strategic: SqliteBool = False
    notes: str | None = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class CompanyAlias(TableModel):
    id: str = Field(default_factory=new_ulid)
    company_id: str
    alias_type: AliasType
    value: str
    source: str
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="before")
    @classmethod
    def normalise_value(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("value") is not None:
            data = {**data, "value": str(data["value"]).strip().lower()}
        return data


class Contact(TableModel):
    id: str = Field(default_factory=new_ulid)
    company_id: str | None = None
    hubspot_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str
    email: str | None = None
    phone: str | None = None
    title: str | None = None
    role_in_deal: str | None = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)

    @model_validator(mode="before")
    @classmethod
    def lowercase_email(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("email"):
            data = {**data, "email": str(data["email"]).strip().lower()}
        return data


class Deal(TableModel):
    id: str = Field(default_factory=new_ulid)
    external_id: str
    source: DealSource
    product: str
    name: str
    company_id: str | None = None
    company_name: str | None = None
    deal_value: float | None = None
    currency: str = "GBP"
    deal_value_gbp: float | None = None
    stage: str | None = None
    stage_key: str | None = None
    is_closed: SqliteBool = False
    is_won: OptionalSqliteBool = None
    close_date: str | None = None
    owner: str | None = None
    last_activity_at: str | None = None
    source_created_at: str | None = None
    source_updated_at: str | None = None
    summary: str | None = None
    summary_updated_at: str | None = None
    summary_stale: SqliteBool = True
    attention_status: AttentionStatus = AttentionStatus.LOW
    priority_score: float = 0
    priority_breakdown_json: str | None = None
    priority_computed_at: str | None = None
    user_pinned_rank: int | None = None
    user_boost: int = 0
    source_record_json: str | None = None
    first_seen_at: str = Field(default_factory=utcnow)
    last_seen_at: str = Field(default_factory=utcnow)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class DealChange(TableModel):
    id: str = Field(default_factory=new_ulid)
    deal_id: str
    sync_run_id: str | None = None
    field: str
    old_value: str | None = None
    new_value: str | None = None
    changed_at: str = Field(default_factory=utcnow)


class FieldDiff(TableModel):
    field: str
    old_value: str | None = None
    new_value: str | None = None


class DealUpsertResult(TableModel):
    deal: Deal
    created: bool
    diff: list[FieldDiff] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence / memory / actions / meetings
# ---------------------------------------------------------------------------


class Evidence(TableModel):
    id: str = Field(default_factory=new_ulid)
    type: EvidenceType
    source: str
    source_id: str | None = None
    file_path: str | None = None
    content_hash: str | None = None
    company_id: str | None = None
    deal_id: str | None = None
    contact_id: str | None = None
    match_confidence: float | None = None
    match_method: str | None = None
    occurred_at: str
    direction: EvidenceDirection | None = None
    participants_json: str | None = None
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    metadata_json: str | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.PENDING
    extraction_provider: str | None = None
    created_at: str = Field(default_factory=utcnow)


class Memory(TableModel):
    id: str = Field(default_factory=new_ulid)
    type: MemoryType
    basis: MemoryBasis = MemoryBasis.OBSERVED
    status: MemoryStatus = MemoryStatus.ACTIVE
    subject: str
    content: str
    dedupe_key: str | None = None
    company_id: str | None = None
    contact_id: str | None = None
    deal_id: str | None = None
    direction: MemoryDirection | None = None
    owner_label: str | None = None
    due_date: str | None = None
    due_text: str | None = None
    confidence: float
    valid_from: str
    valid_until: str | None = None
    superseded_by_id: str | None = None
    resolution_note: str | None = None
    created_by: str
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class MemoryEvidence(TableModel):
    memory_id: str
    evidence_id: str
    quote: str | None = None
    relation: MemoryRelation = MemoryRelation.SUPPORTS
    created_at: str = Field(default_factory=utcnow)


class Action(TableModel):
    id: str = Field(default_factory=new_ulid)
    title: str
    description: str | None = None
    type: ActionType
    tier: int = 2
    status: ActionStatus = ActionStatus.OPEN
    source: str
    source_id: str | None = None
    origin_memory_id: str | None = None
    company_id: str | None = None
    deal_id: str | None = None
    contact_id: str | None = None
    meeting_id: str | None = None
    due_date: str | None = None
    snoozed_until: str | None = None
    priority_score: float = 0
    priority_breakdown_json: str | None = None
    system_rank: int | None = None
    user_priority_override: int | None = None
    user_boost: int = 0
    external_write_status: ExternalWriteStatus | None = None
    completed_at: str | None = None
    dismissed_at: str | None = None
    dismissed_reason: str | None = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class ActionEvidence(TableModel):
    action_id: str
    evidence_id: str


class Meeting(TableModel):
    id: str = Field(default_factory=new_ulid)
    source: MeetingSource
    external_id: str | None = None
    title: str | None = None
    event_type: str | None = None
    start_at: str
    end_at: str | None = None
    duration_minutes: int | None = None
    status: MeetingStatus = MeetingStatus.SCHEDULED
    company_id: str | None = None
    deal_id: str | None = None
    contact_id: str | None = None
    invitees_json: str | None = None
    join_url: str | None = None
    transcript_evidence_id: str | None = None
    followup_action_id: str | None = None
    metadata_json: str | None = None
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class ProspectingItem(TableModel):
    id: str = Field(default_factory=new_ulid)
    row_key: str
    sheet_row_number: int | None = None
    due_date: str | None = None
    priority: str | None = None
    company_name: str | None = None
    company_id: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    channel: str | None = None
    step: str | None = None
    subject: str | None = None
    body: str | None = None
    phone: str | None = None
    zoominfo_url: str | None = None
    outcome: str | None = None
    done: SqliteBool = False
    actual_date: str | None = None
    notes: str | None = None
    sequence_id: str | None = None
    raw_row_json: str | None = None
    first_seen_at: str = Field(default_factory=utcnow)
    last_seen_at: str = Field(default_factory=utcnow)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Operations / safety / learning
# ---------------------------------------------------------------------------


class SyncRun(TableModel):
    id: str = Field(default_factory=new_ulid)
    source: str
    trigger: SyncTrigger
    started_at: str
    finished_at: str | None = None
    status: SyncStatus
    records_fetched: int = 0
    records_created: int = 0
    records_changed: int = 0
    records_unchanged: int = 0
    error_count: int = 0
    errors_json: str | None = None
    message: str | None = None
    cursor_json: str | None = None


class ProcessedFile(TableModel):
    id: str = Field(default_factory=new_ulid)
    inbox_kind: InboxKind
    original_name: str
    stored_path: str | None = None
    sha256: str
    size_bytes: int | None = None
    status: ProcessedFileStatus
    evidence_id: str | None = None
    error: str | None = None
    processed_at: str = Field(default_factory=utcnow)


class ReviewItem(TableModel):
    id: str = Field(default_factory=new_ulid)
    kind: ReviewKind
    status: ReviewStatus = ReviewStatus.OPEN
    question: str
    evidence_id: str | None = None
    memory_id: str | None = None
    deal_id: str | None = None
    candidates_json: str | None = None
    resolution_json: str | None = None
    created_at: str = Field(default_factory=utcnow)
    resolved_at: str | None = None


class AuditLog(TableModel):
    id: str = Field(default_factory=new_ulid)
    timestamp: str = Field(default_factory=utcnow)
    actor: str
    event: str
    external_system: str | None = None
    external_ref: str | None = None
    action_id: str | None = None
    reasoning: str | None = None
    proposed_change_json: str | None = None
    approval_status: ApprovalStatus | None = None
    approved_at: str | None = None
    executed_at: str | None = None
    result_json: str | None = None


class AuditLogEvidence(TableModel):
    audit_id: str
    evidence_id: str


class AiCall(TableModel):
    id: str = Field(default_factory=new_ulid)
    timestamp: str = Field(default_factory=utcnow)
    provider: str
    model: str | None = None
    purpose: str
    evidence_id: str | None = None
    deal_id: str | None = None
    input_chars: int
    output_chars: int | None = None
    redacted: SqliteBool = False
    latency_ms: int | None = None
    status: AiCallStatus
    error: str | None = None


class UserFeedback(TableModel):
    id: str = Field(default_factory=new_ulid)
    timestamp: str = Field(default_factory=utcnow)
    action_id: str | None = None
    deal_id: str | None = None
    event: FeedbackEvent
    system_priority: int | None = None
    user_priority: int | None = None
    manual_override: SqliteBool = False
    context_json: str | None = None


class Setting(TableModel):
    key: str
    value_json: str
    updated_at: str = Field(default_factory=utcnow)


# Table name → model. evidence_fts and schema_migrations are intentionally absent.
DOMAIN_TABLE_MODELS: dict[str, type[TableModel]] = {
    "companies": Company,
    "company_aliases": CompanyAlias,
    "contacts": Contact,
    "deals": Deal,
    "deal_changes": DealChange,
    "evidence": Evidence,
    "memories": Memory,
    "memory_evidence": MemoryEvidence,
    "actions": Action,
    "action_evidence": ActionEvidence,
    "meetings": Meeting,
    "prospecting_items": ProspectingItem,
    "sync_runs": SyncRun,
    "processed_files": ProcessedFile,
    "review_items": ReviewItem,
    "audit_log": AuditLog,
    "audit_log_evidence": AuditLogEvidence,
    "ai_calls": AiCall,
    "user_feedback": UserFeedback,
    "settings": Setting,
}
