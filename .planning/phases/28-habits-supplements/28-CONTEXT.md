# Phase 28: Habits & Supplements - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Native habit & supplement tracking inside the Klaus Hub — a Firestore `HabitStore`
that **replaces the separate habit-tracker app**. Delivers (HABIT-01..05 + TIME-06):

- **Definition:** habits and supplements with name, `type` (`habit`|`supplement`),
  optional dose, scheduled days (daily or specific weekdays), and a time-of-day slot,
  stored in `HabitStore`.
- **Check-off:** single-tap completion from the Today timeline or the Habits tab;
  supplements show a dose label at check-off (and the dose is editable — see D-09).
- **Streaks:** scheduled-days-only streak computation (non-scheduled days neutral),
  Asia/Jerusalem local time, DST-boundary tested.
- **History:** a per-habit contribution-style (GitHub-grid) history in the detail view.
- **Today timeline:** habits/supplements due today appear on the timeline (TIME-06)
  with one-tap check-off.
- **Klaus integration:** native tools to read today's pending check-offs + adherence;
  the autonomous tick's Layer-0 gather (`core/autonomous.py`) includes today's habit/
  supplement state so the tick-brain can judge adherence nudges.

**Key cross-domain decision (D-01):** the new HabitStore supplement check-offs become
the **source of truth** that the existing v4.0 supplement accountability reads —
`core/proactive_alerts.py::SLOT_SUPPLEMENTS` (and any coaching that consumes it) is
rewired to read **real check-off data** instead of inferring adherence from meal-slot
misses. This is the heart of the phase's value and changes existing v4.0 behavior.

**NOT in this phase:** Web Push / OS reminders (Phase 29), health-trend pages
(Phase 30), tasks (Phase 27, done). **Visual/pixel design** is handled separately by
`/gsd:ui-phase 28` (UI hint = yes) — this file captures product/behavior, not layout.

</domain>

<decisions>
## Implementation Decisions

### Supplement ↔ coaching link (HABIT-05, the cross-domain core)
- **D-01:** **Unified source of truth.** HabitStore supplement check-offs feed the
  existing v4.0 supplement accountability. `core/proactive_alerts.py::SLOT_SUPPLEMENTS`
  (currently inferred from meal-slot misses) is rewired to read real check-off state, so
  Klaus's nutrition coaching + the 21:30 alert can reflect "you logged creatine" or flag a
  genuine miss. Most aligned with the cross-domain coaching philosophy — but **must not
  double-nag** (see D-15 dedup).
- **D-02:** **Slot→fueling-slot mapping under the hood.** With manual seeding (D-03), the
  unified link keys off the supplement's simple **time slot** (D-07) mapping to the v4.0
  fueling slot (e.g., Bedtime→`pre-bed`, post-AM→`post-am-run`, post-lift→`pm-post-lift`).
  The hardcoded `SLOT_SUPPLEMENTS` dict is **superseded/fed by** HabitStore items at the
  matching slots. Exact mapping mechanics → research/Claude's discretion.
- **D-03:** **Manual seeding — no seed data.** Build the store + UI but pre-create nothing;
  Amit defines all habits and supplements himself in the hub. Mirrors the Phase-27 manual
  TickTick migration (27-CONTEXT D-08). No assumptions baked in from the blueprint's
  `supplement_schedule`.

### Schedule & data model (HABIT-01)
- **D-04:** **Two day-scheduling patterns only: daily OR specific weekdays** (e.g.,
  Mon/Wed/Fri). No every-N-days/interval cadence for habits — keeps streak math clean.
  (This is narrower than the Phase-27 task recurrence engine; do **not** reuse it wholesale.)
- **D-05:** **Simple named time-of-day slots: Morning / Noon / Evening / Bedtime.** Drives
  timeline ordering and maps to v4.0 fueling slots under the hood (D-02). NOT the raw 6
  fueling-slot vocabulary in the UI (too training-relative for generic habits).
