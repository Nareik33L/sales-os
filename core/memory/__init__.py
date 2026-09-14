"""Memory lifecycle rules (docs/04 §§2–7, §10).

Public API: ``ingest_candidates``, ``extract_rules``. Prioritisation is
SOS-09 — this package never scores deals.
"""

from core.memory.candidates import (
    IngestResult,
    MemoryCandidate,
    MemoryIngestConfig,
    RelationToExisting,
)
from core.memory.confidence import (
    BAND_HIGH,
    BAND_MEDIUM,
    INFERRED_NO_QUOTE_CAP,
    RULES_CONFIDENCE_CAP,
    combine_confidence,
    corroborate,
    source_reliability,
)
from core.memory.dates import resolve_due_date
from core.memory.ingest import ingest_candidates
from core.memory.keys import make_dedupe_key, normalise_subject, subject_similarity
from core.memory.quotes import TRANSCRIPT_FUZZY_MIN, verify_quote
from core.memory.rules import extract_rules

__all__ = [
    "BAND_HIGH",
    "BAND_MEDIUM",
    "INFERRED_NO_QUOTE_CAP",
    "RULES_CONFIDENCE_CAP",
    "TRANSCRIPT_FUZZY_MIN",
    "IngestResult",
    "MemoryCandidate",
    "MemoryIngestConfig",
    "RelationToExisting",
    "combine_confidence",
    "corroborate",
    "extract_rules",
    "ingest_candidates",
    "make_dedupe_key",
    "normalise_subject",
    "resolve_due_date",
    "source_reliability",
    "subject_similarity",
    "verify_quote",
]
