"""Complete / Snooze / ↑ / ↓ / Dismiss. Widgets only — no DB access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

import streamlit as st

from app.feedback import (
    SNOOZE_OPTIONS,
    SNOOZE_PICK_DATE,
    snooze_until_date,
)
from app.today_data import ActionCardRow
from core.models import ActionType
from core.prioritisation.engine import local_today, user_timezone


class FeedbackChoice(StrEnum):
    COMPLETE = "complete"
    SNOOZE = "snooze"
    BOOST_UP = "boost_up"
    BOOST_DOWN = "boost_down"
    DISMISS = "dismiss"
    OPEN_DEAL = "open_deal"


@dataclass
class FeedbackResult:
    choice: FeedbackChoice
    snooze_until: date | None = None
    dismiss_reason: str | None = None
    fulfil_commitment: bool = False


def _enum_str(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def feedback_buttons(row: ActionCardRow) -> FeedbackResult | None:
    action = row.action
    aid = action.id
    has_commitment = bool(
        action.origin_memory_id
        and _enum_str(action.type) == ActionType.COMMITMENT.value
    )
    fulfil = False
    if has_commitment:
        fulfil = st.checkbox(
            "Mark linked commitment as fulfilled?",
            value=True,
            key=f"fulfil_{aid}",
        )

    c1, c2, c3, c4, c5, c6 = st.columns([1.2, 1.6, 0.5, 0.5, 1.1, 1.1])
    clicked: FeedbackResult | None = None
    with c1:
        if st.button("Complete", key=f"complete_{aid}"):
            clicked = FeedbackResult(
                choice=FeedbackChoice.COMPLETE,
                fulfil_commitment=bool(fulfil),
            )
    with c2:
        snooze_choice = st.selectbox(
            "Snooze",
            options=list(SNOOZE_OPTIONS),
            key=f"snooze_choice_{aid}",
            label_visibility="collapsed",
        )
        picked: date | None = None
        if snooze_choice == SNOOZE_PICK_DATE:
            picked = st.date_input(
                "Snooze until",
                value=local_today(tz=user_timezone()),
                key=f"snooze_date_{aid}",
            )
            if not isinstance(picked, date):
                picked = None
        if st.button("Snooze", key=f"snooze_{aid}"):
            clicked = FeedbackResult(
                choice=FeedbackChoice.SNOOZE,
                snooze_until=snooze_until_date(
                    str(snooze_choice), picked=picked
                ),
            )
    with c3:
        if st.button("↑", key=f"boost_up_{aid}"):
            clicked = FeedbackResult(choice=FeedbackChoice.BOOST_UP)
    with c4:
        if st.button("↓", key=f"boost_down_{aid}"):
            clicked = FeedbackResult(choice=FeedbackChoice.BOOST_DOWN)
    with c5:
        reason = st.text_input(
            "Dismiss reason",
            key=f"dismiss_reason_{aid}",
            placeholder="reason (optional)",
            label_visibility="collapsed",
        )
        if st.button("Dismiss", key=f"dismiss_{aid}"):
            clicked = FeedbackResult(
                choice=FeedbackChoice.DISMISS,
                dismiss_reason=reason,
            )
    with c6:
        if row.deal is not None and st.button("Open deal", key=f"open_deal_{aid}"):
            clicked = FeedbackResult(choice=FeedbackChoice.OPEN_DEAL)
    return clicked
