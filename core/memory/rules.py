"""Deterministic no-AI memory extractor (docs/04 §10).

Confidence is capped at 0.60. Quotes are exact spans copied from the
evidence body — the extractor will miss things; it will not invent them.
"""

from __future__ import annotations

import re

from core.memory.candidates import MemoryCandidate
from core.memory.confidence import RULES_CONFIDENCE_CAP
from core.memory.dates import find_due_in_text
from core.models.schemas import (
    Evidence,
    EvidenceDirection,
    MemoryDirection,
    MemoryType,
)

# First-person commitment: I'll / I will / we'll / we will / I can / let me + verb.
_COMMITMENT = re.compile(
    r"\b((?:I(?:'ll| will| can)|[Ww]e(?:'ll| will)|[Ll]et me)\s+"
    r"[A-Za-z][\w']*(?:\s+\S+){0,18})",
    re.IGNORECASE,
)

# Request in the opposite direction.
_REQUEST = re.compile(
    r"\b((?:could you|can you|please send|we need)\s+"
    r"[A-Za-z][\w']*(?:\s+\S+){0,18})",
    re.IGNORECASE,
)

_STATE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("security review", "Security review"),
    ("infosec", "Infosec"),
    ("procurement", "Procurement"),
    ("redlines", "Redlines"),
    ("signature", "Signature"),
    ("approval", "Approval"),
    ("legal", "Legal"),
)

_OBJECTION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("not a priority", "Not a priority"),
    ("too expensive", "Too expensive"),
    ("competitor", "Competitor"),
    ("budget", "Budget"),
)

_INTERNAL = re.compile(
    r"\b(procurement|legal|internally|infosec|security review)\b",
    re.IGNORECASE,
)

_LEADING_VERB = re.compile(
    r"^(send|share|give|provide|forward|email|call|review|speak)\s+(the\s+)?",
    re.IGNORECASE,
)

_PREFIX = re.compile(
    r"^(I(?:'ll| will| can)|we(?:'ll| will)|let me|could you|can you|"
    r"please send|we need)\s+",
    re.IGNORECASE,
)


def _sentences(content: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", content.strip())
    return [p.strip() for p in parts if p.strip()]


def _cap(value: float) -> float:
    return min(max(value, 0.0), RULES_CONFIDENCE_CAP)


def _direction_for_speaker(
    evidence: Evidence, *, first_person: bool, is_request: bool, text: str
) -> MemoryDirection | None:
    ev = evidence.direction
    if ev is None:
        return None
    ev_val = ev.value if hasattr(ev, "value") else str(ev)
    if is_request:
        if ev_val == EvidenceDirection.OUTBOUND.value:
            return MemoryDirection.CUSTOMER_TO_USER
        if ev_val == EvidenceDirection.INBOUND.value:
            return MemoryDirection.USER_TO_CUSTOMER
        return None
    if not first_person:
        return None
    if ev_val == EvidenceDirection.OUTBOUND.value:
        return MemoryDirection.USER_TO_CUSTOMER
    if ev_val == EvidenceDirection.INBOUND.value:
        if _INTERNAL.search(text):
            return MemoryDirection.CUSTOMER_INTERNAL
        return MemoryDirection.CUSTOMER_TO_USER
    return None


def _subject_from_span(span: str, due_text: str | None) -> str:
    text = _PREFIX.sub("", span).strip()
    if due_text:
        text = re.sub(re.escape(due_text), "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .,;:\"'")
    text = _LEADING_VERB.sub("", text).strip(" .,;:")
    if not text:
        text = span.strip(" .,;:")
    subject = text[:1].upper() + text[1:] if text else span
    return subject[:80]


def _quote_in(content: str, span: str) -> str | None:
    """Return ``span`` only when it is an exact substring of ``content``."""
    cleaned = span.strip().rstrip(".,;:")
    if cleaned and cleaned in content:
        return cleaned
    if span in content:
        return span
    return None


def extract_rules(evidence: Evidence) -> list[MemoryCandidate]:
    """Propose candidate memories from ``evidence.content``. No AI."""
    content = evidence.content or ""
    if not content.strip():
        return []

    occurred = evidence.occurred_at
    items: list[MemoryCandidate] = []
    seen_quotes: set[str] = set()

    for sentence in _sentences(content):
        due_text, _due_date = find_due_in_text(sentence, occurred)

        commit = _COMMITMENT.search(sentence)
        request = _REQUEST.search(sentence)
        picked_commitment = False

        if commit:
            span = commit.group(1)
            quote = _quote_in(content, span) or _quote_in(content, sentence)
            if quote and quote not in seen_quotes:
                direction = _direction_for_speaker(
                    evidence, first_person=True, is_request=False, text=sentence
                )
                owner = "me" if direction == MemoryDirection.USER_TO_CUSTOMER else None
                items.append(
                    MemoryCandidate(
                        type=MemoryType.COMMITMENT,
                        subject=_subject_from_span(span, due_text),
                        content=quote.rstrip(".") + ".",
                        quote=quote,
                        extraction_confidence=_cap(RULES_CONFIDENCE_CAP),
                        direction=direction,
                        owner_label=owner,
                        due_text=due_text,
                        is_inference=False,
                    )
                )
                seen_quotes.add(quote)
                picked_commitment = True

        if request and not picked_commitment:
            span = request.group(1)
            quote = _quote_in(content, span) or _quote_in(content, sentence)
            if quote and quote not in seen_quotes:
                direction = _direction_for_speaker(
                    evidence, first_person=False, is_request=True, text=sentence
                )
                items.append(
                    MemoryCandidate(
                        type=MemoryType.COMMITMENT,
                        subject=_subject_from_span(span, due_text),
                        content=quote.rstrip(".") + ".",
                        quote=quote,
                        extraction_confidence=_cap(RULES_CONFIDENCE_CAP),
                        direction=direction,
                        due_text=due_text,
                        is_inference=False,
                    )
                )
                seen_quotes.add(quote)

        for keyword, subject in _STATE_KEYWORDS:
            if keyword not in sentence.lower():
                continue
            quote = _quote_in(content, sentence)
            if not quote or quote in seen_quotes:
                break
            items.append(
                MemoryCandidate(
                    type=MemoryType.DEAL_STATE,
                    subject=subject,
                    content=quote.rstrip(".") + ".",
                    quote=quote,
                    extraction_confidence=_cap(RULES_CONFIDENCE_CAP),
                    is_inference=True,
                )
            )
            seen_quotes.add(quote)
            break

        for keyword, subject in _OBJECTION_KEYWORDS:
            if keyword not in sentence.lower():
                continue
            quote = _quote_in(content, sentence)
            if not quote or quote in seen_quotes:
                break
            items.append(
                MemoryCandidate(
                    type=MemoryType.OBJECTION,
                    subject=subject,
                    content=quote.rstrip(".") + ".",
                    quote=quote,
                    extraction_confidence=_cap(0.4),
                    is_inference=True,
                )
            )
            seen_quotes.add(quote)
            break

        if len(items) >= 20:
            break

    for item in items:
        item.extraction_confidence = _cap(item.extraction_confidence)
    return items
