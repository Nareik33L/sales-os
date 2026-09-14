"""Memory lifecycle: quote check → create-or-update → relations → actions.

Public entry point: ``ingest_candidates`` (docs/04 §§2–7). Nothing here
calls an AI provider; candidates arrive already proposed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date

from core.memory.candidates import (
    IngestResult,
    MemoryCandidate,
    MemoryIngestConfig,
)
from core.memory.confidence import (
    BAND_HIGH,
    INFERRED_NO_QUOTE_CAP,
    combine_confidence,
    corroborate,
    match_confidence,
    source_reliability as reliability_of,
)
from core.memory.dates import parse_occurred_at, resolve_due_date, user_timezone
from core.memory.keys import (
    DEDUPE_THRESHOLD,
    RELATION_THRESHOLD,
    make_dedupe_key,
    subject_similarity,
    type_value,
)
from core.memory.quotes import verify_quote
from core.models.action import tier_for_action_type
from core.models.common import utcnow
from core.models.repos import (
    add_action_evidence,
    add_memory_evidence,
    get_deal,
    list_memories,
    list_memory_evidence,
    list_review_items,
    upsert_action,
    upsert_deal,
    upsert_memory,
    upsert_review_item,
)
from core.models.schemas import (
    Action,
    ActionType,
    Evidence,
    EvidenceDirection,
    EvidenceType,
    Memory,
    MemoryBasis,
    MemoryDirection,
    MemoryEvidence,
    MemoryRelation,
    MemoryStatus,
    MemoryType,
    ReviewItem,
    ReviewKind,
    ReviewStatus,
)

SINGLE_ACTIVE_TYPES = frozenset({MemoryType.DEAL_STATE, MemoryType.NEXT_STEP})

_FIRST_PERSON_RE = re.compile(
    r"\b(i(?:'m|'ll|'ve| am| will| can| cannot| won't)|"
    r"we(?:'re|'ll| will| can)|let me)\b",
    re.IGNORECASE,
)
_INTERNAL_RE = re.compile(
    r"\b(procurement|legal|internally|infosec|security review)\b",
    re.IGNORECASE,
)

_ACTION_SOURCE = "memory"


def _as_candidate(raw: MemoryCandidate | Mapping) -> MemoryCandidate:
    if isinstance(raw, MemoryCandidate):
        return raw
    return MemoryCandidate.model_validate(dict(raw))


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _is_user_input(evidence: Evidence) -> bool:
    return _enum_str(evidence.type) == EvidenceType.USER_INPUT.value


def _basis_for(
    candidate: MemoryCandidate, evidence: Evidence, *, quote_ok: bool
) -> MemoryBasis:
    if _is_user_input(evidence) and not candidate.is_inference:
        return MemoryBasis.STATED_BY_USER
    if candidate.is_inference or not quote_ok:
        return MemoryBasis.INFERRED
    return MemoryBasis.OBSERVED


def _override_direction(
    candidate: MemoryCandidate, evidence: Evidence, quote: str
) -> MemoryDirection | None:
    if candidate.type != MemoryType.COMMITMENT:
        return candidate.direction
    text = quote or candidate.content or ""
    if not _FIRST_PERSON_RE.search(text):
        return candidate.direction
    ev = evidence.direction
    if ev is None:
        return candidate.direction
    ev_val = _enum_str(ev)
    if ev_val == EvidenceDirection.OUTBOUND.value:
        return MemoryDirection.USER_TO_CUSTOMER
    if ev_val == EvidenceDirection.INBOUND.value:
        if _INTERNAL_RE.search(text):
            return MemoryDirection.CUSTOMER_INTERNAL
        return MemoryDirection.CUSTOMER_TO_USER
    return candidate.direction


def _local_today(now: str, timezone_name: str | None) -> date:
    tz = user_timezone(timezone_name)
    return parse_occurred_at(now).astimezone(tz).date()


def _is_overdue(due_date: str | None, now: str, timezone_name: str | None) -> bool:
    if not due_date:
        return False
    try:
        return date.fromisoformat(due_date) < _local_today(now, timezone_name)
    except ValueError:
        return False


def _later_due(existing: str | None, incoming: str | None) -> str | None:
    if incoming is None:
        return existing
    if existing is None:
        return incoming
    return incoming if incoming > existing else existing


def _active_memories(conn: sqlite3.Connection, deal_id: str) -> list[Memory]:
    return list_memories(conn, deal_id=deal_id, status=MemoryStatus.ACTIVE.value)


def _best_match(
    memories: Sequence[Memory],
    subject: str,
    *,
    memory_type: MemoryType | None,
    threshold: float,
) -> Memory | None:
    best: Memory | None = None
    best_score = 0.0
    want_type = type_value(memory_type) if memory_type is not None else None
    for mem in memories:
        if mem.status != MemoryStatus.ACTIVE:
            continue
        if want_type is not None and type_value(mem.type) != want_type:
            continue
        score = subject_similarity(mem.subject, subject)
        if score >= threshold and score > best_score:
            best = mem
            best_score = score
    return best


def _link(
    conn: sqlite3.Connection,
    memory_id: str,
    evidence: Evidence,
    *,
    quote: str | None,
    relation: MemoryRelation,
    now: str,
) -> MemoryEvidence | None:
    stored_quote = quote or None
    if stored_quote and not verify_quote(stored_quote, evidence):
        stored_quote = None
    existing = list_memory_evidence(conn, memory_id=memory_id, evidence_id=evidence.id)
    for link in existing:
        if link.relation == relation:
            return link
    try:
        return add_memory_evidence(
            conn,
            memory_id,
            evidence.id,
            quote=stored_quote,
            relation=relation,
            created_at=now,
        )
    except sqlite3.IntegrityError:
        return None


def _already_supports(conn: sqlite3.Connection, memory_id: str, evidence_id: str) -> bool:
    for link in list_memory_evidence(conn, memory_id=memory_id, evidence_id=evidence_id):
        if link.relation == MemoryRelation.SUPPORTS:
            return True
    return False


def _touch_deal(conn: sqlite3.Connection, evidence: Evidence, now: str) -> None:
    if not evidence.deal_id:
        return
    deal = get_deal(conn, evidence.deal_id)
    if deal is None:
        return
    updates: dict = {"summary_stale": True}
    if not deal.last_activity_at or evidence.occurred_at > deal.last_activity_at:
        updates["last_activity_at"] = evidence.occurred_at
    upsert_deal(conn, deal.model_copy(update=updates), now=now)


def _supersede(
    conn: sqlite3.Connection,
    old: Memory,
    new: Memory,
    evidence: Evidence,
    *,
    quote: str | None,
    now: str,
) -> Memory:
    updated = old.model_copy(
        update={
            "status": MemoryStatus.SUPERSEDED,
            "superseded_by_id": new.id,
            "valid_until": evidence.occurred_at,
            "updated_at": now,
        }
    )
    saved = upsert_memory(conn, updated, now=now)
    _link(
        conn,
        saved.id,
        evidence,
        quote=quote,
        relation=MemoryRelation.SUPERSEDES,
        now=now,
    )
    return saved


def _fulfil(
    conn: sqlite3.Connection,
    existing: Memory,
    evidence: Evidence,
    *,
    quote: str | None,
    now: str,
) -> Memory:
    saved = upsert_memory(
        conn,
        existing.model_copy(
            update={
                "status": MemoryStatus.FULFILLED,
                "valid_until": evidence.occurred_at,
                "updated_at": now,
            }
        ),
        now=now,
    )
    _link(
        conn,
        saved.id,
        evidence,
        quote=quote,
        relation=MemoryRelation.FULFILS,
        now=now,
    )
    return saved


def _supports_update(
    conn: sqlite3.Connection,
    existing: Memory,
    evidence: Evidence,
    *,
    quote: str | None,
    new_confidence: float,
    due_date: str | None,
    due_text: str | None,
    now: str,
) -> Memory:
    updates: dict = {"updated_at": now}
    if not _already_supports(conn, existing.id, evidence.id):
        updates["confidence"] = corroborate(existing.confidence, new_confidence)
    later = _later_due(existing.due_date, due_date)
    if later != existing.due_date:
        updates["due_date"] = later
        if due_text:
            updates["due_text"] = due_text
    saved = upsert_memory(conn, existing.model_copy(update=updates), now=now)
    _link(
        conn,
        saved.id,
        evidence,
        quote=quote,
        relation=MemoryRelation.SUPPORTS,
        now=now,
    )
    return saved


def _open_review(
    conn: sqlite3.Connection,
    *,
    kind: ReviewKind,
    question: str,
    evidence: Evidence,
    memory: Memory | None,
    candidates: list[dict],
    now: str,
) -> ReviewItem:
    for existing in list_review_items(conn, status=ReviewStatus.OPEN.value):
        if (
            existing.kind == kind
            and existing.evidence_id == evidence.id
            and (memory is None or existing.memory_id == memory.id)
        ):
            return existing
    return upsert_review_item(
        conn,
        ReviewItem(
            kind=kind,
            status=ReviewStatus.OPEN,
            question=question,
            evidence_id=evidence.id,
            memory_id=memory.id if memory else None,
            deal_id=evidence.deal_id,
            candidates_json=json.dumps(candidates),
            created_at=now,
        ),
        now=now,
    )


def _quote_for(conn: sqlite3.Connection, memory: Memory) -> str | None:
    links = list_memory_evidence(conn, memory_id=memory.id)
    for link in links:
        if link.quote:
            return link.quote
    return None


def _create_memory(
    conn: sqlite3.Connection,
    *,
    candidate: MemoryCandidate,
    evidence: Evidence,
    basis: MemoryBasis,
    confidence: float,
    direction: MemoryDirection | None,
    due_date: str | None,
    now: str,
    created_by: str,
) -> Memory:
    owner = candidate.owner_label
    if direction == MemoryDirection.USER_TO_CUSTOMER and not owner:
        owner = "me"
    memory = Memory(
        type=candidate.type,
        basis=basis,
        status=MemoryStatus.ACTIVE,
        subject=candidate.subject,
        content=candidate.content,
        dedupe_key=make_dedupe_key(candidate.type, evidence.deal_id, candidate.subject),
        company_id=evidence.company_id,
        contact_id=evidence.contact_id,
        deal_id=evidence.deal_id,
        direction=direction,
        owner_label=owner,
        due_date=due_date,
        due_text=candidate.due_text,
        confidence=confidence,
        valid_from=evidence.occurred_at,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    return upsert_memory(conn, memory, now=now)


def _maybe_commitment_action(
    conn: sqlite3.Connection,
    memory: Memory,
    evidence: Evidence,
    *,
    now: str,
    timezone_name: str | None,
) -> Action | None:
    if memory.type != MemoryType.COMMITMENT:
        return None
    if memory.status != MemoryStatus.ACTIVE:
        return None
    direction = memory.direction
    if direction == MemoryDirection.CUSTOMER_INTERNAL:
        return None
    if direction == MemoryDirection.CUSTOMER_TO_USER:
        if not _is_overdue(memory.due_date, now, timezone_name):
            return None
        who = memory.owner_label or "them"
        title = f"Chase {who} for {memory.subject}"
    elif direction == MemoryDirection.USER_TO_CUSTOMER:
        title = memory.content if memory.content else memory.subject
    else:
        return None

    action = upsert_action(
        conn,
        Action(
            title=title[:200],
            description=memory.content,
            type=ActionType.COMMITMENT,
            tier=tier_for_action_type(ActionType.COMMITMENT),
            source=_ACTION_SOURCE,
            source_id=memory.id,
            origin_memory_id=memory.id,
            company_id=memory.company_id,
            deal_id=memory.deal_id,
            contact_id=memory.contact_id,
            due_date=memory.due_date,
        ),
        now=now,
    )
    try:
        add_action_evidence(conn, action.id, evidence.id)
    except sqlite3.IntegrityError:
        pass
    return action


def _single_active_supersede(
    conn: sqlite3.Connection,
    created: Memory,
    evidence: Evidence,
    *,
    quote: str | None,
    now: str,
) -> list[Memory]:
    if created.type not in SINGLE_ACTIVE_TYPES:
        return []
    superseded: list[Memory] = []
    if created.deal_id is None:
        return superseded
    for other in _active_memories(conn, created.deal_id):
        if other.id == created.id:
            continue
        if other.type != created.type:
            continue
        superseded.append(
            _supersede(conn, other, created, evidence, quote=quote, now=now)
        )
    return superseded


def ingest_candidates(
    conn: sqlite3.Connection,
    evidence: Evidence,
    candidates: Sequence[MemoryCandidate | Mapping],
    *,
    cfg: MemoryIngestConfig | None = None,
    now: str | None = None,
) -> IngestResult:
    """Apply doc 04 lifecycle rules to proposed memories for one evidence row.

    Unmatched evidence (``deal_id`` null) produces no memories. Every
    OBSERVED insert has a quote verified against ``evidence.content``.
    """
    cfg = cfg or MemoryIngestConfig()
    now = now or utcnow()
    result = IngestResult()

    if evidence.deal_id is None:
        result.dropped = len(list(candidates))
        return result

    source_rel = (
        cfg.source_reliability
        if cfg.source_reliability is not None
        else reliability_of(evidence)
    )
    match_c = match_confidence(evidence)
    created_by = "user" if _is_user_input(evidence) else cfg.created_by
    tz_name = cfg.timezone

    parsed: list[MemoryCandidate] = [_as_candidate(c) for c in candidates]

    for candidate in parsed:
        quote = (candidate.quote or "").strip()
        quote_ok = bool(quote) and verify_quote(quote, evidence)
        if quote and not quote_ok:
            result.dropped += 1
            continue
        if not quote and not candidate.is_inference and not _is_user_input(evidence):
            result.dropped += 1
            continue

        basis = _basis_for(candidate, evidence, quote_ok=quote_ok)
        extraction = max(0.0, min(1.0, float(candidate.extraction_confidence)))
        confidence = combine_confidence(source_rel, extraction, match_c)
        if basis == MemoryBasis.STATED_BY_USER:
            confidence = 1.0
        elif not quote_ok:
            confidence = min(confidence, INFERRED_NO_QUOTE_CAP)
            basis = MemoryBasis.INFERRED

        due_date = resolve_due_date(
            candidate.due_text, evidence.occurred_at, timezone_name=tz_name
        )
        direction = _override_direction(candidate, evidence, quote)
        stored_quote = quote if quote_ok else None

        active = _active_memories(conn, evidence.deal_id)
        rel = candidate.relation_to_existing
        conflict_target: Memory | None = None
        handled = False
        if rel is not None:
            target = _best_match(
                active,
                rel.existing_subject,
                memory_type=None,
                threshold=RELATION_THRESHOLD,
            )
            if target is None:
                fact = MemoryCandidate(
                    type=MemoryType.FACT,
                    subject=candidate.subject,
                    content=candidate.content,
                    quote=candidate.quote,
                    extraction_confidence=extraction,
                    is_inference=candidate.is_inference,
                )
                created = _create_memory(
                    conn,
                    candidate=fact,
                    evidence=evidence,
                    basis=basis if basis != MemoryBasis.OBSERVED or quote_ok else MemoryBasis.INFERRED,
                    confidence=confidence,
                    direction=None,
                    due_date=due_date,
                    now=now,
                    created_by=created_by,
                )
                link = _link(
                    conn,
                    created.id,
                    evidence,
                    quote=stored_quote,
                    relation=MemoryRelation.SUPPORTS,
                    now=now,
                )
                result.memories.append(created)
                result.created_ids.append(created.id)
                if link:
                    result.links.append(link)
                review = _open_review(
                    conn,
                    kind=ReviewKind.CONFIRM_MEMORY,
                    question=(
                        f"Does {stored_quote!r} mean {rel.existing_subject!r} is done?"
                    ),
                    evidence=evidence,
                    memory=created,
                    candidates=[
                        {
                            "id": None,
                            "label": rel.existing_subject,
                            "reason": "no active memory ≥ 0.8",
                        }
                    ],
                    now=now,
                )
                result.review_items.append(review)
                handled = True
            elif rel.relation == MemoryRelation.FULFILS:
                saved = _fulfil(
                    conn, target, evidence, quote=stored_quote, now=now
                )
                result.memories.append(saved)
                result.updated_ids.append(saved.id)
                handled = True
            elif rel.relation == MemoryRelation.SUPPORTS:
                saved = _supports_update(
                    conn,
                    target,
                    evidence,
                    quote=stored_quote,
                    new_confidence=confidence,
                    due_date=due_date,
                    due_text=candidate.due_text,
                    now=now,
                )
                result.memories.append(saved)
                result.updated_ids.append(saved.id)
                action = _maybe_commitment_action(
                    conn, saved, evidence, now=now, timezone_name=tz_name
                )
                if action:
                    result.actions.append(action)
                handled = True
            elif rel.relation == MemoryRelation.SUPERSEDES:
                created = _create_memory(
                    conn,
                    candidate=candidate,
                    evidence=evidence,
                    basis=basis,
                    confidence=confidence,
                    direction=direction,
                    due_date=due_date,
                    now=now,
                    created_by=created_by,
                )
                link = _link(
                    conn,
                    created.id,
                    evidence,
                    quote=stored_quote,
                    relation=MemoryRelation.SUPPORTS,
                    now=now,
                )
                _supersede(
                    conn, target, created, evidence, quote=stored_quote, now=now
                )
                result.memories.append(created)
                result.created_ids.append(created.id)
                if link:
                    result.links.append(link)
                action = _maybe_commitment_action(
                    conn, created, evidence, now=now, timezone_name=tz_name
                )
                if action:
                    result.actions.append(action)
                handled = True
            elif rel.relation == MemoryRelation.CONTRADICTS:
                handled = False  # fall through to conflict after create
                conflict_target = target
            else:
                conflict_target = None
        else:
            conflict_target = None

        if handled:
            continue

        # Dedupe-key create-or-update (same type + deal, fuzzy ≥ 0.9).
        if conflict_target is None:
            match = _best_match(
                active,
                candidate.subject,
                memory_type=candidate.type,
                threshold=DEDUPE_THRESHOLD,
            )
            if match is not None and rel is None:
                saved = _supports_update(
                    conn,
                    match,
                    evidence,
                    quote=stored_quote,
                    new_confidence=confidence,
                    due_date=due_date,
                    due_text=candidate.due_text,
                    now=now,
                )
                result.memories.append(saved)
                result.updated_ids.append(saved.id)
                action = _maybe_commitment_action(
                    conn, saved, evidence, now=now, timezone_name=tz_name
                )
                if action:
                    result.actions.append(action)
                continue

        created = _create_memory(
            conn,
            candidate=candidate,
            evidence=evidence,
            basis=basis,
            confidence=confidence,
            direction=direction,
            due_date=due_date,
            now=now,
            created_by=created_by,
        )
        link = _link(
            conn,
            created.id,
            evidence,
            quote=stored_quote,
            relation=(
                MemoryRelation.CONTRADICTS
                if rel is not None and rel.relation == MemoryRelation.CONTRADICTS
                else MemoryRelation.SUPPORTS
            ),
            now=now,
        )
        result.memories.append(created)
        result.created_ids.append(created.id)
        if link:
            result.links.append(link)

        if rel is not None and rel.relation == MemoryRelation.CONTRADICTS:
            target = conflict_target or _best_match(
                active,
                rel.existing_subject,
                memory_type=None,
                threshold=RELATION_THRESHOLD,
            )
            if target is not None:
                incoming_is_user = created.basis == MemoryBasis.STATED_BY_USER
                existing_is_user = target.basis == MemoryBasis.STATED_BY_USER
                if incoming_is_user and not existing_is_user:
                    _supersede(
                        conn, target, created, evidence, quote=stored_quote, now=now
                    )
                elif (not incoming_is_user) and existing_is_user:
                    _supersede(
                        conn, created, target, evidence, quote=stored_quote, now=now
                    )
                    result.created_ids = [i for i in result.created_ids if i != created.id]
                    result.updated_ids.append(created.id)
                elif target.confidence >= BAND_HIGH or created.confidence <= target.confidence:
                    # High-confidence contradiction, or newer is not stronger:
                    # both stay ACTIVE and a review item is opened.
                    review = _open_review(
                        conn,
                        kind=ReviewKind.CONFLICTING_MEMORY,
                        question=(
                            f"⚠ conflicting information about {target.subject}"
                        ),
                        evidence=evidence,
                        memory=target,
                        candidates=[
                            {
                                "id": target.id,
                                "label": target.subject,
                                "confidence": target.confidence,
                                "quote": _quote_for(conn, target),
                            },
                            {
                                "id": created.id,
                                "label": created.subject,
                                "confidence": created.confidence,
                                "quote": stored_quote,
                            },
                        ],
                        now=now,
                    )
                    result.review_items.append(review)
                else:
                    _supersede(
                        conn, target, created, evidence, quote=stored_quote, now=now
                    )
        elif created.basis in {MemoryBasis.OBSERVED, MemoryBasis.STATED_BY_USER}:
            _single_active_supersede(
                conn, created, evidence, quote=stored_quote, now=now
            )

        action = _maybe_commitment_action(
            conn, created, evidence, now=now, timezone_name=tz_name
        )
        if action:
            result.actions.append(action)

    if result.created_ids or result.updated_ids:
        _touch_deal(conn, evidence, now)
    return result
