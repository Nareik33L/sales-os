"""Builders for fictional prioritisation fixtures. Acme Ltd only, no real names."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config.loaders import load_priority_weights
from core.models.schemas import (
    Action,
    ActionType,
    Deal,
    DealSource,
    Meeting,
    MeetingSource,
    MeetingStatus,
    Memory,
    MemoryDirection,
    MemoryStatus,
    MemoryType,
)

NOW = datetime(2026, 9, 14, 8, 0, 0, tzinfo=timezone.utc)
TZ = ZoneInfo("Europe/London")
VALID_FROM = "2026-09-14T08:00:00Z"


def default_cfg():
    return load_priority_weights()


def acme_deal(**overrides) -> Deal:
    data = dict(
        id="dl_acme_sign",
        external_id="hs-acme-sign",
        source=DealSource.HUBSPOT,
        product="XODO_SIGN",
        name="Acme — Xodo Sign",
        company_name="Acme",
        deal_value=75000.0,
        currency="GBP",
        deal_value_gbp=75000.0,
        close_date="2026-09-18",
        last_activity_at="2026-09-05T08:00:00Z",
        is_closed=False,
    )
    data.update(overrides)
    return Deal(**data)


def commitment_memory(**overrides) -> Memory:
    data = dict(
        type=MemoryType.COMMITMENT,
        status=MemoryStatus.ACTIVE,
        subject="revised pricing",
        content="Send revised pricing to Acme.",
        direction=MemoryDirection.USER_TO_CUSTOMER,
        due_date="2026-09-13",
        confidence=0.85,
        valid_from=VALID_FROM,
        created_by="rules",
    )
    data.update(overrides)
    return Memory(**data)


def send_pricing_action(**overrides) -> Action:
    data = dict(
        id="ac_acme_pricing",
        title="Send revised pricing",
        type=ActionType.COMMITMENT,
        source="memory",
        source_id="mem_acme_pricing",
        deal_id="dl_acme_sign",
        due_date="2026-09-13",
    )
    data.update(overrides)
    return Action(**data)


def meeting(**overrides) -> Meeting:
    data = dict(
        source=MeetingSource.CALENDLY,
        start_at="2026-09-14T09:30:00Z",
        end_at="2026-09-14T10:00:00Z",
        status=MeetingStatus.SCHEDULED,
        deal_id="dl_acme_sign",
    )
    data.update(overrides)
    return Meeting(**data)
