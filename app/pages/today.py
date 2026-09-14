"""Today page — docs/09-ui-spec.md §1.

Render functions only. Streamlit's pages/ autodiscovery of this file is
harmless: importing ``render_today`` does not draw widgets.
"""

from __future__ import annotations

import logging

import streamlit as st

from app.components.action_card import action_card
from app.components.deal_card import deal_card
from app.components.feedback_buttons import FeedbackChoice
from app.components.source_health_row import source_health_row
from app.feedback import (
    apply_add_next_step,
    apply_boost,
    apply_complete,
    apply_dismiss,
    apply_snooze,
)
from app.runtime import (
    db_session,
    greeting_name,
    prepare_today,
    trigger_manual_refresh,
)
from app.today_data import ActionCardRow, TodaySnapshot, load_today
from core.prioritisation.engine import format_gbp as _format_gbp

log = logging.getLogger("salesos.app.today")


def _safe(title: str, body) -> None:
    try:
        body()
    except Exception:
        log.exception("Today section %s failed", title)
        st.error(f"Couldn't load {title}. The rest of Today is still available.")


def _open_deal(deal_id: str) -> None:
    st.query_params["deal"] = deal_id
    st.rerun()


def _handle_action_feedback(row: ActionCardRow, result) -> None:
    if result is None:
        return
    if result.choice == FeedbackChoice.OPEN_DEAL and row.deal is not None:
        _open_deal(row.deal.id)
        return
    with db_session() as conn:
        if result.choice == FeedbackChoice.COMPLETE:
            apply_complete(
                conn,
                row.action.id,
                fulfil_commitment=result.fulfil_commitment,
            )
        elif result.choice == FeedbackChoice.SNOOZE and result.snooze_until is not None:
            apply_snooze(conn, row.action.id, until=result.snooze_until)
        elif result.choice == FeedbackChoice.BOOST_UP:
            apply_boost(conn, row.action.id, up=True)
        elif result.choice == FeedbackChoice.BOOST_DOWN:
            apply_boost(conn, row.action.id, up=False)
        elif result.choice == FeedbackChoice.DISMISS:
            apply_dismiss(conn, row.action.id, reason=result.dismiss_reason)
    st.rerun()


def _counts_row(snap: TodaySnapshot) -> None:
    value = _format_gbp(snap.tier1_high_value_gbp) if snap.tier1_high_value_gbp else "£0"
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"🔴 **DEALS** {snap.tier1_count} actions · {value}")
    c2.markdown(f"🟠 **FOLLOW-UPS** {snap.tier2_count}")
    c3.markdown(f"🔵 **PROSPECTING** {snap.tier3_count}")
    c4.markdown(f"📅 **MEETINGS today** {snap.meetings_today_count}")


def _header(snap: TodaySnapshot) -> None:
    left, right = st.columns([3, 2])
    with left:
        st.title(f"Good morning, {snap.greeting_name}.")
        things = "thing" if snap.attention_total == 1 else "things"
        questions = "question" if snap.question_count == 1 else "questions"
        st.caption(
            f"{snap.attention_total} {things} need your attention · "
            f"{snap.question_count} {questions}"
        )
    with right:
        if st.button("↻ Refresh", key="today_refresh"):
            with st.spinner("Refreshing sources…"):
                try:
                    with db_session() as conn:
                        trigger_manual_refresh(conn)
                except Exception:
                    log.exception("manual refresh failed")
                    st.warning("Refresh failed. Today is still using saved data.")
            st.rerun()
        summary = snap.health_summary
        extra = f" ({summary})" if summary else ""
        st.caption(f"Last refresh {snap.last_refresh_label} {snap.overall_icon}{extra}")
        source_health_row(snap.health)
    _counts_row(snap)


def _start_here(snap: TodaySnapshot) -> None:
    st.subheader("START HERE")
    tier1 = [row for row in snap.actions if row.action.tier == 1]
    if not tier1:
        st.info("Nothing in tier 1 right now.")
        return
    for row in tier1:
        with st.container(border=True):
            result = action_card(row)
        _handle_action_feedback(row, result)


