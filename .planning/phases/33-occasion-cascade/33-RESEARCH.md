# Phase 33: Occasion Cascade - Research

**Researched:** 2026-07-29
**Domain:** Internal refactor — generalizing Klaus's 3-layer autonomous-tick cascade
(`core/autonomous.py`) to also drive three scheduled/triggered "occasions" (nightly
review, morning briefing, Sunday weekly review), replacing their always-fire
template composers.
**Confidence:** HIGH (this is a from-the-codebase refactor; every claim below is
grounded in files actually read this session, not external docs)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

> **Three of these override text locked in REQUIREMENTS.md / ROADMAP.md.** They are
> deliberate user decisions taken during this discussion, not drift. They are marked
> **[OVERRIDE]** and must be treated as authoritative over the superseded wording.

#### Skip appetite — when silence is the right answer (OCC-01/02/03)

- **D-01: High prior toward speaking; skip is the exception.** All three occasions
  default to speaking. Judgment shapes *what* is said far more often than *whether*
  anything is said. Rationale: lowest-risk posture during the flag rollout, and an
  occasion that routinely goes quiet stops being an occasion.
- **D-02: Four legitimate skip causes**, and only these:
  1. **A standing directive says so** — Phase 31 Step-0 veto, wins above all logic.
  2. **Already covered it recently** — the tick or an earlier occasion said the
     substantive thing; repeating it as a scheduled block is noise.
  3. **Genuinely nothing happened** — empty day, empty tomorrow, no signal.
  4. **Reaction history says back off** — Amit has been consistently ignoring or
     pushing back on this occasion (from the Phase 31 reflection reaction-pairing loop).
- **D-03: The weekly review never self-skips.** Its triage judgment governs **shape
  and emphasis** — what this week is *about*, which topics lead, whether it's a
  scorecard week or a "you've been sick, here's the reset" week — never whether it
  fires. A standing directive can still veto it (Phase 31 D-21/D-22 invariant intact).
  Rationale: a missing Sunday leaves a hole in the training record; a fixed cadence
  with judged content is the real win over the template.
- **D-04: The 01:00 nightly backstop gets fresh judgment.** It runs the full cascade
  like any occasion, but `skipped_by_judgment` is **terminal** — the backstop never
  re-litigates a night Klaus already decided to stay quiet on. It only judges nights
  where nothing ran at all. No raised bar for the late hour: Amit is asleep and reads
  it in the morning regardless, so the hour is irrelevant to the decision.

#### Perception vs. speech — what gets written on a skip (OCC-01/02)

- **D-05: The snapshot is always written; the send is separate.** Layer 0 writes the
  morning `structured` snapshot on **every** occasion run, sent or skipped, so the
  Hub's `/api/today` always has its day summary. *This inverts the plan's
  "`structured` snapshot + `daily_note` written only on actual send".* Rationale:
  "Klaus perceived the day" and "Klaus decided to speak" are different facts and the
  Hub depends on the first, not the second.
- **D-06: `daily_note` on a skip comes from the Layer-1 triage draft.** Layer 1
  already produces a free `draft` even when it votes not to act — use its one-liner
  as `daily_note`. Costs nothing, is Klaus's own voice, and is precisely the thing he
  judged wasn't worth interrupting Amit over. (`daily_note_date` guard unchanged.)
- **D-07: The nightly journal is always written.** `_ensure_reflection` (journal entry
  + self_state update) runs on every nightly occasion regardless of send. Klaus's
  continuity, self-state, and the reaction-pairing learning loop are internal
  machinery — choosing not to interrupt must not give him amnesia about that day.
  Same principle as D-05.

#### Morning wake-up: push trigger replaces the Garmin anchor **[OVERRIDE]**

> **Supersedes OCC-02's "Garmin wake-up anchor and 10:15 cutoff kept"** and the
> ROADMAP SC-2 wording "behind its existing Garmin wake-up anchor and 10:15 cutoff".
> Also **supersedes OCC-06's "no Cloud Scheduler changes"** for exactly one job.

- **D-08: The morning briefing becomes push-triggered, mirroring the nightly.**
  New `POST /trigger/morning`, hit by an iOS Shortcuts automation when **Sleep Focus
  turns off** (alarm fires, or Amit disables it manually). This is the exact mirror of
  the existing Sleep-Focus-*on* → `POST /trigger/nightly` automation. Rationale: it is
  the true wake signal — push, not poll — which removes the detection-latency and
  early-wake gaps that Garmin polling has, at zero recurring cost.
- **D-09: No Garmin gate, no cutoff, no time floor, no backstop.**
  - The Garmin sync is **no longer a gate** — sleep data is briefing *content*, not a
    trigger.
  - The 10:15 cutoff is **gone**, along with the `pending → sync_detected → sent`
    polling state machine and its retry counter.
  - **No time floor**: if Sleep Focus is off at 03:40, Klaus trusts the signal.
  - **No backstop**: if the automation doesn't fire (phone off, travel, forgot), there
    is no briefing that day. Amit's call: Sleep Focus is in the routine ~99% of days,
    and a missed trigger plausibly means a morning that didn't need a briefing.
- **D-10: `morning-briefing-tick` (`*/10 6-10`) is retired.** This is the OCC-06
  scheduler exception. See D-24 for the safe sequencing.
- **D-11: Fire immediately on trigger.** No delay, no wait-for-Garmin. If Garmin sleep
  data hasn't synced yet, **compose without it and name the gap** ("no sleep data yet")
  rather than fabricating or silently omitting — consistent with the existing Tier A/B
  no-fabrication contract.
- **D-12: Dedup via the daily state doc**, exactly as `/trigger/nightly` + `was_sent`
  already work. Once `sent` or `skipped_by_judgment`, later triggers (snooze, second
  alarm, focus toggled off/on/off) no-op. One proven pattern in both directions.
- **D-13: Own bearer token — `MORNING_TRIGGER_TOKEN`.** Follows the least-privilege
  rationale already documented in `_verify_trigger_request` (a leaked credential must
  not unlock every proactive surface). New Secret Manager entry + `deploy.yml` env.
- **D-14: A manual "brief me" in chat runs the occasion and ignores dedup**, marking
  state `manual` (the existing code path already does this).
- **D-15: If last night's nightly never ran, the morning widens its window.** Reads
  yesterday + today so a night without a wind-down doesn't silently drop out of Klaus's
  narrative. Both surfaces are push-triggered and both can miss; the pair must not lose
  a day.

#### Occasion ↔ tick collision (OCC-04)

- **D-16: Occasions fold around recent outreach — they don't repeat and don't
  wholesale skip.** If the tick already said the substantive thing, the occasion
  composes *around* it: covers what's left, references rather than restates. This is
  skip-cause #2 applied at content level instead of all-or-nothing.
- **D-17: Fold requires the actual sent text.** The Layer-2 compose prompt carries the
  **full message text** of today's Klaus-initiated outreach, not just topic keys —
  topic keys can prevent repetition but cannot enable natural back-reference ("as I
  flagged earlier, tomorrow's tight"). Layer 1 keeps topic keys + reasons only: it is
  on the Groq per-request budget and must not grow (Phase 32 guard test).
- **D-18: The inverse direction needs no new machinery.** Occasion topic keys
  (`nightly:<date>` / `morning:<date>` / `weekly:<date>`) land in the **same**
  OutreachLog the tick already de-dupes against — **one shared namespace, occasions
  and ticks as peers**, no precedence rules. Existing per-day topic dedup handles it.
- **D-19: On a same-minute race, the occasion wins and the tick yields.** Needs a
  lightweight in-flight marker. The occasion is the more substantial message and
  already covers what the tick would have said.
- **D-20: Sunday morning defers training to the weekly.** When a weekly review is
  scheduled for later the same day, the morning occasion stays light on training —
  orientation only — leaving the scorecard/projection to 10:00. Two messages, no overlap.

#### Agentic Layer 2 — powers and limits (OCC-05)

- **D-21: No product-level tool budget.** Amit explicitly rejected a fixed budget:
  Klaus should "be able to think and look through stuff… be smart and sophisticated
  about it." The **existing `MAX_TOOL_ITERATIONS = 12`** in `core/main.py:50` (the same
  `_run_smart_loop` Layer 2 already uses) remains the sole runaway guard. Do **not**
  add a tighter occasion-specific cap. This satisfies OCC-05's "bounded" wording —
  bounded by the safety net, not by a product constraint.
- **D-22: On iteration exhaustion, force a final answer.** Strip the tools and take one
  more turn to write the message from what was gathered. Only if *that* fails does the
  existing D-19 draft fallback apply. Never truncate mid-thought; never silently
  downgrade to the free draft just because Klaus was thorough.
- **D-23: Full chat toolset, writes ungated, disclosed after. [OVERRIDE]**
  *Supersedes OCC-05's "directive-gated proactive calendar writes".* Layer 2 gets the
  same tools as a chat turn and may **write without prior consent** — including
  destructive actions (move, delete) — provided it **declares what it did**. Two
  invariants survive unchanged:
  - **Idempotency check is mandatory** before any proactive calendar create — check for
    an existing planned row / Training-calendar event for that date+slot first (review
    amendment B2: compose succeeds → send fails → D-10 logs nothing → next occasion
    re-composes → duplicate event). This is correctness, not permission.
  - **Standing directives still veto** ("don't touch my calendar") — Phase 31 invariant.
- **D-24: Disclosure is an explicit action line**, not woven prose — e.g.
  `Created: Upper Body, tomorrow 18:00`. Actions must always be scannable and never
  buried. (Note: this is the one place the phase mandates structure; everything else in
  the occasion prompts stays unmandated.)
- **D-25: Actions are recorded independently of sends.** A write gets its own audit
  record the moment it happens, decoupled from D-10's send-gated OutreachLog. The next
  occasion sees "I already did this but never told him" and discloses it then. Nothing
  Klaus does to Amit's calendar may stay invisible. Records land in the **same store
  `get_recent_decisions` reads** (D-26) so "what did you do?" and "why were you quiet?"
  are one tool, one place.

#### Explaining himself (OCC-07)

