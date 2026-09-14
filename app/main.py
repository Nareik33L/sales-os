"""Sales OS Streamlit entrypoint.

Sidebar: Today · Deals · Inbox · Settings. Streamlit is bound to localhost by
``.streamlit/config.toml`` (ADR-008). Never pass ``--server.address 0.0.0.0``.

DB connections are short-lived (see ``app.runtime.db_session``) and are never
stored in ``st.session_state``.
"""

from __future__ import annotations

import streamlit as st

from app.pages.deals import render_deals
from app.pages.inbox import render_inbox
from app.pages.settings import render_settings
from app.pages.today import render_today
from app.runtime import configure_page

configure_page(title="Sales OS")

st.sidebar.markdown("**Sales OS**")
page = st.sidebar.radio(
    "Page",
    ("Today", "Deals", "Inbox", "Settings"),
    index=0,
)

if page == "Today":
    render_today()
elif page == "Deals":
    render_deals()
elif page == "Inbox":
    render_inbox()
else:
    render_settings()
