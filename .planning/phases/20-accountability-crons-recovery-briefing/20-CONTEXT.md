# Phase 20: Accountability Crons & Recovery Briefing - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Klaus moves from passively *answering* training questions to actively *tracking adherence* and *surfacing recovery concerns*. This phase delivers:

- **`TrainingLogStore`** — per-session training log (Garmin + manual reconciled into one record per session).
- **Evidence-first training check-in** — runs inside the existing 21:30 `proactive-alerts` cron (see D-09, a deliberate deviation from CHECKIN-01/06). Silent-syncs Garmin RPE; prompts via inline keyboard only for planned workouts left unlogged.
- **Weekly training review cron** — Sunday 10:00, brain-composed.
- **`recovery_concern` flag** — reshapes morning briefing + evening proactive-alert tone when ACWR/HRV/sleep + today's planned intensity indicate overreach.
- **Cloud Scheduler bootstrap** — for the (now single) new scheduler job.

**In scope:** the four crons/stores above + the net-new Telegram inline-keyboard / callback-query infrastructure they require + `RECOVERY_THRESHOLDS` v0 heuristics + DEPLOYMENT.md updates.

**Out of scope (v3.0 discipline + deferred):** personalized numeric targets (HR zones, lift weights, pace goals); per-set strength tracking; a persistent `MealAuditStore`; the recurring "daily review" skill (deferred — see Deferred Ideas); historical backfill.

</domain>

<decisions>
## Implementation Decisions

