"""Today page queries assembled from repositories + stored scores.

No SQL and no scoring live here. Ordering is the spec key
``tier ASC, user_pinned_rank NULLS LAST, priority_score DESC``.
Why bullets come from ``core.prioritisation.explain`` over stored breakdowns.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from config.loaders import load_priority_weights, load_sources
from core.models import (
    Action,
    ActionStatus,
    AttentionStatus,
    Company,
    Deal,
    Meeting,
    MeetingStatus,
    ReviewItem,
    ReviewStatus,
    SyncRun,
    SyncStatus,
    get_company,
    get_deal,
    list_actions,
    list_deal_changes,
    list_deals,
    list_meetings,
    list_review_items,
    list_sync_runs,
)
from core.prioritisation import ComponentBreakdown, ScoreBreakdown, explain
from core.prioritisation.engine import (
    PIN_LAST,
    format_day,
    format_gbp,
    format_local_hm,
    local_date_of,
    local_today,
    parse_date,
    parse_timestamp,
    user_timezone,
)

_BREAKDOWN_META = frozenset({"score", "attention", "tier", "pinned_rank"})
_ALWAYS_WHY = frozenset({"user_boost", "is_strategic", "pinned"})
_WARN_STATUSES = {
    SyncStatus.FAILED.value,
    SyncStatus.NOT_CONFIGURED.value,
    SyncStatus.PARTIAL.value,
    "FAILED",
    "NOT_CONFIGURED",
    "PARTIAL",
}


@dataclass(frozen=True)
class ActionCardRow:
    action: Action
    deal: Deal | None
    company: Company | None
    why: tuple[str, ...]
    rank: int
    attention: AttentionStatus
    product_label: str
    headline: str
    due_label: str
    score_label: str


@dataclass(frozen=True)
class DealCardRow:
    deal: Deal
    company: Company | None
    why: tuple[str, ...]
    product_label: str
    headline: str
    attention: AttentionStatus


@dataclass(frozen=True)
class MeetingRow:
    meeting: Meeting
    deal: Deal | None
    company: Company | None
    when_label: str
    title: str


@dataclass(frozen=True)
class ChangeRow:
    text: str
    changed_at: str


@dataclass(frozen=True)
class SourceHealth:
    source: str
    label: str
    status: str
    icon: str
    message: str | None
    finished_at: str | None
    time_label: str


@dataclass
class TodaySnapshot:
    greeting_name: str
    today: date
    actions: list[ActionCardRow] = field(default_factory=list)
    deal_cards: list[DealCardRow] = field(default_factory=list)
    meetings: list[MeetingRow] = field(default_factory=list)
    questions: list[ReviewItem] = field(default_factory=list)
    changes: list[ChangeRow] = field(default_factory=list)
    health: list[SourceHealth] = field(default_factory=list)
    last_refresh_label: str = "no refresh yet"
    overall_icon: str = "–"
    health_summary: str = ""
    attention_total: int = 0
    question_count: int = 0
    tier1_count: int = 0
    tier2_count: int = 0
    tier3_count: int = 0
    tier1_high_value_gbp: float = 0.0
    meetings_today_count: int = 0


def enum_str(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def pinned_rank_for(action: Action, deals: dict[str, Deal]) -> int | None:
    """Action pin wins; otherwise the deal's ``user_pinned_rank`` (docs/03 §2.6)."""
    if action.user_priority_override is not None:
        return int(action.user_priority_override)
    if action.deal_id and action.deal_id in deals:
        return deals[action.deal_id].user_pinned_rank
    return None


def today_sort_key(
    action: Action, deals: dict[str, Deal]
) -> tuple[int, int, float, str]:
    """Exactly ``tier ASC, user_pinned_rank NULLS LAST, priority_score DESC``."""
    pin = pinned_rank_for(action, deals)
    return (
        int(action.tier),
        pin if pin is not None else PIN_LAST,
        -float(action.priority_score or 0),
        action.id,
    )


def sort_today_actions(
    actions: list[Action], deals: dict[str, Deal]
) -> list[Action]:
    return sorted(actions, key=lambda action: today_sort_key(action, deals))


