# 07 — AI Boundaries

AI is an optional extractor and explainer. It is never the prioritiser, never the matcher, never a writer to external systems, and the application must be fully usable with `AI_PROVIDER=none`.

## 1. Provider abstraction (`ai/provider.py`)

```python
class AIProvider(ABC):
    name: str

    # Called by the application
    def summarize(self, content: str, *, purpose_ctx: CallContext) -> str: ...
    def extract_actions(self, content: str, ctx: CallContext) -> list[ActionCandidate]: ...
    def extract_memory(self, content: str, ctx: CallContext) -> list[MemoryCandidate]: ...
    def generate_deal_summary(self, memories: list[Memory], evidence: list[Evidence], ctx: CallContext) -> DealSummary: ...
    def answer_question(self, question: str, facts: list[Fact], ctx: CallContext) -> str: ...

    # Implemented by each provider — the only thing that differs between them
    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict, ctx: CallContext) -> dict: ...
```

The five public methods are implemented once in the base class: build prompt from `ai/prompts/*.md`, call `complete_json`, validate against `ai/prompts/schemas/*.json`, run the post-validators (§3), write `ai_calls`. Providers only implement `complete_json`.

Providers in V1:

| provider | file | notes |
|---|---|---|
| `NullProvider` | `ai/providers/null_provider.py` | returns empty results; the rules extractor and templated summaries take over. Default |
| `OpenAIProvider` | `ai/providers/openai_provider.py` | `response_format=json_schema`, temperature 0 |
| `LocalProvider` | `ai/providers/local_provider.py` | any OpenAI-compatible endpoint (`OPENAI_BASE_URL`), e.g. Ollama. Same code path with schema enforcement done client-side if the server lacks it |
| other approved | drop-in subclass | corporate-approved gateway; same interface |

Selection: `AI_PROVIDER` env → factory. The application code holds a single `provider` object and never checks its type.

## 2. Task contracts

| task | input | output schema | used by |
|---|---|---|---|
| `extract_memory` | one evidence's `content` + who "I" am + occurred_at + known contacts for the deal | `memory_candidate[]` (type, subject, content, direction, owner_label, due_text, quote, extraction_confidence, relation_to_existing) | ingestion |
| `extract_actions` | same | `action_candidate[]` (title, due_text, quote, linked_memory_subject) | ingestion |
| `summarize` | one evidence's `content` | `{summary: str ≤ 3 sentences}` | evidence list |
| `generate_deal_summary` | ACTIVE memories + last N evidence titles/dates for one deal (no raw bodies) | `{sentences: [{text, cites: [memory_id | evidence_id]}]}` | deal detail "Current situation" |
| `answer_question` | question + deterministic query result rows | `{answer: str, cites: [...]}` | Brain Q&A (late V1) |

Prompts live in `ai/prompts/` as Markdown with `{placeholders}`; schemas in `ai/prompts/schemas/`. Both are versioned in Git; the version string is stored in `ai_calls.purpose` suffix so extraction quality changes are traceable.

## 3. Hallucination controls (enforced in code)

1. **Quote verification** — every `memory_candidate`/`action_candidate` carries `quote`. Post-validator checks it against the source text: exact substring, else `rapidfuzz.fuzz.partial_ratio ≥ 92` (transcripts have punctuation drift). Fail → item dropped; `ai_calls.status = REJECTED_OUTPUT` if *all* items fail, otherwise `OK` with `output_chars` and a `rejected_items` count in `error`.
2. **Schema validation** — `jsonschema` on every response; enums restricted to the memory/action types in the database; unknown fields rejected. Malformed → one retry with the validation error appended, then give up and fall back to rules for that evidence.
3. **Closed-world summaries** — `generate_deal_summary` receives only memory rows and evidence titles; the prompt forbids new facts; each sentence must cite ≥1 id from the input; uncited sentences are removed before saving. Max 5 sentences. If nothing survives, the templated summary is used.
4. **No numbers from AI** — deal values, dates and counts in summaries are rendered by the template layer from structured data, never taken from AI text. The AI writes "the customer is reviewing pricing"; the UI adds "£75k · closes Fri".
5. **Confidence is not self-reported alone** — `extraction_confidence` from the model is one factor; source reliability and match confidence multiply it (doc 04 §6). An AI cannot make a badly matched transcript produce a high-confidence memory.
6. **Deterministic direction override** — evidence `direction` + first-person detection can overrule the model's `direction` (doc 04 §2).

## 4. Deal summary generation

```
if provider is Null or task disabled:
    summary = template(memories)      # "You owe: X (due Fri). They owe: Y. State: Procurement. Risk: Z."
else:
    summary = provider.generate_deal_summary(active_memories, recent_evidence_meta)
    summary = drop_uncited_sentences(summary)
    if empty: summary = template(memories)
deals.summary = summary; summary_stale = 0
```

Regenerated lazily on deal-detail view when `summary_stale = 1`, and in the morning refresh for deals with `attention_status = HIGH`. Concise by construction (≤ 5 sentences).

## 5. Privacy and transparency

- `ai_calls` logs every call: provider, model, purpose, evidence/deal, chars in/out, redaction flag, latency, status.
- Prompts never include `deal_value`, phone numbers, or attachments. Email addresses are optionally replaced with `<email:1>` tokens (`AI_REDACT_EMAIL_ADDRESSES`) and restored in output by the post-validator.
- Settings shows: current provider, model, endpoint host, "today: N calls · M characters sent", and a per-evidence "sent to AI: yes/no" badge on Inbox.
- Local provider mode keeps all data on the machine; the banner says so.
- Switching provider requires no data migration; existing memories keep `created_by`.

## 6. Cost and volume

Roughly: 30 deals × a handful of emails/transcripts per week → tens of extraction calls a day, a few thousand tokens each. Summaries are regenerated only when stale. No embeddings, no background loops. A daily cap (`AI_MAX_INPUT_CHARS` per call; optional daily call limit in `ai.yaml`) prevents runaway costs if a large PDF is dropped.

## 7. What happens when AI is unavailable

| situation | behaviour |
|---|---|
| `AI_PROVIDER=none` | rules extractor (doc 04 §10), templated summaries, Q&A returns structured lists |
| provider error/timeout | same as above for that evidence; `extraction_provider = rules`, `ai_calls.status = ERROR`; Inbox shows "Reprocess with AI" |
| output rejected | fall back to rules for that evidence |
| provider changed later | "Reprocess pending/rules-extracted evidence" button re-runs extraction; existing memories are deduped, not duplicated |

Core loop — sync, match, prioritise, Today page, approvals — has no AI dependency at all.