- **D-06:** **One binary check-off per scheduled day.** Done/not-done for the day; an item
  lives in **one slot** for timeline placement. No multiple-slots-per-item, no
  times-per-day target. A genuinely multi-dose supplement (creatine AM+PM) would be modeled
  as separate items if ever needed.

### Check-off interaction (HABIT-02)
- **D-07:** **Tap toggles.** Single tap completes; **tap again un-checks** (habits are
  retained, so nothing is destroyed — no undo toast needed for the check-off itself, unlike
  Phase-27 tasks). Reversible by design.
- **D-08:** Check-off lives on **both** the Today timeline (TIME-06) and the Habits tab,
  same one-tap action.
- **D-09:** **Dose is editable at check-off.** Default dose shows as a label (e.g.,
  "Creatine 5g") but can be adjusted at check-off to capture **partial adherence** (took
  half). The completion-log entry records the **dose actually taken**, not just a boolean.

### Streak rules (HABIT-03 — core locked, these fill the gaps)
- **D-10:** **Pure reset.** Any unmarked missed **scheduled** day resets the streak to 0.
  **No skip/freeze/grace action, no auto-grace allowance.** Matches Amit's accountability
  coaching style. Non-scheduled days remain neutral (locked by HABIT-03).
- **D-11:** **Backfill the previous day only.** You can retroactively check off **yesterday**
  (took it but forgot to tap) and the streak is repaired; days older than yesterday are
  locked. Tight enough to prevent gaming, realistic for a forgotten late-night log.
- **D-12:** **Miss is confirmed at end of the next day** (a consequence of D-10 + D-11): a
  scheduled day D becomes a *hard* miss only once day D+1 ends without a backfill. Within the
  yesterday-backfill window the day is **pending-repair**, not yet a streak break. This same
  window is when Klaus can still nudge before it's a confirmed miss.
- **D-13:** **Contribution grid has four states:** `done` / `missed` / `not-scheduled` /
  `pending` (today + yesterday-still-repairable). Derived directly from D-10..D-12.

### History grid (HABIT-04)
- **D-14:** **Rolling ~year (≈365 days), per-habit detail only.** GitHub-style grid inside
  each habit's detail view. **No all-habits overview / no home-screen grid** — consistent
  with the milestone Out-of-Scope ("grid lives in the Habits tab detail, not home screen").
  Visual specifics → `/gsd:ui-phase 28`.

### Klaus adherence nudging (HABIT-05 — NEW proactive behavior)
- **D-15:** **Per-slot salience, all-pending, light-touch, deduped.** Channel is the existing
  autonomous tick (`*/20 7-21`), NOT a new cron. When a scheduled slot's window **passes**
  with the item still unchecked, that becomes a salient Layer-0 signal; the **free tick-brain
  judges** whether to actually nudge (not guaranteed). Any pending item can qualify (habits
  too, not just supplements). Tone = Klaus's normal warm-but-brief voice. **Reuse
  `CoachingTopicStore` cross-cron dedup** so a supplement is never flagged by BOTH the habit
  nudge AND the 21:30 `SLOT_SUPPLEMENTS` alert.
- **D-16:** **Pass current streak into the gather** so a long streak at risk weighs heavier
  in the tick-brain's salience judgment (protect momentum over nagging routine items).
- **D-17:** **One nudge per item per day, max** — repeat-suppression (CoachingTopicStore /
  OutreachLog topic_key per item-per-day) so the 20-minute tick doesn't re-fire the same
  slot-miss every cycle.
- **D-18:** **Tick-window caveat (accepted):** the autonomous tick runs 7-21, so
  **Bedtime/`pre-bed`-slot misses fall outside its window** and get no per-slot habit nudge
  at night. That's fine — the existing **21:30 fueling-supplement alert** already covers the
  pre-bed window, so the two complement cleanly. This deliberately **diverges from Phase-27
  tasks** (27-CONTEXT D-17 chose NO new proactive nudging); habits intentionally add it.

