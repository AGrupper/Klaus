# Phase 28: Habits & Supplements - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-26
**Phase:** 28-Habits & Supplements
**Areas discussed:** Supplement↔coaching link, Schedule & check-off mechanics, Streak rules, Klaus adherence nudging, Definition edit/delete lifecycle, History-grid scope, Habit vs supplement treatment

---

## Supplement ↔ coaching link

| Option | Description | Selected |
|--------|-------------|----------|
| Unified source of truth | Rewire SLOT_SUPPLEMENTS / coaching to read real check-off data from HabitStore instead of inferring from meal-slot misses; needs dedup to avoid double-nag | ✓ |
| Read-only link (baseline) | Klaus can read check-offs via tools, but the 21:30 fueling accountability stays meal-slot-inferred | |
| Fully independent | HabitStore purely a hub ledger; v4.0 coaching never reads it | |

**User's choice:** Unified source of truth
**Notes:** Most aligned with the cross-domain coaching philosophy — Klaus's real accountability should be powered by actual check-offs. → CONTEXT D-01/D-02.

## Seeding

| Option | Description | Selected |
|--------|-------------|----------|
| Seed supplements, manual habits | Pre-create the 3 blueprint supplements from supplement_schedule; habits manual | |
| Manual, like TickTick (D-08) | Build store + UI, create nothing; Amit defines all items himself | ✓ |
| Seed both — tell me your habits | Seed supplements + Amit's current tracked habits | |

**User's choice:** Manual, like TickTick (D-08)
**Notes:** Mirrors the Phase-27 manual migration. With manual seeding + unified link, the supplement→fueling-slot mapping keys off the item's time slot. → CONTEXT D-03.

## Schedule & check-off mechanics

| Option | Description | Selected |
|--------|-------------|----------|
| Daily + specific weekdays | Two day patterns only | ✓ |
| Reuse task cadences | daily/weekdays/specific-weekdays/every-N-days | |
| Daily + weekdays + every-N-days | Adds interval cadence | |

**User's choice:** Daily + specific weekdays → CONTEXT D-04.

| Option | Description | Selected |
|--------|-------------|----------|
| Simple slots, mapped under the hood | Morning/Noon/Evening/Bedtime; mapped to fueling slots internally | ✓ |
| Reuse the 6 fueling slots | Pick directly from post-am-run/pm-post-lift/pre-bed… | |
| Free time-of-day | Optional clock time/label; weakens the fueling-slot link | |

**User's choice:** Simple slots, mapped under the hood → CONTEXT D-05.

| Option | Description | Selected |
|--------|-------------|----------|
| One check-off per scheduled day | Binary done/not-done; item in one slot | ✓ |
| Multiple slots per item | Several check-offs/day; day complete when all done | |

**User's choice:** One check-off per scheduled day → CONTEXT D-06.

| Option | Description | Selected |
|--------|-------------|----------|
| Tap toggles + dose as label | Tap to complete/un-check; dose read-only label | |
| Tap toggles + dose editable | Toggle + adjust dose at check-off (partial adherence) | ✓ |
| Undo toast like tasks | Mirror Phase-27 complete→undo-toast | |

**User's choice:** Tap toggles + dose editable → CONTEXT D-07/D-09. Completion log records dose actually taken.

## Streak rules

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit skip + pure reset | Un-marked miss resets; deliberate "skip" marks a day neutral | |
| Pure — any miss resets | One missed scheduled day breaks the streak, no exceptions | ✓ |
| Auto-grace (N free misses) | Small allowance before the streak breaks | |

**User's choice:** Pure — any miss resets → CONTEXT D-10. Matches accountability coaching style.

| Option | Description | Selected |
|--------|-------------|----------|
| Yesterday only | Backfill the previous day only; repairs the streak | ✓ |
| Any past day | Edit/check off any historical day | |
| Today only — no backfill | Only the current day counts | |

**User's choice:** Yesterday only → CONTEXT D-11/D-12. Realistic forgot-to-tap valve without anti-honesty rigidity.

## Klaus adherence nudging

| Option | Description | Selected |
|--------|-------------|----------|
| End-of-day window only | Tick considers a nudge only in an evening window | |
| Per-slot as it passes | A scheduled slot passing unchecked becomes a salient signal | ✓ |
| Only the streak-at-risk case | Tick flags only when a real streak is about to break | |

**User's choice:** Per-slot as it passes → CONTEXT D-15. (Streak still weighted into salience — D-16. Tick-window caveat for Bedtime — D-18.)

| Option | Description | Selected |
|--------|-------------|----------|
| All pending, light touch, deduped | Any pending item; CoachingTopicStore dedup vs 21:30 alert; warm-brief tone; streak weighted | ✓ |
| Supplements-emphasis, accountability tone | Lean on supplements with firmer v4.0 framing | |
| Supplements only — habits never nudge | Only supplements trigger autonomous nudges | |

**User's choice:** All pending, light touch, deduped → CONTEXT D-15/D-16/D-17.

## Editing/deleting a definition

| Option | Description | Selected |
|--------|-------------|----------|
| Forward-only; freeze past | Schedule changes apply forward; past grid/streak frozen (effective-dated) | ✓ |
| Recompute against new schedule | Whole history recomputes against current schedule | |
| Schedule change resets streak | Any schedule change starts a fresh streak | |

**User's choice:** Forward-only; freeze past → CONTEXT D-19.

| Option | Description | Selected |
|--------|-------------|----------|
| Hard delete + undo toast | Definition + history removed; brief undo toast | ✓ |
| Archive (hide, keep history) | Hidden but revivable; history retained | |

**User's choice:** Hard delete + undo toast → CONTEXT D-20. Consistent with the Phase-27 "don't retain what I don't review" stance.

## History-grid scope

| Option | Description | Selected |
|--------|-------------|----------|
| Rolling year, per-habit only | ~365-day grid in each habit's detail view; no overview | ✓ |
| 90-day, per-habit | Shorter rolling window | |
| Year + all-habits overview | Per-habit grid + combined overview heatmap | |

**User's choice:** Rolling year, per-habit only → CONTEXT D-14. Consistent with Out-of-Scope (no home-screen grid).

## Habit vs supplement treatment

| Option | Description | Selected |
|--------|-------------|----------|
| Type tag + dose only | Supplement = habit with type=supplement + dose; identical behavior | ✓ |
| Grouped + supplement framing | Separate sections + coaching-flavored framing | |

**User's choice:** Type tag + dose only → CONTEXT D-21. Differences are the dose label + the unified coaching link.

---

## Claude's Discretion

- `HabitStore` document/collection shape + completion-log structure (records dose-taken; `_jsonsafe_doc`).
- Effective-dated-schedule representation for D-19; slot→fueling-slot mapping mechanics for D-01/D-02.
- DST-boundary streak algorithm + test fixtures; four-state grid derivation.
- Undo-toast duration / soft-then-hard delete mechanics (mirror Phase 27).
- react-query/optimistic/zustand check-off wiring; repeat-suppression topic_key shape.
- All visual/layout/animation specifics → `/gsd:ui-phase 28`.

## Deferred Ideas

- Every-N-days / interval scheduling; multiple-slots-per-item / times-per-day; skip-freeze/auto-grace; backfill older than yesterday; all-habits overview heatmap; archive/history-after-delete; stern supplement-specific nudge framing; Web Push delivery of nudges (Phase 29).
- No scope-creep items arose — all deferrals are explicit narrowings of in-phase options.
