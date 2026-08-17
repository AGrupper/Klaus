# Klaus — Product Requirements (v7.x)

> The pre-v7 PRD is at `docs/archive/PRD-pre-v7.md`. It describes TickTick,
> Gmail, Telegram, Notion, WhatsApp attendance flows and chat-log ingestion —
> all retired. Read it for history, never for current behaviour.

## Vision

Klaus is a personal operating system for one person. It holds the authoritative
picture of Amit's life — calendar, tasks, habits, training, nutrition,
recovery, reviews, actions and portfolio — and puts a capable agent on top of
it that can reason across all of it at once and safely administer reversible
life logistics without being asked twice.

The bet of v7 is **subtraction**. Klaus stopped hosting its own reasoning and
became the thing a subscription-grade model reasons *with*. What remains is the
part a model cannot be: durable memory, authorization, deterministic rules, and
a clock.

## Shape

| Component | Role |
|---|---|
| **Claude Project** | The conversational surface and the reasoning. Four skills: live agent, morning review, nightly review, weekly review. |
| **Cloud Run backend** | Authoritative data, scoped MCP tools, OAuth, deterministic alerts, routine coordination, Web Push, Hub APIs. |
| **Web Hub** | The life dashboard. Read-and-write React PWA at the same origin, launching Claude rather than hosting chat. |

Detail in `docs/ARCHITECTURE.md`.

## What Klaus knows

| Domain | Source | Notes |
|---|---|---|
| Calendar | Google Calendar | Calendar-only OAuth scope. Klaus-owned blocks are marked and are the only ones it moves autonomously. |
| Tasks | Things 3 (Cloud) | Firestore mirror; Things is authoritative. |
| Training | Garmin, Hevy | Per-run detail and per-set strength. Reconciled into one status per session. |
| Nutrition | HealthKit via iOS Shortcut | Per-meal macros including fiber. |
| Recovery | Garmin | Sleep, HRV, resting HR, body battery. |
| Habits | Firestore | Streaks and adherence. Grouped into named routines; a routine's streak counts days on which every scheduled member was completed. |
| Long-term memory | Pinecone | `gemini-embedding-2`; the only generative-adjacent capability in production. |
| Portfolio | Firestore + Claude web research | Weekly ILS valuation with sourced quotes. |

## Requirements

**R1 — One authoritative state.** Every surface reads the same Klaus data.
Claude's own memory is supplemental and never overrides it.

**R2 — Reasoning is Claude's, rules are Klaus's.** The backend returns
normalized facts and makes deterministic decisions (buffer arithmetic, adherence
reconciliation, alert thresholds). Claude decides what matters and writes the
prose. No generative model runs in the backend.

**R3 — Ambient knowledge, not repeated instruction.** Facts about Amit live in
`docs/USER.md` and reach Claude every turn through `get_life_snapshot`. Nothing
that is true about him is written into an individual skill.

**R4 — Reversible by default, gated when not.** Klaus acts on reversible life
administration without asking and reports afterward. Payments, credential and
security changes, permanent bulk deletion, medical commitments and first-time
outreach require an explicit prepare-then-confirm handshake. Routines may
prepare such an action but can never approve one.

**R5 — Routines always produce something.** Morning, nightly and weekly reviews
publish even on a quiet day. If Claude misses the deadline, a deterministic
fallback is published instead, then silently enriched if Claude arrives late.
A routine never produces silence.

**R6 — Truthful degradation.** When a source is unreadable, Klaus reports the
data as incomplete rather than inferring a zero. An adherence figure computed
over a degraded window is wrong, not merely partial.

**R7 — Preservation.** Historical Firestore documents, vectors, logs and reviews
are never destroyed. `KLAUS_USER_ID` is the permanent namespace.

**R8 — Retired means gone, and provably so.** Removed runtimes keep their routes
as 410 tombstones asserted by tests, and their secrets are quarantined rather
than deleted until the observation window closes.

## Non-goals

- Multi-user support. Klaus is single-tenant by design.
- Hosting chat in the Hub. That was tried and retired; the Hub launches Claude.
- Running any generative model in the backend.
- Autonomous outbound messaging to third parties.
