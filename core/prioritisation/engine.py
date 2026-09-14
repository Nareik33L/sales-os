"""Deterministic prioritisation (docs/03). Pure functions; never calls AI.

Every number comes from a ``PriorityWeightsConfig`` passed in by the caller.
Scoring does not read YAML, the clock is injected via ``now`` (or
``datetime.now(timezone.utc)`` so tests can freeze time), and dates are
interpreted in the user's timezone.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from config.loaders import PriorityWeightsConfig
from core.models.action import tier_for_action_type
from core.models.schemas import (
    Action,
    ActionStatus,
    ActionType,
    AttentionStatus,
    Deal,
    Meeting,
    MeetingStatus,
    Memory,
    MemoryDirection,
    MemoryStatus,
    MemoryType,
)

DEFAULT_TZ_NAME = "Europe/London"
PIN_LAST = 10**9

_COMPONENT_ORDER = (
    "deal_value",
    "close_urgency",
    "stale_activity",
    "outstanding_commitment",
    "meeting_proximity",
)


# ---------------------------------------------------------------------------
# Breakdown types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentBreakdown:
    """One signal in ``priority_breakdown_json`` (docs/03 §5, docs/02)."""

    signal: float
    weight: float | None
    contribution: float
    reason: str
    extra_reasons: tuple[str, ...] = ()
    always_include: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "signal": self.signal,
            "score": self.signal,  # docs/02 alias
            "weight": self.weight,
            "contribution": self.contribution,
            "reason": self.reason,
        }
        if self.extra_reasons:
            payload["extra_reasons"] = list(self.extra_reasons)
        return payload


@dataclass(frozen=True)
class ScoreBreakdown:
    """Deal or action score plus the per-component breakdown."""

    score: float
    attention: AttentionStatus
    components: dict[str, ComponentBreakdown]
    pinned_rank: int | None = None
    tier: int | None = None

    def to_json(self) -> str:
        payload: dict[str, Any] = {
            "score": self.score,
            "attention": str(self.attention),
        }
        if self.tier is not None:
            payload["tier"] = self.tier
        if self.pinned_rank is not None:
            payload["pinned_rank"] = self.pinned_rank
        for name, component in self.components.items():
            payload[name] = component.as_dict()
        return json.dumps(payload, sort_keys=False)


@dataclass(frozen=True)
class RankedAction:
    action: Action
    breakdown: ScoreBreakdown
    tier: int
    score: float
    pinned_rank: int | None = None
    sheet_priority_key: tuple[int, int, str] = (1, 99, "")
    due_sort: date = field(default_factory=lambda: date.max)


# ---------------------------------------------------------------------------
# Clock / timezone / rounding
# ---------------------------------------------------------------------------


def user_timezone(tz: ZoneInfo | str | None = None) -> ZoneInfo:
    if isinstance(tz, ZoneInfo):
        return tz
    name = tz or os.environ.get("SALESOS_TIMEZONE") or DEFAULT_TZ_NAME
    return ZoneInfo(name)


def utc_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def local_today(now: datetime | None = None, tz: ZoneInfo | str | None = None) -> date:
    zone = user_timezone(tz)
    return utc_now(now).astimezone(zone).date()


def parse_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        ts = parse_timestamp(text)
        return ts.date() if ts else None
    return date.fromisoformat(text[:10])


def local_date_of(
    value: str | datetime | date | None,
    *,
    now: datetime | None = None,
    tz: ZoneInfo | str | None = None,
) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = parse_timestamp(value) if not isinstance(value, datetime) else value
    if parsed is None:
        as_date = parse_date(value if isinstance(value, str) else None)
        return as_date
    return parsed.astimezone(user_timezone(tz)).date()


def round_points(value: float) -> float:
    """One decimal, half-up. Acme contributions then sum to 82.4 (docs/03 §8)."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def interpolate(days: float, points: Sequence[tuple[int, float]]) -> float:
    """Piecewise linear interpolation over ``[x, y]`` points, clamped at the ends."""
    ordered = sorted((int(x), float(y)) for x, y in points)
    if not ordered:
        return 0.0
    if days <= ordered[0][0]:
        return ordered[0][1]
    if days >= ordered[-1][0]:
        return ordered[-1][1]
    for (x0, y0), (x1, y1) in zip(ordered, ordered[1:]):
        if x0 <= days <= x1:
            if x1 == x0:
                return y0
            t = (days - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return ordered[-1][1]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _enum_str(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def format_day(value: date) -> str:
    return f"{value.day} {value.strftime('%b')}"


def format_gbp(value: float) -> str:
    if abs(value) >= 1000:
        thousands = value / 1000.0
        if abs(thousands - round(thousands)) < 1e-9:
            return f"£{int(round(thousands))}k"
        text = f"£{thousands:.1f}k"
        return text.replace(".0k", "k")
    if abs(value - round(value)) < 1e-9:
        return f"£{int(round(value))}"
    return f"£{value:.0f}"


def format_local_hm(
    value: str | datetime,
    *,
    tz: ZoneInfo | str | None = None,
) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return ""
    local = parsed.astimezone(user_timezone(tz))
    return local.strftime("%H:%M")


# ---------------------------------------------------------------------------
# Deal signals
# ---------------------------------------------------------------------------


def _deal_value_gbp(deal: Deal) -> float | None:
    if deal.deal_value_gbp is not None:
        return float(deal.deal_value_gbp)
    if deal.deal_value is None:
        return None
    currency = (deal.currency or "GBP").upper()
    if currency == "GBP":
        return float(deal.deal_value)
    return None


def signal_deal_value(deal: Deal, cfg: PriorityWeightsConfig) -> ComponentBreakdown:
    scale = cfg.deal.deal_value
    weight = cfg.deal.weights.deal_value
    amount = _deal_value_gbp(deal)
    if amount is None or amount <= 0:
        return ComponentBreakdown(
            signal=0.0,
            weight=weight,
            contribution=0.0,
            reason="no value recorded",
            always_include=True,
        )
    raw = 100.0 * math.log10(1.0 + amount) / math.log10(1.0 + scale.reference_value_gbp)
    signal = min(100.0, raw)
    if signal < scale.min_signal_for_known_value:
        signal = float(scale.min_signal_for_known_value)
    return ComponentBreakdown(
        signal=100.0 if signal >= 100.0 else round_points(signal),
        weight=weight,
        contribution=round_points(signal * weight),
        reason=f"{format_gbp(amount)} deal",
    )


def signal_close_urgency(
    deal: Deal,
    cfg: PriorityWeightsConfig,
    *,
    today: date,
) -> ComponentBreakdown:
    scale = cfg.deal.close_urgency
    weight = cfg.deal.weights.close_urgency
    close = parse_date(deal.close_date)
    if close is None:
        signal = float(scale.unknown_close_date_signal)
        return ComponentBreakdown(
            signal=signal,
            weight=weight,
            contribution=round_points(signal * weight),
            reason="no close date recorded",
            always_include=True,
        )
    days = (close - today).days
    signal = interpolate(days, scale.points)
    if days < 0:
        signal = 100.0
        reason = f"Close date passed ({format_day(close)})"
    elif days == 0:
        reason = "Closing today"
    elif days == 1:
        reason = "Closing in 1 day"
    else:
        reason = f"Closing in {days} days"
    return ComponentBreakdown(
        signal=round_points(signal) if days >= 0 else 100.0,
        weight=weight,
        contribution=round_points(signal * weight),
        reason=reason,
    )


def days_to_close(deal: Deal, today: date) -> int | None:
    close = parse_date(deal.close_date)
    if close is None:
        return None
    return (close - today).days


def signal_stale_activity(
    deal: Deal,
    cfg: PriorityWeightsConfig,
    *,
    today: date,
    tz: ZoneInfo | str | None = None,
) -> ComponentBreakdown:
    scale = cfg.deal.stale_activity
    weight = cfg.deal.weights.stale_activity
    activity = local_date_of(deal.last_activity_at, tz=tz)
    if activity is None:
        signal = float(scale.unknown_activity_signal)
        days_close = days_to_close(deal, today)
        if days_close is not None and days_close > scale.cap_when_close_beyond_days:
            signal = min(signal, float(scale.cap_signal))
        return ComponentBreakdown(
            signal=signal,
            weight=weight,
            contribution=round_points(signal * weight),
            reason="no activity recorded",
            always_include=True,
        )
    days = (today - activity).days
    if days < 0:
        days = 0
    signal = interpolate(days, scale.points)
    days_close = days_to_close(deal, today)
    if days_close is not None and days_close > scale.cap_when_close_beyond_days:
        signal = min(signal, float(scale.cap_signal))
    if days == 0:
        reason = "Activity in the last 3 days"
    elif days == 1:
        reason = "No activity for 1 day"
    else:
        reason = f"No activity for {days} days"
    return ComponentBreakdown(
        signal=round_points(signal),
        weight=weight,
        contribution=round_points(signal * weight),
        reason=reason,
    )


def _due_phrase(due: date | None, today: date) -> str:
    if due is None:
        return ""
    delta = (due - today).days
    if delta == 0:
        return "due today"
    if delta == 1:
        return "due tomorrow"
    if delta == -1:
        return "due yesterday"
    return f"due {format_day(due)}"


def _commitment_reason(memory: Memory, today: date) -> str:
    subject = (memory.subject or "").strip() or "commitment"
    due = parse_date(memory.due_date)
    phrase = _due_phrase(due, today)
    direction = _enum_str(memory.direction)
    if direction == MemoryDirection.USER_TO_CUSTOMER.value:
        base = f"You owe: {subject}"
    elif direction == MemoryDirection.CUSTOMER_TO_USER.value:
        base = f"Customer owes: {subject}"
    else:
        base = subject
    if phrase:
        return f"{base} ({phrase})"
    return base


def signal_outstanding_commitment(
    memories: Sequence[Memory],
    cfg: PriorityWeightsConfig,
    *,
    today: date,
) -> ComponentBreakdown:
    scale = cfg.deal.outstanding_commitment
    weight = cfg.deal.weights.outstanding_commitment
    best_signal = float(scale.none)
    reasons: list[tuple[float, str]] = []
    for memory in memories:
        if _enum_str(memory.type) != MemoryType.COMMITMENT.value:
            continue
        if _enum_str(memory.status) != MemoryStatus.ACTIVE.value:
            continue
        direction = _enum_str(memory.direction)
        due = parse_date(memory.due_date)
        days_until = (due - today).days if due is not None else None
        signal = 0.0
        if direction == MemoryDirection.USER_TO_CUSTOMER.value:
            if days_until is not None and days_until < 0:
                signal = float(scale.user_owes_customer_overdue)
            elif days_until is not None and days_until <= scale.user_owes_customer_due_within_days:
                signal = float(scale.user_owes_customer_due_soon)
            else:
                signal = float(scale.user_owes_customer_open)
        elif direction == MemoryDirection.CUSTOMER_TO_USER.value:
            if days_until is not None and days_until < 0:
                signal = float(scale.customer_owes_user_overdue)
            else:
                continue
        else:
            continue
        reasons.append((signal, _commitment_reason(memory, today)))
        if signal > best_signal:
            best_signal = signal
    reasons.sort(key=lambda item: -item[0])
    extra = tuple(reason for _signal, reason in reasons[1:])
    primary = reasons[0][1] if reasons else "No outstanding commitment"
    return ComponentBreakdown(
        signal=best_signal,
        weight=weight,
        contribution=round_points(best_signal * weight),
        reason=primary,
        extra_reasons=extra,
    )


def _followup_completed(
    meeting: Meeting,
    actions: Sequence[Action],
) -> bool:
    completed = {
        action.id
        for action in actions
        if _enum_str(action.type) == ActionType.MEETING_FOLLOWUP.value
        and _enum_str(action.status) == ActionStatus.COMPLETED.value
    }
    if meeting.followup_action_id and meeting.followup_action_id in completed:
        return True
    for action in actions:
        if _enum_str(action.type) != ActionType.MEETING_FOLLOWUP.value:
            continue
        if action.meeting_id and action.meeting_id == meeting.id:
            if _enum_str(action.status) == ActionStatus.COMPLETED.value:
                return True
    return False


def signal_meeting_proximity(
    meetings: Sequence[Meeting],
    cfg: PriorityWeightsConfig,
    *,
    today: date,
    tz: ZoneInfo | str | None = None,
    actions: Sequence[Action] = (),
) -> ComponentBreakdown:
    scale = cfg.deal.meeting_proximity
    weight = cfg.deal.weights.meeting_proximity
    best_signal = float(scale.none)
    reason = ""
    for meeting in meetings:
        status = _enum_str(meeting.status)
        if status in {MeetingStatus.CANCELLED.value, MeetingStatus.NO_SHOW.value}:
            continue
        start = local_date_of(meeting.start_at, tz=tz)
        if start is None:
            continue
        end = local_date_of(meeting.end_at, tz=tz) or start
        days = (start - today).days
        signal = 0.0
        this_reason = ""
        if days == 0:
            signal = float(scale.today)
            stamp = format_local_hm(meeting.start_at, tz=tz)
            this_reason = f"Meeting today {stamp}".rstrip()
        elif days == 1:
            signal = float(scale.tomorrow)
            this_reason = "Meeting tomorrow"
        elif 1 < days <= scale.within_days:
            signal = float(scale.within_signal)
            this_reason = f"Meeting in {days} days"
        elif (end - today).days == -1 or days == -1:
            if not _followup_completed(meeting, actions):
                signal = float(scale.held_yesterday_no_followup)
                this_reason = "Met yesterday — no follow-up yet"
        if signal > best_signal:
            best_signal = signal
            reason = this_reason
    return ComponentBreakdown(
        signal=best_signal,
        weight=weight,
        contribution=round_points(best_signal * weight),
        reason=reason,
    )


def _attention_for(score: float, cfg: PriorityWeightsConfig, *, closed: bool) -> AttentionStatus:
    if closed:
        return AttentionStatus.NONE
    thresholds = cfg.deal.attention_thresholds
    if score >= thresholds.high:
        return AttentionStatus.HIGH
    if score >= thresholds.medium:
        return AttentionStatus.MEDIUM
    return AttentionStatus.LOW


def _adjustment_components(
    deal: Deal,
    cfg: PriorityWeightsConfig,
    *,
    is_strategic: bool,
) -> tuple[dict[str, ComponentBreakdown], float, int | None]:
    adj = cfg.deal.user_adjustments
    raw_boost = int(deal.user_boost or 0)
    boost = int(clamp(raw_boost, -adj.max_boost_points, adj.max_boost_points))
    components: dict[str, ComponentBreakdown] = {}
    total = 0.0
    if boost != 0:
        reason = (
            "You marked this more important"
            if boost > 0
            else "You marked this less important"
        )
        components["user_boost"] = ComponentBreakdown(
            signal=float(boost),
            weight=None,
            contribution=float(boost),
            reason=reason,
            always_include=True,
        )
        total += boost
    if is_strategic:
        points = float(adj.strategic_account_points)
        components["is_strategic"] = ComponentBreakdown(
            signal=points,
            weight=None,
            contribution=points,
            reason="Strategic account",
            always_include=True,
        )
        total += points
    pinned = deal.user_pinned_rank
    if pinned is not None:
        components["pinned"] = ComponentBreakdown(
            signal=0.0,
            weight=None,
            contribution=0.0,
            reason="Pinned by you",
            always_include=True,
        )
    return components, total, pinned


def score_deal(
    deal: Deal,
    memories: Sequence[Memory],
    meetings: Sequence[Meeting],
    cfg: PriorityWeightsConfig,
    *,
    actions: Sequence[Action] = (),
    is_strategic: bool = False,
    now: datetime | None = None,
    tz: ZoneInfo | str | None = None,
) -> ScoreBreakdown:
    """Weighted deal score 0–100 plus bounded user adjustments (docs/03 §2)."""
    today = local_today(now, tz)
    components: dict[str, ComponentBreakdown] = {
        "deal_value": signal_deal_value(deal, cfg),
        "close_urgency": signal_close_urgency(deal, cfg, today=today),
        "stale_activity": signal_stale_activity(deal, cfg, today=today, tz=tz),
        "outstanding_commitment": signal_outstanding_commitment(
            memories, cfg, today=today
        ),
        "meeting_proximity": signal_meeting_proximity(
            meetings, cfg, today=today, tz=tz, actions=actions
        ),
    }
    weighted = sum(components[name].contribution for name in _COMPONENT_ORDER)
    extras, adjustment_total, pinned = _adjustment_components(
        deal, cfg, is_strategic=is_strategic
    )
    components.update(extras)
    score = round_points(weighted + adjustment_total)
    attention = _attention_for(score, cfg, closed=bool(deal.is_closed))
    return ScoreBreakdown(
        score=score,
        attention=attention,
        components=components,
        pinned_rank=pinned,
    )


# ---------------------------------------------------------------------------
# Action signals
# ---------------------------------------------------------------------------


def signal_action_due_date(
    action: Action,
    cfg: PriorityWeightsConfig,
    *,
    today: date,
) -> ComponentBreakdown:
    scale = cfg.action.due_date
    weight = cfg.action.weights.due_date
    due = parse_date(action.due_date)
    if due is None:
        signal = float(scale.no_due_date)
        reason = "no due date"
    else:
        days = (due - today).days
        if days < 0:
            overdue = -days
            signal = min(100.0, scale.overdue_base + scale.overdue_per_day * overdue)
            reason = _due_phrase(due, today)
        elif days == 0:
            signal = float(scale.today)
            reason = "due today"
        elif days == 1:
            signal = float(scale.tomorrow)
            reason = "due tomorrow"
        elif days <= scale.within_days:
            signal = float(scale.within_signal)
            reason = _due_phrase(due, today)
        else:
            signal = float(scale.no_due_date)
            reason = _due_phrase(due, today)
    return ComponentBreakdown(
        signal=signal,
        weight=weight,
        contribution=round_points(signal * weight),
        reason=reason,
    )


def score_action(
    action: Action,
    deal_breakdown: ScoreBreakdown | None,
    cfg: PriorityWeightsConfig,
    *,
    now: datetime | None = None,
    tz: ZoneInfo | str | None = None,
) -> ScoreBreakdown:
    """``0.6 × inherited deal score + 0.4 × due-date signal`` (docs/03 §3)."""
    today = local_today(now, tz)
    inherited = (
        deal_breakdown.score
        if deal_breakdown is not None
        else float(cfg.action.no_deal_inherited_score)
    )
    inherit_weight = cfg.action.weights.inherited_deal_score
    inherited_component = ComponentBreakdown(
        signal=inherited,
        weight=inherit_weight,
        contribution=round_points(inherited * inherit_weight),
        reason="inherited deal score" if deal_breakdown is not None else "no linked deal",
    )
    due_component = signal_action_due_date(action, cfg, today=today)
    components = {
        "inherited_deal_score": inherited_component,
        "due_date": due_component,
    }
    adj = cfg.deal.user_adjustments
    raw_boost = int(action.user_boost or 0)
    boost = int(clamp(raw_boost, -adj.max_boost_points, adj.max_boost_points))
    extra = 0.0
    if boost != 0:
        reason = (
            "You marked this more important"
            if boost > 0
            else "You marked this less important"
        )
        components["user_boost"] = ComponentBreakdown(
            signal=float(boost),
            weight=None,
            contribution=float(boost),
            reason=reason,
            always_include=True,
        )
        extra += boost
    score = round_points(
        inherited_component.contribution + due_component.contribution + extra
    )
    if deal_breakdown is not None:
        attention = deal_breakdown.attention
    else:
        attention = _attention_for(score, cfg, closed=False)
    tier = tier_for_action_type(action.type, tier_by_type=cfg.action.tier_by_type)
    pin = action.user_priority_override
    if pin is not None:
        components["pinned"] = ComponentBreakdown(
            signal=0.0,
            weight=None,
            contribution=0.0,
            reason="Pinned by you",
            always_include=True,
        )
    return ScoreBreakdown(
        score=score,
        attention=attention,
        components=components,
        pinned_rank=pin,
        tier=tier,
    )


# ---------------------------------------------------------------------------
# Why bullets
# ---------------------------------------------------------------------------


def explain(breakdown: ScoreBreakdown, cfg: PriorityWeightsConfig | None = None) -> list[str]:
    """Templated Why bullets from the breakdown. No AI (docs/03 §5)."""
    min_contrib = 5.0
    max_bullets = 4
    if cfg is not None:
        min_contrib = float(cfg.explanations.min_contribution_for_bullet)
        max_bullets = int(cfg.explanations.max_bullets)
    candidates: list[tuple[float, int, str]] = []
    order = 0
    for component in breakdown.components.values():
        include = component.always_include or component.contribution >= min_contrib
        if not include and not component.extra_reasons:
            continue
        reasons = []
        if include and component.reason:
            reasons.append(component.reason)
        if component.extra_reasons:
            # Max-not-sum: extra commitments still get their own bullets.
            reasons.extend(reason for reason in component.extra_reasons if reason)
        if not reasons and include and component.reason:
            reasons = [component.reason]
        for reason in reasons:
            if not reason:
                continue
            candidates.append((component.contribution, order, reason))
            order += 1
    candidates.sort(key=lambda item: (-item[0], item[1]))
    seen: set[str] = set()
    bullets: list[str] = []
    for _contrib, _order, reason in candidates:
        if reason in seen:
            continue
        seen.add(reason)
        bullets.append(reason)
        if len(bullets) >= max_bullets:
            break
    return bullets


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _sheet_priority_key(raw: str | None) -> tuple[int, int, str]:
    if not raw:
        return (1, 99, "")
    text = str(raw).strip()
    if text.isdigit():
        return (0, int(text), text)
    if len(text) == 1 and text.isalpha():
        return (0, ord(text.upper()) - ord("A"), text.upper())
    return (1, 99, text.lower())


def _as_deal_map(
    deals: Sequence[Deal] | Mapping[str, Deal] | None,
) -> dict[str, Deal]:
    if deals is None:
        return {}
    if isinstance(deals, Mapping):
        return dict(deals)
    return {deal.id: deal for deal in deals}


def _as_prospecting_map(
    items: Sequence[Any] | Mapping[str, Any] | None,
) -> dict[str, Any]:
    if items is None:
        return {}
    if isinstance(items, Mapping):
        return dict(items)
    mapped: dict[str, Any] = {}
    for item in items:
        key = getattr(item, "row_key", None)
        if key:
            mapped[str(key)] = item
    return mapped


def rank_actions(
    actions: Sequence[Action],
    deal_breakdowns: Mapping[str, ScoreBreakdown],
    cfg: PriorityWeightsConfig,
    *,
    deals: Sequence[Deal] | Mapping[str, Deal] | None = None,
    prospecting_items: Sequence[Any] | Mapping[str, Any] | None = None,
    now: datetime | None = None,
    tz: ZoneInfo | str | None = None,
) -> list[RankedAction]:
    """Today order: ``tier ASC, pinned rank NULLS LAST, score DESC`` (docs/09).

    Prospecting (tier 3) additionally sorts by the sheet's Priority then Due
    date so sheet order survives inside the tier. Score never lifts prospecting
    above tier 1 (ADR-007).
    """
    today = local_today(now, tz)
    deal_map = _as_deal_map(deals)
    sheet_map = _as_prospecting_map(prospecting_items)
    ranked: list[RankedAction] = []
    for action in actions:
        status = _enum_str(action.status)
        if status != ActionStatus.OPEN.value:
            continue
        if action.snoozed_until:
            until = parse_date(action.snoozed_until)
            if until is not None and until > today:
                continue
        deal_id = action.deal_id
        breakdown = score_action(
            action,
            deal_breakdowns.get(deal_id) if deal_id else None,
            cfg,
            now=now,
            tz=tz,
        )
        tier = breakdown.tier or 3
        pin = action.user_priority_override
        if pin is None and deal_id and deal_id in deal_map:
            pin = deal_map[deal_id].user_pinned_rank
        sheet_key = (1, 99, "")
        due_sort = date.max
        if tier == 3:
            item = sheet_map.get(action.source_id or "")
            raw_priority = None
            raw_due = action.due_date
            if item is not None:
                raw_priority = getattr(item, "priority", None)
                raw_due = getattr(item, "due_date", None) or raw_due
            sheet_key = _sheet_priority_key(raw_priority)
            parsed_due = parse_date(raw_due)
            due_sort = parsed_due if parsed_due is not None else date.max
        ranked.append(
            RankedAction(
                action=action,
                breakdown=breakdown,
                tier=tier,
                score=breakdown.score,
                pinned_rank=pin,
                sheet_priority_key=sheet_key,
                due_sort=due_sort,
            )
        )
    ranked.sort(
        key=lambda item: (
            item.tier,
            item.pinned_rank if item.pinned_rank is not None else PIN_LAST,
            item.sheet_priority_key if item.tier == 3 else (0, 0, ""),
            item.due_sort if item.tier == 3 else date.min,
            -item.score,
            item.action.id,
        )
    )
    return ranked
