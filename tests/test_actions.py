"""Action tier assignment and (source, source_id) upsert.

Fictional companies only (Acme Ltd, Zeta Example). See docs/02-data-model.md
§actions, docs/03-prioritisation.md §3, ADR-007, SOS-05.
"""

from __future__ import annotations

import pytest

from config.loaders import load_priority_weights
from core.models import (
    Action,
    ActionType,
    assign_action_tier,
    get_action,
    get_action_by_source_id,
    list_actions,
    load_action_tier_by_type,
    tier_for_action_type,
    upsert_action,
)

# docs/03 §3 and config/priority_weights.yaml action.tier_by_type
TIER_1_TYPES = (
    ActionType.COMMITMENT,
    ActionType.TRANSCRIPT_ACTION,
    ActionType.EMAIL_FOLLOWUP,
    ActionType.HUBSPOT_TASK,
    ActionType.MEETING_PREP,
    ActionType.MEETING_FOLLOWUP,
)
TIER_2_TYPES = (
    ActionType.TODO_TASK,
    ActionType.DATA_HYGIENE,
    ActionType.REVIEW,
    ActionType.MANUAL,
)


def test_committed_config_maps_every_action_type():
    mapping = load_priority_weights().action.tier_by_type
    assert mapping == load_action_tier_by_type()
    assert set(mapping) == {t.value for t in ActionType}
    for action_type in TIER_1_TYPES:
        assert mapping[action_type.value] == 1
    for action_type in TIER_2_TYPES:
        assert mapping[action_type.value] == 2
    assert mapping[ActionType.PROSPECTING.value] == 3


def test_tier_derived_from_type_and_config():
    mapping = load_action_tier_by_type()
    for action_type in ActionType:
        expected = mapping[action_type.value]
        assert tier_for_action_type(action_type) == expected
        assert tier_for_action_type(action_type.value) == expected


def test_prospecting_is_always_tier_3():
    assert tier_for_action_type(ActionType.PROSPECTING) == 3
    # ADR-007: a mapping (or caller) cannot promote prospecting above deal work.
    assert tier_for_action_type(ActionType.PROSPECTING, tier_by_type={"PROSPECTING": 1}) == 3
    assert tier_for_action_type("PROSPECTING", tier_by_type={"PROSPECTING": 2}) == 3


def test_custom_mapping_overrides_non_prospecting_types():
    assert tier_for_action_type(ActionType.MANUAL, tier_by_type={"MANUAL": 1}) == 1


def test_unknown_type_raises():
    with pytest.raises(ValueError, match="no action.tier_by_type mapping"):
        tier_for_action_type("NOT_A_TYPE")


def test_invalid_tier_in_mapping_raises():
    with pytest.raises(ValueError, match="invalid action tier"):
        tier_for_action_type(ActionType.MANUAL, tier_by_type={"MANUAL": 9})


def test_assign_action_tier_sets_tier_without_caller_value():
    action = Action(
        title="Send revised pricing to Acme Ltd",
        type=ActionType.COMMITMENT,
        source="memory",
        source_id="mem_acme_pricing",
    )
    assigned = assign_action_tier(action)
    assert assigned.tier == 1
    assert action.tier == 2  # default left unchanged on the original


def test_upsert_sets_tier_for_every_mapped_type(db):
    mapping = load_action_tier_by_type()
    for type_name, expected in mapping.items():
        saved = upsert_action(
            db,
            Action(
                title=f"Acme Ltd — {type_name}",
                type=ActionType(type_name),
                source="fixture",
                source_id=f"acme-{type_name.lower()}",
            ),
        )
        assert saved.tier == expected
        assert get_action(db, saved.id).tier == expected


