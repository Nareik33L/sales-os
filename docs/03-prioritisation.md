# 03 — Prioritisation

Deterministic. No LLM anywhere in this path. Every number comes from `config/priority_weights.yaml`; the engine (`core/prioritisation/`) is pure functions over structured rows, which makes it trivially testable with fixtures.

## 1. Two scores, one list

```
deal score  (0–100)   = Σ weight_i × signal_i(deal)          + user adjustments
action score (0–100)  = 0.6 × inherited deal score + 0.4 × due-date signal + user adjustments
Today ordering        = ORDER BY tier ASC, pinned rank, action score DESC
```

Why two scores: value, close date, staleness and commitments are properties of a **deal**; the Today list shows **actions**. An action inherits its deal's score so that "send pricing to Acme" outranks "send pricing to a £5k deal", and adds its own due-date pressure.

Deals with a high score but no open action still appear on Today as a *deal card* ("Acme needs attention — no next step recorded"), so a deal cannot fall off the radar just because nobody wrote a task.

## 2. Deal signals

Each signal is 0–100. Weights (initial): value .30, close .30, stale .15, commitment .15, meeting .10.

### 2.1 Deal value

```
signal = min(100, 100 × log10(1 + value_gbp) / log10(1 + reference))     reference = £100k
```

Log scale so a £150k deal is "very high" (≈104 → 100) and a £10k deal is "meaningful" (≈80), rather than the linear 100 vs 7. Unknown value → `min_signal_for_known_value` is *not* applied; unknown gets 0 and a "no value recorded" bullet.

### 2.2 Close urgency

Piecewise linear over days to `close_date`:

| days | signal |
|---|---|
| passed | 100 (+ `DATA_HYGIENE` action "Update close date") |
| 0 | 100 |
| 3 | 95 |
| 7 | 80 |
| 14 | 60 |
| 30 | 35 |
| 60 | 15 |
| 90+ | 5 |

Unknown close date → 20 and a bullet.

### 2.3 Stale activity

**Definition of `last_activity_at`** (this is where most implementations go wrong):

Counts: HubSpot calls, meetings, notes, logged emails, *completed* tasks; local email evidence in either direction; processed transcripts; Calendly meetings whose `end_at` is in the past.
Does not count: sync runs, property edits without an engagement, the user viewing the deal, open tasks, future meetings.

`last_activity_at = max(source engagement timestamp, local evidence.occurred_at)`.

| days since activity | signal |
|---|---|
| 0–3 | 0 |
| 7 | 60 |
| 14+ | 100 |

Conflict rule: if `close_date` is more than 60 days out, cap the stale signal at 50. Unknown activity date → 70 (probably stale, but say so: "no activity recorded").

### 2.4 Outstanding commitment

Looks at `ACTIVE` `COMMITMENT` memories on the deal:

| situation | signal |
|---|---|
| I owe the customer, overdue | 100 |
| I owe the customer, due within 2 days | 85 |
| I owe the customer, no/later due date | 60 |
| Customer owes me, overdue | 40 (and a `COMMITMENT` follow-up action is created: "Chase X for Y") |
| nothing outstanding | 0 |

Take the max, not the sum; three overdue commitments are not three times as urgent as one, they are one very urgent deal with three bullets.

### 2.5 Meeting proximity

| situation | signal |
|---|---|
| meeting today | 100 |
| meeting tomorrow | 70 |
| meeting within 7 days | 40 |
| meeting held yesterday, no `MEETING_FOLLOWUP` action completed | 80 |
| none | 0 |

Meeting today also creates a `MEETING_PREP` action if none exists ("Prepare for Acme 10:30").

### 2.6 User adjustments (added after the weighted sum)

- `user_boost`: each ↑/↓ is ±8 points, cumulative, bounded ±24. Bounded so an override can never silently become the whole model — the model's job is to be legible, the user's job is to disagree with it.
- `is_strategic` company flag: +10, shown as a bullet ("Strategic account").
- `user_pinned_rank`: forces list position; score is still computed and shown so the user can see what the system thinks.

## 3. Action signals

