"""Deal card for a high-attention deal with no open action."""

from __future__ import annotations

import streamlit as st

from app.components.why_bullets import why_bullets
from app.today_data import DealCardRow


def deal_card(row: DealCardRow) -> str | None:
    """Return ``add`` / ``open`` if a button was clicked, else None."""
    st.markdown(f"**{row.headline}**")
    why_bullets(row.why)
    add, open_deal = st.columns(2)
    clicked: str | None = None
    with add:
        if st.button("Add next step", key=f"add_step_{row.deal.id}"):
            clicked = "add"
    with open_deal:
        if st.button("Open deal", key=f"open_deal_card_{row.deal.id}"):
            clicked = "open"
    return clicked