### Definition lifecycle (edit / delete)
- **D-19:** **Forward-only schedule edits.** Changing a habit's scheduled days/slot applies
  **from the change date forward**; past grid/streak stay as computed under the schedule that
  was active then (**schedule is effective-dated** — a past miss stays a miss). No
  retroactive rewrite of history. Renames are free (don't affect history).
- **D-20:** **Hard delete + undo toast.** Deleting a habit/supplement removes the definition
  **and its history**; a brief undo toast is the only safety net. Consistent with Amit's
  Phase-27 "don't retain what I don't review" stance (27-CONTEXT D-13/D-14). No archive.

### Habit vs supplement treatment
- **D-21:** **`supplement` is just a `type` tag + dose.** Identical streak, check-off, grid,
  and nudge behavior to a habit. The only real differences are the **dose label/field** (D-09)
  and the **unified coaching link** (D-01). Any visual grouping in the Habits tab →
  `/gsd:ui-phase 28`. No separate "supplements get stern framing" path (would reopen D-15's
  light-touch decision).

### Claude's Discretion
- `HabitStore` document/collection shape + the daily completion-log structure (must record
  dose-taken per D-09; `_jsonsafe_doc` ISO-conversion for `DatetimeWithNanoseconds`).
- Exact effective-dated-schedule representation for D-19 (e.g., a list of dated schedule
  revisions vs a per-day snapshot) — choose the simplest robust option.
- Slot→fueling-slot mapping table mechanics (D-02) and how `SLOT_SUPPLEMENTS` is fed/
  superseded by HabitStore (D-01).
- DST-boundary streak handling + the test fixtures proving it (HABIT-03 mandate).
- Streak computation algorithm + the four-state grid derivation (D-13).
- Undo-toast duration / soft-delete-then-hard-delete mechanics for D-20 (mirror Phase-27).
- react-query + optimistic-update + zustand wiring for check-offs (mirror Phase 26/27).
- Repeat-suppression `topic_key` shape for D-17.
- All visual/layout/animation specifics → `/gsd:ui-phase 28`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements (locked source of truth — with this session's decisions)
- `docs/superpowers/specs/2026-06-13-klaus-hub-design.md` — v5.0 design spec: § Architecture
  (`HabitStore` definition + daily completion log + streak computation; Klaus tool additions;
  autonomous Layer-0 habit/supplement extension), § Layout (Habits tab; glance-rail streaks),
  § Build phases (Phase 3 = Habits/supplements), § Verification. Where it conflicts with the
  decisions above, **the decisions here win.**
- `.planning/REQUIREMENTS.md` — HABIT-01..05 + TIME-06 + Out-of-Scope table (no habit grid on
  home screen, supplements are check-offs with a dose field and no inventory).
- `.planning/ROADMAP.md` § Phase 28 — goal + 5 success criteria.

### v4.0 supplement-accountability integration (the unified link — D-01/D-02)
- `core/proactive_alerts.py` — `SLOT_SUPPLEMENTS` (≈ line 90: D3+K2/Omega-3 on `post-am-run`,
  Creatine on `pm-post-lift`, Mg-Glycinate/Zinc/Copper `pre-bed`) + the 21:30 alert flow;
  this is what gets rewired to read HabitStore check-offs and deduped against the habit nudge.
- `memory/firestore_db.py` — `UserProfileStore.supplement_schedule` (≈ lines 184, 210:
  `[{slot, items}]`) — the v4.0 blueprint supplement model; reference for the slot vocabulary,
  NOT seeded (D-03). Add `HabitStore` here following existing store-class + `_jsonsafe_doc`.
- `core/autonomous.py` — Layer-0 gather; extend with today's pending habit/supplement state +
  current streak (D-15/D-16). Mirror the Phase-27 `ticktick_overdue`→TaskStore repoint pattern
  (27-CONTEXT D-17) for how a new situation key threads through triage/compose.
- `CoachingTopicStore` (in `memory/firestore_db.py`, added v4.0) — cross-cron dedup reused for
  the habit-nudge / 21:30-alert dedup (D-15) and repeat-suppression (D-17).

### Prior-phase context (patterns to follow)
- `.planning/phases/27-tasks/27-CONTEXT.md` — Phase 27 task decisions: Firestore store +
  `/api/*` CRUD + `_jsonsafe_doc`, react-query + optimistic + zustand, undo-toast mechanics
  (D-13/D-14), Today-timeline band + glance-rail surfacing, native-tool + autonomous-gather
  repoint pattern, Asia/Jerusalem date logic. **Habits deliberately diverge on nudging** (P27
  D-17 = none; P28 D-15 = per-slot nudges).
- `.planning/phases/26-hub-shell/26-CONTEXT.md` — Hub Shell decisions: `/api/*` session auth,
  Cloud Tasks full-CPU path, single-worker, timeline/glance-rail structure, optimistic+
  react-query patterns.

### Backend integration points
- `memory/firestore_db.py` — add `HabitStore` (definitions + daily completion log) following
  existing store classes; `_jsonsafe_doc` for all reads.
- `interfaces/web_server.py` — FastAPI `/api/*` routes + `require_hub_session`; add habit CRUD
  + check-off endpoints without touching existing OIDC `/cron|/internal|/trigger` routes
  (HUB-04 invariant).
- `core/tools.py` — `_HANDLERS` dispatch + tool-schema convention; add native habit/adherence
  read tools (HABIT-05) the same way task tools register.
- `core/autonomous.py` — Layer-0 gather extension (D-15/D-16/D-17) + situation key through
  triage/compose.
- `core/proactive_alerts.py` — rewire `SLOT_SUPPLEMENTS` to consume HabitStore (D-01/D-02),
  deduped (D-15).

### Frontend integration points
- `frontend/src/App.tsx` — `/habits` route (currently a `ComingSoon` placeholder).
- `frontend/src/components/layout/{Sidebar,BottomTabs,GlanceRail}.tsx` — Habits nav already
  referenced; glance rail gains a streaks summary (design spec § Layout).
- `frontend/src/components/timeline/TimelineDay.tsx` — TIME-06 surfacing (habits/supplements
  due today with one-tap check-off); reference the Phase-27 "Due today" band pattern.
- `frontend/src/api/*`, `frontend/src/hooks/*` (`useToday`, `api/client.ts` `apiFetch`) —
  react-query + optimistic-update pattern for check-off hooks.

### Project invariants
- `CLAUDE.md` § 6 Invariants — single uvicorn worker, agent/tick turns inside tracked requests,
  lowercase `klaus-` naming, `load_dotenv(override=True)`, JSON-safe Firestore reads, autonomous
  tick cost-gating (Layer 0 → tick-brain free → brain only on affirmative), HealthKit/Lifesum
  slot-time caveat (irrelevant to habits but note the slot-time discipline).
- `.planning/STATE.md` § Notes — Asia/Jerusalem time; Python 3.11/3.13 (NEVER 3.14); 1153+ test
  baseline must hold; run pytest per-file (full-suite segfault).
- **Frontend gotchas (from memory):** inline `display` in `style={{}}` overrides Tailwind
  `md:hidden`/`hidden md:block` (leaks phone-only UI to desktop — bit Phase-27 UAT 4×); iOS
  bottom-sheet z-index/keyboard/blur-before-click traps. Re-apply for any Phase-28 phone UI
  (→ `/gsd:ui-phase 28`).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `memory/firestore_db.py` store classes + `_jsonsafe_doc` — model `HabitStore` directly on
  these (definitions collection + daily completion-log subcollection/docs).
- `CoachingTopicStore` (v4.0) — ready-made cross-cron dedup + topic_key repeat-suppression for
  the new habit nudges (D-15/D-17).
- Phase 27 `/api/*` CRUD + `require_hub_session` + react-query/optimistic/zustand + undo-toast +
  Today-timeline band + glance-rail count — the habit feature mirrors this almost 1:1 (minus
  recurrence; plus streaks/grid).
- `core/tools.py` `_HANDLERS` dispatch + tool-schema convention — habit read tools register the
  same way.
- `core/autonomous.py` Layer-0 gather + situation-key threading — the Phase-27 `ticktick_overdue`
  repoint is the template for adding a `habit_adherence` situation.

### Established Patterns
- Firestore `SERVER_TIMESTAMP` → `DatetimeWithNanoseconds`; ISO-convert before `json.dumps`
  in every `/api/*` response (`_jsonsafe_doc`).
- `/api/*` = session-cookie auth (P26); `/cron|/internal|/trigger` = OIDC — new routes must not
  weaken existing OIDC routes (HUB-04).
- Autonomous tick cost-gating: Layer 0 (gather, $0) → Layer 1 (tick-brain Groq, free) → Layer 2
  (brain, costs money). Habit nudges run inside this existing gated pipeline (D-15).
- All date/streak logic in **Asia/Jerusalem** local time; DST-boundary tests mandatory (HABIT-03).

### Integration Points
- New `HabitStore` in `memory/firestore_db.py`.
- New habit CRUD + check-off endpoints under `/api/*` in `interfaces/web_server.py`.
- Native habit/adherence read tools in `core/tools.py`.
- Layer-0 gather extension + situation key in `core/autonomous.py`.
- `SLOT_SUPPLEMENTS` rewire + dedup in `core/proactive_alerts.py`.
- `/habits` route in `frontend/src/App.tsx` (ComingSoon → real Habits page); Today timeline +
  glance rail gain habit surfacing (TIME-06 + streaks).

</code_context>

<specifics>
## Specific Ideas

- The **unified supplement source of truth** (D-01) is the feature Amit cares most about: he
  wants Klaus's real coaching/accountability to be powered by actual check-offs, not inferred
  from meal-slot misses. This is the cross-domain coaching philosophy made concrete.
- He chose **strict streaks** (pure reset, no grace — D-10) consistent with his accountability
  coaching style, but wanted a **realistic forgot-to-tap valve** → yesterday-only backfill
  (D-11), not anti-honesty "no backfill."
- **Dose editable at check-off** (D-09) — he explicitly wanted to capture partial adherence
  (took half), so the completion log stores the dose actually taken.
- Habits **deliberately get proactive nudging** (D-15) even though tasks explicitly did not
  (27-CONTEXT D-17) — adherence is worth a gentle prompt; tasks weren't.
- **Don't retain what I don't review** carries over from Phase 27: hard delete (D-20), no
  archive, no all-habits overview grid (D-14).

</specifics>

<deferred>
## Deferred Ideas

- **Every-N-days / interval habit scheduling** — not needed; daily + specific weekdays only
  (D-04). Revisit if a real interval habit appears.
- **Multiple slots per item / times-per-day targets** (creatine AM+PM as one item; "water 3×")
  — rejected for one-binary-check-off-per-day (D-06); model as separate items if ever needed.
- **Skip/freeze/vacation mode + auto-grace streak allowance** — rejected in favor of pure reset
  (D-10).
- **Backfill older than yesterday / arbitrary history editing** — rejected (D-11).
- **All-habits overview heatmap** — rejected; per-habit grid only (D-14).
- **Archive / habit history retention after delete** — rejected; hard delete (D-20).
- **Stern supplement-specific accountability framing in nudges** — rejected for uniform
  light-touch (D-21/D-15); the firmer v4.0 framing stays in the existing 21:30 alert.
- **Web Push delivery of these nudges when the app is closed** — Phase 29 (PUSH); Phase 28
  nudges ride the existing Telegram/autonomous-tick delivery.

### None — discussion stayed within phase scope
No scope-creep items arose; all deferrals above are explicit narrowings of in-phase options.

</deferred>

---

*Phase: 28-Habits & Supplements*
*Context gathered: 2026-06-26*