def test_upsert_overwrites_caller_supplied_tier(db):
    commitment = upsert_action(
        db,
        Action(
            title="Send revised pricing to Acme Ltd",
            type=ActionType.COMMITMENT,
            tier=3,
            source="memory",
            source_id="mem_acme_pricing",
        ),
    )
    assert commitment.tier == 1

    prospecting = upsert_action(
        db,
        Action(
            title="Intro email — Zeta Example",
            type=ActionType.PROSPECTING,
            tier=1,
            source="google_sheets",
            source_id="seq-1|zeta example|zee example|intro",
        ),
    )
    assert prospecting.tier == 3


def test_upsert_by_source_and_source_id_updates_in_place(db):
    first = upsert_action(
        db,
        Action(
            title="Call Ada Example at Acme Ltd",
            type=ActionType.HUBSPOT_TASK,
            source="hubspot",
            source_id="hs-task-acme-1",
            description="first sync",
        ),
        now="2026-09-14T08:00:00Z",
    )
    second = upsert_action(
        db,
        Action(
            title="Call Ada Example at Acme Ltd — follow up",
            type=ActionType.HUBSPOT_TASK,
            source="hubspot",
            source_id="hs-task-acme-1",
            description="second sync",
        ),
        now="2026-09-14T09:00:00Z",
    )
    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.title == "Call Ada Example at Acme Ltd — follow up"
    assert second.description == "second sync"
    assert second.tier == 1
    assert second.updated_at == "2026-09-14T09:00:00Z"
    count = db.execute(
        "SELECT count(*) AS n FROM actions WHERE source = ? AND source_id = ?",
        ("hubspot", "hs-task-acme-1"),
    ).fetchone()["n"]
    assert count == 1
    assert get_action_by_source_id(db, "hubspot", "hs-task-acme-1").id == first.id


def test_upsert_different_source_id_inserts_new_row(db):
    first = upsert_action(
        db,
        Action(
            title="Prepare for Acme Ltd 10:30",
            type=ActionType.MEETING_PREP,
            source="calendly",
            source_id="cal-acme-1",
        ),
    )
    second = upsert_action(
        db,
        Action(
            title="Follow up after Acme Ltd",
            type=ActionType.MEETING_FOLLOWUP,
            source="calendly",
            source_id="cal-acme-2",
        ),
    )
    assert first.id != second.id
    assert first.tier == 1 and second.tier == 1
    count = db.execute("SELECT count(*) AS n FROM actions").fetchone()["n"]
    assert count == 2


def test_upsert_refreshes_tier_when_type_changes(db):
    first = upsert_action(
        db,
        Action(
            title="Update Acme Ltd close date",
            type=ActionType.MANUAL,
            source="ui",
            source_id="hygiene-acme-1",
        ),
    )
    assert first.tier == 2
    updated = upsert_action(
        db,
        Action(
            title="Update Acme Ltd close date",
            type=ActionType.COMMITMENT,
            source="ui",
            source_id="hygiene-acme-1",
        ),
    )
    assert updated.id == first.id
    assert updated.tier == 1
    assert updated.type == ActionType.COMMITMENT


def test_prospecting_cannot_outrank_tier1_in_list_order(db):
    """ADR-007: list_actions sorts tier first, so score cannot lift prospecting."""
    upsert_action(
        db,
        Action(
            title="Intro email — Zeta Example",
            type=ActionType.PROSPECTING,
            source="google_sheets",
            source_id="row-zeta-intro",
            priority_score=99.0,
        ),
    )
    upsert_action(
        db,
        Action(
            title="Review close date for Acme Ltd",
            type=ActionType.DATA_HYGIENE,
            source="rules",
            source_id="hygiene-acme-close",
            priority_score=50.0,
        ),
    )
    upsert_action(
        db,
        Action(
            title="Send revised pricing to Acme Ltd",
            type=ActionType.COMMITMENT,
            source="memory",
            source_id="mem_acme_pricing",
            priority_score=1.0,
        ),
    )
    ordered = list_actions(db)
    assert [a.tier for a in ordered] == [1, 2, 3]
    assert [a.type for a in ordered] == [
        ActionType.COMMITMENT,
        ActionType.DATA_HYGIENE,
        ActionType.PROSPECTING,
    ]
