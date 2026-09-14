"""JSON fixtures under tests/prioritisation/cases/ (skill salesos-test-and-verify)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.models.schemas import Action, Deal, Meeting, Memory
from core.prioritisation import explain, score_action, score_deal
from tests.prioritisation.helpers import default_cfg

CASES_DIR = Path(__file__).parent / "cases"


def _cases() -> list[Path]:
    return sorted(CASES_DIR.glob("*.json"))


def _parse_now(raw: str | None) -> datetime:
    text = raw or "2026-09-14T08:00:00Z"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_case(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build(model, rows: list[dict] | dict | None):
    if rows is None:
        return [] if model is not Deal else None
    if isinstance(rows, dict):
        return model.model_validate(rows)
    return [model.model_validate(row) for row in rows]


@pytest.mark.parametrize("path", _cases(), ids=lambda p: p.stem)
def test_json_fixture_case(path: Path):
    payload = _load_case(path)
    cfg = default_cfg()
    now = _parse_now(payload.get("now"))
    tz = ZoneInfo(payload.get("timezone") or "Europe/London")
    deal = Deal.model_validate(payload["deal"])
    memories = _build(Memory, payload.get("memories") or [])
    meetings = _build(Meeting, payload.get("meetings") or [])
    actions = _build(Action, payload.get("actions") or [])
    breakdown = score_deal(
        deal,
        memories,
        meetings,
        cfg,
        now=now,
        tz=tz,
        is_strategic=bool(payload.get("is_strategic")),
    )
    expect = payload["expect"]
    if "score" in expect:
        assert breakdown.score == expect["score"]
    if "score_between" in expect:
        lo, hi = expect["score_between"]
        assert lo <= breakdown.score <= hi
    if "attention" in expect:
        assert str(breakdown.attention) == expect["attention"]
    bullets = explain(breakdown, cfg)
    if "bullets" in expect:
        assert bullets == expect["bullets"]
    for needle in expect.get("bullets_include") or []:
        assert needle in bullets, bullets
    for name, fields in (expect.get("components") or {}).items():
        component = breakdown.components[name]
        if "signal" in fields:
            assert component.signal == fields["signal"]
        if "contribution" in fields:
            assert component.contribution == fields["contribution"]
    if actions and "action_score" in expect:
        action_bd = score_action(actions[0], breakdown, cfg, now=now, tz=tz)
        assert action_bd.score == expect["action_score"]
        if "action_tier" in expect:
            assert action_bd.tier == expect["action_tier"]