def _meetings(snap: TodaySnapshot) -> None:
    st.subheader("UPCOMING MEETINGS")
    if not snap.meetings:
        st.caption("No meetings today.")
        return
    for row in snap.meetings:
        cols = st.columns([1, 4, 1])
        cols[0].markdown(f"**{row.when_label}**")
        cols[1].markdown(row.title)
        if row.deal is not None and cols[2].button(
            "Open deal", key=f"open_meeting_{row.meeting.id}"
        ):
            _open_deal(row.deal.id)


def _questions(snap: TodaySnapshot) -> None:
    st.subheader(f"QUESTIONS ({snap.question_count})")
    if not snap.questions:
        st.caption("No open questions.")
        return
    for item in snap.questions:
        cols = st.columns([4, 1])
        cols[0].markdown(item.question)
        cols[1].button("Answer", key=f"answer_{item.id}", disabled=True)


def _other_actions(snap: TodaySnapshot) -> None:
    st.subheader("OTHER ACTIONS")
    rest = [row for row in snap.actions if row.action.tier != 1]
    if not rest:
        st.caption("No follow-up or prospecting actions.")
        return
    for row in rest:
        with st.container(border=True):
            result = action_card(row)
        _handle_action_feedback(row, result)


def _recently_changed(snap: TodaySnapshot) -> None:
    st.subheader("RECENTLY CHANGED")
    if not snap.changes:
        st.caption("No deal changes since yesterday.")
        return
    for change in snap.changes:
        st.markdown(f"- {change.text}")


def _deal_cards(snap: TodaySnapshot) -> None:
    if not snap.deal_cards:
        return
    st.subheader("HIGH-PRIORITY DEALS WITHOUT A NEXT STEP")
    for row in snap.deal_cards:
        with st.container(border=True):
            clicked = deal_card(row)
        if clicked == "add":
            with db_session() as conn:
                apply_add_next_step(conn, row.deal.id)
            st.rerun()
        elif clicked == "open":
            _open_deal(row.deal.id)


def _deal_stub(deal_id: str) -> None:
    from core.models import get_deal

    if st.button("← Back to Today", key="back_today"):
        st.query_params.clear()
        st.rerun()
    with db_session() as conn:
        deal = get_deal(conn, deal_id)
    if deal is None:
        st.warning("Deal not found.")
        return
    st.header(deal.company_name or deal.name)
    value = _format_gbp(deal.deal_value_gbp) if deal.deal_value_gbp is not None else "—"
    st.caption(
        f"{value} · {deal.product} · Stage: {deal.stage or '—'} · "
        f"Close: {deal.close_date or '—'}"
    )
    st.info("Full deal detail ships in SOS-16. This is a Today v0 stub.")
    from app.today_data import why_from_stored
    from app.components.why_bullets import why_bullets as render_why

    render_why(why_from_stored(deal.priority_breakdown_json))


def render_today() -> None:
    deal_id = st.query_params.get("deal")
    if deal_id:
        _safe("Deal stub", lambda: _deal_stub(str(deal_id)))
        return
    try:
        with db_session() as conn:
            prepare_today(conn)
            name = greeting_name(conn)
            snap = load_today(conn, greeting=name)
    except Exception:
        log.exception("Today failed to load")
        st.error("Today could not load. Check Settings / logs; connector failures should not take this page down.")
        return
    _safe("Header", lambda: _header(snap))
    _safe("START HERE", lambda: _start_here(snap))
    _safe("Meetings", lambda: _meetings(snap))
    _safe("Questions", lambda: _questions(snap))
    _safe("Other actions", lambda: _other_actions(snap))
    _safe("Deal cards", lambda: _deal_cards(snap))
    _safe("Recently changed", lambda: _recently_changed(snap))
