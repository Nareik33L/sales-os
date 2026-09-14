"""Recompute persists scores, breakdown JSON, attention, and side-effect actions."""

from __future__ import annotations

import json

from core.models import (
    Action,
    ActionType,
    Company,
    Deal,
    DealSource,
    Memory,
    MemoryDirection,
    MemoryType,
    Meeting,
    MeetingSource,
    get_action,
    get_deal,
    list_actions,
    list_review_items,
    upsert_action,
    upsert_company,
    upsert_deal,
    upsert_meeting,
    upsert_memory,
)
from core.prioritisation import recompute_all
from tests.prioritisation.helpers import NOW, TZ


def _acme_rows(db):
    company = upsert_company(
        db,
        Company(id="co_acme_p", name="Acme", normalised_name="acme", is_strategic=False),
    )
    deal = upsert_deal(
        db,
        Deal(
            id="dl_acme_p",
            external_id="hs-acme-p",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Acme — Xodo Sign",
            company_id=company.id,
            company_name="Acme",
            deal_value=75000,
            currency="GBP",
            deal_value_gbp=75000,
            close_date="2026-09-18",
            last_activity_at="2026-09-05T08:00:00Z",
        ),
    ).deal
    memory = upsert_memory(
        db,
        Memory(
            id="mem_acme_p",
            type=MemoryType.COMMITMENT,
            subject="revised pricing",
            content="Send revised pricing to Acme.",
            deal_id=deal.id,
            direction=MemoryDirection.USER_TO_CUSTOMER,
            due_date="2026-09-13",
            confidence=0.85,
            valid_from="2026-09-14T08:00:00Z",
            created_by="rules",
        ),
    )
    action = upsert_action(
        db,
        Action(
            id="ac_acme_p",
            title="Send revised pricing",
            type=ActionType.COMMITMENT,
            source="memory",
            source_id="mem_acme_p",
            origin_memory_id=memory.id,
            deal_id=deal.id,
            due_date="2026-09-13",
        ),
    )
    return deal, action


def test_recompute_persists_acme_82_4_and_breakdown(db):
    deal, action = _acme_rows(db)
    result = recompute_all(db, now=NOW, tz=TZ)
    stored = get_deal(db, deal.id)
    assert stored.priority_score == 82.4
    assert str(stored.attention_status) == "HIGH"
    assert stored.priority_computed_at is not None
    payload = json.loads(stored.priority_breakdown_json)
    assert payload["score"] == 82.4
    for key in ("deal_value", "close_urgency", "stale_activity", "outstanding_commitment"):
        component = payload[key]
        assert "signal" in component
        assert "weight" in component
        assert "contribution" in component
        assert "reason" in component
    assert payload["deal_value"]["signal"] == 97.5
    scored = get_action(db, action.id)
    assert scored.priority_score == 86.2
    assert scored.system_rank == 1
    assert result.deal_scores[deal.id].score == 82.4


def test_recompute_creates_hygiene_prep_and_chase(db):
    company = upsert_company(db, Company(name="Gamma", normalised_name="gamma"))
    deal = upsert_deal(
        db,
        Deal(
            external_id="hs-gamma-p",
            source=DealSource.HUBSPOT,
            product="XODO_SIGN",
            name="Gamma — Xodo Sign",
            company_id=company.id,
            company_name="Gamma",
            deal_value_gbp=20000,
            close_date="2026-09-01",
            last_activity_at="2026-09-10T08:00:00Z",
        ),
    ).deal
    upsert_meeting(
        db,
        Meeting(
            id="mt_gamma_today",
            source=MeetingSource.CALENDLY,
            start_at="2026-09-14T09:30:00Z",
            end_at="2026-09-14T10:00:00Z",
            deal_id=deal.id,
            company_id=company.id,
        ),
    )
    upsert_memory(
        db,
        Memory(
            type=MemoryType.COMMITMENT,
            subject="signed order",
            content="Gamma will send the signed order.",
            deal_id=deal.id,
            direction=MemoryDirection.CUSTOMER_TO_USER,
            owner_label="Gina Sample",
            due_date="2026-09-10",
            confidence=0.7,
            valid_from="2026-09-14T08:00:00Z",
            created_by="rules",
        ),
    )
    first = recompute_all(db, now=NOW, tz=TZ)
    assert first.created_action_ids
    titles = {a.title for a in list_actions(db)}
    assert any(t.startswith("Update close date for Gamma") for t in titles)
    assert any(t.startswith("Prepare for Gamma") for t in titles)
    assert any(t.startswith("Chase Gina Sample for signed order") for t in titles)
    kinds = {str(item.kind) for item in list_review_items(db)}
    assert "CLOSE_DATE_PASSED" in kinds
    second = recompute_all(db, now=NOW, tz=TZ)
    assert second.created_action_ids == []
    assert len(list_actions(db)) == len(list(titles))


def test_recompute_on_seeded_db_does_not_raise(seeded_db):
    result = recompute_all(seeded_db, now=NOW, tz=TZ)
    assert result.deal_scores
    acme = get_deal(seeded_db, "dl_acme_sign")
    assert acme.priority_breakdown_json
    assert acme.priority_computed_at