- **D-26: `get_recent_decisions(days=2)` returns four things** — verdict + triage
  reasoning per run; what was sent and when; **actions taken** (D-25); and the skip
  cause categorized (which of D-02's four fired). Default 2 days, callable further for
  pattern questions.
- **D-27: Skips never surface unasked.** Silence stays silent — Klaus never opens with
  "by the way, I decided not to message you last night", which would defeat the point
  of skipping. The tool is there when Amit is curious. (Undisclosed *actions* are the
  exception — D-25 forces those out at the next opportunity.)
- **D-28: Rollout is watched by asking Klaus + a heartbeat summary.**
  `get_recent_decisions` is the live debugging surface (its original rationale in the
  review amendment). The hourly heartbeat additionally flags four anomaly classes:
  1. **Any occasion that errored** — Layer-1/2 exception, plain-text fallback fired,
     send failed. This is the failure-skip class and must never pass silently (SC-1).
  2. **A skip streak** — N consecutive judgment-skips on one occasion (could be a quiet
     week, could be a prompt regression making Klaus mute).
  3. **The weekly not firing** — by D-03 it never self-skips, so a missing Sunday is
     either a directive veto or a fault.
  4. **Undisclosed actions pending** — an orphaned D-25 write.
- **D-29: Go/no-go for Phase 35 deletion is Amit's judgment from the daily asks.** The
  messages are either better than the templates or they aren't; no metric answers that.
  No checklist gate.

#### Rollout & dispatch

- **D-30: Morning ships cascade-only; nightly and weekly get the A/B. [OVERRIDE]**
  *Partially supersedes OCC-06's "both live for a 3-4 day observation window".* Retiring
  `morning-briefing-tick` leaves no legacy morning path to compare against, so the
  `OCCASION_CASCADE` flag A/Bs nightly + weekly only. Accepted: morning is the surface
  Amit sees first every day, so misbehavior surfaces within one day.
- **D-31: `/trigger/morning` ships dark.** The route deploys and does nothing until
  Amit's iOS Shortcut starts hitting it; `morning-briefing-tick` stays running until the
  trigger is confirmed firing, and is retired only then. No silent-morning gap.
  **Operator step for Amit:** build the Sleep-Focus-*off* Shortcut (mirror of the
  existing wind-down one) — this is a hard prerequisite, same shape as the nightly one.
- **D-32: Every occasion compose runs inside a tracked Cloud Tasks request.**
  `/trigger/nightly` currently composes in a Starlette `BackgroundTask` — which
  CLAUDE.md's own invariant forbids (Cloud Run throttles CPU once no request is in
  flight; this caused the 2026-06-12 18-minute reply). It survives today only because
  compose is one LLM call; under D-21's agentic loop it very likely will not.
  `/trigger/morning` would inherit the same shape. **Fix both trigger routes** to ACK
  immediately (202) and enqueue via `core/task_dispatch.py` to an internal endpoint, the
  same full-CPU pattern Telegram and Hub already use. The `/cron/*` occasions (weekly
  Sunday, nightly 01:00 backstop) move to the same dispatch path **for consistency and
  request-timeout headroom** — honest caveat: they are *not* broken today, since holding
  the request open keeps CPU allocated. The trigger routes are the actual defect.

#### Prompts — what survives the template deletion

- **D-33: Knowledge lives in the data, not the prompt.** The legacy composers' real
  substance (fuel plan, recovery framing, "Week N of 16", projection, macro
  accountability) is already available as gathered Layer-0 signals and callable tools.
  If Layer 0 hands Klaus the numbers and Layer 2 can call the tools, he reaches for them
  when they matter — no prompt needs to enumerate them. This is the milestone's
  values-not-scripts thesis applied literally.
- **D-34: Regression is caught by Amit noticing and saying so.** If the morning stops
  mentioning fuel, he says so — and under Phase 31 that becomes a standing directive
  that fixes it permanently. The correction loop already exists and beats a checklist.
  No old-vs-new output diffing during the window.
- **D-35: Occasion prompts carry identity + standing question only.** A few lines each:
  what this occasion is, when it fires, and the one question it exists to answer (e.g.
  "you're winding down — what's worth knowing before tomorrow?"). Tone, values, tools
  and data all come from the shared layers. No mandated sections, no scheduling scripts
  (OCC-04 confirmed).
- **D-36: Cross-cutting behaviors go in the shared cascade prompts**, not per-occasion
  and not in `smart_agent.md`: the four skip causes (D-02) → `prompts/autonomous_triage.md`;
  write-and-disclose (D-23/D-24) and folding (D-16/D-17) → `prompts/autonomous.md`.
  Occasions inherit them for free and the `*/20` tick gets the same improvements — one
  place to change behavior. Keeps the Phase-30.5 always-on prompt slimming intact.

### Claude's Discretion

- Exact shape of the action-audit record (D-25) and how it merges into
  `get_recent_decisions`' return payload (D-26) — new store vs. an extension of
  TickLog/OutreachLog.
- The in-flight marker mechanism for D-19 (occasion wins the race).
- Concrete wording of all three occasion prompts (D-35) and the shared-prompt additions
  (D-36).
