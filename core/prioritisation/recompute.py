"""Persist priority scores after a refresh or feedback event.

Scoring stays pure (``engine.py``). This module loads YAML once and writes
``deals`` / ``actions`` via the models repositories.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config.loaders import PriorityWeightsConfig, load_priority_weights
from core.models.action import tier_for_action_type
from core.models.common import utcnow
from core.models.repos import (
    get_action_by_source_id,
    get_company,
    list_actions,
    list_deals,
    list_meetings,
    list_memories,
    list_prospecting_items,
    list_review_items,
    upsert_action,
    upsert_deal,
    upsert_review_item,
)
from core.models.schemas import (
    Action,
    ActionStatus,
    ActionType,
    Deal,
    Meeting,
    MeetingStatus,
    Memory,
    MemoryDirection,
    MemoryStatus,
    MemoryType,
    ReviewItem,
    ReviewKind,
    ReviewStatus,
)
from core.prioritisation.engine import (
    RankedAction,
    ScoreBreakdown,
    _enum_str,
    format_local_hm,
    local_date_of,
    local_today,
    parse_date,
    rank_actions,
    score_deal,
    user_timezone,
)

SOURCE = "prioritisation"


@dataclass
class RecomputeResult:
    deal_scores: dict[str, ScoreBreakdown] = field(default_factory=dict)
    ranked: list[RankedAction] = field(default_factory=list)
    created_action_ids: list[str] = field(default_factory=list)


def _stamp(now: datetime | None) -> str:
    if now is None:
        return utcnow()
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_strategic(conn: sqlite3.Connection, deal: Deal) -> bool:
    if not deal.company_id:
        return False
    company = get_company(conn, deal.company_id)
    return bool(company and company.is_strategic)


def _ensure_close_date_hygiene(
    conn: sqlite3.Connection,
    deal: Deal,
    *,
    today,
    now: str,
    cfg: PriorityWeightsConfig,
) -> Action | None:
    close = parse_date(deal.close_date)
    if close is None or close >= today or deal.is_closed:
        return None
    source_id = f"close-date:{deal.id}"
    existing = get_action_by_source_id(conn, SOURCE, source_id)
    if existing and _enum_str(existing.status) == ActionStatus.OPEN.value:
        return None
    label = deal.company_name or deal.name
    action = upsert_action(
        conn,
        Action(
            title=f"Update close date for {label}",
            type=ActionType.DATA_HYGIENE,
            source=SOURCE,
            source_id=source_id,
            deal_id=deal.id,
            company_id=deal.company_id,
            due_date=today.isoformat(),
        ),
        now=now,
        tier_by_type=cfg.action.tier_by_type,
    )
    already = any(
        item.deal_id == deal.id
        and _enum_str(item.kind) == ReviewKind.CLOSE_DATE_PASSED.value
        for item in list_review_items(conn, status=ReviewStatus.OPEN)
    )
    if not already:
        upsert_review_item(
            conn,
            ReviewItem(
                kind=ReviewKind.CLOSE_DATE_PASSED,
                status=ReviewStatus.OPEN,
                question=(
                    f"Close date for {label} has passed ({close.isoformat()}). "
                    "Update it?"
                ),
                deal_id=deal.id,
            ),
            now=now,
        )
    return action


def _ensure_meeting_prep(
    conn: sqlite3.Connection,
    deal: Deal,
    meeting: Meeting,
    *,
    today,
    now: str,
    tz: ZoneInfo | str | None,
    cfg: PriorityWeightsConfig,
    existing: Sequence[Action],
) -> Action | None:
    if _enum_str(meeting.status) in {
        MeetingStatus.CANCELLED.value,
        MeetingStatus.NO_SHOW.value,
    }:
        return None
    start = local_date_of(meeting.start_at, tz=tz)
    if start != today:
        return None
    for action in existing:
        if _enum_str(action.type) != ActionType.MEETING_PREP.value:
            continue
        if _enum_str(action.status) != ActionStatus.OPEN.value:
            continue
        if action.meeting_id == meeting.id:
            return None
    source_id = f"meeting-prep:{meeting.id}"
    if get_action_by_source_id(conn, SOURCE, source_id):
        return None
    label = deal.company_name or deal.name
    stamp = format_local_hm(meeting.start_at, tz=tz)
    title = f"Prepare for {label} {stamp}".rstrip()
    return upsert_action(
        conn,
        Action(
            title=title,
            type=ActionType.MEETING_PREP,
            source=SOURCE,
            source_id=source_id,
            deal_id=deal.id,
            company_id=deal.company_id,
            meeting_id=meeting.id,
            due_date=today.isoformat(),
        ),
        now=now,
        tier_by_type=cfg.action.tier_by_type,
    )


def _ensure_chase(
    conn: sqlite3.Connection,
    deal: Deal,
    memory: Memory,
    *,
    today,
    now: str,
    cfg: PriorityWeightsConfig,
) -> Action | None:
    if _enum_str(memory.type) != MemoryType.COMMITMENT.value:
        return None
    if _enum_str(memory.status) != MemoryStatus.ACTIVE.value:
        return None
    if _enum_str(memory.direction) != MemoryDirection.CUSTOMER_TO_USER.value:
        return None
    due = parse_date(memory.due_date)
    if due is None or due >= today:
        return None
    source_id = f"chase:{memory.id}"
    if get_action_by_source_id(conn, SOURCE, source_id):
        return None
    who = memory.owner_label or "customer"
    what = memory.subject or "commitment"
    return upsert_action(
        conn,
        Action(
            title=f"Chase {who} for {what}",
            type=ActionType.COMMITMENT,
            source=SOURCE,
            source_id=source_id,
            origin_memory_id=memory.id,
            deal_id=deal.id,
            company_id=deal.company_id,
            due_date=today.isoformat(),
        ),
        now=now,
        tier_by_type=cfg.action.tier_by_type,
    )


def recompute_all(
    conn: sqlite3.Connection,
    *,
    cfg: PriorityWeightsConfig | None = None,
    now: datetime | None = None,
    tz: ZoneInfo | str | None = None,
) -> RecomputeResult:
    """Score every deal and open action; persist breakdown + attention.

    Also creates the side-effect actions docs/03 describes: ``DATA_HYGIENE``
    when a close date has passed, ``MEETING_PREP`` for a meeting today, and a
    chase ``COMMITMENT`` when the customer owes something overdue.
    """
    cfg = cfg or load_priority_weights()
    zone = user_timezone(tz)
    today = local_today(now, zone)
    stamp = _stamp(now)

    result = RecomputeResult()
    created: list[str] = []

    deals = list_deals(conn)
    meetings_by_deal: dict[str, list[Meeting]] = {}
    for meeting in list_meetings(conn):
        if meeting.deal_id:
            meetings_by_deal.setdefault(meeting.deal_id, []).append(meeting)
    memories_by_deal: dict[str, list[Memory]] = {}
    for memory in list_memories(conn):
        if memory.deal_id:
            memories_by_deal.setdefault(memory.deal_id, []).append(memory)

    for deal in deals:
        actions = list_actions(conn, deal_id=deal.id)
        memories = memories_by_deal.get(deal.id, [])
        meetings = meetings_by_deal.get(deal.id, [])
        breakdown = score_deal(
            deal,
            memories,
            meetings,
            cfg,
            actions=actions,
            is_strategic=_is_strategic(conn, deal),
            now=now,
            tz=zone,
        )
        upsert_deal(
            conn,
            deal.model_copy(
                update={
                    "priority_score": breakdown.score,
                    "priority_breakdown_json": breakdown.to_json(),
                    "attention_status": breakdown.attention,
                    "priority_computed_at": stamp,
                }
            ),
            now=stamp,
        )
        result.deal_scores[deal.id] = breakdown
        if deal.is_closed:
            continue
        hygiene = _ensure_close_date_hygiene(
            conn, deal, today=today, now=stamp, cfg=cfg
        )
        if hygiene:
            created.append(hygiene.id)
        for meeting in meetings:
            prep = _ensure_meeting_prep(
                conn,
                deal,
                meeting,
                today=today,
                now=stamp,
                tz=zone,
                cfg=cfg,
                existing=actions,
            )
            if prep:
                created.append(prep.id)
        for memory in memories:
            chase = _ensure_chase(
                conn, deal, memory, today=today, now=stamp, cfg=cfg
            )
            if chase:
                created.append(chase.id)

    prospecting = list_prospecting_items(conn)
    open_actions = list_actions(conn, status=ActionStatus.OPEN)
    ranked = rank_actions(
        open_actions,
        result.deal_scores,
        cfg,
        deals=deals,
        prospecting_items=prospecting,
        now=now,
        tz=zone,
    )
    for index, item in enumerate(ranked, start=1):
        upsert_action(
            conn,
            item.action.model_copy(
                update={
                    "priority_score": item.score,
                    "priority_breakdown_json": item.breakdown.to_json(),
                    "system_rank": index,
                    "tier": tier_for_action_type(
                        item.action.type, tier_by_type=cfg.action.tier_by_type
                    ),
                }
            ),
            now=stamp,
            tier_by_type=cfg.action.tier_by_type,
        )
    result.ranked = ranked
    result.created_action_ids = created
    return result
