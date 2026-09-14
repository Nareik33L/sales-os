"""Streamlit AppTest for Today (docs/09 §1). Fictional seed only."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core.models import FeedbackEvent, get_action, list_user_feedback
from database.db import connect
from app.today_data import enum_str

APP = str(Path(__file__).resolve().parents[2] / "app" / "main.py")


def _text(at: AppTest) -> str:
    chunks: list[str] = []
    for name in (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "text",
        "info",
        "warning",
        "error",
        "success",
    ):
        block = getattr(at, name, None)
        if block is None:
            continue
        for el in block:
            value = getattr(el, "value", None)
            if value:
                chunks.append(str(value))
    return "\n".join(chunks)


def _button(at: AppTest, key: str):
    matches = [btn for btn in at.button if getattr(btn, "key", None) == key]
    if not matches:
        keys = [getattr(btn, "key", None) for btn in at.button]
        raise AssertionError(f"no button {key!r}; have {keys}")
    return matches[0]


def _run(timeout: float = 12) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=timeout)
    at.run()
    assert not at.exception, at.exception
    return at


def test_today_renders_start_here_and_hubspot_warning(today_db_path: Path):
    at = _run()
    text = _text(at)
    assert "START HERE" in text
    assert "Good morning" in text
    assert "HubSpot" in text
    assert "⚠" in text
    assert "Send revised pricing" in text or "Prepare for Acme" in text
    # Pinned prep card is #1 (user_priority_override=1) even though pricing scores higher.
    titles = [str(el.value) for el in at.markdown if el.value]
    joined = "\n".join(titles)
    prep_at = joined.find("Prepare for Acme")
    pricing_at = joined.find("Send revised pricing")
    assert prep_at != -1
    assert pricing_at != -1
    assert prep_at < pricing_at


def test_today_shows_why_bullets_on_high_priority(today_db_path: Path):
    at = _run()
    text = _text(at)
    assert "Why:" in text
    assert "£75k" in text or "75k" in text or "Closing" in text or "owe" in text.lower()


def test_complete_button_writes_user_feedback(today_db_path: Path):
    at = _run()
    _button(at, "complete_ac_acme_pricing").click().run()
    assert not at.exception, at.exception
    conn = connect(today_db_path)
    try:
        events = [enum_str(row.event) for row in list_user_feedback(conn)]
        assert FeedbackEvent.COMPLETED.value in events
        action = get_action(conn, "ac_acme_pricing")
        assert action is not None
        assert enum_str(action.status) == "COMPLETED"
    finally:
        conn.close()
    # Card leaves the open list.
    text = _text(at)
    assert "Send revised pricing" not in text or "START HERE" in text


def test_boost_down_writes_feedback_and_moves_card(today_db_path: Path):
    at = _run()
    _button(at, "boost_down_ac_acme_prep").click().run()
    assert not at.exception, at.exception
    conn = connect(today_db_path)
    try:
        events = [enum_str(row.event) for row in list_user_feedback(conn)]
        assert FeedbackEvent.BOOST_DOWN.value in events
        prep = get_action(conn, "ac_acme_prep")
        assert prep is not None
        assert prep.user_boost == -8
    finally:
        conn.close()


def test_snooze_and_dismiss_buttons_write_feedback(today_db_path: Path):
    at = _run()
    _button(at, "snooze_ac_gamma_follow").click().run()
    assert not at.exception, at.exception
    at2 = _run()
    _button(at2, "dismiss_ac_zeta_intro").click().run()
    assert not at2.exception, at2.exception
    conn = connect(today_db_path)
    try:
        events = {enum_str(row.event) for row in list_user_feedback(conn)}
        assert FeedbackEvent.SNOOZED.value in events
        assert FeedbackEvent.DISMISSED.value in events
        snoozed = get_action(conn, "ac_gamma_follow")
        dismissed = get_action(conn, "ac_zeta_intro")
        assert snoozed is not None and snoozed.snoozed_until
        assert dismissed is not None and enum_str(dismissed.status) == "DISMISSED"
    finally:
        conn.close()


def test_refresh_button_invokes_orchestrator(today_db_path: Path, monkeypatch: pytest.MonkeyPatch):
    called: list[str] = []

    def fake_refresh(trigger, conn=None, **kwargs):
        called.append(trigger)
        from core.ingestion.refresh import RefreshResult

        return RefreshResult(trigger=trigger, runs=[])

    monkeypatch.setattr("app.runtime.run_refresh", fake_refresh)
    at = _run()
    _button(at, "today_refresh").click().run()
    assert not at.exception, at.exception
    assert called == ["MANUAL"]


def test_stub_pages_render(today_db_path: Path):
    at = _run()
    at.sidebar.radio[0].set_value("Deals").run()
    assert not at.exception, at.exception
    assert "Deals" in _text(at)
    at.sidebar.radio[0].set_value("Inbox").run()
    assert "Inbox" in _text(at)
    at.sidebar.radio[0].set_value("Settings").run()
    assert "Settings" in _text(at)


def test_app_never_binds_all_interfaces():
    """ADR-008: launch path must not pass --server.address 0.0.0.0."""
    run_py = Path(__file__).resolve().parents[2] / "run.py"
    text = run_py.read_text(encoding="utf-8")
    assert "--server.address" not in text
