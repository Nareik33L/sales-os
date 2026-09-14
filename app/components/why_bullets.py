"""Why bullets from ``core.prioritisation.explain`` — no AI, no scoring here."""

from __future__ import annotations

from collections.abc import Sequence

import streamlit as st


def why_bullets(bullets: Sequence[str]) -> None:
    if not bullets:
        return
    st.caption("Why: " + " · ".join(bullets))
