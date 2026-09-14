"""Dedupe key: ``type | deal_id | normalise(subject)`` (docs/04 §3).

``normalise`` = lowercase, strip punctuation, strip stop words, stem-ish.
Matching uses rapidfuzz token-sort ratio on the normalised subject.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from core.models.schemas import MemoryType

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "to",
        "of",
        "for",
        "and",
        "or",
        "in",
        "on",
        "at",
        "is",
        "be",
        "as",
        "by",
        "with",
        "from",
        "it",
        "this",
        "that",
        "our",
        "we",
        "i",
        "my",
        "your",
        "their",
    }
)

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SUFFIXES = ("ing", "ed", "es", "s")

DEDUPE_THRESHOLD = 0.9
RELATION_THRESHOLD = 0.8


def _stem(token: str) -> str:
    if len(token) <= 4:
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def normalise_subject(subject: str) -> str:
    lowered = subject.lower()
    stripped = _PUNCT.sub(" ", lowered)
    tokens = [_stem(t) for t in stripped.split() if t and t not in STOP_WORDS]
    joined = " ".join(tokens).strip()
    return joined or re.sub(r"\s+", " ", stripped).strip()


def type_value(memory_type: MemoryType | str) -> str:
    return memory_type.value if isinstance(memory_type, MemoryType) else str(memory_type)


def make_dedupe_key(
    memory_type: MemoryType | str, deal_id: str | None, subject: str
) -> str:
    deal = deal_id or ""
    return f"{type_value(memory_type)}|{deal}|{normalise_subject(subject)}"


def subject_similarity(a: str, b: str) -> float:
    """0–1 token-sort ratio of normalised subjects."""
    left = normalise_subject(a)
    right = normalise_subject(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return fuzz.token_sort_ratio(left, right) / 100.0