def is_visible_today(action: Action, today: date) -> bool:
    status = enum_str(action.status)
    if status == ActionStatus.SNOOZED.value:
        until = parse_date(action.snoozed_until)
        return until is not None and until <= today
    if status != ActionStatus.OPEN.value:
        return False
    if action.snoozed_until:
        until = parse_date(action.snoozed_until)
        if until is not None and until > today:
            return False
    return True


def breakdown_from_stored(raw: str | None) -> ScoreBreakdown | None:
    """Rebuild a ``ScoreBreakdown`` from ``priority_breakdown_json`` (no rescoring)."""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    components: dict[str, ComponentBreakdown] = {}
    for key, val in payload.items():
        if key in _BREAKDOWN_META or not isinstance(val, dict):
            continue
        extra = val.get("extra_reasons") or []
        if not isinstance(extra, list):
            extra = []
        components[str(key)] = ComponentBreakdown(
            signal=float(val.get("signal") if val.get("signal") is not None else val.get("score") or 0),
            weight=val.get("weight"),
            contribution=float(val.get("contribution") or 0),
            reason=str(val.get("reason") or ""),
            extra_reasons=tuple(str(item) for item in extra),
            always_include=str(key) in _ALWAYS_WHY,
        )
    attention_raw = payload.get("attention") or AttentionStatus.LOW.value
    try:
        attention = AttentionStatus(attention_raw)
    except ValueError:
        attention = AttentionStatus.LOW
    return ScoreBreakdown(
        score=float(payload.get("score") or 0),
        attention=attention,
        components=components,
        pinned_rank=payload.get("pinned_rank"),
        tier=payload.get("tier"),
    )


def why_from_stored(raw: str | None) -> tuple[str, ...]:
    breakdown = breakdown_from_stored(raw)
    if breakdown is None:
        return ()
    cfg = load_priority_weights()
    return tuple(explain(breakdown, cfg))


def why_for_action(action: Action, deal: Deal | None) -> tuple[str, ...]:
    """Prefer the deal Why (docs/03 §5); fall back to the action breakdown."""
    if deal is not None:
        bullets = why_from_stored(deal.priority_breakdown_json)
        if bullets:
            return bullets
    return why_from_stored(action.priority_breakdown_json)


def product_label(product: str | None) -> str:
    if not product:
        return ""
    sources = load_sources()
    entry = sources.products.get(product)
    if entry is None:
        return product
    return entry.label


def attention_of(action: Action, deal: Deal | None) -> AttentionStatus:
    if deal is not None:
        return deal.attention_status
    score = float(action.priority_score or 0)
    cfg = load_priority_weights()
    if score >= cfg.deal.attention_thresholds.high:
        return AttentionStatus.HIGH
    if score >= cfg.deal.attention_thresholds.medium:
        return AttentionStatus.MEDIUM
    return AttentionStatus.LOW


def due_label(due: str | None, today: date) -> str:
    parsed = parse_date(due)
    if parsed is None:
        return ""
    delta = (parsed - today).days
    if delta == 0:
        return "due today"
    if delta == -1:
        return "due yesterday"
    if delta < 0:
        return f"due {abs(delta)} days ago"
    if delta == 1:
        return "due tomorrow"
    return f"due {format_day(parsed)}"


def close_label(close: str | None) -> str:
    parsed = parse_date(close)
    if parsed is None:
        return ""
    return f"Closing {parsed.strftime('%a')} {format_day(parsed)}"


def value_label(deal: Deal | None) -> str:
    if deal is None or deal.deal_value_gbp is None:
        return ""
    return format_gbp(deal.deal_value_gbp)


def action_headline(action: Action, deal: Deal | None, company: Company | None) -> str:
    company_name = (
        (company.name if company is not None else None)
        or (deal.company_name if deal is not None else None)
        or "No company"
    )
    parts = [company_name]
    value = value_label(deal)
    if value:
        parts.append(value)
    product = product_label(deal.product if deal is not None else None)
    if product:
        parts.append(product)
    closing = close_label(deal.close_date if deal is not None else None)
    if closing:
        parts.append(closing)
    if len(parts) == 1:
        return f"{parts[0]} — {action.title}"
    return f"{parts[0]} — " + " · ".join(parts[1:])


