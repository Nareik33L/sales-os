"""Round-trip tests for core models and repositories.

Fixtures are fictional (Acme Ltd, Beta Corp, acme-example.test) — no real
customer data. See docs/02-data-model.md and SOS-02 acceptance.
"""

from __future__ import annotations

import pytest

from core.models import (
    DEAL_TRACKED_FIELDS,
    DOMAIN_TABLE_MODELS,
    Action,
    ActionType,
    AiCall,
    AiCallStatus,
    AliasType,
    ApprovalStatus,
    AuditLog,
    Company,
    CompanyAlias,
    Contact,
    Deal,
    DealSource,
    Evidence,
    EvidenceDirection,
    EvidenceType,
    FeedbackEvent,
    InboxKind,
    Meeting,
    MeetingSource,
    Memory,
    MemoryDirection,
    MemoryRelation,
    MemoryType,
    ProcessedFile,
    ProcessedFileStatus,
    ProspectingItem,
    ReviewItem,
    ReviewKind,
    SyncRun,
    SyncStatus,
    SyncTrigger,
    UserFeedback,
    add_action_evidence,
    add_audit_log_evidence,
    add_memory_evidence,
    get_action,
    get_action_by_source_id,
    get_ai_call,
    get_audit_log,
    get_company,
    get_company_by_hubspot_id,
    get_contact_by_email,
    get_deal,
    get_deal_by_source_id,
    get_evidence,
    get_meeting,
    get_memory,
    get_processed_file_by_sha256,
    get_prospecting_item_by_row_key,
    get_review_item,
    get_setting_value,
    get_sync_run,
    get_user_feedback,
    is_ulid,
    list_action_evidence,
    list_audit_log_evidence,
    list_companies,
    list_contacts,
    list_deal_changes,
    list_deals,
    list_evidence,
    list_meetings,
    list_memories,
    list_memory_evidence,
    list_prospecting_items,
    new_ulid,
    set_setting,
    upsert_action,
    upsert_ai_call,
    upsert_audit_log,
    upsert_company,
    upsert_company_alias,
    upsert_contact,
    upsert_deal,
    upsert_evidence,
    upsert_meeting,
    upsert_memory,
    upsert_processed_file,
    upsert_prospecting_item,
    upsert_review_item,
    upsert_sync_run,
    upsert_user_feedback,
)
from database.db import connect, migrate, table_names

NOW = "2026-09-14T08:00:00Z"
LATER = "2026-09-14T09:00:00Z"


@pytest.fixture
def conn():
    c = connect(":memory:")
    migrate(c)
    yield c
    c.close()


def _acme(conn) -> Company:
    return upsert_company(
        conn,
        Company(
            name="Acme Ltd",
            normalised_name="acme",
            hubspot_id="hs-co-acme",
            primary_domain="acme-example.test",
            industry="software",
        ),
        now=NOW,
    )


def _acme_deal(conn, company: Company, **overrides) -> Deal:
    payload = {
        "external_id": "hs-deal-acme-1",
        "source": DealSource.HUBSPOT,
        "product": "XODO_SIGN",
        "name": "Acme — Xodo Sign",
        "company_id": company.id,
        "company_name": "Acme Ltd",
        "deal_value": 75000,
        "currency": "GBP",
        "deal_value_gbp": 75000,
        "stage": "Proposal",
        "stage_key": "presentationscheduled",
        "is_closed": False,
        "close_date": "2026-09-18",
        "owner": "Sam Taylor",
        **overrides,
    }
    return upsert_deal(conn, Deal(**payload), now=NOW).deal


def test_every_domain_table_has_a_model(conn):
    plumbing = {
        "evidence_fts",
        "evidence_fts_data",
        "evidence_fts_idx",
        "evidence_fts_docsize",
        "evidence_fts_config",
        "schema_migrations",
    }
    domain = {name for name in table_names(conn) if name not in plumbing}
    assert domain == set(DOMAIN_TABLE_MODELS)
    for table, model in DOMAIN_TABLE_MODELS.items():
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert set(model.model_fields) <= columns, (
            f"{model.__name__} fields not in {table}: "
            f"{set(model.model_fields) - columns}"
        )


