"""Public API for deterministic prioritisation (docs/03). Never imports ``ai/``."""

from core.prioritisation.engine import (
    ComponentBreakdown,
    RankedAction,
    ScoreBreakdown,
    explain,
    rank_actions,
    score_action,
    score_deal,
)
from core.prioritisation.recompute import RecomputeResult, recompute_all

__all__ = [
    "ComponentBreakdown",
    "RankedAction",
    "RecomputeResult",
    "ScoreBreakdown",
    "explain",
    "rank_actions",
    "recompute_all",
    "score_action",
    "score_deal",
]