def score_label(action: Action, attention: AttentionStatus) -> str:
    marker = {
        AttentionStatus.HIGH: "🔴",
        AttentionStatus.MEDIUM: "🟠",
        AttentionStatus.LOW: "🔵",
        AttentionStatus.NONE: "",
    }.get(attention, "")
    score = action.priority_score or 0
    text = f"{enum_str(attention)} {score:.0f}".strip()
    return f"{marker} {text}".strip()


def health_icon(status: str) -> str:
    if status in {SyncStatus.SUCCESS.value, "SUCCESS"}:
        return "✓"
    if status in {SyncStatus.PARTIAL.value, "PARTIAL"}:
        return "✓⚠"
    if status in _WARN_STATUSES or status in {SyncStatus.FAILED.value, SyncStatus.NOT_CONFIGURED.value}:
        return "⚠"
    return "–"


def _time_label(stamp: str | None) -> str:
    parsed = parse_timestamp(stamp)
    if parsed is None:
        return ""
    return format_local_hm(parsed)


def load_source_health(conn: sqlite3.Connection) -> list[SourceHealth]:
    sources = load_sources()
    latest: dict[str, SyncRun] = {}
    for run in list_sync_runs(conn):
        if run.source not in latest:
            latest[run.source] = run
    rows: list[SourceHealth] = []
    for name, entry in sources.connectors.items():
        run = latest.get(name)
        if run is None:
            status = "SKIPPED" if (not entry.enabled or entry.mode == "disabled") else "NONE"
            icon = "–"
            message = (
                "Disabled in sources.yaml"
                if (not entry.enabled or entry.mode == "disabled")
                else "No run yet"
            )
            rows.append(
                SourceHealth(
                    source=name,
                    label=entry.label,
                    status=status,
                    icon=icon,
                    message=message,
                    finished_at=None,
                    time_label="",
                )
            )
            continue
        status = enum_str(run.status)
        rows.append(
            SourceHealth(
                source=name,
                label=entry.label,
                status=status,
                icon=health_icon(status),
                message=run.message,
                finished_at=run.finished_at,
                time_label=_time_label(run.finished_at or run.started_at),
            )
        )
    return rows


def health_header(rows: list[SourceHealth]) -> tuple[str, str, str]:
    """Return (last_refresh_label, overall_icon, parenthetical summary)."""
    timed = [row for row in rows if row.finished_at]
    if timed:
        latest = max(timed, key=lambda row: row.finished_at or "")
        last_label = latest.time_label or "unknown"
    else:
        last_label = "none"
    failed = [row for row in rows if row.icon == "⚠" or row.icon == "✓⚠"]
    overall = "⚠" if failed else ("✓" if any(row.icon == "✓" for row in rows) else "–")
    bits: list[str] = []
    for row in rows:
        if row.icon in {"⚠", "✓⚠", "–"}:
            bits.append(f"{row.label} {row.icon}")
    summary = ", ".join(bits)
    return last_label, overall, summary


