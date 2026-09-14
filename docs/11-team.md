# 11 — Engineering Team (Grok agents in Cursor)

The build is executed by a small team of Cursor subagents, all pinned to Grok 4.6. Definitions are committed so they travel with the repo:

| Path | What |
|---|---|
| `.cursor/rules/salesos-team.mdc` | Team charter: model policy, autonomy contract, definition of done, invariants, merge policy. Always applied |
| `.cursor/agents/*.md` | One brief per agent (frontmatter pins `model: grok-4.6[effort=…]`) |
| `.cursor/skills/*/SKILL.md` | Reusable procedures the agents load on demand |
| `AGENTS.md` | Plain-markdown entry point for any agent, including Cloud Agents |
| `docs/backlog.md` | Ticket board maintained by the lead |
| `docs/manual-tests/phase-N.md` | The checklist you run at each phase gate |

## Roster

| Agent | Model | Owns | Called for |
|---|---|---|---|
| `salesos-lead` | grok-4.6 xhigh | `docs/backlog.md`, reviews, merges, phase gates | plan, review, status, what's next |
| `salesos-core-engineer` | grok-4.6 high | `database/`, `core/models`, `core/prioritisation`, `core/memory`, `core/matching`, `core/audit`, `core/brain` | schema, scoring, memory rules, matching, approval gate |
| `salesos-connector-engineer` | grok-4.6 high | `connectors/`, `core/ingestion` | HubSpot, Excel, Calendly, Sheets, email/transcript parsing, refresh, inbox |
| `salesos-intelligence-engineer` | grok-4.6 high | `ai/`, `core/summarisation`, extraction step | providers, validators, extraction, cited summaries, no-AI fallback |
| `salesos-ui-engineer` | grok-4.6 high | `app/` | Today, Deals, Deal detail, Inbox, Settings, components |
| `salesos-qa-release-engineer` | grok-4.6 high | `tests/`, CI, `CHANGELOG.md`, `VERSION`, `docs/manual-tests/` | verify tickets, cut phase releases, write manual tests |

## Skills

| Skill | Used by | Purpose |
|---|---|---|
| `salesos-ticket-workflow` | all engineers | pick up → branch → implement → verify → PR → done |
| `salesos-connector-build` | connector engineer | connector recipe, health, offline tests |
| `salesos-test-and-verify` | all, QA | fixtures, fictional data, fault injection, AppTest |
| `salesos-architecture-guardrails` | lead, QA | 14 invariants and how to check them |
| `salesos-release` | QA/release | clean install, migration safety, demo mode, tag, changelog |
| `salesos-manual-test-request` | QA/release, lead | the ≤ 15-minute checklist the user runs |

## Workflow

```
lead: backlog ticket ──► engineer: branch + tests + code ──► PR
                                                          │
                       QA: verify (+ tests) ──► lead: guardrails review ──► merge (per MERGE_POLICY)
                                                          │
             end of phase: QA release + docs/manual-tests/phase-N.md ──► YOU run it (10–15 min) ──► lead files fixes
```

## What you will be asked to do (and nothing else)

1. Add a credential in Cursor → Cloud Agents → Secrets when a connector needs one (the agent names the exact variable).
2. Run the manual test checklist at each phase gate and reply with ✓/✗ per step.
3. Decide the rare things only you can: enabling an external write capability, deleting data, approving an architecture deviation (arrives as an ADR in a PR), confirming the second product's name.

Everything else is decided by the agents and recorded in PR descriptions and `docs/decisions-log.md`.

## Merge policy

Default `MERGE_POLICY: lead-merges-after-green` in `.cursor/rules/salesos-team.mdc`: the lead merges PRs it has reviewed once tests are green and the PR stays within its ticket's area. PRs that change write flags, drop data, or edit `.cursor/` wait for you. Change the line to `user-merges` to click merge yourself.

## Starting the team

In Cursor (Cloud Agent or local Agent on this repo), send:

```
/salesos-lead Read docs/00-overview.md and docs/10-build-plan.md. Confirm docs/backlog.md
covers Phases 1–2, then dispatch the Phase 1 and vertical-slice tickets to the owning agents.
Run autonomously under .cursor/rules/salesos-team.mdc. Report back only at the Phase 2 gate
with the manual test checklist, or if you hit one of the five stop-and-ask cases.
```

For a single ticket: `/salesos-connector-engineer Take SOS-07 (HubSpot connector) from docs/backlog.md.`

## Notes

- `model: grok-4.6[effort=…]` follows Cursor's documented model-ID syntax. If the model picker shows a different Grok 4.6 ID for your plan, update the six agent files (one line each). Cursor silently falls back to the parent model if an ID is unavailable or blocked by a team admin — the team rule "Grok only" is the second line of defence, and an Enterprise model allowlist would be the hard one.
- Cloud Agents never prompt for approval; autonomy is governed entirely by the charter and briefs above.
