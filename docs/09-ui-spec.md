# 09 — UI Specification

Streamlit at `http://localhost:8501`. Four pages in the sidebar: **Today · Deals · Inbox · Settings**. Deal detail is reached from Today or Deals (query param `?deal=<id>`). One screen should replace the six-tool morning.

Design rules: no charts, no KPIs, no quota. Cards, bullets, buttons. Every high-priority item shows *why*. Every button that would touch an external system says "Propose…" and goes through approval.

## 1. Today

```
Good morning, Sam.                                   ↻ Refresh   Last refresh 08:42 ✓ (Excel ⚠, To-Do –)
7 things need your attention · 2 questions

🔴 DEALS 3 actions · £142k     🟠 FOLLOW-UPS 2     🔵 PROSPECTING 2     📅 MEETINGS today 2

── START HERE ───────────────────────────────────────────────────────────────
#1  Acme — £75k · Xodo Sign · Closing Fri                              HIGH 86
    Send revised pricing                                    due yesterday
    Why: £75k deal · Closing in 4 days · You owe: revised pricing · No activity 9d
    [Complete] [Snooze ▾] [↑] [↓] [Dismiss] [Open deal]

#2  Beta Corp — £42k · Xodo Sign · Closing next week                  HIGH 74
    Prepare for meeting 14:00
    Why: £42k deal · Meeting today · Closing in 8 days
    …

── UPCOMING MEETINGS ────────────────────────────────────────────────────────
10:30  Acme — Discovery follow-up (Calendly)              [Open deal]
14:00  Beta Corp — Pricing review                          [Open deal]

── QUESTIONS (2) ────────────────────────────────────────────────────────────
Transcript "Acme call 13 Sep" — which deal?   [Answer]
Email from j.smith@gammaltd.co.uk — new company?  [Answer]

── OTHER ACTIONS ────────────────────────────────────────────────────────────
tier 1 remaining … tier 2 … tier 3 (Prospecting: ABC — Step 3 (Email) · DEF — Step 1 (Call))

── RECENTLY CHANGED ─────────────────────────────────────────────────────────
Gamma: stage Proposal → Negotiation (HubSpot, 07:55)
Delta (Excel): close date 30 Sep → 15 Oct
```

Behaviour:
- Counts at the top are computed from open actions by tier; the £ total is the sum of `deal_value_gbp` for distinct deals in tier-1 actions with `attention_status = HIGH`.
- Ordering: `tier ASC, user_pinned_rank NULLS LAST, priority_score DESC`.
- Controls write `user_feedback` and, for Complete, prompt about fulfilling the linked commitment (doc 04 §7). Snooze options: tomorrow / 3 days / next week / pick date. Dismiss asks for an optional reason.
- ↑/↓ adjust `user_boost` ±8 (bounded) and recompute immediately, so the card visibly moves.
- High-priority deals with no open action appear as deal cards with a single button: **[Add next step]** (creates a `MANUAL` action) and **[Open deal]**.
- The first load of the day triggers a refresh if none has run (spinner with per-connector status lines).
- No capacity limit: if there are 14 things, 14 are shown; nothing is hidden behind "show more" in tier 1.

## 2. Deals

Table over both products (`deals` where `is_closed = 0` by default; toggle to include closed ≤ 90 days).

Columns: Attention · Company · Product · Value · Stage · Close · Last activity · Priority · Next action · Source.
Sort default: `priority_score DESC`. Filters: product, attention, "stale > 7d", "closing ≤ 14d", "not seen since last sync" (source dropped it).

Row click → Deal detail. Excel rows show a small "Excel" badge and, if the connector is unavailable, "data as of 14 Sep".

## 3. Deal detail

