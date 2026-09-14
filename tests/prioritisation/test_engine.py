"""Doc 03 §8 Acme worked example and the engine's other locked behaviours."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from core.models.schemas import (
    Action,
    ActionType,
    AttentionStatus,
    DealSource,
    MemoryDirection,
    MemoryStatus,
)
from core.prioritisation import explain, score_action, score_deal
from tests.prioritisation.helpers import (
    NOW,
    TZ,
    acme_deal,
    commitment_memory,
    default_cfg,
    meeting,
    send_pricing_action,
)


def test_acme_worked_example_score_82_4_high():
    """docs/03 §8: Acme £75k, close in 4 days, stale 9d, overdue commitment, no meeting."""
    cfg = default_cfg()
    deal = acme_deal()
    memories = [commitment_memory()]
    breakdown = score_deal(deal, memories, [], cfg, now=NOW, tz=TZ, is_strategic=False)
    assert breakdown.score == 82.4
    assert breakdown.attention == AttentionStatus.HIGH
    value = breakdown.components["deal_value"]
    assert value.signal == 97.5
    assert value.contribution == 29.3
    assert breakdown.components["outstanding_commitment"].signal == 100
    assert breakdown.components["outstanding_commitment"].contribution == 15.0
    assert breakdown.components["meeting_proximity"].signal == 0
    stored = breakdown.to_json()
    assert '"signal"' in stored
    assert '"weight"' in stored
    assert '"contribution"' in stored
    assert '"reason"' in stored
    bullets = explain(breakdown, cfg)
    assert bullets == [
        "£75k deal",
        "Closing in 4 days",
        "You owe: revised pricing (due yesterday)",
        "No activity for 9 days",
    ]
    action = score_action(send_pricing_action(), breakdown, cfg, now=NOW, tz=TZ)
    assert action.score == 86.2
    assert action.tier == 1
    assert action.components["due_date"].signal == 92


def test_log_scaling_10k_meaningful_150k_capped():
    cfg = default_cfg()
    small = score_deal(
        acme_deal(deal_value=10000, deal_value_gbp=10000, last_activity_at=NOW.strftime("%Y-%m-%dT%H:%M:%SZ")),
        [],
        [],
        cfg,
        now=NOW,
        tz=TZ,
    )
    huge = score_deal(
        acme_deal(deal_value=150000, deal_value_gbp=150000, last_activity_at=NOW.strftime("%Y-%m-%dT%H:%M:%SZ")),
        [],
        [],
        cfg,
        now=NOW,
        tz=TZ,
    )
    ref = score_deal(
        acme_deal(deal_value=100000, deal_value_gbp=100000, last_activity_at=NOW.strftime("%Y-%m-%dT%H:%M:%SZ")),
        [],
        [],
        cfg,
        now=NOW,
        tz=TZ,
    )
    assert small.components["deal_value"].signal == 80.0
    assert huge.components["deal_value"].signal == 100.0
    assert ref.components["deal_value"].signal == 100.0
    raw_150 = 100 * math.log10(1 + 150000) / math.log10(1 + 100000)
    assert raw_150 > 100


def test_close_date_passed_is_maximum_urgency():
    cfg = default_cfg()
    breakdown = score_deal(
        acme_deal(close_date="2026-09-12"),
        [],
        [],
        cfg,
        now=NOW,
        tz=TZ,
    )
    assert breakdown.components["close_urgency"].signal == 100
    assert "Close date passed (12 Sep)" in explain(breakdown, cfg)


def test_stale_but_far_cap():
    cfg = default_cfg()
    far = score_deal(
        acme_deal(
            close_date="2026-12-20",
            last_activity_at="2026-08-01T08:00:00Z",
        ),
        [],
        [],
        cfg,
        now=NOW,
        tz=TZ,
    )
    near = score_deal(
        acme_deal(
            close_date="2026-10-01",
            last_activity_at="2026-08-01T08:00:00Z",
        ),
        [],
        [],
        cfg,
        now=NOW,
        tz=TZ,
    )
    assert far.components["stale_activity"].signal == 50
    assert near.components["stale_activity"].signal == 100


def test_commitment_max_not_sum():
    cfg = default_cfg()
    memories = [
        commitment_memory(subject="revised pricing", due_date="2026-09-10"),
        commitment_memory(subject="security questionnaire", due_date="2026-09-11"),
        commitment_memory(subject="case study", due_date="2026-09-12"),
    ]
    breakdown = score_deal(acme_deal(deal_value_gbp=5000, deal_value=5000), memories, [], cfg, now=NOW, tz=TZ)
    component = breakdown.components["outstanding_commitment"]
    assert component.signal == 100
    assert component.contribution == 15.0
    bullets = explain(breakdown, cfg)
    assert "You owe: revised pricing (due 10 Sep)" in bullets
    assert "You owe: security questionnaire (due 11 Sep)" in bullets


def test_boost_bound_clamps_to_24():
    cfg = default_cfg()
    high = score_deal(acme_deal(user_boost=999), [commitment_memory()], [], cfg, now=NOW, tz=TZ)
    low = score_deal(acme_deal(user_boost=-999), [commitment_memory()], [], cfg, now=NOW, tz=TZ)
    assert high.components["user_boost"].contribution == 24
    assert low.components["user_boost"].contribution == -24
    assert high.score == 106.4
    assert low.score == 58.4


def test_strategic_account_adds_ten_and_bullet():
    cfg = default_cfg()
    breakdown = score_deal(
        acme_deal(),
        [commitment_memory()],
        [],
        cfg,
        now=NOW,
        tz=TZ,
        is_strategic=True,
    )
    assert breakdown.score == 92.4
    assert breakdown.components["is_strategic"].reason == "Strategic account"
    quiet = score_deal(
        acme_deal(
            close_date="2026-12-31",
            last_activity_at="2026-09-14T08:00:00Z",
            deal_value=1000,
            deal_value_gbp=1000,
        ),
        [],
        [],
        cfg,
        now=NOW,
        tz=TZ,
        is_strategic=True,
    )
    assert "Strategic account" in explain(quiet, cfg)


def test_closed_deal_attention_none():
    cfg = default_cfg()
    breakdown = score_deal(acme_deal(is_closed=True), [commitment_memory()], [], cfg, now=NOW, tz=TZ)
    assert breakdown.attention == AttentionStatus.NONE
    assert breakdown.score == 82.4


def test_unknown_value_close_activity_bullets():
    cfg = default_cfg()
    breakdown = score_deal(
        acme_deal(
            deal_value=None,
            deal_value_gbp=None,
            close_date=None,
            last_activity_at=None,
        ),
        [],
        [],
        cfg,
        now=NOW,
        tz=TZ,
    )
    bullets = explain(breakdown, cfg)
    assert "no value recorded" in bullets
    assert "no close date recorded" in bullets
    assert "no activity recorded" in bullets
    assert breakdown.components["deal_value"].signal == 0
    assert breakdown.components["close_urgency"].signal == 20
    assert breakdown.components["stale_activity"].signal == 70


def test_meeting_today_and_yesterday_followup():
    cfg = default_cfg()
    today = score_deal(acme_deal(), [], [meeting()], cfg, now=NOW, tz=TZ)
    assert today.components["meeting_proximity"].signal == 100
    assert "Meeting today 10:30" in explain(today, cfg)

    yesterday = meeting(
        start_at="2026-09-13T14:00:00Z",
        end_at="2026-09-13T14:30:00Z",
        status="HELD",
    )
    stale = score_deal(acme_deal(), [], [yesterday], cfg, now=NOW, tz=TZ)
    assert stale.components["meeting_proximity"].signal == 80
    assert "Met yesterday — no follow-up yet" in explain(stale, cfg)

    done = Action(
        title="Follow up after Acme",
        type=ActionType.MEETING_FOLLOWUP,
        source="calendly",
        status="COMPLETED",
        meeting_id=yesterday.id,
        deal_id="dl_acme_sign",
    )
    followed = score_deal(
        acme_deal(), [], [yesterday], cfg, now=NOW, tz=TZ, actions=[done]
    )
    assert followed.components["meeting_proximity"].signal == 0


def test_fulfilled_commitment_does_not_score():
    cfg = default_cfg()
    memory = commitment_memory(status=MemoryStatus.FULFILLED)
    breakdown = score_deal(acme_deal(), [memory], [], cfg, now=NOW, tz=TZ)
    assert breakdown.components["outstanding_commitment"].signal == 0


def test_customer_overdue_is_40_not_deal_alarm():
    cfg = default_cfg()
    memory = commitment_memory(
        direction=MemoryDirection.CUSTOMER_TO_USER,
        subject="internal approval",
        due_date="2026-09-10",
    )
    breakdown = score_deal(acme_deal(), [memory], [], cfg, now=NOW, tz=TZ)
    assert breakdown.components["outstanding_commitment"].signal == 40
    assert "Customer owes: internal approval (due 10 Sep)" in explain(breakdown, cfg)


def test_action_without_deal_inherits_30():
    cfg = default_cfg()
    action = Action(
        title="General to-do",
        type=ActionType.TODO_TASK,
        source="todo",
        due_date="2026-09-14",
    )
    breakdown = score_action(action, None, cfg, now=NOW, tz=TZ)
    assert breakdown.components["inherited_deal_score"].signal == 30
    assert breakdown.tier == 2
    # today due = 85; 0.6*30 + 0.4*85 = 18+34 = 52
    assert breakdown.score == 52.0


def test_midnight_london_uses_local_date_not_utc():
    """00:30 BST on 14 Sep is still 13 Sep 23:30 UTC — close date 'today' is the 14th."""
    cfg = default_cfg()
    now = datetime(2026, 9, 13, 23, 30, tzinfo=timezone.utc)
    breakdown = score_deal(
        acme_deal(close_date="2026-09-14", last_activity_at="2026-09-14T00:00:00+01:00"),
        [],
        [],
        cfg,
        now=now,
        tz=TZ,
    )
    assert breakdown.components["close_urgency"].reason == "Closing today"


def test_dst_spring_forward_london():
    cfg = default_cfg()
    tz = ZoneInfo("Europe/London")
    before = datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)  # 00:30 GMT, local 29th
    after = datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)  # 02:30 BST, local 29th
    deal = acme_deal(
        source=DealSource.HUBSPOT,
        close_date="2026-03-29",
        last_activity_at="2026-03-29T00:00:00Z",
    )
    for instant in (before, after):
        breakdown = score_deal(deal, [], [], cfg, now=instant, tz=tz)
        assert breakdown.components["close_urgency"].reason == "Closing today"
