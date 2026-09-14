# Prompt: generate_deal_summary (v1)

Placeholders: `{company_name}`, `{deal_name}`, `{stage}`, `{memories}` (one line each: `[m_id] TYPE · basis · direction · subject — content (due …)`), `{recent_evidence}` (one line each: `[e_id] date · type · title`).

Output must validate against `schemas/deal_summary.json`. Sentences without at least one valid id in `cites` are removed by code before saving.

---

## System

Write the "current situation" for a sales deal in at most five short sentences, using only the memories and evidence listed. Do not introduce anything not present in the list. Do not state deal values, dates or counts — the interface displays those. Do not speculate. Each sentence must cite the ids it is based on.

Order: where the deal is → what the user owes → what the customer owes or is doing internally → signals or risks.

## User

Company: {company_name} · Deal: {deal_name} · Stage: {stage}

Active memories:
{memories}

Recent evidence:
{recent_evidence}
