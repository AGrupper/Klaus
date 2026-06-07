# Phase 25: Progress Projection + Benchmark Trend Reporting - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-07
**Phase:** 25-progress-projection-benchmark-trend-reporting
**Areas discussed:** Projection confidence, Framing & prescription, Facet coverage, Pace vs strength data sources

---

## Projection confidence (thin / sparse benchmark data)

| Option | Description | Selected |
|--------|-------------|----------|
| Hedge hard, project anyway | ≥2 points → project + confidence label naming the count; 1 → baseline only; 0 → log a benchmark. Never silent. | ✓ |
| Withhold until enough data | Refuse to project until N≥3 measured points; below that, "insufficient data, reassess at next benchmark." | |
| Let me discuss the threshold | Talk through the cutoff/wording. | |

**User's choice:** Hedge hard, project anyway
**Notes:** Surfaced reality that `TrainingLogStore` has no top-set load — only `BenchmarkStore` entries (sparse) feed strength trends. User wants the data-point count always named in the confidence caveat.

---

## Framing & prescription (on-track / behind report)

| Option | Description | Selected |
|--------|-------------|----------|
| Number + gap + one rec | Projected number + date + gap; "behind" → one ranked rec → "your call, Sir." | ✓ |
| Number + gap, no rec | Report number/date/gap only, no unsolicited fix. | |
| Directional, no hard number | "Trending behind/on pace" without a point estimate. | |

**User's choice:** Number + gap + one rec
**Notes:** Continues the Phase-24 strict-coaching voice — concrete numbers, exactly one ranked recommendation on "behind", never a menu.

---

## Facet coverage & surfacing

| Option | Description | Selected |
|--------|-------------|----------|
| Dated goals only, one block | Project only facets with a dated_goal; one Sunday pace-to-deadline block; reactive answers any facet on demand; push-ups/pull-ups not projected unless asked. | ✓ |
| All 5 facets, per-facet lines | Project every BenchmarkStore facet with data, each its own Sunday line. | |
| Discuss coverage + dedup | Talk through facets + COACH-05 dedup interaction. | |

**User's choice:** Dated goals only, one block
**Notes:** Dedup handled via Claude's discretion (reuse COACH-05 `structural-critique:projection:*` namespace, post-send write).

---

## Pace vs strength data sources

| Option | Description | Selected |
|--------|-------------|----------|
| Pace uses richer Garmin trend | threshold_pace from dense Garmin running history; strength from sparse benchmarks; different confidence per facet. | ✓ |
| Benchmark-only, uniform | All facets project from BenchmarkStore only; one method. | |
| Let research decide | Defer the data-source question to research/planner. | |

**User's choice:** Pace uses richer Garmin trend
**Notes:** Two code paths accepted; best-quality projection per facet beats a uniform-but-weaker method.

---

## Claude's Discretion

- Numbers computed deterministically server-side (slope→deadline), brain only frames — required by Tier A/B no-fabrication contract.
- Reactive path shape (thin `project_goal_progress` tool vs brain-composed) left to research/planner, biased toward an auditable deterministic helper.
- Sunday projection lines reuse the Phase-24 COACH-05 `structural-critique:*` dedup with post-send write discipline.
- Lift the Phase-24 projection fence in `prompts/weekly_training_review.md`; keep "Week N of 16" framing alongside the dated projection.

## Deferred Ideas

- Per-session top-set load capture (denser strength trend than sparse benchmarks) — biggest lever on projection quality; new capture capability, future phase/backlog.
- Reviewed-not-folded todos: `coaching-query-iteration-cap-double-send` (resolved in P24-03), `phase-22-code-review-advisory` (WR-02 fixed in P24-03; WR-03 unrelated).
