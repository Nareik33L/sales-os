"""Action tier assignment from ``config/priority_weights.yaml``.

``actions.tier`` is the hard Today sort key (docs/03, ADR-007): 1 deal work,
2 follow-ups/admin, 3 prospecting. It is derived from ``type`` via
``action.tier_by_type``. Prospecting is always tier 3 — the mapping cannot
promote it above deal work.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from config.loaders import load_priority_weights
from core.models.schemas import Action, ActionType

ActionTier = Literal[1, 2, 3]
VALID_TIERS = frozenset({1, 2, 3})


def load_action_tier_by_type() -> dict[str, ActionTier]:
    """Return the committed ``action.tier_by_type`` mapping."""
    return dict(load_priority_weights().action.tier_by_type)


def tier_for_action_type(
    action_type: ActionType | str,
    *,
    tier_by_type: Mapping[str, int] | None = None,
) -> ActionTier:
    """Return the hard sort tier for an action type.

    Looks up ``action.tier_by_type`` from the SOS-06b typed loader unless a
    mapping is passed in (tests). ``PROSPECTING`` is always 3.
    """
    key = action_type.value if isinstance(action_type, ActionType) else str(action_type)
    mapping: Mapping[str, int]
    if tier_by_type is not None:
        mapping = tier_by_type
    else:
        mapping = load_action_tier_by_type()
    if key == ActionType.PROSPECTING.value:
        return 3
    if key not in mapping:
        raise ValueError(f"no action.tier_by_type mapping for action type {key!r}")
    tier = int(mapping[key])
    if tier not in VALID_TIERS:
        raise ValueError(
            f"invalid action tier {tier} for type {key!r}; expected 1, 2, or 3"
        )
    return tier  # type: ignore[return-value]


def assign_action_tier(
    action: Action, *, tier_by_type: Mapping[str, int] | None = None
) -> Action:
    """Return a copy of ``action`` with ``tier`` derived from ``type``."""
    return action.model_copy(
        update={"tier": tier_for_action_type(action.type, tier_by_type=tier_by_type)}
    )