def load_today(
    conn: sqlite3.Connection,
    *,
    greeting: str,
    now: datetime | None = None,
) -> TodaySnapshot:
    today = local_today(now, user_timezone())
    deals = {deal.id: deal for deal in list_deals(conn)}
    companies: dict[str, Company] = {}

    def company_for(company_id: str | None, deal: Deal | None) -> Company | None:
        cid = company_id or (deal.company_id if deal is not None else None)
        if not cid:
            return None
        if cid not in companies:
            companies[cid] = get_company(conn, cid)  # type: ignore[assignment]
        return companies.get(cid)

    open_actions = [
        action
        for action in list_actions(conn, status=ActionStatus.OPEN)
        if is_visible_today(action, today)
    ]
    ordered = sort_today_actions(open_actions, deals)

    action_rows: list[ActionCardRow] = []
    for index, action in enumerate(ordered, start=1):
        deal = get_deal(conn, action.deal_id) if action.deal_id else None
        if deal is None and action.deal_id:
            deal = deals.get(action.deal_id)
        company = company_for(action.company_id, deal)
        attention = attention_of(action, deal)
        action_rows.append(
            ActionCardRow(
                action=action,
                deal=deal,
                company=company,
                why=why_for_action(action, deal),
                rank=index,
                attention=attention,
                product_label=product_label(deal.product if deal is not None else None),
                headline=action_headline(action, deal, company),
                due_label=due_label(action.due_date, today),
                score_label=score_label(action, attention),
            )
        )

    open_deal_ids = {row.action.deal_id for row in action_rows if row.action.deal_id}
    deal_cards: list[DealCardRow] = []
    for deal in deals.values():
        if deal.is_closed:
            continue
        if enum_str(deal.attention_status) != AttentionStatus.HIGH.value:
            continue
        if deal.id in open_deal_ids:
            continue
        company = company_for(deal.company_id, deal)
        deal_cards.append(
            DealCardRow(
                deal=deal,
                company=company,
                why=why_from_stored(deal.priority_breakdown_json),
                product_label=product_label(deal.product),
                headline=_deal_card_headline(deal, company),
                attention=deal.attention_status,
            )
        )

    meetings_today: list[MeetingRow] = []
    for meeting in list_meetings(conn):
        if enum_str(meeting.status) in {
            MeetingStatus.CANCELLED.value,
            MeetingStatus.NO_SHOW.value,
        }:
            continue
        if local_date_of(meeting.start_at) != today:
            continue
        deal = deals.get(meeting.deal_id) if meeting.deal_id else None
        company = company_for(meeting.company_id, deal)
        title = meeting.title or (
            f"{company.name} meeting" if company is not None else "Meeting"
        )
        meetings_today.append(
            MeetingRow(
                meeting=meeting,
                deal=deal,
                company=company,
                when_label=format_local_hm(meeting.start_at),
                title=title,
            )
        )
    meetings_today.sort(key=lambda row: row.meeting.start_at)

    questions = list_review_items(conn, status=ReviewStatus.OPEN)

    since = (today - timedelta(days=1)).isoformat()
    changes: list[ChangeRow] = []
    for change in list_deal_changes(conn, since=since):
        deal = deals.get(change.deal_id)
        if deal is None:
            continue
        label = deal.company_name or deal.name
        source = enum_str(deal.source).title()
        when = _time_label(change.changed_at) or change.changed_at
        old = change.old_value or "—"
        new = change.new_value or "—"
        changes.append(
            ChangeRow(
                text=f"{label}: {change.field} {old} → {new} ({source}, {when})",
                changed_at=change.changed_at,
            )
        )

    health = load_source_health(conn)
    last_label, overall, summary = health_header(health)

    tier1 = [row for row in action_rows if row.action.tier == 1]
    high_deal_ids: set[str] = set()
    high_value = 0.0
    for row in tier1:
        if row.deal is None or row.deal.id in high_deal_ids:
            continue
        if enum_str(row.attention) != AttentionStatus.HIGH.value:
            continue
        if row.deal.deal_value_gbp is None:
            continue
        high_deal_ids.add(row.deal.id)
        high_value += float(row.deal.deal_value_gbp)

    return TodaySnapshot(
        greeting_name=greeting,
        today=today,
        actions=action_rows,
        deal_cards=deal_cards,
        meetings=meetings_today,
        questions=questions,
        changes=changes,
        health=health,
        last_refresh_label=last_label,
        overall_icon=overall,
        health_summary=summary,
        attention_total=len(action_rows),
        question_count=len(questions),
        tier1_count=len(tier1),
        tier2_count=sum(1 for row in action_rows if row.action.tier == 2),
        tier3_count=sum(1 for row in action_rows if row.action.tier == 3),
        tier1_high_value_gbp=high_value,
        meetings_today_count=len(meetings_today),
    )


def _deal_card_headline(deal: Deal, company: Company | None) -> str:
    name = (company.name if company is not None else None) or deal.company_name or deal.name
    value = format_gbp(deal.deal_value_gbp) if deal.deal_value_gbp is not None else ""
    product = product_label(deal.product)
    bits = [bit for bit in (value, product) if bit]
    suffix = " · ".join(bits)
    base = f"{name} — needs attention — no next step recorded"
    return f"{base} · {suffix}" if suffix else base
