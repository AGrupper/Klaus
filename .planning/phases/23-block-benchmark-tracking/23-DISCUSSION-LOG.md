# Phase 23: Block + Benchmark Tracking - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-05
**Phase:** 23-block-benchmark-tracking
**Areas discussed:** Block seeding model, Benchmark composition, Validity-gate deferral, Pre-cycle behavior

---

## Block seeding model

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-seed all 4 at cycle start | Klaus auto-creates the 4 mesocycle blocks from the blueprint at the 2026-06-21 anchor; get_current() resolves by date; benchmarks + cross-block comparison work automatically | ✓ |
| Roll one block at a time (manual) | Block exists only when you call start_block; get_current() returns None until you act | |
| Auto-seed, confirm each rollover | Derived from blueprint but Klaus asks to confirm each deload transition | |

**User's choice:** Auto-seed all 4 at cycle start.

| Option | Description | Selected |
|--------|-------------|----------|
| Benchmark W4/8/12 only; W16 = race | Blocks 1-3 get the deload benchmark; Block 4's test is the actual half-marathon (terminal goal) | ✓ |
| Benchmark all 4 block-ends | Fire a benchmark at every deload incl. W16 (risks fatiguing test during taper) | |

**User's choice:** Benchmark at W4/8/12 only; W16 = race.
**Notes:** Block table — B1 W1-4 Aerobic Base · B2 W5-8 Capacity Build · B3 W9-12 Deep Waters→Peak · B4 W13-16 Race Spec→Taper.

---

## Benchmark composition

| Option | Description | Selected |
|--------|-------------|----------|
| Mixed: fresh calisthenics, derived strength/pace | Push-ups/pull-ups = fresh max-rep set you report; bench/squat = Epley from logged top-set; threshold = avg last 3 sessions | ✓ |
| All fresh tests | Every facet an actual test session (heavy single, max reps, time-trial) | |
| All derived from existing logs | No fresh test; everything snapshot from TrainingLogStore/Garmin | |

**User's choice:** Mixed — fresh test for calisthenics, derived for strength/pace.

| Option | Description | Selected |
|--------|-------------|----------|
| Strength + calisthenics + threshold; speed near Nov | Deload tests bench/squat/push-ups/pull-ups/threshold; 3k/400m only near November deadline | ✓ |
| All seven facets every benchmark | bench/squat/push-ups/pull-ups/threshold/3k/400m every deload | |
| Klaus chooses per block focus_facets | Test only the block's emphasis (uneven cross-block trend) | |

**User's choice:** Strength + calisthenics + threshold pace at deloads; speed (3k/400m) only near the November deadline.

---

## Validity-gate deferral

| Option | Description | Selected |
|--------|-------------|----------|
| Defer + auto-re-prompt when biometrics clear | Explain the hold, keep benchmark_due=True, re-check nightly via 21:30 cron, re-prompt when HRV/ACWR pass; one stale-caveat prompt if window ends red | ✓ |
| Defer + you pick the day | Klaus flags failure, asks you to choose a fresh day | |
| Note caveat but allow if you insist | Test anyway, record annotated tested-under-fatigue | |

**User's choice:** Defer + auto-re-prompt when biometrics clear.
**Notes:** Gate thresholds = HRV < 70% of 7-day baseline OR ACWR > 1.2 (ROADMAP SC-3).

---

## Pre-cycle behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Countdown note in crons | get_current()=None pre-anchor; crons surface "Pre-cycle — starts in N days (Sun 2026-06-21)"; no benchmark logic runs | ✓ |
| Silent until Week 1 | No block framing at all before 2026-06-21 | |
| Treat now as Week 1 | Move anchor earlier (contradicts locked plan_start_date) | |

**User's choice:** Countdown note in crons.

---

## Claude's Discretion

- BlockStore/BenchmarkStore field names + lazy-singleton/never-raises discipline.
- Auto-seed as idempotent script vs lazy on first get_current() after anchor.
- "Week N of 16, [phase]" exact wording and placement per cron.
- Optional "not preceded by a heavy training day" validity criterion (research extra, not required by SC-3).
- Epley vs Brzycki for strength estimate; rounding of displayed numbers.
- get_block_status payload shape; _HANDLERS wiring for all 7 tools.
- Re-prompt cadence phrasing in proactive_alert.md.

## Deferred Ideas

- 3k/400m maximal-sprint benchmarks near the November deadline (not at deloads) — trigger wiring beyond the deferral note is out of scope here.
- Pace-to-deadline trend projection + per-facet trajectory in Sunday review → Phase 25 (PROG-02).
- Session-quality annotation at log time → Phase 24 (PROG-04).
- Cross-cron dedup / strict skip pushback / nutrition accountability → Phase 24.
