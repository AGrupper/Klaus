# Phase 33: Occasion Cascade - Context

**Gathered:** 2026-07-28
**Status:** Ready for planning

<domain>
## Phase Boundary

The nightly review, morning briefing, and Sunday weekly training review stop being
always-fire template composers and become **occasions** routed through the same
3-layer cascade as the `*/20` autonomous tick: Layer 0 gather (free) → Layer 1
tick-brain triage (free, Groq) → Layer 2 agentic brain compose (paid, Sonnet 5) →
send. Silence becomes a real, recorded decision (`skipped_by_judgment`) that is
distinguishable in the logs from an infra failure. Ships with a brain-direct
`get_recent_decisions` introspection tool and an `OCCASION_CASCADE` flag rollout.
Requirements OCC-01..07.

**Out of scope:** mutating the training source of truth from calendar actions or
chat reports (Phase 34 Write-Backs); deleting the legacy composers, retired prompts
and the flag (Phase 35, after the observation window); new eval fixtures (Phase 35).

</domain>

<decisions>
## Implementation Decisions

> **Three of these override text locked in REQUIREMENTS.md / ROADMAP.md.** They are
> deliberate user decisions taken during this discussion, not drift. They are marked
> **[OVERRIDE]** and must be treated as authoritative over the superseded wording.

### Skip appetite — when silence is the right answer (OCC-01/02/03)

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

### Perception vs. speech — what gets written on a skip (OCC-01/02)

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

### Morning wake-up: push trigger replaces the Garmin anchor **[OVERRIDE]**

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

### Occasion ↔ tick collision (OCC-04)

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

### Agentic Layer 2 — powers and limits (OCC-05)

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

### Explaining himself (OCC-07)

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

### Rollout & dispatch

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

### Prompts — what survives the template deletion

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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone plan & review (source of the locked decisions this phase amends)
- `~/.claude/plans/klaus-is-extremely-stupid-graceful-cascade.md` §"Phase 33 — Occasion
  cascade" — the approved v6.0 implementation plan; file list, failure semantics,
  rollout, cost model. **Read the OVERRIDE decisions above first** — D-08/09/10 replace
  its morning-anchor design and D-23 replaces its directive-gated writes.
- `~/.claude/plans/mellow-puzzling-nest.md` §B2 (calendar-write idempotency — still
  binding), §C1 (`get_recent_decisions` rationale), §E1 (weekly-review fold-in decision)

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §OCC-01..07 verbatim — mechanics locked there (topic-key
  format, D-10 send-gating, empty-gate bypass). Three clauses are superseded by the
  OVERRIDE decisions above: OCC-02's Garmin anchor + 10:15 cutoff, OCC-05's
  directive-gated writes, OCC-06's no-scheduler-changes + both-live window.
- `.planning/ROADMAP.md` §Phase 33 — goal + 7 success criteria

### v6.0 research
- `.planning/research/ARCHITECTURE.md` — cascade structure, gather isolation,
  context-only invariant, verified build order
- `.planning/research/PITFALLS.md` — cost-gate / over-fire pitfalls, prompt-cache
  prefix ordering
- `.planning/research/SUMMARY.md` — v6.0 delivery list

