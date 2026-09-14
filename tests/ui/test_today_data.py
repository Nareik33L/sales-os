"""Today ordering and Why bullets — no Streamlit, fictional seed only."""

from __future__ import annotations

from datetime import date

from app.feedback import apply_boost, apply_complete, apply_dismiss, apply_snooze
from app.today_data import (
    enum_str,
    is_visible_today,
    sort_today_actions,
    today_sort_key,
    why_for_action,
    why_from_stored,
)
from core.models import (
    Action,
    ActionStatus,
    ActionType,
    Deal,
    DealSource,
    FeedbackEvent,
    get_action,
    get_deal,
    list_actions,
    list_deals,
    list_user_feedback,
)
from core.prioritisation import recompute_all
from core.prioritisation.engine import local_today
from tests.prioritisation.helpers import NOW, TZ


def test_sort_is_tier_then_pin_then_score_desc(db):
    deals = {
        "d1": Deal(
            id="d1",
            external_id="e1",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme",
            company_name="Acme",
        ),
        "d2": Deal(
            id="d2",
            external_id="e2",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Beta Corp",
            company_name="Beta Corp",
            user_pinned_rank=2,
        ),
    }
    prospect = Action(
        id="a_prospect",
        title="Intro email — Zeta Example",
        type=ActionType.PROSPECTING,
        source="google_sheets",
        source_id="row-zeta",
        tier=3,
        priority_score=99.0,
    )
    low_tier1 = Action(
        id="a_low",
        title="Low score tier 1",
        type=ActionType.COMMITMENT,
        source="memory",
        deal_id="d1",
        tier=1,
        priority_score=10.0,
    )
    high_tier1 = Action(
        id="a_high",
        title="High score tier 1",
        type=ActionType.HUBSPOT_TASK,
        source="hubspot",
        deal_id="d1",
        tier=1,
        priority_score=80.0,
    )
    pinned_via_deal = Action(
        id="a_pinned_deal",
        title="Pinned via deal",
        type=ActionType.MEETING_PREP,
        source="calendly",
        deal_id="d2",
        tier=1,
        priority_score=5.0,
    )
    pinned_via_action = Action(
        id="a_pinned_action",
        title="Pinned via action",
        type=ActionType.EMAIL_FOLLOWUP,
        source="rules",
        deal_id="d1",
        tier=1,
        priority_score=1.0,
        user_priority_override=1,
    )
    ordered = sort_today_actions(
        [prospect, low_tier1, high_tier1, pinned_via_deal, pinned_via_action],
        deals,
    )
    assert [action.id for action in ordered] == [
        "a_pinned_action",  # user_priority_override = 1
        "a_pinned_deal",  # deal.user_pinned_rank = 2
        "a_high",
        "a_low",
        "a_prospect",  # tier 3 last despite score 99
    ]
    keys = [today_sort_key(action, deals) for action in ordered]
    assert keys == sorted(keys)


def test_prospecting_cannot_outrank_tier1_even_with_higher_score(db):
    deals: dict[str, Deal] = {}
    ordered = sort_today_actions(
        [
            Action(
                id="p",
                title="Prospect",
                type=ActionType.PROSPECTING,
                source="google_sheets",
                source_id="p1",
                tier=3,
                priority_score=100,
            ),
            Action(
                id="t1",
                title="Deal work",
                type=ActionType.COMMITMENT,
                source="memory",
                tier=1,
                priority_score=1,
            ),
        ],
        deals,
    )
    assert [a.id for a in ordered] == ["t1", "p"]


def test_why_from_stored_acme_breakdown(seeded_db):
    recompute_all(seeded_db, now=NOW, tz=TZ)
    deal = get_deal(seeded_db, "dl_acme_sign")
    assert deal is not None
    bullets = why_from_stored(deal.priority_breakdown_json)
    assert bullets
    joined = " ".join(bullets)
    assert "£75k" in joined or "75k" in joined
    action = get_action(seeded_db, "ac_acme_pricing")
    assert action is not None
    why = why_for_action(action, deal)
    assert why
    assert any("clos" in b.lower() or "£" in b or "owe" in b.lower() for b in why)


def test_apply_complete_writes_feedback_and_completes_action(seeded_db):
    recompute_all(seeded_db, now=NOW, tz=TZ)
    apply_complete(seeded_db, "ac_acme_pricing", fulfil_commitment=True)
    action = get_action(seeded_db, "ac_acme_pricing")
    assert action is not None
    assert enum_str(action.status) == ActionStatus.COMPLETED.value
    events = [enum_str(row.event) for row in list_user_feedback(seeded_db)]
    assert FeedbackEvent.COMPLETED.value in events


def test_apply_boost_writes_feedback_and_moves_card(seeded_db):
    recompute_all(seeded_db, now=NOW, tz=TZ)
    deals = {deal.id: deal for deal in list_deals(seeded_db)}
    today = local_today(NOW, TZ)
    before = sort_today_actions(
        [
            action
            for action in list_actions(seeded_db, status=ActionStatus.OPEN)
            if is_visible_today(action, today)
        ],
        deals,
    )
    assert before
    first_id = before[0].id
    apply_boost(seeded_db, first_id, up=False)
    deals_after = {deal.id: deal for deal in list_deals(seeded_db)}
    after = sort_today_actions(
        [
            action
            for action in list_actions(seeded_db, status=ActionStatus.OPEN)
            if is_visible_today(action, today)
        ],
        deals_after,
    )
    assert after[0].id != first_id or len(after) == 1
    boosted = get_action(seeded_db, first_id)
    assert boosted is not None
    assert boosted.user_boost == -8
    events = [enum_str(row.event) for row in list_user_feedback(seeded_db)]
    assert FeedbackEvent.BOOST_DOWN.value in events


def test_apply_snooze_and_dismiss_write_feedback(seeded_db):
    recompute_all(seeded_db, now=NOW, tz=TZ)
    until = date(2026, 9, 15)
    apply_snooze(seeded_db, "ac_gamma_follow", until=until)
    snoozed = get_action(seeded_db, "ac_gamma_follow")
    assert snoozed is not None
    assert snoozed.snoozed_until == "2026-09-15"
    assert not is_visible_today(snoozed, local_today(NOW, TZ))
    apply_dismiss(seeded_db, "ac_zeta_intro", reason="not now")
    dismissed = get_action(seeded_db, "ac_zeta_intro")
    assert dismissed is not None
    assert enum_str(dismissed.status) == ActionStatus.DISMISSED.value
    assert dismissed.dismissed_reason == "not now"
    events = {enum_str(row.event) for row in list_user_feedback(seeded_db)}
    assert FeedbackEvent.SNOOZED.value in events
    assert FeedbackEvent.DISMISSED.value in events