### Planned-workout detection
- **D-01:** Planned workouts come from a **dedicated Google calendar named "Training"**, located by **name lookup** against the user's calendar list (not a hardcoded calendar ID, not the primary calendar). The calendar tool currently hardcodes `calendarId="primary"` everywhere (`mcp_tools/calendar_tool.py`) — this phase adds a training-calendar read path. Make the matched name configurable (default `"Training"`) so it's not magic-stringed.
- **D-02:** The calendar **is** the filter — but buffer blocks also live on it. An event is a planned workout **unless** its title starts with `"Get Ready:"` (the user's confirmed buffer naming, e.g. `"Get Ready: Gym"`) — also filter a `"Travel:"` prefix defensively. All remaining events are trackable workouts.
- **D-03:** **Five Fingers practice (Wed/Sun) IS tracked** as a workout — attendance + a subjective RPE even though it carries no Garmin activity. (It flows through the "watch off → ask RPE" branch, D-08.)
- **D-04:** The Training calendar is **created but empty** at discussion time. Check-ins stay silent until it's populated — forward-only, consistent with v0 plumbing discipline. No backfill.

### Training check-in flow (folded into proactive-alerts)
- **D-05:** **Notes step is "open until you reply"** — RPE is logged immediately on button tap; the notes prompt then sits with no auto-finalize timer. The note attaches **deterministically when the user replies-to the prompt message** (native Telegram reply). If the user does **not** reply-to but sends a free-text message while a note is pending, the **brain decides from injected pending-note context** whether that message is the note. `/skip` (or tapping a skip control) dismisses the notes step. RPE-only entries (no notes) are valid.
- **D-06:** **One `training_log` entry per session, keyed by the specific session** (calendar event id / start time), so two same-day trackable sessions (e.g. morning run + evening gym) never collide. (Refines LOG-01's `{date}_{slot}` → slot = per-session key.)
- **D-07:** **Time-gating:** at 21:30 the check-in only prompts about planned workouts **whose scheduled start has already passed**. A 22:00 session is not questioned (picked up a later cycle / next day).
- **D-08:** **Watch-off branch:** when Garmin has no record of a planned workout, prompt "skipped or watch off?". Choosing **"did it, watch was off" → then ask RPE 1–10** so watch-off and Five Fingers sessions still carry a subjective load value.
- **D-08b:** **"Skipped" branch → quick reason buttons** (Rest/recovery · Sick/injured · Too busy · Other→free text). One tap, structured enough to surface in the weekly review.

### Check-in ↔ Garmin matching & dedup
- **D-09 (DEVIATION — requirements reconciliation needed):** The separate **21:00 `/cron/training-checkin` endpoint and `klaus-training-checkin` scheduler job are REPLACED** by running the check-in logic **inside the existing 21:30 `proactive-alerts` cron**. Consequences for the planner to reconcile in REQUIREMENTS.md:
    - **CHECKIN-01** — no new `/cron/training-checkin` endpoint; logic folds into the `proactive-alerts` handler (likely a new `core/training_checkin.py` module invoked from `core/proactive_alerts.py`).
    - **CHECKIN-06** — `0 21` time is moot; runs at 21:30 within proactive-alerts.
    - **CRON-01** — `bootstrap_shifu_crons.sh` creates **only** `klaus-weekly-training-review` (not `klaus-training-checkin`).
    - Still holds: CHECKIN-02 (silent Garmin sync), CHECKIN-03 (branch logic), CHECKIN-04 (inline keyboard + notes), CHECKIN-05 (fully silent when all covered). The check-in still emits its **own** inline-keyboard prompt message(s); folding is about the *cron trigger*, not merging into one text body.
- **D-10:** **A Garmin activity "covers" a planned Training event** when its start falls **within the event window (± a buffer)** AND its **type loosely matches** (run↔Running, strength↔Gym, etc.). Prevents a stray walk from masking a skipped lift. "Garmin RPE present" = `perceived_exertion` (from `directWorkoutRpe`) is non-null (`mcp_tools/garmin_tool.py:332`).
- **D-11:** **Garmin-vs-manual merge = one entry per session; Garmin owns objective fields** (training_load, feel, RPE when present), the manual reply **fills gaps** (notes; RPE if Garmin lacks it). Garmin wins on direct conflict. `source` reflects the contributing path(s) per LOG-01.

### Recovery concern (morning + evening)
- **D-12:** **Severity levels (mild / strong)**, not a bare boolean. `RECOVERY_THRESHOLDS` (RECOVERY-02) carries the level cutoffs as v0 heuristics with a docstring noting they're to be tuned after ~2 weeks of journaled data.
- **D-13:** **Tone shift + general (non-fabricated) prescription.** Klaus may name a *qualitative, metric-anchored* modification ("ACWR's at 1.6 and HRV's low — drop a set or two, keep it submaximal"). With the profile empty he **must NOT invent personalized numeric targets** (specific weights, HR zones, paces) — consistent with `smart_agent.md` PROMPT-02 ("empty profile → don't invent goals"). This is a richer coaching posture than strict v0 "tone-only," chosen deliberately by the user with the no-fabricated-numbers guardrail.
- **D-14:** **Workout intensity classified by event-title keyword** on the Training-calendar event (e.g. "heavy", "long run", "intervals", plus type defaults). Unknown/unkeyed → treat as moderate. v0 heuristic, tunable.
- **D-15:** **Consecutive-low-sleep rule:** 2 consecutive nights with Garmin **sleep score < 70** + an intense session today. (Plus the other RECOVERY-02 rules: ACWR > 1.5 + high-intensity; HRV unbalanced/low + low sleep + heavy lifting.)
- **D-16:** **Surfaced in BOTH morning briefing and evening proactive-alert, equally** (full recovery framing in each). Wires `recovery_concern` into `prompts/morning_briefing.md` and `prompts/proactive_alert.md` per RECOVERY-03.

### Weekly training review (Sunday 10:00)
- **D-17:** **Brain-composed** (`gemini-3.5-flash`) — once-weekly, trivial cost; matches the daily-reflection cron's use of the brain. (Not the free tick-brain.)
- **D-18:** **Format = emoji/bullet scorecard** (per-workout lines: ✅ done / ❌ skipped / ⚠️ no-log + RPE) — renders natively on mobile, avoids monospace-table alignment breakage.
- **D-19:** **Depth = richer narrative on top of the scorecard** — a few paragraphs of reflective coaching analysis, not just a terse card.
- **D-20:** **"One suggestion" grounded in this week's actual data, JARVIS voice** — direct and specific from gaps/load/recovery; no invented personal targets.
- **D-21:** **Nutrition source = raw `MealStore` 7-day totals** (calories/protein/carbs/fiber). `meal_audits` are **not persisted** (only the `meal_audit.md` prompt exists at runtime in `core/autonomous.py` + `core/morning_briefing.py`) — so REVIEW-02's "meal_audits" source resolves to live MealStore aggregates; the brain generates fresh critique at review time using `meal_audit.md` guidance. **No `MealAuditStore` built** (deferred). Planner to reconcile REVIEW-02 wording.
- **D-22:** **Trend window = week-over-week** — pull ~14 days; show this week's HRV/RHR/sleep values with arrows vs last week.
- **D-23:** **Week boundary = previous Sun–Sat calendar week** (last Sun 00:00 → Sat 23:59), aligned to the Israeli workweek; DST handled by the Cloud Scheduler tz string.
- **D-24:** **Empty-log behavior = always send** every Sunday, with a "quiet week / not enough data yet" note when sparse (reinforces the ritual). NOTE: this differs from the morning-recap silent-omit pattern — intentional for the weekly review.

### Operations
- **D-25:** **`bootstrap_shifu_crons.sh` is re-runnable** (describe-or-create / update existing), matching DEPLOYMENT.md operator-runbook discipline. Creates only `klaus-weekly-training-review` (per D-09). Uses the existing `CLOUD_SCHEDULER_SA_EMAIL` OIDC SA (CRON-01).
- **D-26:** **RPE inline keyboard = two rows of 5** (1–5 / 6–10) with the scale anchored in the prompt text ("1 = easy · 10 = max effort").

### Claude's Discretion
Per [[feedback_trust_code]], these were left to implementation judgment:
- Where callback/pending-prompt state is persisted (Firestore collection shape, TTL) and how the webhook router is extended to dispatch `callback_query` (today `interfaces/_router.py:65` drops any update with no `.message`).
- How `send_and_inject` (`core/scheduled_message.py`) is extended to accept `reply_markup` for inline keyboards.
- Module layout (`core/training_checkin.py` vs inline in `proactive_alerts.py`; `TrainingLogStore` placement in `memory/firestore_db.py`).
- Exact buffer-window minutes for D-10 time-overlap matching and the type-synonym map.
- Logging/structured-log style (follow existing conventions).
- TDD RED→GREEN commit discipline per project convention.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap (RECONCILIATION REQUIRED)
- `.planning/REQUIREMENTS.md` § "Phase 20" — LOG-01..04, CHECKIN-01..06, REVIEW-01..04, RECOVERY-01..03, CRON-01..02. **D-09 deviates from CHECKIN-01/06 and CRON-01; D-21 deviates from REVIEW-02. The planner MUST reconcile these requirement texts (and the traceability table) to match the decisions here.**
- `.planning/ROADMAP.md` § "Phase 20" — goal + 5 success criteria. SC #5 references two new jobs; D-09 reduces this to one (`klaus-weekly-training-review`) — reconcile.

### Existing crons & route shape to mirror
- `interfaces/web_server.py:232` — `_verify_cron_request` (OIDC) — reuse for the weekly-review endpoint.
- `interfaces/web_server.py:273` — `_log_cron_run` — call on success + exception of the new cron.
- `interfaces/web_server.py:398` — `@app.post("/cron/autonomous-tick")` — OIDC route shape to mirror for `/cron/weekly-training-review` (REVIEW-01).
- `interfaces/web_server.py:350` — `@app.post("/cron/proactive-alerts")` — **the cron the training check-in folds into (D-09).**
- `core/proactive_alerts.py` — 21:30 handler; the check-in logic hooks in here.

### Telegram inline-keyboard infrastructure (NET-NEW — does not exist yet)
- `interfaces/_router.py:51-66` — `handle_update`; **line 65 `if update.message is None: return` silently drops `callback_query` updates today.** Must extend to dispatch button presses + reply-to detection for the notes step (D-05).
- `core/scheduled_message.py:22` — `send_and_inject`; no `reply_markup` support today — extend for inline keyboards.
- CHECKIN-04 references "the five-fingers attendance pattern" — **no such inline-keyboard pattern exists in the codebase** (verified via grep). Treat the keyboard/callback flow as net-new.

### Training data & recovery inputs
- `mcp_tools/garmin_tool.py:286` — `fetch_garmin_activities(days)`; `:332` `perceived_exertion` ← `directWorkoutRpe` (D-10 "RPE present" test).
- `mcp_tools/garmin_tool.py:339` `compute_acwr`, `:396` `compute_acwr_from_db` — ACWR input for `recovery_concern`.
- `core/morning_briefing.py` — `_gather_data()` is where `recovery_concern` is computed (RECOVERY-01) and `data["nutrition"]` aggregation lives; `MealStore` 7-day totals for the weekly review (D-21).
- `memory/firestore_db.py` — `MealStore` (raw nutrition source, D-21); `TrainingLogStore` to be added here.
- `mcp_tools/calendar_tool.py:71,108` — `list_events` (hardcoded `calendarId="primary"`); training-calendar read path added here (D-01).

### Prompts to add/extend
- `prompts/morning_briefing.md`, `prompts/proactive_alert.md` — read `recovery_concern` (D-16, RECOVERY-03).
- `prompts/weekly_training_review.md` — **new** (REVIEW-03, D-17..D-22).
- `prompts/meal_audit.md` — reused at weekly-review time for nutrition critique (D-21); no change.

### Patterns & discipline
- `docs/DEPLOYMENT.md` §19 "Cloud Scheduler Full Job Inventory" — add the new job (CRON-02); §"Phase Shifu" section.
- `docs/USER.md` §2 Hardcoded Routines (Five Fingers Wed/Sun; Friday long run), §4 Pre-Workout Logic (Get Ready / Travel buffer naming) — basis for D-01..D-03.
- `.planning/phases/19.1-healthkit-nutrition-bridge/19.1-CONTEXT.md` — prior phase's cron/auth/MealStore decisions; sibling discipline.
- `CLAUDE.md` — invariants (lowercase `klaus-` names; `load_dotenv(override=True)`; `OutreachLogStore.append` gated on send success; `_get_orchestrator` singleton).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`_verify_cron_request` / `_log_cron_run` (`interfaces/web_server.py`)** — drop-in for the new weekly-review cron.
- **`core/proactive_alerts.py` (21:30 handler)** — host for the folded training check-in (D-09).
- **`compute_acwr_from_db` / `fetch_garmin_activities` (`mcp_tools/garmin_tool.py`)** — recovery + matching inputs; activities already expose `perceived_exertion`, `feel`, `training_load`.
- **`MealStore` (`memory/firestore_db.py`)** — 7-day nutrition totals feed the weekly review (D-21); no new store needed.
- **`core/morning_briefing.py::_gather_data`** — natural home for `recovery_concern` computation (RECOVERY-01).
- **`send_and_inject` (`core/scheduled_message.py`)** — extend (not replace) for `reply_markup`.

### Established Patterns
- **`/cron/*` OIDC route shape** — verify → lazy-import handler → call → `_log_cron_run(ok)` on both paths → re-raise. Mirror for `/cron/weekly-training-review`.
- **Silent-omit discipline** — morning recap omits when no data; the weekly review **intentionally departs** from this (D-24, always-send).
- **v3.0 plumbing-only** — `RECOVERY_THRESHOLDS` ships as documented v0 heuristics, not personalized targets.

### Integration Points (net-new vs. extend)
- **NET-NEW:** `callback_query` dispatch in `interfaces/_router.py`; pending-prompt/note state store; `core/training_checkin.py`; `TrainingLogStore`; `prompts/weekly_training_review.md`; `/cron/weekly-training-review` route; `scripts/bootstrap_shifu_crons.sh`; training-calendar read in `calendar_tool.py`.
- **EXTEND:** `core/proactive_alerts.py` (fold check-in); `core/morning_briefing.py` (recovery flag); `prompts/morning_briefing.md` + `prompts/proactive_alert.md`; `send_and_inject`; `core/heartbeat.py` (staleness key for the new cron, mirroring 19.1's `healthkit-sync`); `docs/DEPLOYMENT.md`; `docs/SELF.md` via `core/self_manifest.py` (new tools `log_training`, `get_training_history`).

</code_context>

<specifics>
## Specific Ideas
- Calendar name is literally **"Training"**; buffer events titled **"Get Ready: \<workout\>"**.
- Recovery prescription voice: metric-anchored and direct but suggesting, e.g. *"ACWR's at 1.6 and HRV's low — might be worth dialing today's session back."* No commands, no invented numbers.
- Weekly review reads like coaching reflection (richer narrative) wrapped around a scannable ✅/❌/⚠️ scorecard.
- Sleep "low" anchor: Garmin sleep score < 70 (chosen more sensitive than typical 60).

</specifics>

<deferred>
## Deferred Ideas
- **Recurring "daily review" skill** (morning-briefing-style) — will OWN check-in persistence / re-surfacing of unanswered prompts. Phase 20 ships ask-once only (no carry-over). **Future phase.**
- **`MealAuditStore`** — persisting per-meal critiques for historical nutrition review. Phase 20 uses live `MealStore` totals instead. Revisit if nutrition history reporting matters.
- **Personalized recovery/intensity thresholds** — `RECOVERY_THRESHOLDS` tuned from 2+ weeks of journaled `training_log` + biometrics data, in a later session via `UserProfileStore`.
- **Personalized prescriptions** (specific weights/HR zones/paces in recovery advice) — unlocked once the profile is populated.
- **Apple Watch / HealthKit workout source** — workouts stay on Garmin (Phase 19 invariant).

### Reviewed Todos (not folded)
None — no pending todos matched this phase's scope at discussion time.

</deferred>

---

*Phase: 20-accountability-crons-recovery-briefing*
*Context gathered: 2026-05-31*
