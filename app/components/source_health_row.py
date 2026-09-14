"""Per-connector health row. Status text only — never raises."""

from __future__ import annotations

from collections.abc import Sequence

import streamlit as st

from app.today_data import SourceHealth


def source_health_row(rows: Sequence[SourceHealth]) -> None:
    if not rows:
        st.caption("No connectors configured.")
        return
    for row in rows:
        message = row.message or ""
        when = f" · {row.time_label}" if row.time_label else ""
        line = f"{row.icon} {row.label}{when}"
        if message:
            line = f"{line} — {message}"
        st.caption(line)