```
ACME                                                   ← Deals
£75,000 · Xodo Sign · Stage: Proposal · Close: Fri 19 Sep · Owner: Sam
Attention: HIGH 82  Why: £75k · closing in 4 days · you owe revised pricing · no activity 9d
[↑ more important] [↓ less important] [Pin to #1] [Mark strategic ☐]

Current situation                                     updated 08:43 · from 6 memories
Proposal is under internal review [m1]. Customer indicated procurement approval is next [m2].
You owe the customer revised pricing [m3]. No activity for 9 days.

You owe                       They owe you                 Waiting on internally
• Revised pricing — due Thu   • Requirements doc — Fri     • Procurement approval
  (email 12 Sep) [Done]         (call 13 Sep) [Chase]        (call 13 Sep)

Next actions
1. Send revised pricing            due yesterday   [Complete]
2. Follow up with procurement      Fri             [Complete]
3. Confirm decision date           —               [Complete]
[+ Add action]

Signals & risks           People                      Preferences
• Buying signal: "budget   • Jane Smith — champion     • Prefers email over calls
  approved" (call 13 Sep)  • Raj Patel — procurement
• Risk: security review
  not yet started (inferred)

Changed since yesterday
• Stage Proposal → Proposal (no change) · Email received 12 Sep · Transcript processed 13 Sep

Recent evidence
• 14 Sep  HubSpot — call logged by Sam                          [view]
• 13 Sep  Zoom — Acme pricing review (42 min)                  [view] → 4 memories
• 12 Sep  Email — Re: revised pricing (outbound)               [view] → 1 memory

Tell the brain something: [ pricing sent this morning                    ] [Add]
```

- Every memory chip opens a popover with quotes, evidence links, confidence band, basis (observed/inferred), and **[Confirm] [Reject] [Move to another deal]**.
- "Current situation" shows citation markers that open the same popovers. If AI is off, it is the templated version.
- Closed deals render read-only with the timeline of superseded `DEAL_STATE` memories.

## 4. Inbox

One page, four sections:

1. **Sources** — the health table from doc 05 §1, one row per connector with icon, message, last run, "view errors", and for file connectors a drop-folder path with **[Process inbox now]**.
2. **Questions** — the review queue (doc 06 §6), answerable inline.
3. **Pending approvals** — audit proposals with reason, evidence and **[Approve] [Reject]**. Empty state: "Nothing waiting for approval."
4. **Recently processed** — `processed_files` and unstructured `evidence` (last 14 days) with status, match, extraction provider, "sent to AI" badge, and **[Reprocess]** / **[Move to deal…]**.

Also a search box over `evidence_fts` ("what did we agree about SSO?") returning evidence rows with the deal and matching snippet.

## 5. Settings

- **Connectors**: for each, configured yes/no (never the secret), mode, enabled toggle, write flags (each labelled "requires approval per action"), test connection button.
- **Prioritisation**: form over `priority_weights.yaml` (weights must sum to 1.0; live preview of the top 5 with the new weights before saving). Save writes YAML + `audit_log CONFIG_CHANGE`.
- **Matching**: aliases table (company ↔ alias), delete/edit; freemail list.
- **Excel mapping**: sheet names and columns, with "detect headers from latest file".
- **AI**: provider, model, endpoint host, redaction toggle, today's `ai_calls` volume, task enable switches.
- **Insights** (late V1): read-only cards from `user_feedback` patterns with a "Apply suggestion" that just pre-fills the Prioritisation form.
- **Data**: DB path/size, export copy, "Re-run all extraction", identity (my email addresses, my speaker names, greeting name).

## 6. Components (`app/components/`)

`action_card`, `deal_card`, `why_bullets`, `memory_chip` (+ popover), `source_health_row`, `review_item_form`, `approval_card`, `evidence_viewer`, `feedback_buttons`. Each is a function of rows → Streamlit calls; no data access inside components.

## 7. Performance envelope

~30 deals, a few hundred actions, low thousands of evidence rows. Every page is a handful of indexed queries; no caching layer beyond `st.cache_data` for config YAML. Refresh runs synchronously with a progress list; the longest step is HubSpot engagements on the first run.
