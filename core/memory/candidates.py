"""Candidate memories and ingest result DTOs (not table rows).

Shape matches ``ai/prompts/schemas/memory_candidate.json`` so AI and the
rules extractor feed the same ``ingest_candidates`` path (docs/04 §2).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.models.schemas import (
    Action,
    Memory,
    MemoryDirection,
    MemoryEvidence,
    MemoryRelation,
    MemoryType,
    ReviewItem,
)


class RelationToExisting(BaseModel):
    relation: MemoryRelation
    existing_subject: str


class MemoryCandidate(BaseModel):
    type: MemoryType
    subject: str
    content: str
    quote: str = ""
    extraction_confidence: float
    direction: MemoryDirection | None = None
    owner_label: str | None = None
    due_text: str | None = None
    is_inference: bool = False
    relation_to_existing: RelationToExisting | None = None
    contact_name: str | None = None


class MemoryIngestConfig(BaseModel):
    """Optional knobs for ``ingest_candidates``.

    ``source_reliability`` overrides the doc 04 §6 table for this evidence
    (tests pin the corroboration arithmetic). ``created_by`` is stored on
    new memory rows (``rules`` / ``user`` / ``openai:…``).
    """

    created_by: str = "rules"
    timezone: str | None = None
    source_reliability: float | None = None


class IngestResult(BaseModel):
    memories: list[Memory] = Field(default_factory=list)
    created_ids: list[str] = Field(default_factory=list)
    updated_ids: list[str] = Field(default_factory=list)
    dropped: int = 0
    actions: list[Action] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    links: list[MemoryEvidence] = Field(default_factory=list)
