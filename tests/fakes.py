"""Test doubles for subsystems that are not built yet.

FakeProvider stands in for ``ai.providers`` until SOS-22. It returns canned
JSON per task purpose and does not call any network. Callers in later tickets
should use this fixture instead of a real provider.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Source snippet the *valid* quotes are copied from. Hallucinated variants
# deliberately use text that is not a substring of this.
SOURCE_TEXT = (
    "Thanks. I will send the revised pricing tomorrow. "
    "We are reviewing internally with procurement."
)

PURPOSES = (
    "extract_memory",
    "extract_actions",
    "summarize",
    "generate_deal_summary",
    "answer_question",
)

VARIANTS = (
    "valid",
    "schema-invalid",
    "hallucinated-quote",
    "uncited-summary-sentence",
)

_SCHEMA_ID_TO_PURPOSE = {
    "salesos/memory_candidate/v1": "extract_memory",
    "salesos/action_candidate/v1": "extract_actions",
    "salesos/deal_summary/v1": "generate_deal_summary",
}

_VALID_QUOTE = "I will send the revised pricing tomorrow."
_HALLUCINATED_QUOTE = "We will sign the seventy-five thousand contract this week."


def canned_payload(purpose: str, variant: str = "valid") -> dict[str, Any]:
    """Return a canned JSON object for ``purpose`` × ``variant``."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose!r}; expected one of {PURPOSES}")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    return _PAYLOADS[(purpose, variant)]


class FakeProvider:
    """Minimal ``complete_json`` stand-in matching docs/07-ai-boundaries.md.

    The five public AIProvider methods are not implemented here — SOS-22 owns
    the real base class. Tests pick a variant via the constructor, ``variant=``
    on ``complete_json`` / ``payload``, or ``with_variant``.
    """

    name = "fake"

    def __init__(self, variant: str = "valid") -> None:
        if variant not in VARIANTS:
            raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
        self.variant = variant

    def with_variant(self, variant: str) -> FakeProvider:
        return FakeProvider(variant=variant)

    def payload(self, purpose: str, variant: str | None = None) -> dict[str, Any]:
        return canned_payload(purpose, variant or self.variant)

    def complete_json(
        self,
        system: str = "",
        user: str = "",
        schema: Mapping[str, Any] | None = None,
        ctx: Any = None,
        *,
        purpose: str | None = None,
        variant: str | None = None,
    ) -> dict[str, Any]:
        resolved = purpose or _purpose_from(ctx, schema, system=system, user=user)
        return canned_payload(resolved, variant or self.variant)


def _purpose_from(
    ctx: Any,
    schema: Mapping[str, Any] | None,
    *,
    system: str,
    user: str,
) -> str:
    if ctx is not None:
        ctx_purpose = getattr(ctx, "purpose", None)
        if ctx_purpose:
            return ctx_purpose
        if isinstance(ctx, Mapping) and ctx.get("purpose"):
            return str(ctx["purpose"])
    if schema:
        schema_id = str(schema.get("$id", ""))
        for suffix, purpose in _SCHEMA_ID_TO_PURPOSE.items():
            if schema_id.endswith(suffix) or suffix in schema_id:
                return purpose
    blob = f"{system}\n{user}".lower()
    for purpose in PURPOSES:
        if purpose.replace("_", " ") in blob or purpose in blob:
            return purpose
    return "extract_memory"


def _memory_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": "COMMITMENT",
        "subject": "Revised pricing",
        "content": "The sender will send revised pricing tomorrow.",
        "direction": "USER_TO_CUSTOMER",
        "owner_label": "me",
        "due_text": "tomorrow",
        "quote": _VALID_QUOTE,
        "is_inference": False,
        "extraction_confidence": 0.85,
        "relation_to_existing": None,
        "contact_name": None,
    }
    item.update(overrides)
    return item


def _action_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": "Send revised pricing",
        "description": "Send the revised pricing that was promised.",
        "due_text": "tomorrow",
        "quote": _VALID_QUOTE,
        "linked_memory_subject": "Revised pricing",
        "extraction_confidence": 0.8,
    }
    item.update(overrides)
    return item


def _valid_summary_sentences() -> list[dict[str, Any]]:
    return [
        {
            "text": "The customer is reviewing pricing with procurement.",
            "cites": ["mem_acme_pricing", "ev_acme_email"],
        }
    ]


_PAYLOADS: dict[tuple[str, str], dict[str, Any]] = {
    ("extract_memory", "valid"): {"items": [_memory_item()]},
    ("extract_memory", "schema-invalid"): {
        "items": [
            {
                "type": "NOT_A_TYPE",
                "subject": "Revised pricing",
                "content": "missing quote and bad type",
                "extraction_confidence": 1.5,
                "invented_field": True,
            }
        ]
    },
    ("extract_memory", "hallucinated-quote"): {
        "items": [_memory_item(quote=_HALLUCINATED_QUOTE)]
    },
    ("extract_memory", "uncited-summary-sentence"): {"items": [_memory_item()]},
    ("extract_actions", "valid"): {"items": [_action_item()]},
    ("extract_actions", "schema-invalid"): {
        "items": [{"title": "Send revised pricing", "extraction_confidence": 0.8}]
    },
    ("extract_actions", "hallucinated-quote"): {
        "items": [_action_item(quote=_HALLUCINATED_QUOTE)]
    },
    ("extract_actions", "uncited-summary-sentence"): {"items": [_action_item()]},
    ("summarize", "valid"): {
        "summary": "The sender will send revised pricing tomorrow. Procurement is reviewing."
    },
    ("summarize", "schema-invalid"): {"summary": 12345},
    ("summarize", "hallucinated-quote"): {
        "summary": "They agreed to sign a seventy-five thousand contract this week."
    },
    ("summarize", "uncited-summary-sentence"): {
        "summary": "They are certain to close this quarter."
    },
    ("generate_deal_summary", "valid"): {"sentences": _valid_summary_sentences()},
    ("generate_deal_summary", "schema-invalid"): {
        "sentences": [{"text": "The customer is reviewing pricing."}]
    },
    ("generate_deal_summary", "hallucinated-quote"): {
        "sentences": [
            {
                "text": "They will sign a seventy-five thousand contract this week.",
                "cites": ["mem_acme_pricing"],
            }
        ]
    },
    ("generate_deal_summary", "uncited-summary-sentence"): {
        "sentences": [
            *_valid_summary_sentences(),
            {
                "text": "They are certain to close this quarter.",
                "cites": ["not-a-supplied-id"],
            },
        ]
    },
    ("answer_question", "valid"): {
        "answer": "You owe revised pricing tomorrow.",
        "cites": ["mem_acme_pricing"],
    },
    ("answer_question", "schema-invalid"): {"answer": None, "cites": "mem_acme_pricing"},
    ("answer_question", "hallucinated-quote"): {
        "answer": "They promised to sign this week.",
        "cites": ["mem_acme_pricing"],
    },
    ("answer_question", "uncited-summary-sentence"): {
        "answer": "They are certain to close this quarter.",
        "cites": [],
    },
}


def all_payloads() -> Iterable[tuple[str, str, dict[str, Any]]]:
    for purpose in PURPOSES:
        for variant in VARIANTS:
            yield purpose, variant, canned_payload(purpose, variant)
