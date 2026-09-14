"""Quote verification before a candidate may become OBSERVED memory.

docs/04 §2 and ADR-009: exact substring, else fuzzy ``partial_ratio ≥ 92``
for transcripts. Unverified quoted items are dropped. Inferred items with
no quote are allowed separately (confidence capped at 0.5).
"""

from __future__ import annotations

from rapidfuzz import fuzz

from core.models.schemas import Evidence, EvidenceType

TRANSCRIPT_FUZZY_MIN = 92


def _type_value(evidence: Evidence) -> str:
    t = evidence.type
    return t.value if hasattr(t, "value") else str(t)


def is_transcript(evidence: Evidence) -> bool:
    return _type_value(evidence) == EvidenceType.ZOOM_TRANSCRIPT.value


def quote_verified(quote: str, content: str, *, fuzzy: bool) -> bool:
    """Return True if ``quote`` is grounded in ``content``."""
    if not quote or not content:
        return False
    if quote in content:
        return True
    stripped = quote.strip()
    if stripped and stripped in content:
        return True
    if fuzzy:
        return fuzz.partial_ratio(stripped, content) >= TRANSCRIPT_FUZZY_MIN
    return False


def verify_quote(quote: str, evidence: Evidence) -> bool:
    """Verify ``quote`` against ``evidence.content`` using the type's rule."""
    return quote_verified(
        quote,
        evidence.content or "",
        fuzzy=is_transcript(evidence),
    )
