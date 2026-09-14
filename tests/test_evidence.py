"""SOS-03: evidence insert is idempotent; evidence_fts is searchable.

Fictional fixtures only (Acme Ltd, Beta Corp, acme-example.test). See
docs/02-data-model.md (evidence, evidence_fts) and docs/04-memory-and-evidence.md §1.
"""

from __future__ import annotations

from core.models import (
    Evidence,
    EvidenceType,
    hash_content,
    search_evidence,
    upsert_evidence,
)

NOW = "2026-09-14T08:00:00Z"
ACME_BODY = (
    "Ada Example at Acme Ltd: We received the pricing and are reviewing "
    "internally with procurement."
)
BETA_BODY = "Ben Tester at Beta Corp asked for a one-pager on Xodo Sign."


def _count_evidence(db) -> int:
    return db.execute("SELECT count(*) FROM evidence").fetchone()[0]


def test_upsert_by_source_id_is_idempotent(db):
    first = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.HUBSPOT_ACTIVITY,
            source="hubspot",
            source_id="eng-acme-1",
            occurred_at="2026-09-13T16:02:00Z",
            title="Acme note",
            content="Follow up with Ada Example about SSO.",
        ),
        now=NOW,
    )
    second = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.HUBSPOT_ACTIVITY,
            source="hubspot",
            source_id="eng-acme-1",
            occurred_at="2026-09-13T16:02:00Z",
            title="Acme note (updated)",
            content="Follow up with Ada Example about SSO.",
        ),
        now=NOW,
    )
    assert second.id == first.id
    assert second.title == "Acme note (updated)"
    assert _count_evidence(db) == 1
    assert (
        db.execute(
            "SELECT count(*) FROM evidence WHERE source = ? AND source_id = ?",
            ("hubspot", "eng-acme-1"),
        ).fetchone()[0]
        == 1
    )


def test_upsert_by_content_hash_is_idempotent_when_source_id_absent(db):
    first = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.EMAIL,
            source="email_files",
            source_id=None,
            occurred_at="2026-09-13T10:00:00Z",
            title="Re: pricing",
            content=ACME_BODY,
        ),
        now=NOW,
    )
    assert first.content_hash == hash_content(ACME_BODY)
    assert first.source_id is None

    second = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.EMAIL,
            source="email_files",
            occurred_at="2026-09-13T10:00:00Z",
            title="Re: pricing (dropped again)",
            content=ACME_BODY,
        ),
        now=NOW,
    )
    assert second.id == first.id
    # File-sourced hash hit is a no-op: existing title is kept.
    assert second.title == "Re: pricing"
    assert _count_evidence(db) == 1

    other = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.EMAIL,
            source="email_files",
            occurred_at="2026-09-13T11:00:00Z",
            title="Beta Corp intro",
            content=BETA_BODY,
        ),
        now=NOW,
    )
    assert other.id != first.id
    assert _count_evidence(db) == 2


def test_blank_source_id_uses_content_hash_dedupe(db):
    first = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.ZOOM_TRANSCRIPT,
            source="transcripts",
            source_id="   ",
            occurred_at="2026-09-13T14:00:00Z",
            title="Acme call",
            content=ACME_BODY,
        ),
        now=NOW,
    )
    second = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.ZOOM_TRANSCRIPT,
            source="transcripts",
            source_id="",
            occurred_at="2026-09-13T14:00:00Z",
            title="Acme call copy",
            content=ACME_BODY,
        ),
        now=NOW,
    )
    assert first.source_id is None
    assert second.id == first.id
    assert _count_evidence(db) == 1


def test_provided_content_hash_dedupes_without_recompute(db):
    digest = "b" * 64
    first = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.EMAIL,
            source="email_files",
            occurred_at=NOW,
            title="Acme .msg",
            content="extracted text that may differ from the raw file bytes",
            content_hash=digest,
        ),
        now=NOW,
    )
    second = upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.EMAIL,
            source="email_files",
            occurred_at=NOW,
            title="Acme .eml of the same file",
            content="different extracted text",
            content_hash=digest,
        ),
        now=NOW,
    )
    assert first.content_hash == digest
    assert second.id == first.id
    assert _count_evidence(db) == 1


def test_search_evidence_fts_hit_and_miss(db):
    upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.ZOOM_TRANSCRIPT,
            source="transcripts",
            source_id="acme-2026-09-13",
            occurred_at="2026-09-13T14:00:00Z",
            title="Acme call",
            content=ACME_BODY,
            summary="Acme reviewing pricing with procurement.",
        ),
        now=NOW,
    )
    upsert_evidence(
        db,
        Evidence(
            type=EvidenceType.EMAIL,
            source="email_files",
            source_id="<msg-beta-1>",
            occurred_at="2026-09-12T09:00:00Z",
            title="Beta Corp intro",
            content=BETA_BODY,
        ),
        now=NOW,
    )

    hits = search_evidence(db, "procurement")
    assert len(hits) == 1
    assert hits[0].title == "Acme call"
    assert "procurement" in (hits[0].content or "")

    # Title/summary are indexed too.
    title_hits = search_evidence(db, "Acme call")
    assert [row.id for row in title_hits] == [hits[0].id]

    miss = search_evidence(db, "quota-forecast")
    assert miss == []

    empty = search_evidence(db, "   ???")
    assert empty == []

    # Punctuation in the query must not break MATCH.
    sso_free = search_evidence(db, "procurement?")
    assert [row.title for row in sso_free] == ["Acme call"]