def test_ulid_format_and_uniqueness():
    ids = [new_ulid() for _ in range(50)]
    assert len(set(ids)) == 50
    assert all(is_ulid(i) for i in ids)
    assert all(len(i) == 26 for i in ids)


def test_company_contact_alias_roundtrip(conn):
    company = _acme(conn)
    assert is_ulid(company.id)
    assert get_company(conn, company.id).name == "Acme Ltd"
    assert get_company_by_hubspot_id(conn, "hs-co-acme").id == company.id
    assert [c.name for c in list_companies(conn)] == ["Acme Ltd"]

    gamma = upsert_company(conn, Company(name="Gamma"), now=NOW)
    assert gamma.normalised_name == "gamma"

    alias = upsert_company_alias(
        conn,
        CompanyAlias(
            company_id=company.id,
            alias_type=AliasType.DOMAIN,
            value="ACME-EXAMPLE.TEST",
            source="HUBSPOT",
        ),
        now=NOW,
    )
    assert alias.value == "acme-example.test"

    # Unique (alias_type, value) updates rather than duplicating.
    moved = upsert_company(
        conn,
        Company(name="Beta Corp", normalised_name="beta"),
        now=NOW,
    )
    same = upsert_company_alias(
        conn,
        CompanyAlias(
            company_id=moved.id,
            alias_type=AliasType.DOMAIN,
            value="acme-example.test",
            source="USER",
        ),
        now=NOW,
    )
    assert same.id == alias.id
    assert same.company_id == moved.id
    assert same.source == "USER"

    contact = upsert_contact(
        conn,
        Contact(
            company_id=company.id,
            first_name="Sam",
            last_name="Taylor",
            full_name="Sam Taylor",
            email="Sam.Taylor@Acme-Example.test",
            title="VP Operations",
            role_in_deal="CHAMPION",
            hubspot_id="hs-ct-sam",
        ),
        now=NOW,
    )
    assert contact.email == "sam.taylor@acme-example.test"
    assert get_contact_by_email(conn, "sam.taylor@acme-example.test").id == contact.id
    again = upsert_contact(
        conn,
        Contact(
            full_name="Samantha Taylor",
            email="sam.taylor@acme-example.test",
            title="VP Operations",
        ),
        now=LATER,
    )
    assert again.id == contact.id
    assert again.full_name == "Samantha Taylor"
    assert list_contacts(conn, company_id=company.id)[0].id == contact.id


def test_deal_insert_get_list_roundtrip(conn):
    company = _acme(conn)
    deal = _acme_deal(conn, company)
    assert is_ulid(deal.id)
    assert deal.first_seen_at == NOW
    assert deal.last_seen_at == NOW
    assert deal.is_closed is False
    assert deal.summary_stale is True
    fetched = get_deal(conn, deal.id)
    assert fetched.name == "Acme — Xodo Sign"
    assert fetched.deal_value == 75000
    by_ext = get_deal_by_source_id(conn, DealSource.HUBSPOT, "hs-deal-acme-1")
    assert by_ext.id == deal.id
    assert list_deals(conn, is_closed=False)[0].id == deal.id
    assert list_deal_changes(conn, deal_id=deal.id) == []