### Prior phase context (directly upstream)
- `.planning/phases/32-unified-situation-ambient-memory/32-CONTEXT.md` — the
  context-only invariant in `_is_empty_signals`, the Groq daily token ledger, the
  token-budget guard test (D-17's Layer-1 restraint is bounded by it), `training_reality`
  reconciliation, `get_recent_window()` usage
- `.planning/phases/31-standing-directives/31-CONTEXT.md` — Step-0 directive veto
  (D-02 #1, D-03, D-23 all depend on it), legacy-cron veto D-21/D-22, the reflection
  reaction-pairing loop that feeds D-02 #4
- `.planning/phases/30.5-brain-upgrade-sonnet-5/30.5-CONTEXT.md` — Sonnet-5 brain and
  prompt-cache breakpoint placement (constrains where new prompt blocks render)

### Project invariants
- `CLAUDE.md` §6 Invariants — the Cloud Tasks / never-a-BackgroundTask rule that D-32
  enforces; the D-10 OutreachLog gating rule that D-25 works around without violating
- `docs/DEPLOYMENT.md` — Cloud Scheduler job inventory (the `morning-briefing-tick`
  retirement in D-10 lands here), Secret Manager (`MORNING_TRIGGER_TOKEN`, D-13)
- `docs/healthkit_shortcut.md` — the existing iOS Shortcut documentation pattern; the
  Sleep-Focus-off Shortcut (D-31) should be documented the same way

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/autonomous.py::run_autonomous_tick` (line 1761) — the 3-layer orchestrator that
  gains the `occasion` parameter. Its docstring already documents the full 8-step
  pipeline; occasions bypass step 2 (the empty gate) and the Layer-0.5 change-detection
  gate (line ~1815) must also be bypassed for occasions — an occasion fires on a
  schedule/trigger, not on signal change.
- `core/autonomous.py::_compose_layer2` (line 1380) and `_compose_followup_layer2`
  (line 1469) — the Layer-2 entry points; D-21/D-22 tool-loop behavior lands here.
- `core/main.py::_run_smart_loop` (line 813) — Layer 2's actual loop.
  **`MAX_TOOL_ITERATIONS = 12` at line 50** is the D-21 guard. Exhaustion is handled at
  line 1034 and already returns `last_response_text` when the brain produced real text
  (Phase-24 double-send fix) — D-22 extends this to a deliberate tools-stripped final turn.
  ⚠️ **`core/self_manifest.py:590` still documents this cap as 8 — stale, fix to 12.**
- `core/nightly_review.py` — `nightly_target_date`, `was_sent` idempotency,
  `_ensure_reflection` (D-07), `_gather_tomorrow`, `_plain_text_fallback` (the SC-1
  infra-failure path) all survive; `_compose_nightly` (line 232) is replaced by the
  cascade call. State doc gains `status: sent | skipped_by_judgment`, both terminal for
  the backstop (D-04).
- `core/morning_briefing.py` — `_gather_data` (line 295), `_fetch_garmin_safe`,
  `_sync_bodyweight_from_garmin` survive. **`handle_tick` (line 58) — the entire
  `pending → sync_detected → sent` polling state machine, the 10:15 cutoff and the
  retry counter — is retired by D-09.** `_compose_briefing` (line 533) replaced by the
  cascade. `_plain_text_fallback` retained.
- `core/weekly_training_review.py::run_weekly_review` (line 548) — `_gather_week_data`
  and `_derive_structural_topics` survive; `_compose_review` (line 389) replaced.
  This surface has a 500-incident history (blocking work starving the send) — D-32's
  Cloud Tasks dispatch is the belt-and-braces fix on top of the existing
  `run_in_executor` repair.
- `interfaces/web_server.py::_verify_trigger_request` (line ~436) and
  `trigger_nightly` (line 539) — the exact template for `/trigger/morning` (D-08/D-13).
  Note `trigger_nightly` uses `BackgroundTasks` — **that is the D-32 defect**, not the
  pattern to copy.
- `core/task_dispatch.py` — the Cloud Tasks enqueue → `/internal/*` full-CPU pattern
  that D-32 applies to every occasion compose.
- `memory/firestore_db.py::OutreachLogStore` (line 2108) / `TickLogStore` (line 2537) —
  the two stores `get_recent_decisions` reads (D-26) and the natural home for the D-25
  action-audit record.
- `core/heartbeat.py` — hourly; gains the four D-28 anomaly checks.

### Established Patterns
- **D-10 invariant:** `OutreachLogStore.append` only after a successful send. D-25's
  action record deliberately sits *outside* this rule — it is not an outreach record.
- **Context-only gathers** (Phase 32 / MEM-05): any new gather must NOT be referenced in
  `_is_empty_signals`. Occasions bypass the gate entirely, which is orthogonal — do not
  weaken the gate to accommodate them.
- **Groq per-request budget:** the Phase 32 token-budget guard test asserts the maximal
  rendered triage prompt + `max_tokens` fits the verified ceiling (`reasoning_effort=low`,
  `TICK_BRAIN_MAX_TOKENS=1024`). D-17 keeps full message text out of Layer 1 for exactly
  this reason. **Never raise the guard target to mask prompt growth.**
- Firestore stores use `_jsonsafe_doc` ISO conversion (SERVER_TIMESTAMP →
  `DatetimeWithNanoseconds` breaks `json.dumps` in read tools — bit MealStore and
  TrainingLogStore). `get_recent_decisions` is a read tool: this applies.
- Every new env var must be added to `deploy.yml` — `--set-env-vars` clobbers
  out-of-band Cloud Run vars (`MORNING_TRIGGER_TOKEN`, `OCCASION_CASCADE`).
- Prompt-cache landmine (Phase 30.5): volatile blocks must sit **after** the stable
  cached prefix or cache reads silently die.
- Test env: full `pytest tests/` segfaults in one process (grpc/protobuf GC) — verify
  per-file. Python 3.13 venv locally, never 3.14. The ~1775-backend baseline must hold.

### Integration Points
- `core/autonomous.py` — `occasion` parameter threading through gather → triage →
  compose; occasion guidance selection; topic-key construction.
- `interfaces/web_server.py` — new `POST /trigger/morning`; both trigger routes and the
  `/cron/*` occasion routes repointed to Cloud Tasks dispatch (D-32).
- `core/tools.py` — new brain-direct `get_recent_decisions` tool + schema registration;
  the write-disclosure path (D-24) touches the calendar/task handlers.
- `interfaces/web_server.py::/api/today` — consumes `daily_note` / `daily_note_date`
  (line ~1306) and `structured`; D-05/D-06 change *when* these are written, not the
  contract shape. The Hub already renders `coach_note: null` cleanly.
- `core/heartbeat.py` — D-28 anomaly surfacing.
- Cloud Scheduler — `morning-briefing-tick` retired (D-10/D-31); no other job changes.
- Secret Manager — `MORNING_TRIGGER_TOKEN` (D-13).

</code_context>

<specifics>
## Specific Ideas

- The morning wake-up trigger was Amit's own counter-proposal, and it is strictly better
  than both options offered (tick-polls-Garmin, or keep the cron): *"we can do that via
  my phone's sleep alarm… my phone turns off sleep mode, that is, when my alarm in the
  morning goes off. I don't have an alarm that day and I just turn off sleep mode anyway
  when I wake up."* Push beats poll — no detection latency, no 06:00 floor, no polling
  cost. It also makes the two ends of the day architecturally symmetric: Sleep Focus on
  → nightly, Sleep Focus off → morning.
- On the missing backstop: *"If I forgot, then I just probably don't need the morning
  briefing because 99% of days I have that sleep focus in my routine."* Deliberate
  simplicity — do not add a fallback detector back in.
- On the tool budget: *"I don't want a specific budget. I want him to be able to think
  and look through stuff if he wants to, just be smart and sophisticated about it."*
  The existing `MAX_TOOL_ITERATIONS = 12` is a safety net, not a product constraint —
  do not introduce a tighter occasion-specific cap.
- On write powers: *"he should be able to read and write without my consent but just
  declare after writing if he does so."* Full agency, full transparency. The disclosure
  is the price of the agency — hence D-24 mandating an explicit action line even though
  the phase otherwise mandates no structure.
- On the 01:00 backstop: *"I won't see it if I'm asleep anyway, so it doesn't really
  matter."* The late hour is not a reason to raise the bar.
- The north star: Klaus should decide like a person who knows what he already said, what
  he already did, and what is actually worth interrupting for — and be able to account
  for all three when asked.

</specifics>

<deferred>
## Deferred Ideas

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

</deferred>

---

*Phase: 33-Occasion Cascade*
*Context gathered: 2026-07-28*