- How "already covered it recently" (D-02 #2) and "reaction history says back off"
  (D-02 #4) are surfaced to Layer 1 within the Groq per-request budget — the Phase 32
  token-budget guard test is the hard ceiling and must still pass.
- Skip-streak threshold N for the heartbeat anomaly (D-28 #2).
- Whether the morning state machine's `sync_detected`/`retry_count` fields are deleted
  or left dormant when the polling path is retired (D-09/D-10).
- The internal endpoint naming/shape for the Cloud Tasks occasion dispatch (D-32).
- How the widened morning window (D-15) detects "last night's nightly never ran".

### Deferred Ideas (OUT OF SCOPE)

- **Deleting the legacy composers, `prompts/nightly_review.md` /
  `morning_briefing.md` / `weekly_training_review.md`, and the `OCCASION_CASCADE`
  flag** — Phase 35, after the observation window (OCC-06). Note D-30: morning's legacy
  composer becomes dead on arrival since its trigger is retired in this phase.
- **Write-backs from calendar actions and chat reports to `TrainingLogStore`** — Phase 34.
  D-23's proactive calendar writes will *benefit* from Phase 34's planned rows as the
  natural idempotency key, but this phase must implement its own check (D-23) without
  depending on Phase 34.
- **New eval fixtures for occasion judgment** (nightly judgment-skip, nightly fold,
  vacation-directive suppression) — Phase 35 / HARD-01.
- **Moving wake-up detection onto the `*/20` tick as a Layer-0 signal** — superseded by
  the push trigger (D-08) and no longer needed. Recorded so it is not re-proposed.
- **A Hub surface for browsing Klaus's decisions/actions** — `get_recent_decisions` is
  chat-only for now. Not in scope.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OCC-01 | Nightly runs as `occasion="nightly"` through the cascade; `skipped_by_judgment` distinguishable from infra-failure | §Architecture Patterns Pattern 1/2, §Common Pitfalls 3/8, §Validation Architecture OCC-01 |
| OCC-02 | Morning runs as `occasion="morning"` through the cascade; push-triggered (D-08 OVERRIDE), no Garmin gate | §Architecture Patterns Pattern 3, §Code Examples "New /trigger/morning route", §Common Pitfalls 4 |
| OCC-03 | Weekly runs as `occasion="weekly_review"`, last legacy composer retired | §Architecture Patterns Pattern 1, §Common Pitfalls 9 |
| OCC-04 | Occasions bypass empty-gate + change-detection gate; shared OutreachLog namespace | §Architecture Patterns Pattern 1 ("Bypass points"), §Common Pitfalls 1/2 |
| OCC-05 | Agentic Layer 2, `MAX_TOOL_ITERATIONS=12` guard, idempotent calendar writes | §Architecture Patterns Pattern 4, §Common Pitfalls 5/6, §Don't Hand-Roll |
| OCC-06 | `OCCASION_CASCADE` flag, scheduler-change sequencing (D-10/D-24), dual-run observation window | §Architecture Patterns Pattern 5, §Common Pitfalls 7/10, §Risks |
| OCC-07 | `get_recent_decisions` tool | §Architecture Patterns Pattern 6, §Code Examples "Tool registration", §Don't Hand-Roll |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- All GCP/Pinecone resource names lowercase `klaus-` — uppercase silently 404s. Any new
  Firestore collection this phase introduces (an action-audit store, if built) must
  follow this.
- `load_dotenv` always `override=True` — not directly touched by this phase but any new
  local smoke-test CLI (mirroring `nightly_review._cli`) must follow it.
- Embeddings via Gemini AI Studio, never Vertex — not touched by this phase.
- **The brain never routes through worker first** — Layer 2's `_run_smart_loop` already
  respects this; the occasion cascade must not introduce a worker-first path.
- **Autonomous tick cost gating**: Layer 0 (free) → Layer 1 (Groq, free) → Layer 2 (paid)
  — occasions must preserve this ordering; D-04/OCC-04's "always a free triage judgment"
  is Layer 1, not Layer 2. Layer 2 (paid Sonnet-5) still only runs when Layer 1 says
  "speak" (or, per D-03, is unconditionally reached for the weekly's shape-not-whether
  judgment).
- `OutreachLogStore.append` is gated on `send_and_inject` success (D-10) — **this
  invariant is unchanged by this phase**; D-25's new action-audit record is explicitly
  a parallel, non-send-gated write and must not be confused with or merged into this rule.
- `_get_orchestrator()` is a process-wide singleton — occasion composes must keep
  reusing it (`core.autonomous._get_orchestrator()`), never construct a fresh
  `AgentOrchestrator()` per occasion run.
- **Agent turns must run inside a tracked Cloud Tasks request, never a Starlette
  `BackgroundTask`** — this is the literal subject of D-32 and the primary infra defect
  this phase must fix in `/trigger/nightly` (and, once added, `/trigger/morning`).
- Every LLM client carries an explicit timeout (`LLM_TIMEOUT_SECONDS`, default 120s) —
  already true of every LLMClient constructed in `core/tick_brain.py` and
  `core/main.py`; no new bypass path should be introduced.
- HealthKit/Lifesum meal timestamps are canonical slot times, not actual eating times —
  relevant if the occasion prompts reference `nutrition`/`meals_since_last_tick`
  (inherited context, not new to this phase).

## Summary

Phase 33 does not invent new infrastructure — it generalizes infrastructure that
already exists and is fully understood from this session's reading. The 3-layer
cascade (`gather_situation` → `TickBrain.think` triage → `_run_smart_loop` compose →
`send_and_inject` → `OutreachLogStore.append`) lives entirely in
`core/autonomous.py::run_autonomous_tick` (1929 lines, read in full this session).
The three legacy composers (`core/nightly_review.py`, `core/morning_briefing.py`,
`core/weekly_training_review.py`) each have their own specialized Layer-0 gather
(tomorrow-facing for nightly, sleep/calendar/nutrition for morning, Sun–Sat week
window for weekly) but currently bypass Layer 1 entirely and call a single-shot
`LLMClient.chat()` compose with a `{"skip": true, "reason": ...}` trailing-JSON veto
convention (three near-identical `_parse_*_skip` functions already exist, one per
composer, all parsing the same fenced-JSON-trailer shape). The core architectural
move this phase makes is: **keep each occasion's specialized Layer-0 gather, but
route its output through the SAME Layer-1 triage (`TickBrain.think` +
`autonomous_triage.md`) and Layer-2 compose (`_run_smart_loop` + `autonomous.md`)
the tick already uses**, rather than each composer's own single-shot LLM call. The
three `_parse_*_skip` trailing-JSON functions and the three independent LLMClient
compose blocks are the code that gets deleted/replaced by calls into a new shared
entry point in `core/autonomous.py`.

Two of the four CONTEXT.md `[OVERRIDE]` decisions materially change what the
ROADMAP/REQUIREMENTS text implied: the morning briefing drops its Garmin-polling
anchor entirely for a push-triggered `POST /trigger/morning` mirroring the existing
`/trigger/nightly` (D-08/D-09), and Layer 2 gets **ungated** write powers with
after-the-fact disclosure rather than directive-gated writes (D-23). Both are more
work than the superseded text, not less: D-08/09 requires deleting an entire
polling state machine (`core/morning_briefing.py::handle_tick`, lines 58-124) and
retiring a Cloud Scheduler job with careful sequencing (D-31: ship the new route
dark, wait for the Shortcut to be live, only then retire the old cron); D-23 raises
the bar on the idempotency check because writes now happen far more often
(ungated, not directive-gated) and every write needs an independent audit trail
(D-25) decoupled from the existing send-gated `OutreachLogStore.append` invariant.

The single highest-leverage technical risk found this session is the Groq
per-request token budget. `tests/test_token_budget.py` (read in full) proves the
*current* maximal triage prompt is **7,146 tokens against a 7,200-token design
target** (hard Groq ceiling 8,000) — a ~54-token margin. D-36 requires the four
occasion skip causes, the fold-in behavior, and the write-and-disclose contract to
live in the **same shared files** (`prompts/autonomous_triage.md`,
`prompts/autonomous.md`) the `*/20` tick already renders on every call — meaning
any token growth from this phase's prompt edits taxes every regular tick's Groq
call, not just the ~3 occasion calls/day. This is a self-enforcing risk (the guard
test fails loudly if crossed) but the margin is thin enough that it must be treated
as a hard design constraint, not an afterthought.

**Primary recommendation:** Generalize `run_autonomous_tick` to accept an
`occasion: str | None = None` parameter (and the pre-gathered occasion-specific
extra situation data as a `dict`, merged into the standard `gather_situation()`
output before Layer 1/2 run) rather than writing three parallel occasion-specific
triage/compose pipelines. Fix `/trigger/nightly`'s `BackgroundTask` defect and add
`/trigger/morning` on the same Cloud-Tasks-dispatch pattern already proven by
`core/task_dispatch.py::enqueue_hub_message`. Keep occasion-specific prompt guidance
minimal (a handful of lines per D-35) and put it in the **user message**, not the
system prompt, wherever token budget allows, so regular ticks are not taxed by
occasion-only guidance.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Occasion trigger receipt (`/trigger/nightly`, `/trigger/morning`, `/cron/*`) | API/Backend (FastAPI routes in `interfaces/web_server.py`) | — | Auth + immediate 202 ACK + Cloud Tasks enqueue; no business logic here (D-32) |
| Occasion-specific Layer-0 gather (tomorrow calendar/tasks/weather, sleep data, week window) | API/Backend (`core/nightly_review.py`, `core/morning_briefing.py`, `core/weekly_training_review.py`) | — | Each occasion's specialized data shape stays in its own module; unaffected by this phase |
| Shared triage judgment (Layer 1) | API/Backend (`core/tick_brain.py` via Groq) | — | Free-tier judgment; occasions and ticks share the same client/prompt |
| Shared compose (Layer 2, agentic) | API/Backend (`core/main.py::_run_smart_loop` via Sonnet-5) | — | Same tool-loop, same `MAX_TOOL_ITERATIONS=12` safety net |
| Message delivery (Telegram + Web Push) | API/Backend (`core/scheduled_message.py::send_and_inject`) | — | Unchanged by this phase |
| Send-gated repeat-suppression log | Database/Storage (`OutreachLogStore`, Firestore) | — | Occasions and ticks share one namespace (D-18) |
| Decision/action audit trail (`get_recent_decisions`) | Database/Storage (Firestore, new/extended store) + API/Backend (tool handler in `core/tools.py`) | — | Read path is brain-direct (chat tool call), write path is per-occasion-run |
| Occasion state/dedup (`was_sent`-equivalent) | Database/Storage (per-occasion date-keyed doc, e.g. `nightly_reviews/{date}`, `morning_briefings/{date}`) | — | Pre-existing pattern, no new tier |
| Push-trigger auth | API/Backend (`_verify_trigger_request`-style bearer check) | — | Shared-secret, not OIDC — matches the existing nightly pattern |
| `/api/today` Hub consumption of `daily_note`/`structured` | Frontend Server / Browser (Hub SPA) | API/Backend (`interfaces/web_server.py::/api/today`) | Contract shape unchanged (D-05/D-06 only change *when* fields are written) |

## Standard Stack

This phase installs **no new external packages**. It reuses the existing dual-model
stack (`gemini-3.5-flash`/`claude-sonnet-5` brain via `core/llm_client.py`,
`openai/gpt-oss-120b` tick-brain via `core/tick_brain.py`), the existing
`google-cloud-tasks` dependency already used by `core/task_dispatch.py`, and the
existing `tiktoken==0.13.0` pin already added in Phase 32 for the token-budget guard
test. `## Package Legitimacy Audit` is therefore **N/A for this phase** — no
`slopcheck`/registry verification is required because nothing new is installed.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Generalizing `run_autonomous_tick` with an `occasion` param | Three fully independent triage/compose pipelines, one per occasion | Independent pipelines would duplicate the Layer-1/Layer-2 call plumbing (system-prompt loading, `render_smart_system` replication, sentinel detection, D-19 draft fallback) three times — directly against D-36's "one place to change behavior" and the existing repeated-code smell already visible across `nightly_review.py`/`morning_briefing.py`/`weekly_training_review.py`'s three near-identical `_parse_*_skip` functions |
| Cloud Tasks dispatch for occasion composes (D-32) | Keep `BackgroundTasks` for `/trigger/nightly`/`/trigger/morning`, only fix `/cron/*` | Explicitly rejected by D-32 — the trigger routes are named as "the actual defect"; `BackgroundTasks` runs after the response with throttled CPU, the exact class of bug that caused the 2026-06-12 18-minute reply |
| A brand-new `ActionLogStore` collection for D-25 | Extend `OutreachLogStore` entries with an `is_action` flag | Explicitly rejected by the D-10 invariant comment in the existing code ("D-25's action record deliberately sits *outside* this rule — it is not an outreach record") — mixing send-gated and non-send-gated writes into one collection would blur the write-after-send discipline that protects against phantom "sent" records |

## Architectural Responsibility Map — Bypass Points (OCC-04 detail)

`gather_situation()` (`core/autonomous.py:881`) computes `gathered["empty"] =
_is_empty_signals(gathered)` at line 977, and `run_autonomous_tick` (line 1793-1801)
returns early with `decision["skipped"] = "empty"` when that flag is true — **before**
Layer 1 ever runs. Immediately after that, a second gate at lines 1814-1830 (the
"Layer 0.5 change-detection gate", `_compute_signal_signature` +
`TickSignatureStore`) skips Layer 1 again if the salient-signal hash matches the
last tick's. **Both gates must be bypassed when `occasion is not None`** — CONTEXT.md
states this explicitly and it is visible in the code: an occasion fires on a
schedule/push-trigger, not on signal novelty, so "nothing changed since last tick"
is meaningless for a once-a-night review.

## Architecture Patterns

### System Architecture Diagram

```
                     ┌─────────────────────────────────────────────┐
                     │              TRIGGER SOURCES                 │
                     │  Cloud Scheduler (*/20 tick, weekly Sun 10:00,│
                     │  nightly 01:00 backstop)                      │
                     │  iOS Shortcuts (Sleep-Focus on/off, D-08)     │
                     └───────────────┬───────────────────────────────┘
                                     │ POST /cron/* (OIDC) or
                                     │ POST /trigger/* (bearer, D-13)
                                     ▼
                     ┌─────────────────────────────────────────────┐
                     │  interfaces/web_server.py route handler       │
                     │  - auth check (_verify_cron_request /          │
                     │    _verify_trigger_request)                    │
                     │  - ACK 202 immediately (D-32)                  │
                     │  - core.task_dispatch.enqueue_*(...)           │
                     └───────────────┬───────────────────────────────┘
                                     │ Cloud Tasks (OIDC, full CPU)
                                     ▼
                     ┌─────────────────────────────────────────────┐
                     │  /internal/process-occasion (new, D-32)        │
                     │  dispatches to the occasion module:            │
                     │  nightly_review.run_nightly /                 │
                     │  morning_briefing.run_morning_briefing /       │
                     │  weekly_training_review.run_weekly_review      │
                     └───────────────┬───────────────────────────────┘
                                     ▼
     ┌───────────────────────────────────────────────────────────────────┐
     │ LAYER 0 — occasion-specific gather (existing, per-module, FREE)      │
     │  nightly: _gather_tomorrow (calendar/tasks/weather/recovery)         │
     │  morning: _gather_data (Garmin/nutrition/block/coaching topics)      │
     │  weekly:  _gather_week_data (7d training/biometrics/projections)     │
     │  ── merged with shared gather_situation() output where useful ──     │
     └───────────────────────────────┬───────────────────────────────────┘
                                     │ occasion="nightly"|"morning"|"weekly_review"
                                     ▼  (empty-gate + change-detection gate BYPASSED)
     ┌───────────────────────────────────────────────────────────────────┐
     │ LAYER 1 — shared triage (FREE, Groq)                                 │
     │  core/tick_brain.py::TickBrain.think(..., system_override=            │
     │    prompts/autonomous_triage.md)                                     │
     │  D-01: occasion default flips to SPEAK; D-02: 4 skip causes only      │
     │  D-03: weekly never self-skips (shape/emphasis only)                  │
     └───────────────────────────────┬───────────────────────────────────┘
                                     │ should_act? / draft / topic_key
                                     ▼
     ┌───────────────────────────────────────────────────────────────────┐
     │ LAYER 2 — shared agentic compose (PAID, Sonnet-5)                    │
     │  core/main.py::_run_smart_loop via prompts/autonomous.md              │
     │  MAX_TOOL_ITERATIONS=12 (D-21); on exhaustion, force final answer      │
     │  with tools stripped (D-22); full chat toolset, writes ungated with    │
     │  mandatory disclosure line (D-23/D-24); idempotency check before any   │
     │  calendar create (D-23)                                               │
     └───────────────────────────────┬───────────────────────────────────┘
                                     │
                    ┌────────────────┴─────────────────┐
                    │ should_act=False (skip)            │ should_act=True (send)
                    ▼                                    ▼
     ┌──────────────────────────────┐   ┌──────────────────────────────────┐
     │ skipped_by_judgment recorded  │   │ send_and_inject (Telegram + Push) │
     │ (D-01..D-04 taxonomy)         │   │ OutreachLogStore.append (D-10,    │
     │ daily_note = Layer-1 draft    │   │  ONLY after send success)         │
     │ (D-06); snapshot ALWAYS       │   │ structured snapshot written       │
     │ written (D-05)                │   │ (D-05, always, sent-or-skipped)   │
     └──────────────────────────────┘   └──────────────────────────────────┘
                    │                                    │
                    └────────────────┬───────────────────┘
                                     ▼
     ┌───────────────────────────────────────────────────────────────────┐
     │ Decision/action log write (get_recent_decisions read path)           │
     │  TickLogStore-style write, occasion-keyed; D-25 action records        │
     │  written independently at write-time, not gated on send success       │
     └───────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

No new top-level modules are required — this is a within-file generalization.

```
core/
├── autonomous.py          # gains: occasion param on run_autonomous_tick (or a new
│                           #   thin wrapper run_occasion_cascade); occasion-aware
│                           #   bypass of _is_empty_signals + change-detection gate;
│                           #   occasion-aware topic_key construction
│                           #   (nightly:<date> / morning:<date> / weekly:<date>)
├── nightly_review.py       # loses: _compose_nightly, _parse review-skip logic
│                           # keeps: _gather_tomorrow, _ensure_reflection,
│                           #   _plain_text_fallback (SC-1 infra path), was_sent
├── morning_briefing.py     # loses: handle_tick's pending/sync_detected state
│                           #   machine (D-09), _compose_briefing,
│                           #   _parse_briefing_skip
│                           # keeps: _gather_data, _fetch_garmin_safe,
│                           #   _sync_bodyweight_from_garmin, _plain_text_fallback
│                           # gains: run_morning_briefing triggered path (no cron
│                           #   polling), MORNING_TRIGGER_TOKEN auth
├── weekly_training_review.py # loses: _compose_review, _parse_review_skip
│                           # keeps: _gather_week_data, _derive_structural_topics
├── task_dispatch.py        # gains: enqueue_occasion(...) mirroring
│                           #   enqueue_hub_message's shape
├── heartbeat.py            # gains: 4 D-28 anomaly checks (errored occasion,
│                           #   skip streak, weekly-not-firing, undisclosed actions)
└── tools.py                # gains: get_recent_decisions schema + handler +
                             #   SMART_AGENT_DIRECT_TOOLS entry

memory/
└── firestore_db.py         # gains: action-audit store (new class, recommended
                             #   name ActionLogStore) OR an extension to
                             #   TickLogStore's decision_trail shape (discretion)

interfaces/
└── web_server.py           # gains: POST /trigger/morning (mirrors
                             #   /trigger/nightly); POST /internal/process-occasion
                             #   (Cloud Tasks target, mirrors
                             #   /internal/process-hub-message); /trigger/nightly's
                             #   BackgroundTasks call replaced with Cloud Tasks
                             #   dispatch (D-32)

prompts/
├── autonomous_triage.md    # gains: D-02 four-skip-causes-for-occasions section,
│                           #   D-01 speak-by-default flip (occasion-only)
├── autonomous.md           # gains: D-16/D-17 fold-around-recent-outreach section,
│                           #   D-23/D-24 write-and-disclose contract
├── (new) nightly_occasion.md  # D-35: identity + standing question, few lines
├── (new) morning_occasion.md  # D-35: identity + standing question, few lines
└── (new) weekly_occasion.md   # D-35: identity + standing question, few lines
```

### Pattern 1: Generalizing the cascade entry point

**What:** `core/autonomous.py::run_autonomous_tick` (line 1761-1929, read in full)
is currently hardwired to the `*/20` tick's own `gather_situation()`. CONTEXT.md's
code-context section explicitly says it "gains the occasion parameter." The cleanest
way to honor that without breaking the tick-specific shape (Layer 0 gather is
today-scoped; nightly needs tomorrow-scoped data; weekly needs a 7-day window) is:

1. Add `occasion: str | None = None` and `extra_situation: dict | None = None`
   parameters to `run_autonomous_tick` (or extract a new
   `run_occasion_cascade(bot, now, occasion, situation)` that shares the Layer 1/2
   body with `run_autonomous_tick` via a shared internal helper — either shape
   satisfies D-36's "one place to change behavior").
2. Each occasion module still runs its own specialized gather (`_gather_tomorrow`,
   `_gather_data`, `_gather_week_data`) — this data becomes `extra_situation`,
   merged into (or passed alongside) the standard `gather_situation()` output before
   Layer 1/2 render.
3. `_is_empty_signals` gate and the Layer-0.5 `_compute_signal_signature` gate are
   both skipped when `occasion is not None`.
4. `topic_key` is deterministic for occasions (`nightly:<date>`, `morning:<date>`,
   `weekly:<date>`) rather than tick-brain-supplied — CONTEXT.md's `code_context`
   confirms this ("occasion guidance selection; topic-key construction" is listed as
   an autonomous.py integration point).

**When to use:** Every occasion entry point (`run_nightly`, `run_morning_briefing`,
`run_weekly_review`) calls into this shared function after its own gather, instead
of building its own `LLMClient` + system-prompt-substitution call.

**Example (shape, not literal code — Claude's discretion on exact signature):**
```python
# core/autonomous.py — illustrative shape only
async def run_autonomous_tick(
    bot, now: datetime | None = None,
    *, occasion: str | None = None, extra_situation: dict | None = None,
) -> dict:
    situation = gather_situation(now)
    if extra_situation:
        situation.update(extra_situation)
    situation["occasion"] = occasion  # renders into both triage + compose prompts

    if occasion is None:
        # existing tick-only bypass logic (empty gate, change-detection gate)
        ...
    # else: occasion runs — skip both gates, go straight to Layer 1
    ...
```

### Pattern 2: `skipped_by_judgment` vs. infra failure (OCC-01, SC-1)

**What:** The current nightly (`core/nightly_review.py::_compose_nightly`, lines
232-316) already has a **two-tier LLM fallback** (primary Sonnet-5 → Gemini
`SMART_AGENT_FALLBACK_*` → `_plain_text_fallback` deterministic template). That
deterministic fallback path is the existing SC-1 "total infra failure" contract —
it must be preserved untouched. The **new** `skipped_by_judgment` outcome is a
*different* code path entirely: Layer 1 (`TickBrain.think`) returns
`{"should_act": false, ...}` — a **successful** judgment call that chose silence.

The critical invariant: these two paths must never be confusable in the state doc
or the logs.
- Infra failure → the deterministic `_plain_text_fallback` text is **still sent**
  (SC-1: "a total infra failure still sends the deterministic plain-text
  fallback"). State doc: `status: "sent"`, with a marker like `"composed_via":
  "plain_text_fallback"` (recommended — Claude's discretion on the exact field
  name) so the distinction is queryable.
- Judgment skip → **nothing is sent**. State doc: `status: "skipped_by_judgment"`.

**Existing precedent to mirror:** `core/morning_briefing.py::run_morning_briefing`
already has this exact shape for a different veto (`_parse_briefing_skip` /
`skipped_by_directive`, lines 152-165) — it writes a *distinct* status string and
returns *before* `send_and_inject` and *before* the structured/daily_note writes.
`skipped_by_judgment` should follow the identical branch shape, just triggered by
Layer 1's `should_act=False` instead of a parsed directive-skip JSON trailer.

**Log distinguishability (heartbeat D-28 #1):** `core/heartbeat.py::check_cron_health`
currently keys off `heartbeat_runs` ledger docs (`_log_cron_run`, `ok`/`consecutive_failures`).
An occasion that hits the infra-failure path (both LLM tiers down) still calls
`_log_cron_run(..., ok=True)` today (the cron itself "succeeded" — it sent
something), which would mask the degraded state from the existing heartbeat cron
checker. **This is a real gap D-28 #1 explicitly targets** ("any occasion that
errored... this is the failure-skip class and must never pass silently") — the
heartbeat anomaly check needs to read the occasion's OWN state doc field
(`composed_via` or equivalent), not just the generic cron ledger's `ok` boolean.

### Pattern 3: Morning push-trigger route (D-08/D-09, OCC-02)

**What:** `interfaces/web_server.py::trigger_nightly` (lines 539-558) is the exact
template to mirror for `/trigger/morning`, with two corrections:
1. Use a **new** bearer token env var `MORNING_TRIGGER_TOKEN` (D-13), not
   `NIGHTLY_TRIGGER_TOKEN` — a dedicated `_verify_morning_trigger_request` mirroring
   `_verify_trigger_request` (lines 432-473) exactly, swapping the env var name.
2. **Do not** use `background_tasks.add_task(...)` — this is the D-32 defect being
   fixed. Use `core.task_dispatch.enqueue_occasion(...)` (new function, mirrors
   `enqueue_hub_message`) targeting a new `/internal/process-occasion` endpoint, ACK
   with 202 immediately.

`core/morning_briefing.py::handle_tick` (lines 58-124) — the entire
`pending → sync_detected → sent` state machine, the `(10, 15)` cutoff tuple
comparison, and `retry_count` — is deleted in favor of a single new entry point
(e.g. `run_morning_briefing_triggered(bot, trigger="focus"|"backstop"|"manual")`)
that fires immediately, no polling, no cutoff (D-09). `_get_state`/`_set_state`
(lines 36-51) survive unchanged — the `morning_briefings/{date}` doc just carries a
simpler `status` enum now (`sent | skipped_by_judgment | skipped_by_directive |
manual`, no more `pending`/`sync_detected`/`failed`).

**Widened window (D-15):** when the morning occasion detects last night's nightly
never ran (its own `was_sent`-equivalent for yesterday's `nightly_reviews/{date}`
doc reads `False`/absent), the morning gather should read **yesterday + today**
rather than today only. `core/nightly_review.py::_get_state(target_date)` is
already the exact function to call for this check — it's a light Firestore read,
no new store needed.

**Note on `docs/DEPLOYMENT.md`:** `_CRON_MAX_STALENESS_HOURS` in `core/heartbeat.py`
(line 109) currently has `"morning-briefing": 26` keyed to the cron. Once
`morning-briefing-tick` retires (D-10, sequenced after D-31), this staleness check
needs re-pointing at the trigger's own ledger entry (or removed if
`/trigger/morning` fully replaces the concept of a heartbeat-monitored cron —
Claude's discretion, but the CLAUDE.md §5 infra table and `docs/DEPLOYMENT.md` §21
must be updated either way).

### Pattern 4: Layer 2 exhaustion — force a final answer (D-22, OCC-05)

**What:** `core/main.py::_run_smart_loop` (lines 813-1055) currently handles
`MAX_TOOL_ITERATIONS` exhaustion at lines 1033-1055: if `last_response_text` is
substantive (>100 chars), it's returned as-is; otherwise an apologetic canned
string is returned. D-22 requires a **new intermediate step**: on exhaustion,
strip the tool schemas and take exactly one more LLM call (no tools available) to
force a final text answer from whatever was gathered in the 12 prior iterations,
**before** falling back to `last_response_text` or the apologetic string.

This is a genuinely new code path — the existing exhaustion handler has no
"one more turn, tools stripped" step today. Concretely: after the `for iteration in
range(MAX_TOOL_ITERATIONS)` loop exits without returning, call
`self.smart_agent.chat(current_messages, system=smart_system, tools=None,
purpose="smart_forced_final", on_text_delta=on_text_delta)` once, and if it returns
non-empty text, return that. Only fall through to the existing
`last_response_text`/apologetic-string logic if that forced call also fails or
returns empty. **Careful:** this touches `core/main.py`, a file shared by every
chat turn, not just occasions — this change benefits the `*/20` tick too (same
function), consistent with D-36's "one place to change behavior" philosophy.

**Stale references to fix (found this session, both wrong):**
- `core/self_manifest.py:590` — `"- **Max tool iterations per conversation:** 8
  (\`MAX_TOOL_ITERATIONS\` in \`core/main.py\`)"` — the actual constant
  (`core/main.py:50`) is `12`. CONTEXT.md flags this explicitly.
- `prompts/autonomous.md:167` — `"Bounded by MAX_TOOL_ITERATIONS = 8 (auto-injected
  from the agent core)."` — same stale `8`, **not flagged in CONTEXT.md** but found
  independently this session; must also be corrected to `12` (and is exactly the
  kind of file D-36 says gets edited this phase anyway, for the write-and-disclose
  addition — same-diff opportunity).

### Pattern 5: `OCCASION_CASCADE` feature flag

**What:** This codebase has **no existing feature-flag precedent** (searched;
`grep` found none). The nearest analog is `CRON_DEV_BYPASS` (a boolean env var read
as `os.getenv("CRON_DEV_BYPASS", "false").lower() == "true"`, used in
`_verify_cron_request` and `_verify_trigger_request`). **Recommendation:** follow
this exact convention for consistency — `os.getenv("OCCASION_CASCADE", "false").lower()
== "true"`, read once per occasion entry point (nightly/weekly only, per D-30 —
morning ships cascade-only with no flag branch at all). When `False`, the occasion
module calls its **existing** `_compose_nightly`/`_compose_review` single-shot
path (kept alive, unmodified, for the observation window); when `True`, it calls
the new shared-cascade path. This keeps the flag-off path byte-identical to
current production behavior — the safest possible A/B.

### Anti-Patterns to Avoid

- **Don't route occasions through `gather_situation()` alone.** It is today-scoped
  (`_gather_calendar` fetches only today's events); nightly needs tomorrow, weekly
  needs a 7-day window. Keep the specialized gathers; merge their output into the
  situation dict passed to Layer 1/2.
- **Don't let occasion-only prompt guidance bloat the shared triage system prompt
  unconditionally.** Prefer rendering occasion-specific instructions into the
  **user message** (`_build_triage_prompt`'s output), gated on `situation.get("occasion")`
  being set, rather than adding always-present text to
  `prompts/autonomous_triage.md`'s body that every one of the ~43 daily tick calls
  also pays for. Where D-36 genuinely requires shared-file text (the 4 skip causes,
  the fold-in behavior, write-and-disclose), keep it as tight as possible and
  re-run `tests/test_token_budget.py` after every edit.
- **Don't reuse `TickLogStore.write()`'s `tick_time` parameter with a real `HH:MM`
  value for an occasion.** Autonomous ticks write to
  `tick_logs/{date}/ticks/{HH:MM}`; an occasion firing at, say, `22:15` could
  collide with a real tick's `HH:MM` doc if not given a distinguishing key (e.g.
  `"occasion:nightly"` instead of `"22:15"`).
- **Don't gate D-25's action-audit write on `send_and_inject` success.** This is the
  explicit point of D-25 — actions must be recorded "the moment it happens,"
  independent of whether the occasion later sends a message. Mixing this into the
  `OutreachLogStore.append` D-10 write-after-send call site would silently drop
  action records on a skip.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Full-CPU async dispatch for a slow multi-LLM compose | A new BackgroundTasks-based "wait longer" hack, or a bespoke async queue | `core/task_dispatch.py::enqueue_update`/`enqueue_hub_message` pattern — add `enqueue_occasion` alongside them | Already solves exactly this problem (proven fix for the 2026-06-12 18-minute-reply incident); reusing it keeps one OIDC/Cloud-Tasks code path instead of three |
| Bearer-token auth for a push trigger | A custom signature scheme or reusing the Cloud Scheduler OIDC path | `_verify_trigger_request` pattern (constant-time `hmac.compare_digest`, refuse-all on unset env, redacted-prefix logging) | Exact precedent exists (`NIGHTLY_TRIGGER_TOKEN`); D-13 explicitly asks for a **new**, not shared, token following this same shape |
| Per-occasion dedup / idempotency | A new locking mechanism or Firestore transaction | The existing date-keyed-doc `_get_state`/`_set_state` + `status` field pattern (`nightly_reviews/{date}`, `morning_briefings/{date}`) | Already proven idempotent across two independent trigger paths (organic + backstop) for the nightly; D-12 explicitly says "one proven pattern in both directions" |
| Groq per-request token counting | A char-count heuristic ("~4 chars/token") | `tiktoken.get_encoding("o200k_harmony")` — the exact tokenizer Groq uses server-side for `openai/gpt-oss-120b` | `tests/test_token_budget.py`'s own docstring explains a char estimate previously **under-measured production by ~420 tokens** and caused a live 413 incident (2026-07-27) — a repeat of that mistake for occasion-guidance sizing would be the same failure mode |
| A repeat-suppression namespace for occasions | A second, occasion-only outreach log | The existing `OutreachLogStore` (D-18: "one shared namespace, occasions and ticks as peers") | The store's `topics_today`/`append` API already supports arbitrary `topic_key` strings; `nightly:<date>` is just a new key shape, no schema change |
| Skip-vs-directive-veto JSON parsing | A fourth `_parse_*_skip` clone for the occasion cascade | The Layer-1 `TickBrain._parse_response`'s existing `should_act`/`reason`/`draft`/`topic_key` JSON contract | The three existing `_parse_*_skip` functions in nightly/morning/weekly are exactly the code this phase should be **deleting**, not adding a fourth copy of — Layer 1's JSON contract already carries `should_act` |

**Key insight:** almost every piece of infrastructure this phase needs already
exists in the codebase in a slightly narrower form (auth, dispatch, dedup,
token-budget, veto-parsing). The work is generalization and deletion of
near-duplicates, not new construction. The two genuinely new pieces are the
`get_recent_decisions` tool/store and the D-25 action-audit write path.

## Common Pitfalls

### Pitfall 1: Forgetting to bypass the Layer-0.5 change-detection gate for occasions

**What goes wrong:** An occasion fires, `gather_situation()` runs, but if the
salient-signal hash happens to match the last tick's (very plausible for a
21:00-adjacent nightly right after the day's last `*/20` tick), the change-detection
gate at `core/autonomous.py:1814-1830` silently skips Layer 1 entirely — the nightly
never even gets triage-judged, let alone composed.
**Why it happens:** The gate was designed purely for tick efficiency and has no
concept of "this is a scheduled occasion, not a repeat evaluation."
**How to avoid:** Explicit `if occasion is not None: skip both gates` branch, as
CONTEXT.md's code_context already flags line-by-line.
**Warning signs:** `decision["trail"]` containing `"signals_unchanged_since_last_tick"`
for an occasion run in `TickLogStore`/logs — this string should never appear when
`occasion` is set.

### Pitfall 2: Empty-gate bypass forgotten breaks "always get a free triage judgment"

**What goes wrong:** Same class of bug as Pitfall 1 but at the earlier gate
(`_is_empty_signals`, line 977) — a genuinely quiet day (`gathered["empty"] = True`)
would cause the occasion to return before Layer 1 ever runs, violating OCC-04's
"occasions always get a free triage judgment regardless of the empty-signal gate."
**Why it happens:** Same root cause — the gate predates occasions.
**How to avoid:** Same explicit bypass; test both gates independently (they are two
separate `if` blocks at two different points in `run_autonomous_tick`).
**Warning signs:** `decision["skipped"] == "empty"` recorded for an occasion — this
value should be structurally impossible once the bypass is correct.

### Pitfall 3: Confusing `skipped_by_judgment` with the plain-text infra fallback

**What goes wrong:** If the state-doc write path doesn't distinguish "Layer 1 said
no" from "both LLM tiers failed, deterministic template sent," the heartbeat D-28
#1 anomaly check ("any occasion that errored... must never pass silently") cannot
detect real infra failures — they'll look identical to a legitimate quiet skip in
the logs.
**Why it happens:** Both paths currently converge on similar-looking early returns
in the existing code (`_compose_nightly` already falls through primary → fallback →
plain-text with no distinguishing marker beyond log lines).
**How to avoid:** A dedicated `composed_via` field (or similar) in the state doc —
`"llm"` (primary or Gemini-fallback compose succeeded) vs. `"plain_text_fallback"`
(both LLM tiers failed) vs. absent (Layer 1 skip, no compose attempted at all).
**Warning signs:** SC-1's acceptance test — "the two are distinguishable in the
logs" — cannot be satisfied without this field; write the field before writing any
test against it.

### Pitfall 4: `daily_note`/`structured` write timing regression (D-05/D-06 override)

**What goes wrong:** `core/morning_briefing.py::run_morning_briefing` (lines
130-227) currently writes `structured` (line 191) and `daily_note` (line 216)
**only in the send-success path**, exactly what CONTEXT.md says this phase must
invert (D-05: snapshot always written; D-06: `daily_note` on skip comes from the
Layer-1 draft). A naive occasion-cascade port that keeps the existing write
placement (after `send_and_inject`) would silently preserve the OLD (superseded)
contract and violate the locked D-05/D-06 decisions.
**Why it happens:** The existing code's write-after-send ordering looks
superficially like the correct "write-after-success" discipline (it mirrors D-10's
`OutreachLogStore` pattern) — but D-05/D-06 explicitly carve out an exception for
the *snapshot* (not the outreach log).
**How to avoid:** Move `structured` snapshot write to happen unconditionally
(sent OR skipped), sourcing `daily_note` from `verdict.get("draft", "")` (Layer 1's
JSON output) on a skip, and from the composed text's first line on a send (existing
logic, lines 206-209, unchanged for the send path).
**Warning signs:** `/api/today`'s `coach_note` field staying null/stale on a night
Klaus skipped — the exact regression the Hub-consumption note in CONTEXT.md warns
about.

### Pitfall 5: Token-budget margin erosion from shared-prompt occasion guidance

**What goes wrong:** D-36 requires the D-02 four-skip-causes taxonomy and the
D-01 speak-by-default flip to live in `prompts/autonomous_triage.md` — the SAME
file every one of the ~43 daily `*/20` tick calls renders as its system prompt.
`tests/test_token_budget.py`'s maximal fixture currently measures 7,146/7,200
tokens — a 54-token margin. Any unconditional addition larger than that budget
regresses the guard test for **every** tick, not just occasions.
**Why it happens:** The shared-file requirement (D-36) and the tight token margin
(Phase 32's own recalibration finding) are in direct tension, and nothing in
CONTEXT.md explicitly reconciles them.
**How to avoid:**
1. Keep the occasion-specific text as short as possible (a handful of lines, per
   the spirit of D-35's "few lines each" applied to the shared additions too).
2. Where the addition is genuinely occasion-conditional in meaning (e.g. "if this
   is an occasion, your default flips to speaking"), consider phrasing it so a
   normal tick reads it as a no-op rather than needing it stripped — cheaper than
   conditional prompt assembly, but still costs tokens on every render.
3. **Re-run `tests/test_token_budget.py` after every edit to
   `prompts/autonomous_triage.md`** — this is a mandatory verification step per
   task, not just a final check (see Validation Architecture).
**Warning signs:** `test_maximal_triage_prompt_plus_completion_budget_fits_groq_ceiling`
failing in CI; a live Groq 413 in production logs (the exact 2026-06-12/2026-07-27
incident class).

### Pitfall 6: Idempotency check racing itself during the observation window

**What goes wrong:** D-23's calendar-write idempotency check (existing planned
row/Training-calendar event for that date+slot) and Phase 34's future write-back
machinery are not yet unified — this phase must implement its own check
independently. If two occasions fire close together (e.g. a same-day nightly +
morning-widened-window read, D-15) and both attempt a calendar write for the same
date+slot without a shared lock, a race is possible even with a correct
per-call idempotency check (check-then-act race, not a logic bug).
**Why it happens:** The idempotency check as described (query for an existing row
before creating) is inherently a check-then-act pattern without an atomic guard.
**How to avoid:** Reuse Firestore's `merge=True`/document-existence-check pattern
already used elsewhere (e.g., `OutreachLogStore.append`'s `ArrayUnion`) where
possible; at minimum, make the calendar-event-lookup query as close in time to the
create call as possible and log every create with enough detail
(date+slot+source-occasion) that a duplicate is detectable after the fact via
`get_recent_decisions`'s action trail.
**Warning signs:** Two `Created: <label>, <date> <time>` disclosure lines for the
same date+slot in consecutive occasion sends.

### Pitfall 7: Scheduler sequencing violated (D-10/D-24/D-31)

**What goes wrong:** Retiring `morning-briefing-tick` (Cloud Scheduler job) before
`/trigger/morning` is confirmed live would create a silent morning gap — no
briefing at all until the iOS Shortcut is built and firing.
**Why it happens:** It's tempting to do all scheduler changes in one deploy for
tidiness.
**How to avoid:** Strict sequencing per D-31: (1) deploy `/trigger/morning` dark
(auth works, route exists, does nothing until hit), (2) Amit builds and enables the
Sleep-Focus-off Shortcut (operator step, outside this codebase), (3) confirm real
triggers are landing (log/heartbeat check), (4) only then retire
`morning-briefing-tick` from Cloud Scheduler and delete the polling code.
**Warning signs:** A gap of zero morning briefings between the Shortcut going live
and the cron retiring, or vice versa — either ordering mistake produces a silent
gap; watch `docs/DEPLOYMENT.md` §5 (Cloud Scheduler job inventory) for the actual
retirement commit.

### Pitfall 8: `_log_cron_run(..., ok=True)` masking degraded occasion sends

**What goes wrong:** Every existing `/cron/*` route wraps its call in
`try/except` and calls `_log_cron_run(job_id, ok=True)` on the happy path — but
"happy path" today means "no Python exception raised," not "the message Klaus
actually wanted to send arrived." An occasion that silently falls through to the
plain-text infra fallback (Pitfall 3) still returns normally and gets logged
`ok=True`.
**Why it happens:** `_log_cron_run`'s `ok` boolean was designed for crash detection,
not judgment-quality detection.
**How to avoid:** Treat `_log_cron_run`'s `ok` flag and the new D-28 heartbeat
anomaly checks as two separate, complementary signals — don't expect the existing
cron-staleness/failure-streak machinery in `check_cron_health` to catch a
degraded-but-non-crashing occasion. The D-28 checks must read the occasion's own
state doc, not rely on `_log_cron_run`.
**Warning signs:** A production incident where Amit reports "the nightly felt off"
but `heartbeat_runs` shows no failures.

### Pitfall 9: Deleting the weekly composer's `_derive_structural_topics` accidentally

**What goes wrong:** `core/weekly_training_review.py::_derive_structural_topics`
(lines 362-386) is NOT part of the composer being replaced — it's a deterministic,
non-LLM function that derives `CoachingTopicStore` dedup keys from already-gathered
week data, used for cross-cron dedup (COACH-05), unrelated to the OCC-03 cascade
migration. A careless "delete everything `_compose_review`-adjacent" pass could
remove this by mistake since it's called from the same `_gather_week_data`
docstring context.
**Why it happens:** Proximity in the file, both touched by the same refactor.
**How to avoid:** `_derive_structural_topics` and its call site
(`data["coaching_topics_included"] = _derive_structural_topics(data)`, inside
`_gather_week_data`) survive untouched — only `_compose_review` and
`_parse_review_skip` are replaced by the cascade call.
**Warning signs:** `CoachingTopicStore` topics no longer being recorded post-send
for the weekly review; a regression in the `coaching_topics_included` post-send
write (lines 605-616 of `run_weekly_review`) which itself is unrelated to the
cascade and must also survive.

### Pitfall 10: Dual-run cost during the observation window (OCC-06)

**What goes wrong:** For the 3-4 day observation window (nightly + weekly only,
per D-30's override — morning has no legacy path to compare against), **both** the
legacy single-shot composer AND the new agentic cascade run for every nightly and
weekly occasion. The legacy composer is one LLM call (Sonnet-5 primary, `max_tokens`
default for nightly / `max_tokens=32000` for weekly per the existing
`_compose_review` call). The new cascade is Layer 1 (free Groq) + Layer 2, which
under D-21 can run up to `MAX_TOOL_ITERATIONS=12` Sonnet-5 tool-calling turns before
returning. **This is a genuine, non-trivial cost multiplier during the window** —
plausibly several times the per-occasion Sonnet-5 spend for nightly/weekly on the
days both paths run, though the exact multiplier depends on how many tool calls
Layer 2 actually makes in practice (unknown without live data — [ASSUMED]).
**Why it happens:** It's the explicit, accepted tradeoff of an A/B rollout (D-30/OCC-06)
— not a bug, but a cost the plan must budget for.
**How to avoid:** Not avoidable by design (it's the point of the A/B), but the plan
should (1) make sure `check_daily_spend`'s existing `KLAUS_DAILY_COST_ALERT` tripwire
(`core/heartbeat.py:819-864`, default $5/day) is expected to fire more often during
the observation window and this is not itself treated as an incident, and (2) keep
the window genuinely short (3-4 days, as locked) rather than letting it drift.
**Warning signs:** A `check_daily_spend` alert firing on the days both nightly and
weekly cascades ran alongside their legacy composers — expected, not alarming,
during the window only.

## Code Examples

### New `/trigger/morning` route (mirrors `trigger_nightly`, D-08/D-13, with the D-32 fix applied)

```python
# interfaces/web_server.py — illustrative shape, mirrors trigger_nightly (lines 539-558)
# but dispatches via Cloud Tasks instead of BackgroundTasks (D-32 fix — do NOT copy
# trigger_nightly's background_tasks.add_task call, that is the defect being fixed).

async def _verify_morning_trigger_request(request: Request) -> None:
    # Identical shape to _verify_trigger_request (lines 432-473), swap the env var:
    # expected = os.environ.get("MORNING_TRIGGER_TOKEN", "")

@app.post("/trigger/morning")
async def trigger_morning(request: Request) -> JSONResponse:
    await _verify_morning_trigger_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    from core.task_dispatch import enqueue_occasion
    if not enqueue_occasion("morning", trigger="focus"):
        # Cloud Tasks unavailable — fall back to BackgroundTasks so the trigger
        # is never silently dropped (same graceful-degradation contract
        # enqueue_update already has), but this is the degraded path, not primary.
        ...
    return JSONResponse(status_code=202, content={"accepted": True})
```

### Tool registration for `get_recent_decisions` (OCC-07, mirrors `forget_memory`)

```python
# core/tools.py — schema (mirrors the forget_memory shape at lines 497-522)
{
    "name": "get_recent_decisions",
    "description": (
        "Look back at recent tick/occasion judgment calls — what Klaus decided, "
        "why, what was sent (or not), and any calendar/task actions taken. "
        "Call this directly — do NOT delegate to the worker. Use when Amit asks "
        "why Klaus did or didn't say something recently, or what he changed on "
        "the calendar."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many days back to look. Default 2.",
            },
        },
        "required": [],
    },
},

# _HANDLERS dict addition (mirrors line 3154):
"get_recent_decisions": lambda args: _handle_get_recent_decisions(**args),

# SMART_AGENT_DIRECT_TOOLS addition (mirrors line 42's "recall" entry):
# add "get_recent_decisions" to the frozenset at lines 40-73.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Three independent single-shot LLM composers with per-composer `_parse_*_skip` trailing-JSON veto convention | One shared 3-layer cascade (tick-brain triage + agentic compose) invoked with an `occasion` parameter | This phase (33) | Judgment moves from "always fire, LLM may append a skip-JSON trailer" to "Layer 1 decides speak/skip before any compose cost is incurred" |
| Morning briefing anchored to a `*/10 6-10` Garmin-sync poll with a 10:15 cutoff and retry state machine | Push-triggered via iOS Shortcuts on Sleep-Focus-off, fires immediately, no cutoff | This phase (33), D-08/D-09 override | Zero detection latency, zero polling cost, but zero backstop — a missed automation means no briefing that day (accepted tradeoff) |
| Directive-gated proactive calendar writes (as originally planned in the milestone doc) | Ungated writes with mandatory after-the-fact disclosure (D-23 override) | This phase (33) | Higher agency, higher disclosure burden; idempotency check becomes load-bearing correctness, not just a nicety |
| `BackgroundTasks` for `/trigger/nightly`'s multi-LLM compose | Cloud Tasks dispatch to `/internal/process-occasion`, mirroring the existing Telegram/Hub full-CPU pattern | This phase (33), D-32 | Fixes a latent defect (throttled-CPU background compose) that has not yet caused a production incident for the nightly (still one LLM call today) but would under the new agentic Layer 2 |

**Deprecated/outdated:**
- `core/morning_briefing.py::handle_tick`'s `pending`/`sync_detected`/`failed`
  state machine — retired by D-09, replaced by immediate-fire-on-trigger.
- The three `_parse_*_skip` trailing-fenced-JSON functions
  (`_parse_briefing_skip`, `_parse_review_skip`, and nightly's equivalent handling)
  — superseded by Layer 1's existing `should_act`/`reason`/`draft`/`topic_key` JSON
  contract (`TickBrain._parse_response`).

## Assumptions Log

> List all claims tagged `[ASSUMED]` in this research. The planner and discuss-phase use this
> section to identify decisions that need user confirmation before becoming a locked decision.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The dual-run cost multiplier during the observation window is "several times" the per-occasion legacy-composer spend, based on `MAX_TOOL_ITERATIONS=12` as a theoretical ceiling, not measured live tool-call counts | Common Pitfalls 10 | If actual Layer-2 tool usage is much lower (e.g. 1-2 calls typical), the cost risk is overstated; if higher usage patterns emerge, `KLAUS_DAILY_COST_ALERT`'s $5 default may need retuning for the window specifically |
| A2 | `ActionLogStore` (a new Firestore collection) is the recommended shape for D-25's action-audit record, over extending `TickLogStore` | Don't Hand-Roll, Recommended Project Structure | This is explicitly flagged as Claude's Discretion in CONTEXT.md — the planner is free to choose the TickLogStore-extension shape instead; no functional risk either way as long as `get_recent_decisions` reads whatever shape is chosen |
| A3 | `_CRON_MAX_STALENESS_HOURS["morning-briefing"]` in `core/heartbeat.py` needs re-pointing once `morning-briefing-tick` retires, rather than being removed outright | Pattern 3 | If left pointed at the now-dead cron's ledger entry, `check_cron_health` will eventually fire a false "stale" critical signal once the old cron stops running entirely — low risk, easily caught during the D-31 sequencing window, but worth an explicit plan task |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed. *(Not applicable — see table above.)*

## Open Questions (RESOLVED)

> All three were resolved during planning (2026-07-29). Resolutions noted inline below;
> the deciding plan/task is cited in each. A fourth question surfaced by the plan-checker
> — the mechanism for the weekly's standing-directive veto — is recorded as Q4.

1. **Exact call-site shape: does `run_autonomous_tick` itself gain the `occasion`
   parameter, or does a new thin wrapper function share its Layer 1/2 body?**
   - **RESOLVED — plan 33-04 Task 1** took the recommendation: a shared internal
     `_run_cascade(...)` body with `run_autonomous_tick` calling it as `occasion=None`
     and a public `run_occasion_cascade(...)` entry for the three occasions.
     `run_autonomous_tick`'s public signature is unchanged, pinned by an acceptance
     criterion (the Cloud Scheduler route depends on it).
   - What we know: CONTEXT.md's code_context literally states "the 3-layer
     orchestrator that gains the occasion parameter," naming
     `run_autonomous_tick` specifically. The function's docstring documents an
     8-step pipeline that includes tick-specific concepts (`_TICK_TOTAL_PER_DAY`,
     `tick_index`) that don't cleanly apply to a once-a-night occasion.
   - What's unclear: whether `now_context`'s `tick_index`/`tick_total` fields
     should render meaningfully for an occasion (e.g. omitted, or a fixed
     sentinel), and whether reusing the exact same function signature vs.
     extracting a shared internal helper is cleaner for testability.
   - Recommendation: extract a shared internal helper (e.g.
     `_run_cascade(bot, now, situation, occasion, topic_key_fn)`) that both
     `run_autonomous_tick` (occasion=None) and the three occasion entry points
     call, rather than overloading `run_autonomous_tick`'s public signature — this
     keeps `now_context`'s tick-specific fields naturally scoped to the tick path
     and gives occasions their own topic-key/skip-taxonomy without conditional
     branches deep inside the tick's own logic. This is presented as a
     recommendation, not a lock — Claude's Discretion per CONTEXT.md leaves the
     exact call-site shape open.

2. **How does the D-15 "widened morning window" merge yesterday's nightly-absent
   detection with the morning's own gather without double-fetching Garmin/calendar
   data?**
   - What we know: `core/nightly_review.py::_get_state(yesterday_iso)` is a cheap
     Firestore read that tells the morning occasion whether last night's review
     ran. `core/morning_briefing.py::_gather_data` already reads yesterday's
     nightly `structured` snapshot for the "what's new since last night" delta
     (lines 317-329) — this existing read could double as the "did it run" check
     (its absence already means "no nightly ran").
   - What's unclear: whether the widened-window behavior needs a genuinely
     different gather (e.g. also pulling yesterday's calendar/tasks, not just
     the existing delta-snapshot) or whether the existing `since_last_night`
     read is already sufficient content for D-15's "the pair must not lose a
     day" goal.
   - Recommendation: start from the existing `since_last_night` read (it already
     exists and is the natural signal) and only add a genuinely wider gather if
     UAT during the observation window shows it's insufficient — avoid building
     new fetch logic speculatively.
   - **RESOLVED — plan 33-07 Task 2** took the recommendation: D-15 is detected from
     the existing `_nightly_state(yesterday)` read via a new `nightly_ran` flag. No
     new fetch logic.

3. **Should the `daily_note`/`structured`-write timing fix (Pitfall 4) also apply
   to the nightly and weekly occasions, or is it morning-only per the literal
   OCC-02 wording?**
   - What we know: CONTEXT.md's D-05/D-06 language is framed around "the morning
     `structured` snapshot" specifically, and `/api/today`'s Hub consumption is
     morning-specific (`daily_note`/`daily_note_date` fields, `coach_note` in the
     Hub API).
   - What's unclear: whether the nightly's own `structured` snapshot (written in
     `core/nightly_review.py::run_nightly`, line 403-408, currently inside the
     `_set_state` call **after** send) should get the same "always write, even on
     skip" treatment for symmetry, even though CONTEXT.md doesn't explicitly say so.
   - Recommendation: apply the same "always write the snapshot, regardless of
     send outcome" principle to the nightly's `structured` field too — it costs
     nothing extra to write and is consistent with D-07's "the nightly journal is
     always written" (same session, same phase, same underlying philosophy: "Klaus
     perceived the day" separate from "Klaus decided to speak"). Flag for
     discuss-phase/plan confirmation since it is not explicitly locked.
   - **RESOLVED — plan 33-06 Task 2** took the recommendation: the always-write-snapshot
     principle extends to the nightly, matching D-05/D-07's philosophy.

4. **[Added by gsd-plan-checker, 2026-07-29] By what mechanism does a standing directive
   veto the weekly review, given `advisory_only=True` ignores Layer 1's `should_act`?**
   - What we found: there is no deterministic option. `StandingDirectiveStore`
     (`memory/firestore_db.py:1841`) stores directives as free-form verbatim `text` with
     no `scope`/`applies_to` field; `_gather_standing_directives`
     (`core/autonomous.py:399`) returns that list unfiltered; and
     `render_standing_directives_block` (`core/tools.py:2339`) is a pure formatter by its
     own docstring. Nothing in the codebase maps directive free-text → occasion
     applicability without an LLM.
   - **RESOLVED — plans 33-04 (`veto_parser` hook), 33-08 Task 2, 33-03 Task 3**: the veto
     stays LLM judgment expressed through the existing `_parse_review_skip` fenced-JSON
     trailer, now passed into `_run_cascade` as a `veto_parser` callable applied to Layer
     2's text before send. This generalizes the three near-duplicate `_parse_*_skip`
     functions flagged earlier in this document, preserves Phase 31 D-21/D-22 literally
     (same parser, same trailer, same log line), and adds **zero** LLM calls — the veto
     rides the Layer-2 compose the weekly already pays for, leaving the Layer 0/1 free →
     Layer 2 paid cost invariant intact.

## Environment Availability

This phase has no new external service/tool dependencies beyond what the
repository already requires (Google Cloud Tasks, Firestore, Groq, Anthropic/Gemini
APIs — all already in production use by the existing tick/composer code this phase
generalizes). The one net-new environment dependency is operator-side, not
code-side: **Amit must build a new iOS Shortcut** (Sleep-Focus-off automation
hitting `/trigger/morning`) before D-31's dark-ship sequencing can complete — this
is documented as an explicit "Operator step for Amit" in CONTEXT.md D-31, not a
code dependency this research needs to probe.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Google Cloud Tasks | D-32 dispatch pattern | ✓ (already used by `core/task_dispatch.py`) | — | — |
| `tiktoken` (o200k_harmony) | Token-budget guard re-verification after prompt edits | ✓ (`tiktoken==0.13.0` pinned, Phase 32) | 0.13.0 | — |
| iOS Shortcuts automation (Sleep-Focus-off) | D-08/D-31 morning trigger | ✗ (must be built by Amit, operator step) | — | None — D-09 explicitly rejects a backstop; D-31 sequencing keeps `morning-briefing-tick` alive until this exists |

**Missing dependencies with no fallback:**
- The Sleep-Focus-off iOS Shortcut — blocks `morning-briefing-tick` retirement
  (D-31) but does NOT block deploying `/trigger/morning` itself (ships dark).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (see `pytest.ini`: `testpaths = tests`, `python_files = test_*.py`) |
| Config file | `pytest.ini` (repo root) |
| Quick run command | `pytest tests/test_autonomous.py tests/test_nightly_review.py tests/test_morning_briefing.py tests/test_weekly_training_review.py tests/test_token_budget.py -x` |
| Full suite command | `pytest tests/` (run per-file where possible — full-suite-in-one-process is known to segfault on grpc/protobuf GC per project MEMORY.md; CI/local should verify per-file or with `-p no:cacheprovider --forked`-style isolation per existing project convention) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OCC-01 | Nightly runs through cascade; `skipped_by_judgment` recorded distinctly from infra-failure plain-text fallback | unit | `pytest tests/test_nightly_review.py -x` (new tests: `test_run_nightly_skipped_by_judgment_records_distinct_status`, `test_run_nightly_infra_failure_still_sends_plain_text`) | ❌ Wave 0 (extend existing file) |
| OCC-01 | SC-1: the two outcomes are distinguishable in logs | manual/log-level | Manual UAT during observation window: trigger one deliberate infra-failure (both LLM tiers unreachable, dev env) and one deliberate judgment-skip (empty day fixture), diff the state-doc/log output | N/A (manual UAT, sampled once per outcome type before rollout, not per-commit) |
| OCC-02 | Morning fires immediately on `/trigger/morning`, no Garmin gate, no cutoff | unit | `pytest tests/test_morning_briefing.py -x` (new tests: `test_trigger_morning_fires_without_garmin_data`, `test_no_1015_cutoff_enforced`; existing `handle_tick` state-machine tests removed alongside the deleted code) | ❌ Wave 0 |
| OCC-02 | `/trigger/morning` auth (bearer token, refuse-all on unset env) | unit | `pytest tests/test_nightly_review.py -k trigger_auth -x` pattern, mirrored into a new `tests/test_morning_briefing.py::test_trigger_morning_auth_*` set (mirrors existing `/trigger/nightly` auth tests) | ❌ Wave 0 |
| OCC-02 | Dedup via daily state doc across snooze/second-alarm/focus-toggle | unit | `pytest tests/test_morning_briefing.py -k dedup -x` | ❌ Wave 0 |
| OCC-02 | Live push trigger actually fires the briefing | manual UAT | Amit's iOS Shortcut hitting the deployed `/trigger/morning` at real wake time, once confirmed before `morning-briefing-tick` retirement (D-31 gate) | N/A (manual, one-time gate before scheduler change) |
| OCC-03 | Weekly runs as `occasion="weekly_review"` through the cascade; never self-skips (D-03) | unit | `pytest tests/test_weekly_training_review.py -x` (new tests: `test_weekly_review_never_returns_skipped_by_judgment`, `test_weekly_review_directive_veto_still_works`) | ❌ Wave 0 |
| OCC-04 | Occasions bypass `_is_empty_signals` gate | unit | `pytest tests/test_autonomous.py -k occasion_bypasses_empty -x` | ❌ Wave 0 |
| OCC-04 | Occasions bypass the Layer-0.5 change-detection gate | unit | `pytest tests/test_autonomous.py -k occasion_bypasses_change_detection -x` | ❌ Wave 0 |
| OCC-04 | OutreachLog topic keys use `nightly:<date>`/`morning:<date>`/`weekly:<date>` format, shared namespace with tick | unit | `pytest tests/test_autonomous.py -k occasion_topic_key -x` | ❌ Wave 0 |
| OCC-04 | OutreachLog append still gated on send success (D-10 invariant preserved) | unit | `pytest tests/test_autonomous.py -k outreach_log_gated -x` (regression test on the existing D-10 invariant, applied to the occasion path) | ❌ Wave 0 |
| OCC-05 | `MAX_TOOL_ITERATIONS=12` bound holds; exhaustion forces a final tools-stripped answer (D-22) | unit | `pytest tests/test_main.py -k smart_loop_exhaustion_forces_final_answer -x` (new test in whichever file already covers `_run_smart_loop` exhaustion — verify exact filename during planning) | ❌ Wave 0 |
| OCC-05 | Idempotency check before proactive calendar create | unit | New test in `tests/test_tools.py` or `tests/test_calendar_tool.py` (verify exact filename) — `test_calendar_create_checks_existing_planned_row_first` | ❌ Wave 0 |
| OCC-05 | Token budget guard still passes after all prompt edits | unit (regression gate) | `pytest tests/test_token_budget.py -x` — **must be run after every commit that touches `prompts/autonomous_triage.md`**, not just at phase end | ✅ exists (extend fixture only if occasion guidance is added to the shared file) |
| OCC-06 | `OCCASION_CASCADE` flag correctly branches nightly/weekly (morning has no flag branch per D-30) | unit | New tests in `tests/test_nightly_review.py`/`tests/test_weekly_training_review.py` — `test_occasion_cascade_flag_off_uses_legacy_composer`, `test_occasion_cascade_flag_on_uses_cascade` | ❌ Wave 0 |
| OCC-06 | Scheduler sequencing (D-31): `/trigger/morning` ships dark, doesn't 500, doesn't send until wired | unit + manual | Unit: route returns 202 correctly even pre-Shortcut-adoption; Manual: confirm zero unexpected sends in the dark-ship window | ❌ Wave 0 (unit) / manual (gate) |
| OCC-06 | Heartbeat D-28 anomaly checks (errored occasion, skip streak, weekly-not-firing, undisclosed actions) | unit | New tests in `tests/test_heartbeat.py` — one per anomaly class | ❌ Wave 0 |
| OCC-06 | Observation-window go/no-go | manual (D-29, explicitly no automated gate) | Amit's subjective judgment from daily message quality — not testable by pytest, not a CI gate | N/A by design |
| OCC-07 | `get_recent_decisions(days)` returns verdict/reasoning/sends/actions/skip-cause | unit | New test in `tests/test_tools.py` — `test_get_recent_decisions_returns_all_four_fields` | ❌ Wave 0 |
| OCC-07 | Tool is brain-direct (registered in `SMART_AGENT_DIRECT_TOOLS`, not delegated to worker) | unit | `pytest tests/test_tools.py -k get_recent_decisions_direct -x` | ❌ Wave 0 |
| OCC-07 | Skips never surface unasked (D-27); undisclosed actions DO surface at next opportunity (D-25 exception) | unit | New tests verifying the compose prompt only injects pending-action disclosure, never pending-skip disclosure, into the next occasion's context | ❌ Wave 0 |
| OCC-07 | Live "why didn't you message me yesterday?" answers correctly | manual UAT | Chat with Klaus post-deploy, ask the question, verify the answer references real recent tick/occasion data | N/A (manual, once per rollout) |

### Sampling Rate
- **Per task commit:** the relevant subset of the quick-run command above
  (whichever file(s) the task touched) — **and always** `pytest
  tests/test_token_budget.py -x` for any task touching
  `prompts/autonomous_triage.md` or `core/autonomous.py`'s triage-prompt
  rendering functions (`_build_triage_prompt` and its helpers).
- **Per wave merge:** the full quick-run command set above.
- **Phase gate:** Full suite green (run per-file per the project's known segfault
  workaround) before `/gsd:verify-work`; plus the manual UAT items above completed
  at least once before the observation window opens (OCC-02's live-trigger
  confirmation, OCC-07's live chat-question confirmation).

### Wave 0 Gaps
- [ ] `tests/test_autonomous.py` — new tests for occasion-parameter bypass of both
      gates (Pitfall 1/2), occasion topic-key format (OCC-04)
- [ ] `tests/test_nightly_review.py` — new tests for `skipped_by_judgment` vs.
      infra-failure distinguishability (OCC-01), `OCCASION_CASCADE` flag branching
      (OCC-06)
- [ ] `tests/test_morning_briefing.py` — new tests for `/trigger/morning`
      (auth, immediate-fire, no-cutoff), deletion of the `handle_tick` state
      machine's tests alongside the deleted code (OCC-02)
- [ ] `tests/test_weekly_training_review.py` — new tests for `occasion="weekly_review"`
      never-self-skips (D-03), `OCCASION_CASCADE` flag branching (OCC-03/OCC-06)
- [ ] `tests/test_heartbeat.py` — new tests for the four D-28 anomaly checks (OCC-06)
- [ ] `tests/test_tools.py` (or wherever tool-handler tests live — verify exact
      filename during planning) — new tests for `get_recent_decisions` (OCC-07)
- [ ] `tests/test_task_dispatch.py` — extend for the new `enqueue_occasion` function
      (D-32)
- [ ] Framework install: none — `pytest`/`tiktoken` already present

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | New `MORNING_TRIGGER_TOKEN` bearer secret (D-13), verified via `hmac.compare_digest` constant-time comparison — exact existing pattern in `_verify_trigger_request`, must not regress to `==` |
| V3 Session Management | no | No new session/cookie surface introduced by this phase |
| V4 Access Control | yes | Least-privilege token separation (D-13's stated rationale: "a leaked credential must not unlock every proactive surface") — `MORNING_TRIGGER_TOKEN` must remain a **distinct** secret from `NIGHTLY_TRIGGER_TOKEN`, not a shared/reused value |
| V5 Input Validation | yes | `get_recent_decisions(days)` — bound/validate the `days` parameter (e.g. reject negative or absurdly large values) before it drives a Firestore date-range query, mirroring existing tool-arg validation patterns in `core/tools.py` |
| V6 Cryptography | no | No new cryptographic primitive introduced — reuses existing `hmac.compare_digest` bearer-token pattern, never hand-rolled |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Timing attack on bearer-token comparison | Information Disclosure | `hmac.compare_digest` (already the pattern; must be preserved for the new `MORNING_TRIGGER_TOKEN` check) |
| Fail-open on unset secret env var | Elevation of Privilege | Refuse-all (HTTP 500) on unset `MORNING_TRIGGER_TOKEN`, exactly mirroring `_verify_trigger_request`'s existing refuse-all-on-unset-env behavior for `NIGHTLY_TRIGGER_TOKEN` |
| Cloud Tasks OIDC audience/service-account confusion | Spoofing | Reuse `CLOUD_SCHEDULER_SA_EMAIL`/`CLOUD_RUN_URL` exactly as `core/task_dispatch.py::enqueue_update`/`enqueue_hub_message` already do — do not introduce a new service account or audience for `enqueue_occasion` |
| Ungated Layer-2 calendar writes (D-23) acting on stale/malicious data | Tampering | The idempotency check (D-23) + standing-directive veto (Phase 31 invariant) are the only guards on write actions — this phase must not weaken either; `get_recent_decisions`'s action trail (D-25) is the detection/audit backstop, not a preventive control |

## Sources

### Primary (HIGH confidence — read directly this session)
- `/Users/amitgrupper/Desktop/Klaus/.planning/phases/33-occasion-cascade/33-CONTEXT.md` — full user-decision record (D-01..D-36), authoritative
- `/Users/amitgrupper/Desktop/Klaus/.planning/phases/32-unified-situation-ambient-memory/32-CONTEXT.md` — upstream context-only invariant, Groq ledger, guard test rationale
- `/Users/amitgrupper/Desktop/Klaus/core/autonomous.py` (full file, 1929 lines) — gather/triage/compose/send pipeline, gates, topic-key logic
- `/Users/amitgrupper/Desktop/Klaus/core/nightly_review.py` (full file, 442 lines) — existing nightly composer, `_ensure_reflection`, `_plain_text_fallback`
- `/Users/amitgrupper/Desktop/Klaus/core/morning_briefing.py` (full file, 735 lines) — existing state machine, `_gather_data`, `_compose_briefing`
- `/Users/amitgrupper/Desktop/Klaus/core/weekly_training_review.py` (full file, 617 lines) — existing week gather/compose, `_derive_structural_topics`
- `/Users/amitgrupper/Desktop/Klaus/core/tick_brain.py` (full file, 352 lines) — TickBrain client, Groq TPD ledger, `think()` contract
- `/Users/amitgrupper/Desktop/Klaus/core/heartbeat.py` (full file, 1277 lines) — signal taxonomy, cron staleness, spend/Groq-budget tripwires
- `/Users/amitgrupper/Desktop/Klaus/core/scheduled_message.py` (full file, 259 lines) — `send_and_inject`, push/mirror gating
- `/Users/amitgrupper/Desktop/Klaus/core/task_dispatch.py` (full file, 180 lines) — Cloud Tasks dispatch pattern
- `/Users/amitgrupper/Desktop/Klaus/interfaces/web_server.py` (lines 160-940, plus grep of full file) — trigger/cron routes, auth functions
- `/Users/amitgrupper/Desktop/Klaus/memory/firestore_db.py` (OutreachLogStore, GroqTokenLedgerStore, TickSignatureStore, CoachingTopicStore, TickLogStore, FollowupStore — ~1000 lines read) — store shapes, write-after-send discipline
- `/Users/amitgrupper/Desktop/Klaus/core/main.py` (lines 468-1055) — `render_smart_system`, `_run_smart_loop`, `MAX_TOOL_ITERATIONS` exhaustion handling
- `/Users/amitgrupper/Desktop/Klaus/core/tools.py` (lines 1-70, 420-600, 3130-3300) — tool schema/handler/dispatch registration pattern
- `/Users/amitgrupper/Desktop/Klaus/prompts/autonomous_triage.md`, `/Users/amitgrupper/Desktop/Klaus/prompts/autonomous.md` (full files) — existing triage/compose prompt contracts
- `/Users/amitgrupper/Desktop/Klaus/tests/test_token_budget.py` (full file, 390 lines) — token-budget guard mechanics and measured margins
- `/Users/amitgrupper/Desktop/Klaus/core/self_manifest.py` (lines 580-596) — confirmed stale `MAX_TOOL_ITERATIONS` reference
- `/Users/amitgrupper/Desktop/Klaus/.planning/REQUIREMENTS.md`, `/Users/amitgrupper/Desktop/Klaus/.planning/ROADMAP.md` — OCC-01..07 verbatim, Phase 33 success criteria
- `/Users/amitgrupper/Desktop/Klaus/CLAUDE.md` — project invariants
- `/Users/amitgrupper/Desktop/Klaus/docs/DEPLOYMENT.md` (§21 Firestore Composite Indexes, §Cloud Scheduler) — index precedent, cron inventory

### Secondary (MEDIUM confidence)
- None — this phase required no external web research; the entire domain is
  internal-codebase.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, fully verified against `requirements.txt`
- Architecture: HIGH — every referenced file/function/line was read in full this
  session, not inferred from training data
- Pitfalls: HIGH for the ones grounded in code read this session (token budget,
  gate-bypass, write-timing); MEDIUM for the dual-run cost estimate (A1, flagged
  `[ASSUMED]` — no live production tool-call-count data available)

**Research date:** 2026-07-29
**Valid until:** ~14 days (fast-moving — this phase's own prior phase, 32, shipped
6 days before this research and Phase 33's implementation will further mutate
`core/autonomous.py`; re-verify line numbers before planning if this research is
consumed more than ~2 weeks after this date)