def test_upsert_deal_returns_diff_and_writes_deal_changes(conn):
    company = _acme(conn)
    sync = upsert_sync_run(
        conn,
        SyncRun(
            source="hubspot",
            trigger=SyncTrigger.MORNING,
            started_at=NOW,
            status=SyncStatus.RUNNING,
        ),
        now=NOW,
    )
    created = upsert_deal(
        conn,
        Deal(
            external_id="hs-deal-acme-1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme — Xodo Sign",
            company_id=company.id,
            deal_value=75000,
            stage="Proposal",
            close_date="2026-09-18",
            owner="Sam Taylor",
            is_closed=False,
        ),
        sync_run_id=sync.id,
        now=NOW,
    )
    assert created.created is True
    assert created.diff == []
    assert list_deal_changes(conn, deal_id=created.deal.id) == []

    updated = upsert_deal(
        conn,
        Deal(
            external_id="hs-deal-acme-1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme — Xodo Sign",
            deal_value=82000,
            stage="Negotiation",
            close_date="2026-09-30",
            owner="Alex Kim",
            is_closed=False,
        ),
        sync_run_id=sync.id,
        now=LATER,
    )
    assert updated.created is False
    assert updated.deal.id == created.deal.id
    assert updated.deal.last_seen_at == LATER
    assert {d.field for d in updated.diff} == {
        "stage",
        "close_date",
        "deal_value",
        "owner",
    }
    by_field = {d.field: d for d in updated.diff}
    assert by_field["stage"].old_value == "Proposal"
    assert by_field["stage"].new_value == "Negotiation"
    assert by_field["deal_value"].old_value == "75000"
    assert by_field["deal_value"].new_value == "82000"
    assert by_field["close_date"].old_value == "2026-09-18"
    assert by_field["close_date"].new_value == "2026-09-30"
    assert by_field["owner"].old_value == "Sam Taylor"
    assert by_field["owner"].new_value == "Alex Kim"

    rows = list_deal_changes(conn, deal_id=created.deal.id)
    assert len(rows) == 4
    assert all(r.sync_run_id == sync.id for r in rows)
    assert all(r.changed_at == LATER for r in rows)
    assert {r.field for r in rows} == {d.field for d in updated.diff}

    closed = upsert_deal(
        conn,
        Deal(
            external_id="hs-deal-acme-1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme — Xodo Sign",
            is_closed=True,
            stage="Closed Won",
            deal_value=82000,
        ),
        now="2026-09-14T10:00:00Z",
    )
    closed_fields = {d.field for d in closed.diff}
    assert "is_closed" in closed_fields
    assert "stage" in closed_fields
    assert "deal_value" not in closed_fields
    is_closed_diff = next(d for d in closed.diff if d.field == "is_closed")
    assert is_closed_diff.old_value == "0"
    assert is_closed_diff.new_value == "1"
    assert get_deal(conn, created.deal.id).is_closed is True
    assert set(DEAL_TRACKED_FIELDS) <= {
        "stage",
        "close_date",
        "deal_value",
        "owner",
        "is_closed",
    }


def test_upsert_deal_noop_writes_no_changes(conn):
    company = _acme(conn)
    first = upsert_deal(
        conn,
        Deal(
            external_id="hs-deal-acme-1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme — Xodo Sign",
            company_id=company.id,
            deal_value=75000.0,
            stage="Proposal",
            owner="Sam Taylor",
            is_closed=False,
        ),
        now=NOW,
    )
    second = upsert_deal(
        conn,
        Deal(
            external_id="hs-deal-acme-1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme — Xodo Sign",
            deal_value=75000,
            stage="Proposal",
            owner="Sam Taylor",
            is_closed=False,
        ),
        now=LATER,
    )
    assert second.diff == []
    assert list_deal_changes(conn, deal_id=first.deal.id) == []
    assert second.deal.last_seen_at == LATER


def test_upsert_deal_does_not_clobber_priority_when_unset(conn):
    company = _acme(conn)
    created = upsert_deal(
        conn,
        Deal(
            external_id="hs-deal-acme-1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme — Xodo Sign",
            company_id=company.id,
            priority_score=82.4,
            user_boost=5,
            user_pinned_rank=1,
        ),
        now=NOW,
    )
    assert created.deal.priority_score == 82.4
    updated = upsert_deal(
        conn,
        Deal(
            external_id="hs-deal-acme-1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme Ltd — Xodo Sign",
            stage="Proposal",
        ),
        now=LATER,
    )
    assert updated.deal.priority_score == 82.4
    assert updated.deal.user_boost == 5
    assert updated.deal.user_pinned_rank == 1
    assert updated.deal.name == "Acme Ltd — Xodo Sign"


