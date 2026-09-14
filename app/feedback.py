"""Today feedback controls — write ``user_feedback`` then recompute.

The UI never scores. Boost bounds come from ``priority_weights.yaml``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from config.loaders import load_priority_weights
from core.models import (
    Action,
    ActionStatus,
    ActionType,
    Evidence,
    EvidenceType,
    ExtractionStatus,
    FeedbackEvent,
    MemoryRelation,
    MemoryStatus,
    UserFeedback,
    add_memory_evidence,
    get_action,
    get_company,
    get_deal,
    get_memory,
    upsert_action,
    upsert_evidence,
    upsert_memory,
    upsert_user_feedback,
    utcnow,
)
from core.prioritisation import recompute_all
from core.prioritisation.engine import clamp, local_today, user_timezone

SNOOZE_TOMORROW = "tomorrow"
SNOOZE_THREE_DAYS = "3 days"
SNOOZE_NEXT_WEEK = "next week"
SNOOZE_PICK_DATE = "pick date"
SNOOZE_OPTIONS = (
    SNOOZE_TOMORROW,
    SNOOZE_THREE_DAYS,
    SNOOZE_NEXT_WEEK,
    SNOOZE_PICK_DATE,
)


def snooze_until_date(
    choice: str,
    *,
    today: date | None = None,
    picked: date | None = None,
) -> date:
    day = today or local_today(tz=user_timezone())
    if choice == SNOOZE_TOMORROW:
        return day + timedelta(days=1)
    if choice == SNOOZE_THREE_DAYS:
        return day + timedelta(days=3)
    if choice == SNOOZE_NEXT_WEEK:
        return day + timedelta(days=7)
    if choice == SNOOZE_PICK_DATE:
        if picked is None:
            return day + timedelta(days=1)
        return picked
    return day + timedelta(days=1)


def _context_json(action: Action, extra: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "tier": action.tier,
        "priority_score": action.priority_score,
        "system_rank": action.system_rank,
        "action_type": action.type.value if hasattr(action.type, "value") else str(action.type),
        "due_date": action.due_date,
        "user_boost": action.user_boost,
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, default=str)


def _snapshot(conn: sqlite3.Connection, action: Action) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if action.deal_id:
        deal = get_deal(conn, action.deal_id)
        if deal is not None:
            extra["deal_value_gbp"] = deal.deal_value_gbp
            extra["attention"] = (
                deal.attention_status.value
                if hasattr(deal.attention_status, "value")
                else str(deal.attention_status)
            )
            extra["close_date"] = deal.close_date
            extra["is_strategic"] = False
            if deal.company_id:
                company = get_company(conn, deal.company_id)
                extra["is_strategic"] = bool(company and company.is_strategic)
    return extra


def _record(
    conn: sqlite3.Connection,
    action: Action,
    event: FeedbackEvent,
    *,
    user_priority: int | None,
    manual_override: bool,
    extra: dict[str, Any] | None = None,
) -> UserFeedback:
    context = _snapshot(conn, action)
    if extra:
        context.update(extra)
    return upsert_user_feedback(
        conn,
        UserFeedback(
            action_id=action.id,
            deal_id=action.deal_id,
            event=event,
            system_priority=action.system_rank,
            user_priority=user_priority,
            manual_override=manual_override,
            context_json=_context_json(action, context),
        ),
    )


def apply_complete(
    conn: sqlite3.Connection,
    action_id: str,
    *,
    fulfil_commitment: bool = False,
) -> None:
    action = get_action(conn, action_id)
    if action is None:
        return
    now = utcnow()
    upsert_action(
        conn,
        action.model_copy(
            update={
                "status": ActionStatus.COMPLETED,
                "completed_at": now,
            }
        ),
        now=now,
    )
    extra: dict[str, Any] = {"fulfil_commitment": fulfil_commitment}
    if fulfil_commitment and action.origin_memory_id:
        _fulfil_memory(conn, action, now=now)
        extra["origin_memory_id"] = action.origin_memory_id
    _record(
        conn,
        action,
        FeedbackEvent.COMPLETED,
        user_priority=action.system_rank,
        manual_override=False,
        extra=extra,
    )
    recompute_all(conn)


def apply_snooze(
    conn: sqlite3.Connection,
    action_id: str,
    *,
    until: date,
) -> None:
    action = get_action(conn, action_id)
    if action is None:
        return
    now = utcnow()
    upsert_action(
        conn,
        action.model_copy(
            update={
                "status": ActionStatus.OPEN,
                "snoozed_until": until.isoformat(),
            }
        ),
        now=now,
    )
    _record(
        conn,
        action,
        FeedbackEvent.SNOOZED,
        user_priority=action.system_rank,
        manual_override=True,
        extra={"snoozed_until": until.isoformat()},
    )
    recompute_all(conn)


def apply_boost(conn: sqlite3.Connection, action_id: str, *, up: bool) -> None:
    action = get_action(conn, action_id)
    if action is None:
        return
    adj = load_priority_weights().deal.user_adjustments
    step = int(adj.boost_step_points)
    bound = int(adj.max_boost_points)
    delta = step if up else -step
    new_boost = int(clamp(int(action.user_boost or 0) + delta, -bound, bound))
    now = utcnow()
    upsert_action(
        conn,
        action.model_copy(update={"user_boost": new_boost}),
        now=now,
    )
    _record(
        conn,
        action,
        FeedbackEvent.BOOST_UP if up else FeedbackEvent.BOOST_DOWN,
        user_priority=action.system_rank,
        manual_override=True,
        extra={"user_boost": new_boost},
    )
    recompute_all(conn)


def apply_dismiss(
    conn: sqlite3.Connection,
    action_id: str,
    *,
    reason: str | None = None,
) -> None:
    action = get_action(conn, action_id)
    if action is None:
        return
    now = utcnow()
    cleaned = (reason or "").strip() or None
    upsert_action(
        conn,
        action.model_copy(
            update={
                "status": ActionStatus.DISMISSED,
                "dismissed_at": now,
                "dismissed_reason": cleaned,
            }
        ),
        now=now,
    )
    _record(
        conn,
        action,
        FeedbackEvent.DISMISSED,
        user_priority=action.system_rank,
        manual_override=True,
        extra={"dismissed_reason": cleaned},
    )
    recompute_all(conn)


def apply_add_next_step(conn: sqlite3.Connection, deal_id: str) -> Action | None:
    deal = get_deal(conn, deal_id)
    if deal is None:
        return None
    now = utcnow()
    label = deal.company_name or deal.name
    action = upsert_action(
        conn,
        Action(
            title=f"Next step — {label}",
            type=ActionType.MANUAL,
            source="ui",
            source_id=f"manual-next:{deal.id}:{now}",
            deal_id=deal.id,
            company_id=deal.company_id,
        ),
        now=now,
    )
    recompute_all(conn)
    return action


def _fulfil_memory(conn: sqlite3.Connection, action: Action, *, now: str) -> None:
    memory = get_memory(conn, action.origin_memory_id or "")
    if memory is None:
        return
    if memory.status != MemoryStatus.ACTIVE and str(memory.status) != MemoryStatus.ACTIVE.value:
        return
    evidence = upsert_evidence(
        conn,
        Evidence(
            type=EvidenceType.USER_INPUT,
            source="ui",
            source_id=f"complete:{action.id}:{now}",
            company_id=action.company_id,
            deal_id=action.deal_id,
            contact_id=action.contact_id,
            occurred_at=now,
            title="Action completed",
            content=f"Completed '{action.title}' in Today.",
            extraction_status=ExtractionStatus.NOT_APPLICABLE,
        ),
        now=now,
    )
    saved = upsert_memory(
        conn,
        memory.model_copy(
            update={
                "status": MemoryStatus.FULFILLED,
                "valid_until": now,
            }
        ),
        now=now,
    )
    add_memory_evidence(
        conn,
        saved.id,
        evidence.id,
        quote=f"Completed '{action.title}' in Today.",
        relation=MemoryRelation.FULFILS,
        created_at=now,
    )
