"""Action card: headline, Why, feedback controls. No SQL / scoring."""

from __future__ import annotations

import streamlit as st

from app.components.feedback_buttons import FeedbackResult, feedback_buttons
from app.components.why_bullets import why_bullets
from app.today_data import ActionCardRow


def action_card(row: ActionCardRow) -> FeedbackResult | None:
    head_l, head_r = st.columns([4, 1])
    with head_l:
        st.markdown(f"**#{row.rank}  {row.headline}**")
        due = f" · {row.due_label}" if row.due_label else ""
        st.markdown(f"{row.action.title}{due}")
    with head_r:
        st.markdown(row.score_label)
    if row.attention.value == "HIGH" or row.why:
        why_bullets(row.why)
    return feedback_buttons(row)