def test_evidence_memory_action_meeting_roundtrip(conn):
    company = _acme(conn)
    deal = _acme_deal(conn, company)
    contact = upsert_contact(
        conn,
        Contact(
            company_id=company.id,
            full_name="Sam Taylor",
            email="sam.taylor@acme-example.test",
        ),
        now=NOW,
    )
    evidence = upsert_evidence(
        conn,
        Evidence(
            type=EvidenceType.EMAIL,
            source="email_files",
            source_id="<msg-acme-pricing>",
            company_id=company.id,
            deal_id=deal.id,
            contact_id=contact.id,
            occurred_at="2026-09-13T16:02:00Z",
            direction=EvidenceDirection.OUTBOUND,
            title="Re: pricing",
            content="Thanks Sam. I will send the revised pricing tomorrow.",
        ),
        now=NOW,
    )
    assert get_evidence(conn, evidence.id).title == "Re: pricing"
    again = upsert_evidence(
        conn,
        Evidence(
            type=EvidenceType.EMAIL,
            source="email_files",
            source_id="<msg-acme-pricing>",
            title="Re: revised pricing",
            occurred_at="2026-09-13T16:02:00Z",
        ),
        now=LATER,
    )
    assert again.id == evidence.id
    assert again.title == "Re: revised pricing"
    assert list_evidence(conn, deal_id=deal.id)[0].id == evidence.id

    memory = upsert_memory(
        conn,
        Memory(
            type=MemoryType.COMMITMENT,
            subject="Revised pricing",
            content="Send revised pricing to Acme",
            deal_id=deal.id,
            company_id=company.id,
            direction=MemoryDirection.USER_TO_CUSTOMER,
            owner_label="me",
            due_date="2026-09-15",
            due_text="tomorrow",
            confidence=0.85,
            valid_from=NOW,
            created_by="rules",
        ),
        now=NOW,
    )
    link = add_memory_evidence(
        conn,
        memory.id,
        evidence.id,
        quote="I will send the revised pricing tomorrow.",
        relation=MemoryRelation.SUPPORTS,
        created_at=NOW,
    )
    assert link.quote.startswith("I will send")
    assert get_memory(conn, memory.id).subject == "Revised pricing"
    assert list_memories(conn, deal_id=deal.id)[0].id == memory.id
    assert list_memory_evidence(conn, memory_id=memory.id)[0].evidence_id == evidence.id

    action = upsert_action(
        conn,
        Action(
            title="Send revised pricing to Acme",
            type=ActionType.COMMITMENT,
            tier=1,
            source="memory",
            source_id=memory.id,
            origin_memory_id=memory.id,
            deal_id=deal.id,
            company_id=company.id,
            due_date="2026-09-15",
        ),
        now=NOW,
    )
    add_action_evidence(conn, action.id, evidence.id)
    assert get_action(conn, action.id).tier == 1
    assert get_action_by_source_id(conn, "memory", memory.id).id == action.id
    assert list_action_evidence(conn, action_id=action.id)[0].evidence_id == evidence.id

    meeting = upsert_meeting(
        conn,
        Meeting(
            source=MeetingSource.CALENDLY,
            external_id="evt-acme-2026-09-13",
            title="Acme discovery",
            start_at="2026-09-13T14:00:00Z",
            end_at="2026-09-13T14:30:00Z",
            duration_minutes=30,
            company_id=company.id,
            deal_id=deal.id,
            contact_id=contact.id,
            transcript_evidence_id=evidence.id,
        ),
        now=NOW,
    )
    assert get_meeting(conn, meeting.id).title == "Acme discovery"
    assert list_meetings(conn, deal_id=deal.id)[0].id == meeting.id


