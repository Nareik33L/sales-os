"""Confidence factors and corroboration (docs/04 §6).

``confidence = source_reliability × extraction_confidence × match_confidence``
Independent evidence corroborates with ``c = 1 − (1 − c₁)(1 − c₂)``.
"""

from __future__ import annotations

from core.models.schemas import Evidence, EvidenceType, MemoryBasis

# Display bands (docs/04 §6). Raw number is stored; UI maps these.
BAND_HIGH = 0.8
BAND_MEDIUM = 0.5

INFERRED_NO_QUOTE_CAP = 0.5
RULES_CONFIDENCE_CAP = 0.60


def _type_value(evidence: Evidence) -> str:
    t = evidence.type
    return t.value if hasattr(t, "value") else str(t)


def source_reliability(evidence: Evidence) -> float:
    """Doc 04 §6 table, keyed off evidence type / file suffix."""
    kind = _type_value(evidence)
    if kind in {
        EvidenceType.HUBSPOT_DEAL.value,
        EvidenceType.EXCEL_DEAL.value,
        EvidenceType.CALENDLY_MEETING.value,
        EvidenceType.PROSPECTING_ACTIVITY.value,
    }:
        return 1.0
    if kind == EvidenceType.USER_INPUT.value:
        return 1.0
    if kind == EvidenceType.ZOOM_TRANSCRIPT.value:
        return 0.85
    if kind == EvidenceType.HUBSPOT_ACTIVITY.value:
        return 0.8
    if kind == EvidenceType.EMAIL.value:
        path = (evidence.file_path or "").lower()
        if path.endswith(".pdf") or path.endswith(".txt"):
            return 0.8
        return 0.95
    return 0.8


def match_confidence(evidence: Evidence) -> float:
    """Doc 06 factor. Unset on an already-linked row is treated as 1.0."""
    if evidence.match_confidence is None:
        return 1.0
    return max(0.0, min(1.0, float(evidence.match_confidence)))


def combine_confidence(
    source_rel: float, extraction: float, match: float
) -> float:
    return max(0.0, min(1.0, source_rel * extraction * match))


def corroborate(c1: float, c2: float) -> float:
    """Independent-evidence combination: ``1 − (1 − c₁)(1 − c₂)``."""
    return 1.0 - (1.0 - c1) * (1.0 - c2)


def clamp_inferred_without_quote(confidence: float, basis: MemoryBasis) -> float:
    if basis == MemoryBasis.INFERRED:
        return min(confidence, INFERRED_NO_QUOTE_CAP)
    return confidence
