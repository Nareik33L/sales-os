"""SOS-04: memory lifecycle rules from docs/04 §3–7 and §10.

Fictional fixtures only (Acme Ltd, Beta Corp, acme-example.test).
"""

from __future__ import annotations

import json

from core.memory import (
    RULES_CONFIDENCE_CAP,
    MemoryCandidate,
    MemoryIngestConfig,
    RelationToExisting,
    corroborate,
    extract_rules,
    ingest_candidates,
    verify_quote,
)
from core.models import (
    Company,
    Deal,
    DealSource,
    Evidence,
    EvidenceDirection,
    EvidenceType,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
    ReviewKind,
    get_deal,
    list_actions,
    list_memories,
    list_memory_evidence,
    list_review_items,
    upsert_company,
    upsert_deal,
    upsert_evidence,
)
from core.models.schemas import ActionType, MemoryBasis, MemoryDirection

NOW = "2026-09-14T08:00:00Z"
MONDAY = "2026-09-07T10:00:00Z"  # 11:00 Europe/London, Monday
CFG = MemoryIngestConfig(source_reliability=1.0, created_by="rules")

PRICING_QUOTE = "I'll send the revised pricing tomorrow."
PRICING_BODY = (
    "Thanks Ada. I'll send the revised pricing tomorrow. "
    "We are reviewing internally with procurement."
)
RECEIVED_QUOTE = "We received the pricing and are reviewing internally."
RECEIVED_BODY = (
    "Ada Example: We received the pricing and are reviewing internally "
    "with procurement."
)


def _acme_deal(db) -> tuple[Company, Deal]:
    company = upsert_company(
        db,
        Company(
            name="Acme Ltd",
            normalised_name="acme",
            primary_domain="acme-example.test",
        ),
        now=NOW,
    )
    deal = upsert_deal(
        db,
        Deal(
            external_id="hs-deal-acme-1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme — Xodo Sign",
            company_id=company.id,
            company_name="Acme Ltd",
            deal_value=75000,
            deal_value_gbp=75000,
            stage="Proposal",
            close_date="2026-09-18",
        ),
        now=NOW,
    ).deal
    return company, deal


def _evidence(
    db,
    deal: Deal,
    company: Company,
    *,
    content: str,
    source_id: str,
    occurred_at: str = MONDAY,
    direction: EvidenceDirection = EvidenceDirection.OUTBOUND,
    type: EvidenceType = EvidenceType.EMAIL,
    match_confidence: float = 1.0,
    deal_id: str | None = ...,
) -> Evidence:
    return upsert_evidence(
        db,
        Evidence(
            type=type,
            source="email_files" if type == EvidenceType.EMAIL else "transcripts",
            source_id=source_id,
            company_id=company.id,
            deal_id=deal.id if deal_id is ... else deal_id,
            match_confidence=match_confidence,
            occurred_at=occurred_at,
            direction=direction,
            title="Acme pricing",
            content=content,
        ),
        now=NOW,
    )


def _commitment_candidate(**overrides) -> MemoryCandidate:
    payload = {
        "type": MemoryType.COMMITMENT,
        "subject": "Revised pricing",
        "content": "Sam will send revised pricing to Acme.",
        "direction": MemoryDirection.USER_TO_CUSTOMER,
        "owner_label": "me",
        "due_text": "tomorrow",
        "quote": PRICING_QUOTE,
        "extraction_confidence": 0.6,
    }
    payload.update(overrides)
    return MemoryCandidate(**payload)


def test_corroboration_formula():
    assert corroborate(0.5, 0.5) == 0.75
    assert abs(corroborate(0.6, 0.6) - 0.84) < 1e-12
    chained = 0.1
    for _ in range(100):
        chained = corroborate(chained, 0.1)
    assert chained <= 1.0
    assert chained > 0.99


