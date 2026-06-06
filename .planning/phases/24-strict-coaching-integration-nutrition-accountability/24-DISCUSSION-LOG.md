# Phase 24: Strict Coaching Integration + Nutrition Accountability - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-06
**Phase:** 24-strict-coaching-integration-nutrition-accountability
**Areas discussed:** Cross-cron dedup gate, Strict pushback & recovery conflict, Nutrition & supplement accountability, Session-quality + progress surfacing

---

## Folded TODOs (cross_reference_todos)

| Todo | Decision |
|------|----------|
| `coaching-query-iteration-cap-double-send` (data-heavy coaching trips tool cap → double-send) | ✓ Folded |
| `phase-22-code-review-advisory` (WR-02 read_coaching_guide wrong-section) | ✓ Folded (WR-02 only; WR-03/IN-* reviewed, not folded) |

---

## Cross-cron dedup gate

| Question | Options | Selected |
|----------|---------|----------|
| Topic granularity | Category+subject ✓ / Coarse category / Fully specific | Category+subject |
| Already-raised behavior | Hard-suppress + escalate on new state ✓ / Always hard-suppress / Light reference | Hard-suppress + escalate-once on worsened state |
| Reactive chat scope | Proactive crons only ✓ / Also gate chat | Proactive crons only |
| Reset/clear | Daily + condition-clear ✓ / Daily only | Daily reset + condition-driven clear |

**User's choice:** All recommended options.
**Notes:** Dedup gate is proactive-cron-only; reactive chat always answers and doesn't burn topics. Reuse OutreachLog per-day topic_key pattern.

---

## Strict pushback & recovery conflict

| Question | Options | Selected |
|----------|---------|----------|
| Consequence concreteness vs Phase 25 boundary | Directional blueprint-anchored ✓ / Deficit only / Dated projection now | Directional, no dated projection |
| Behavior on repeated misses | Escalate tone/stakes ✓ / Consistent firmness | Escalate on repeats |
| Recovery conflict — ever no rec? | Always one ranked rec ✓ / Menu when ambiguous | Always exactly one ranked rec |
| Trigger surface | 21:30 primary + morning recap ✓ / 21:30 only / You decide | 21:30 primary + morning recap + reactive always |

**User's choice:** All recommended options.
**Notes:** Dated pace-to-deadline projection explicitly reserved for Phase 25 (PROG-02).

---

## Nutrition & supplement accountability

| Question | Options | Selected |
|----------|---------|----------|
| Macro-adherence trigger | Meaningful-gap threshold ✓ / Trailing pattern / Always show number | Meaningful-gap threshold |
| Fueling-slot mapping & scope | Training-anchored, key slots ✓ / All 6 / Fixed clock | Training-anchored, flag key structural slots (#2/#5/#6) |
| Supplement surfacing | Rider on meal-slot ✓ / Independent reminders / Defer | Rider on carrier slot; pre-bed standalone |
| Structural-critique escalation | Pattern-triggered, distinct ✓ / Always pair | Pattern-triggered, kept distinct from daily flags |

**User's choice:** All recommended options.
**Notes:** Stays clear of out-of-scope daily macro micro-optimization; structural target critique (COACH-07 overlap) is rare and dedup-gated.

---

## Session-quality + progress surfacing

| Question | Options | Selected |
|----------|---------|----------|
| Capture mechanism | Structured 3-button keyboard / Infer from RPE+notes ✓(user override) / Free-text | **Derive from existing signals (Garmin + RPE + notes)** |
| Scale/vocabulary | Strong/Solid/Grind / 5-point / You decide | Free-text: *"you already have the rpe and how I felt from the garmin data or strava data..."* |
| Silent-sync coverage | Quality on interactive, null otherwise ✓ / Always prompt post-hoc | Interactive + Garmin-derived (broader coverage); null where no signal |
| Weekly review vs Phase 25 boundary | Within-block status + trend ✓ / Light deadline framing | Within-block status + quality trend, no deadline projection |

**User's choice:** Diverged from the recommended "new keyboard" on Q1 — chose to **derive** quality from existing signals (no new tap). Then requested research on Garmin vs Strava.

**Notes / Research (user-requested):** Investigated Strava MCP + Strava/Garmin APIs for the "how it felt" signal. Findings: Strava's official MCP is read-only, subscription-gated, end-user-chat-only (not usable server-side by a Cloud Run cron); the Strava REST API doesn't reliably expose `perceived_exertion`; Strava tightened third-party API access. Garmin already captures per-activity Feel (5-pt) + Perceived Effort (0–10) and is already integrated. **Decision locked: Garmin + RPE + notes, no Strava** (D-14/D-19). A small in-phase research/ingest sub-task confirms/surfaces the Garmin self-eval fields (likely `directWorkoutFeel`/`directWorkoutRpe`).

---

## Claude's Discretion

- Exact macro-shortfall thresholds and "structurally meaningful" operationalization (D-09).
- Slot-window widths around AM-run/PM-lift anchors and anchor-time resolution (D-10).
- Dedup gate storage (reuse OutreachLogStore vs thin coaching-topic store) and topic-key enum (D-01/D-04).
- Session-quality derivation heuristic from RPE + Garmin Feel/Perceived-Effort + notes and its stored field shape (D-13).
- Prompt wording for strict pushback / recovery single-rec / structural critique / integrated morning-briefing framing.

## Deferred Ideas

- Pace-to-deadline trend projection + per-facet trajectory / "on track / N behind" framing → Phase 25 (PROG-02).
- Strava integration → rejected this phase; revisit only if Strava opens server-side feel-data access.
- 3k / 400m maximal-sprint benchmarks near November deadline (carried from Phase 23).
- WR-03 + IN-01/02/03 from the Phase 22 code-review todo — reviewed, not folded (advisory/cosmetic).