def test_ops_safety_settings_roundtrip(conn):
    company = _acme(conn)
    deal = _acme_deal(conn, company)
    evidence = upsert_evidence(
        conn,
        Evidence(
            type=EvidenceType.USER_INPUT,
            source="manual",
            source_id="note-1",
            occurred_at=NOW,
            title="Follow up Beta Corp intro",
            content="Beta Corp asked for a one-pager.",
        ),
        now=NOW,
    )

    item = upsert_prospecting_item(
        conn,
        ProspectingItem(
            row_key="seq-1|beta-corp|riley-chen|intro",
            sheet_row_number=12,
            company_name="Beta Corp",
            contact_name="Riley Chen",
            channel="email",
            step="intro",
            subject="Intro to Gamma",
            done=False,
        ),
        now=NOW,
    )
    assert get_prospecting_item_by_row_key(
        conn, "seq-1|beta-corp|riley-chen|intro"
    ).id == item.id
    again = upsert_prospecting_item(
        conn,
        ProspectingItem(
            row_key="seq-1|beta-corp|riley-chen|intro",
            done=True,
            outcome="replied",
        ),
        now=LATER,
    )
    assert again.id == item.id
    assert again.done is True
    assert again.company_name == "Beta Corp"
    assert list_prospecting_items(conn, done=True)[0].id == item.id

    run = upsert_sync_run(
        conn,
        SyncRun(
            source="google_sheets",
            trigger=SyncTrigger.MANUAL,
            started_at=NOW,
            status=SyncStatus.SUCCESS,
            records_fetched=1,
            records_created=1,
            finished_at=LATER,
            message="ok",
        ),
        now=NOW,
    )
    assert get_sync_run(conn, run.id).status == SyncStatus.SUCCESS

    processed = upsert_processed_file(
        conn,
        ProcessedFile(
            inbox_kind=InboxKind.EMAIL,
            original_name="acme-pricing.eml",
            sha256="a" * 64,
            size_bytes=128,
            status=ProcessedFileStatus.PROCESSED,
            evidence_id=evidence.id,
        ),
        now=NOW,
    )
    assert get_processed_file_by_sha256(conn, "a" * 64).id == processed.id

    review = upsert_review_item(
        conn,
        ReviewItem(
            kind=ReviewKind.MATCH_COMPANY,
            question="Is 'Beta Corp' the same company as Beta Corporation?",
            evidence_id=evidence.id,
        ),
        now=NOW,
    )
    assert get_review_item(conn, review.id).status.value == "OPEN"

    audit = upsert_audit_log(
        conn,
        AuditLog(
            actor="user",
            event="PROPOSE_EXTERNAL_WRITE",
            external_system="HUBSPOT",
            approval_status=ApprovalStatus.PENDING,
            proposed_change_json='{"id":"hs-task-1","status":"COMPLETED"}',
        ),
        now=NOW,
    )
    add_audit_log_evidence(conn, audit.id, evidence.id)
    assert get_audit_log(conn, audit.id).event == "PROPOSE_EXTERNAL_WRITE"
    assert list_audit_log_evidence(conn, audit_id=audit.id)[0].evidence_id == evidence.id

    call = upsert_ai_call(
        conn,
        AiCall(
            provider="none",
            purpose="extract_memory",
            evidence_id=evidence.id,
            deal_id=deal.id,
            input_chars=120,
            output_chars=40,
            redacted=True,
            status=AiCallStatus.OK,
        ),
        now=NOW,
    )
    assert get_ai_call(conn, call.id).redacted is True

    feedback = upsert_user_feedback(
        conn,
        UserFeedback(
            deal_id=deal.id,
            event=FeedbackEvent.BOOST_UP,
            system_priority=4,
            user_priority=2,
            context_json='{"tier":1,"is_strategic":0}',
        ),
        now=NOW,
    )
    assert get_user_feedback(conn, feedback.id).event == FeedbackEvent.BOOST_UP

    stored = set_setting(conn, "today_greeting_name", "Alex", now=NOW)
    assert stored.key == "today_greeting_name"
    assert get_setting_value(conn, "today_greeting_name") == "Alex"
    set_setting(conn, "today_greeting_name", "Sam", now=LATER)
    assert get_setting_value(conn, "today_greeting_name") == "Sam"