def test_dedupe_key_update_supports_instead_of_duplicate(db):
    company, deal = _acme_deal(db)
    first = _evidence(db, deal, company, content=PRICING_BODY, source_id="msg-1")
    r1 = ingest_candidates(db, first, [_commitment_candidate()], cfg=CFG, now=NOW)
    assert len(r1.created_ids) == 1
    assert len(list_memories(db, deal_id=deal.id)) == 1

    follow_quote = "I'll send the revised pricing tomorrow as promised."
    follow_body = f"Following up — {follow_quote}"
    second = _evidence(
        db,
        deal,
        company,
        content=follow_body,
        source_id="msg-2",
        occurred_at="2026-09-08T10:00:00Z",
    )
    r2 = ingest_candidates(
        db,
        second,
        [
            _commitment_candidate(
                quote=follow_quote,
                due_text="Friday",
                extraction_confidence=0.6,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    memories = list_memories(db, deal_id=deal.id)
    assert len(memories) == 1
    memory = memories[0]
    assert memory.id == r1.created_ids[0]
    assert memory.id in r2.updated_ids
    assert memory.content == "Sam will send revised pricing to Acme."
    links = list_memory_evidence(db, memory_id=memory.id)
    assert {link.relation for link in links} == {MemoryRelation.SUPPORTS}
    assert {link.evidence_id for link in links} == {first.id, second.id}
    assert abs(memory.confidence - corroborate(0.6, 0.6)) < 1e-12
    # Later explicit due date from the new evidence wins.
    assert memory.due_date == "2026-09-11"


def test_corroboration_maths_on_independent_evidence(db):
    company, deal = _acme_deal(db)
    first = _evidence(db, deal, company, content=PRICING_BODY, source_id="msg-1")
    ingest_candidates(db, first, [_commitment_candidate()], cfg=CFG, now=NOW)
    second_quote = "I'll send the revised pricing tomorrow."
    second = _evidence(
        db,
        deal,
        company,
        content=f"Copying the thread. {second_quote}",
        source_id="msg-2",
        occurred_at="2026-09-08T09:00:00Z",
    )
    ingest_candidates(
        db, second, [_commitment_candidate(quote=second_quote)], cfg=CFG, now=NOW
    )
    memory = list_memories(db, deal_id=deal.id)[0]
    # Two medium beliefs (0.6) combine to 0.84 — a high band.
    assert abs(memory.confidence - 0.84) < 1e-12
    assert memory.confidence >= 0.8


def test_fulfils_sets_fulfilled_and_valid_until(db):
    company, deal = _acme_deal(db)
    outbound = _evidence(db, deal, company, content=PRICING_BODY, source_id="msg-1")
    ingest_candidates(db, outbound, [_commitment_candidate()], cfg=CFG, now=NOW)
    original = list_memories(db, deal_id=deal.id)[0]

    transcript = _evidence(
        db,
        deal,
        company,
        content=RECEIVED_BODY,
        source_id="zoom-1",
        occurred_at="2026-09-13T14:00:00Z",
        direction=EvidenceDirection.UNKNOWN,
        type=EvidenceType.ZOOM_TRANSCRIPT,
    )
    result = ingest_candidates(
        db,
        transcript,
        [
            MemoryCandidate(
                type=MemoryType.FACT,
                subject="Pricing received",
                content="Acme received the revised pricing.",
                quote=RECEIVED_QUOTE,
                extraction_confidence=0.6,
                relation_to_existing=RelationToExisting(
                    relation=MemoryRelation.FULFILS,
                    existing_subject="Revised pricing",
                ),
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    memories = list_memories(db, deal_id=deal.id)
    assert len(memories) == 1
    memory = memories[0]
    assert memory.id == original.id
    assert memory.status == MemoryStatus.FULFILLED
    assert memory.valid_until == transcript.occurred_at
    assert memory.id in result.updated_ids
    links = list_memory_evidence(db, memory_id=memory.id)
    assert any(link.relation == MemoryRelation.FULFILS for link in links)


def test_single_active_supersede_deal_state(db):
    company, deal = _acme_deal(db)
    proposal_quote = "We are at proposal stage with Acme."
    first = _evidence(
        db,
        deal,
        company,
        content=proposal_quote,
        source_id="msg-state-1",
    )
    ingest_candidates(
        db,
        first,
        [
            MemoryCandidate(
                type=MemoryType.DEAL_STATE,
                subject="Proposal",
                content="Deal is in proposal.",
                quote=proposal_quote,
                extraction_confidence=0.9,
                is_inference=False,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    procurement_quote = "Acme has moved this into procurement."
    second = _evidence(
        db,
        deal,
        company,
        content=procurement_quote,
        source_id="msg-state-2",
        occurred_at="2026-09-10T10:00:00Z",
    )
    ingest_candidates(
        db,
        second,
        [
            MemoryCandidate(
                type=MemoryType.DEAL_STATE,
                subject="Procurement",
                content="Deal is in procurement.",
                quote=procurement_quote,
                extraction_confidence=0.9,
                is_inference=False,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    rows = list_memories(db, deal_id=deal.id)
    assert len(rows) == 2
    active = [m for m in rows if m.status == MemoryStatus.ACTIVE]
    superseded = [m for m in rows if m.status == MemoryStatus.SUPERSEDED]
    assert len(active) == 1
    assert active[0].subject == "Procurement"
    assert len(superseded) == 1
    assert superseded[0].subject == "Proposal"
    assert superseded[0].superseded_by_id == active[0].id
    assert superseded[0].valid_until == second.occurred_at


def test_high_confidence_conflict_opens_review_item(db):
    company, deal = _acme_deal(db)
    close_quote = "Close date is 30 September."
    first = _evidence(
        db, deal, company, content=close_quote, source_id="msg-close-1"
    )
    ingest_candidates(
        db,
        first,
        [
            MemoryCandidate(
                type=MemoryType.FACT,
                subject="Close date",
                content="Close date is 30 September.",
                quote=close_quote,
                extraction_confidence=0.9,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    original = list_memories(db, deal_id=deal.id)[0]
    assert original.confidence >= 0.8

    other_quote = "Close date is 15 October, not September."
    second = _evidence(
        db,
        deal,
        company,
        content=other_quote,
        source_id="msg-close-2",
        occurred_at="2026-09-10T10:00:00Z",
    )
    ingest_candidates(
        db,
        second,
        [
            MemoryCandidate(
                type=MemoryType.FACT,
                subject="Close date October",
                content="Close date is 15 October.",
                quote=other_quote,
                extraction_confidence=0.9,
                relation_to_existing=RelationToExisting(
                    relation=MemoryRelation.CONTRADICTS,
                    existing_subject="Close date",
                ),
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    rows = list_memories(db, deal_id=deal.id)
    assert len(rows) == 2
    assert all(m.status == MemoryStatus.ACTIVE for m in rows)
    reviews = list_review_items(db)
    assert len(reviews) == 1
    assert reviews[0].kind == ReviewKind.CONFLICTING_MEMORY
    assert reviews[0].memory_id == original.id
    payload = json.loads(reviews[0].candidates_json)
    assert {row["id"] for row in payload} == {rows[0].id, rows[1].id}


def test_user_to_customer_commitment_creates_tier1_action(db):
    company, deal = _acme_deal(db)
    evidence = _evidence(db, deal, company, content=PRICING_BODY, source_id="msg-1")
    result = ingest_candidates(
        db, evidence, [_commitment_candidate()], cfg=CFG, now=NOW
    )
    memory = list_memories(db, deal_id=deal.id)[0]
    assert memory.direction == MemoryDirection.USER_TO_CUSTOMER
    assert len(result.actions) == 1
    action = result.actions[0]
    assert action.type == ActionType.COMMITMENT
    assert action.tier == 1
    assert action.origin_memory_id == memory.id
    assert action.source == "memory"
    assert action.source_id == memory.id
    listed = list_actions(db, deal_id=deal.id)
    assert [a.id for a in listed] == [action.id]


def test_customer_internal_commitment_creates_no_action(db):
    company, deal = _acme_deal(db)
    quote = "I'll speak to procurement this week."
    evidence = _evidence(
        db,
        deal,
        company,
        content=quote,
        source_id="msg-internal",
        direction=EvidenceDirection.INBOUND,
    )
    ingest_candidates(
        db,
        evidence,
        [
            _commitment_candidate(
                subject="Speak to procurement",
                content="Acme will speak to procurement.",
                quote=quote,
                direction=MemoryDirection.CUSTOMER_TO_USER,
                due_text=None,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    memory = list_memories(db, deal_id=deal.id)[0]
    assert memory.direction == MemoryDirection.CUSTOMER_INTERNAL
    assert list_actions(db, deal_id=deal.id) == []


def test_rules_extractor_caps_confidence_and_uses_exact_quotes(db):
    company, deal = _acme_deal(db)
    evidence = _evidence(
        db,
        deal,
        company,
        content=PRICING_BODY,
        source_id="msg-rules",
        direction=EvidenceDirection.OUTBOUND,
    )
    candidates = extract_rules(evidence)
    assert candidates
    for item in candidates:
        assert item.extraction_confidence <= RULES_CONFIDENCE_CAP
        assert item.quote
        assert item.quote in (evidence.content or "")
        assert verify_quote(item.quote, evidence)

    types = {item.type for item in candidates}
    assert MemoryType.COMMITMENT in types
    assert MemoryType.DEAL_STATE in types
    commitment = next(c for c in candidates if c.type == MemoryType.COMMITMENT)
    assert commitment.direction == MemoryDirection.USER_TO_CUSTOMER
    assert commitment.due_text == "tomorrow"
    state = next(c for c in candidates if c.type == MemoryType.DEAL_STATE)
    assert state.is_inference is True
    assert state.subject == "Procurement"

    result = ingest_candidates(db, evidence, candidates, cfg=CFG, now=NOW)
    assert result.dropped == 0
    memories = list_memories(db, deal_id=deal.id)
    assert any(m.type == MemoryType.COMMITMENT for m in memories)
    assert any(m.type == MemoryType.DEAL_STATE for m in memories)
    for memory in memories:
        for link in list_memory_evidence(db, memory_id=memory.id):
            if link.quote:
                assert link.quote in (evidence.content or "")


def test_unverified_quote_is_dropped(db):
    company, deal = _acme_deal(db)
    evidence = _evidence(
        db, deal, company, content=PRICING_BODY, source_id="msg-hallucination"
    )
    result = ingest_candidates(
        db,
        evidence,
        [
            MemoryCandidate(
                type=MemoryType.FACT,
                subject="Price agreed",
                content="Customer agreed to 60k.",
                quote="Customer agreed to 60k.",
                extraction_confidence=0.99,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    assert result.dropped == 1
    assert list_memories(db, deal_id=deal.id) == []


def test_unmatched_evidence_produces_no_memories(db):
    company, deal = _acme_deal(db)
    evidence = _evidence(
        db,
        deal,
        company,
        content=PRICING_BODY,
        source_id="msg-unmatched",
        deal_id=None,
    )
    result = ingest_candidates(
        db, evidence, [_commitment_candidate()], cfg=CFG, now=NOW
    )
    assert result.dropped == 1
    assert list_memories(db) == []


def test_transcript_fuzzy_quote_accepted(db):
    company, deal = _acme_deal(db)
    body = "Ada: Ill send the revised pricing tomorrow"
    evidence = _evidence(
        db,
        deal,
        company,
        content=body,
        source_id="zoom-fuzzy",
        type=EvidenceType.ZOOM_TRANSCRIPT,
        direction=EvidenceDirection.OUTBOUND,
    )
    quote = "I'll send the revised pricing tomorrow."
    assert quote not in body
    result = ingest_candidates(
        db,
        evidence,
        [_commitment_candidate(quote=quote, due_text="tomorrow")],
        cfg=CFG,
        now=NOW,
    )
    assert result.dropped == 0
    assert len(result.created_ids) == 1


def test_due_date_resolves_relative_to_evidence_not_now(db, frozen_now):
    company, deal = _acme_deal(db)
    evidence = _evidence(
        db,
        deal,
        company,
        content=PRICING_BODY,
        source_id="msg-monday",
        occurred_at=MONDAY,
    )
    ingest_candidates(db, evidence, [_commitment_candidate()], cfg=CFG, now=NOW)
    memory = list_memories(db, deal_id=deal.id)[0]
    # occurred_at is Monday 7 Sep; "tomorrow" → 8 Sep, not frozen_now (14 Sep).
    assert memory.due_date == "2026-09-08"
    assert frozen_now.strftime("%Y-%m-%d") == "2026-09-14"


def test_direction_override_from_outbound_first_person(db):
    company, deal = _acme_deal(db)
    evidence = _evidence(
        db,
        deal,
        company,
        content=PRICING_BODY,
        source_id="msg-dir",
        direction=EvidenceDirection.OUTBOUND,
    )
    ingest_candidates(
        db,
        evidence,
        [
            _commitment_candidate(
                direction=MemoryDirection.CUSTOMER_TO_USER,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    memory = list_memories(db, deal_id=deal.id)[0]
    assert memory.direction == MemoryDirection.USER_TO_CUSTOMER


def test_low_confidence_contradiction_supersedes_when_newer_is_stronger(db):
    company, deal = _acme_deal(db)
    first_quote = "They mentioned a June close once."
    first = _evidence(db, deal, company, content=first_quote, source_id="msg-low-1")
    ingest_candidates(
        db,
        first,
        [
            MemoryCandidate(
                type=MemoryType.FACT,
                subject="Close date",
                content="Possible June close.",
                quote=first_quote,
                extraction_confidence=0.4,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    original = list_memories(db, deal_id=deal.id)[0]
    assert original.confidence < 0.8

    second_quote = "Close date is confirmed as 18 September."
    second = _evidence(
        db,
        deal,
        company,
        content=second_quote,
        source_id="msg-low-2",
        occurred_at="2026-09-10T10:00:00Z",
    )
    ingest_candidates(
        db,
        second,
        [
            MemoryCandidate(
                type=MemoryType.FACT,
                subject="Close date September",
                content="Close date is 18 September.",
                quote=second_quote,
                extraction_confidence=0.9,
                relation_to_existing=RelationToExisting(
                    relation=MemoryRelation.CONTRADICTS,
                    existing_subject="Close date",
                ),
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    rows = {m.id: m for m in list_memories(db, deal_id=deal.id)}
    assert rows[original.id].status == MemoryStatus.SUPERSEDED
    winner = next(m for m in rows.values() if m.status == MemoryStatus.ACTIVE)
    assert rows[original.id].superseded_by_id == winner.id
    assert list_review_items(db) == []


def test_inferred_without_quote_capped_and_not_observed(db):
    company, deal = _acme_deal(db)
    evidence = _evidence(
        db, deal, company, content=PRICING_BODY, source_id="msg-inferred"
    )
    ingest_candidates(
        db,
        evidence,
        [
            MemoryCandidate(
                type=MemoryType.DEAL_STATE,
                subject="Procurement",
                content="Likely in procurement.",
                quote="",
                extraction_confidence=0.9,
                is_inference=True,
            )
        ],
        cfg=CFG,
        now=NOW,
    )
    memory = list_memories(db, deal_id=deal.id)[0]
    assert memory.basis == MemoryBasis.INFERRED
    assert memory.confidence <= 0.5


def test_ingest_marks_deal_summary_stale(db):
    company, deal = _acme_deal(db)
    evidence = _evidence(db, deal, company, content=PRICING_BODY, source_id="msg-stale")
    ingest_candidates(db, evidence, [_commitment_candidate()], cfg=CFG, now=NOW)
    refreshed = get_deal(db, deal.id)
    assert refreshed.summary_stale is True
    assert refreshed.last_activity_at == evidence.occurred_at


def test_objection_rules_confidence_is_0_4():
    evidence = Evidence(
        type=EvidenceType.EMAIL,
        source="email_files",
        occurred_at=MONDAY,
        direction=EvidenceDirection.INBOUND,
        content="Ada at Acme Ltd: this is too expensive versus a competitor.",
    )
    items = extract_rules(evidence)
    objections = [i for i in items if i.type == MemoryType.OBJECTION]
    assert objections
    assert all(i.extraction_confidence == 0.4 for i in objections)
    assert all(i.quote in evidence.content for i in objections)
