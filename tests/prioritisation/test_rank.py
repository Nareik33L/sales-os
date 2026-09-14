"""Ranking: tier first, then pin, then score. Prospecting never above tier 1."""

from __future__ import annotations

from core.models.schemas import Action, ActionType, ProspectingItem
from core.prioritisation import rank_actions, score_deal
from tests.prioritisation.helpers import (
    NOW,
    TZ,
    acme_deal,
    commitment_memory,
    default_cfg,
    send_pricing_action,
)


def test_prospecting_never_above_tier1():
    cfg = default_cfg()
    deal = acme_deal(
        id="dl_small",
        external_id="hs-small",
        deal_value=1000,
        deal_value_gbp=1000,
        close_date="2026-12-31",
        last_activity_at="2026-09-14T08:00:00Z",
    )
    deal_bd = score_deal(deal, [], [], cfg, now=NOW, tz=TZ)
    commitment = Action(
        id="a_commit",
        title="Send a note to Acme",
        type=ActionType.COMMITMENT,
        source="memory",
        deal_id=deal.id,
        due_date=None,
        priority_score=1.0,
    )
    prospecting = Action(
        id="a_prospect",
        title="Intro email — Zeta Example",
        type=ActionType.PROSPECTING,
        source="google_sheets",
        source_id="row-zeta",
        due_date="2026-09-01",
        priority_score=99.0,
    )
    ranked = rank_actions(
        [prospecting, commitment],
        {deal.id: deal_bd},
        cfg,
        now=NOW,
        tz=TZ,
    )
    assert [item.tier for item in ranked] == [1, 3]
    assert ranked[0].action.type == ActionType.COMMITMENT
    assert ranked[1].action.type == ActionType.PROSPECTING
    assert ranked[1].score > ranked[0].score


def test_pinned_rank_overrides_score_within_tier():
    cfg = default_cfg()
    deal = acme_deal()
    deal_bd = score_deal(deal, [commitment_memory()], [], cfg, now=NOW, tz=TZ)
    overdue = send_pricing_action(id="a_overdue", user_priority_override=None)
    later = send_pricing_action(
        id="a_later",
        title="Send a deck",
        source_id="mem_deck",
        due_date="2026-10-01",
        user_priority_override=1,
    )
    ranked = rank_actions(
        [overdue, later],
        {deal.id: deal_bd},
        cfg,
        deals=[deal],
        now=NOW,
        tz=TZ,
    )
    assert ranked[0].action.id == "a_later"
    assert ranked[0].pinned_rank == 1
    assert ranked[1].action.id == "a_overdue"
    assert ranked[0].score < ranked[1].score


def test_deal_pin_applies_to_its_actions():
    cfg = default_cfg()
    pinned = acme_deal(id="dl_pin", external_id="hs-pin", user_pinned_rank=1)
    other = acme_deal(id="dl_other", external_id="hs-other")
    bd_pin = score_deal(pinned, [commitment_memory()], [], cfg, now=NOW, tz=TZ)
    bd_other = score_deal(other, [commitment_memory()], [], cfg, now=NOW, tz=TZ)
    a_pin = send_pricing_action(id="a_pin", deal_id=pinned.id, due_date="2026-10-01")
    a_other = send_pricing_action(
        id="a_other",
        deal_id=other.id,
        source_id="other",
        due_date="2026-09-13",
    )
    ranked = rank_actions(
        [a_other, a_pin],
        {pinned.id: bd_pin, other.id: bd_other},
        cfg,
        deals=[pinned, other],
        now=NOW,
        tz=TZ,
    )
    assert ranked[0].action.id == "a_pin"


def test_prospecting_sheet_priority_then_due_date():
    cfg = default_cfg()
    a_item = Action(
        id="p_a",
        title="A-row — Zeta Example",
        type=ActionType.PROSPECTING,
        source="google_sheets",
        source_id="row-a",
        due_date="2026-09-20",
    )
    b_item = Action(
        id="p_b",
        title="B-row — Zeta Example",
        type=ActionType.PROSPECTING,
        source="google_sheets",
        source_id="row-b",
        due_date="2026-09-15",
    )
    items = [
        ProspectingItem(row_key="row-a", priority="A", due_date="2026-09-20"),
        ProspectingItem(row_key="row-b", priority="B", due_date="2026-09-15"),
    ]
    ranked = rank_actions(
        [b_item, a_item],
        {},
        cfg,
        prospecting_items=items,
        now=NOW,
        tz=TZ,
    )
    assert [item.action.id for item in ranked] == ["p_a", "p_b"]