`due_date` signal: overdue 90 + 2/day (cap 100); today 85; tomorrow 65; within 7 days 40; none 20.

Tier from type: `COMMITMENT`, `TRANSCRIPT_ACTION`, `EMAIL_FOLLOWUP`, `HUBSPOT_TASK`, `MEETING_PREP`, `MEETING_FOLLOWUP` → 1. `TODO_TASK`, `DATA_HYGIENE`, `REVIEW`, `MANUAL` → 2. `PROSPECTING` → 3.

Actions with no deal (general To-Do items) inherit a flat 30.

Prospecting items additionally use the sheet's own `Priority` column and `Due date` inside tier 3, so the sheet's ordering survives.

## 4. Attention status

`HIGH ≥ 70`, `MEDIUM ≥ 40`, else `LOW`. Closed deals are `NONE`. Displayed as 🔴 🟠 🔵.

## 5. Explanations ("Why")

Every component stores `{signal, weight, contribution, reason}` in `priority_breakdown_json`. The Why panel lists components with contribution ≥ 5 points, largest first, max 4 bullets, rendered from templates:

| component | template |
|---|---|
| deal_value | "£75k deal" |
| close_urgency | "Closing Friday" / "Closing in 4 days" / "Close date passed (12 Sep)" |
| stale_activity | "No activity for 9 days" |
| outstanding_commitment | "You owe: revised pricing (due yesterday)" / "Customer owes: internal approval" |
| meeting_proximity | "Meeting today 10:30" / "Met yesterday — no follow-up yet" |
| user_boost / is_strategic / pinned | "You marked this more important" / "Strategic account" / "Pinned by you" |

The bullets are the *only* explanation. AI is not consulted for "Why". If the numbers say something odd, the bullets will say something odd, and that is the signal to change a weight.

## 6. Recompute triggers

- After every refresh (all connectors).
- After any feedback event on an action or deal.
- After any memory changes status (a fulfilled commitment removes its bullet immediately).
- On Today page load if `priority_computed_at` is older than 15 minutes (cheap: ~30 deals).

## 7. Learning signals (V1 = record, do not act)

Every feedback event writes `user_feedback` with `system_priority` (the rank the system gave), `user_priority` (what the user did: pinned rank, or the rank at which it was completed), `manual_override`, and a `context_json` snapshot.

Patterns detectable later with plain SQL:

- Completed order vs system order (Spearman-ish agreement over the last N days).
- Boost-ups concentrated on `is_strategic` companies → "increase strategic weighting?"
- Snoozes concentrated on stale-but-far-close deals → "lower stale weight when close > 60 days?"
- Dismissals of `DATA_HYGIENE` actions → "stop generating close-date reminders?"

These appear as read-only insight cards on Settings once ≥ 30 events exist. Applying a suggestion edits `priority_weights.yaml` through the UI with an `audit_log` `CONFIG_CHANGE` row. **Nothing is ever changed automatically.**

## 8. Worked example

Acme, £75k GBP, closes in 4 days, last activity 9 days ago, open `USER_TO_CUSTOMER` commitment "revised pricing" due yesterday, no meeting.

| component | signal | weight | contribution |
|---|---|---|---|
| deal_value | 97.5 | .30 | 29.3 |
| close_urgency | 90 | .30 | 27.0 |
| stale_activity | 74 | .15 | 11.1 |
| outstanding_commitment | 100 | .15 | 15.0 |
| meeting_proximity | 0 | .10 | 0 |
| **deal score** | | | **82.4 → HIGH** |

Action "Send revised pricing" (due yesterday): `0.6 × 82.4 + 0.4 × 92 = 86.2`, tier 1.

Why:
- £75k deal
- Closing in 4 days
- You owe: revised pricing (due yesterday)
- No activity for 9 days

## 9. Test fixtures the engine must pass

`tests/prioritisation/` will hold JSON fixtures of (deal row, memories, meetings, config) → (expected score band, expected top bullets, expected tier ordering). Key cases: log scaling, close date passed, stale-but-far cap, commitment max-not-sum, prospecting never above tier 1 regardless of due date, boost bound, pinned rank override.
