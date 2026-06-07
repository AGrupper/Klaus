# Phase 25: Progress Projection + Benchmark Trend Reporting - Context

**Gathered:** 2026-06-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Klaus projects strength/pace **trends** against the dated Oct/Nov goals in `UserProfileStore.dated_goals` and reports **on-track / behind** — both **reactively** ("am I on track for my October bench target?") and **proactively** in the Sunday weekly review. This phase **lifts the Phase-24 "no dated projection" fence** and replaces it with the projection behavior. It is the highest dependency-chain feature of v4.0 (depends on Phase 23 benchmarks + Phase 24 strict coaching).

**In scope:** computing a deadline-relative trend from measured data, the on-track/behind report (reactive + Sunday), Tier-A-vs-Tier-B honesty, per-facet confidence handling, lifting the prompt fence.

**Out of scope (new capabilities → own phase):** capturing per-session top-set load (see Deferred); any new benchmark facets; changing the benchmark/block machinery from Phase 23.

</domain>

<decisions>
## Implementation Decisions

### Data reality (drives everything below)
- **`TrainingLogStore` does NOT capture per-session top-set load** (only type/rpe/feel/quality/notes/skipped_reason). Despite the ROADMAP's "TrainingLogStore top-set history" wording, the **only measured strength/pace data points are `BenchmarkStore` entries** (via the existing `get_benchmark_history(facet, n)` tool). These are logged at benchmark windows / block boundaries → **sparse** (~1 per facet per block; blocks end 2026-07-18 / 08-15 / 09-12 / 10-10). Projection logic must be robust to 0–3 data points per facet for most of the cycle.

### D-01 — Projection confidence: hedge hard, project anyway (never silent)
- **≥2 measured points** → project AND attach a confidence label that **names the data-point count** (e.g. "from only 2 benchmarks — low confidence — trending toward ~100kg by Oct 10").
- **1 point** → "baseline only, no trend yet — need another benchmark to project."
- **0 points** → "no measured data for this facet — log a benchmark."
- Klaus is never silent on a dated-goal facet; thin data is surfaced with its count, not hidden.

### D-02 — Framing & prescription: number + gap + one rec (strict-coaching)
- Report the **projected number + target date + gap in concrete units**.
  - On track: "trend → 106kg by Oct 10, ahead of the 105kg target."
  - Behind: "trend → 98kg by Oct 10, ~7kg behind. Closer: [one ranked rec]. Your call, Sir."
- **"Behind" triggers exactly ONE ranked recommendation** (consistent with Phase-24 strict coaching: concrete number → one rec → "your call, Sir" — never a menu). On-track does not prescribe.

### D-03 — Facet coverage & surfacing: dated goals only, one Sunday block
- **Proactively project ONLY facets that have a `dated_goal` target** (bench / squat / half-marathon etc.). Facets with no dated goal (e.g. push-ups, pull-ups) are **NOT projected proactively** — only on explicit reactive request.
- **Sunday weekly review:** ONE consolidated "pace-to-deadline" block, one line per dated-goal facet that has enough data (per D-01).
- **Reactive:** "am I on track for X?" answers **any** facet on demand (computed live), even non-dated ones.

### D-04 — Data sources: pace uses richer Garmin trend; strength uses sparse benchmarks
- **`threshold_pace`** projects from **dense Garmin running history** (frequent data points → a real trend line, higher confidence).
- **Strength facets** project from **sparse `BenchmarkStore` entries** (hedged per D-01).
- Two code paths / different confidence per facet is acceptable and intended — best-quality projection per facet beats a single uniform-but-weaker method.

### Claude's Discretion (derived, grounded in locked prior decisions — not re-asking)
- **Numbers are computed, never LLM-invented.** The slope→deadline projection MUST be a **deterministic server-side computation** (e.g. linear trend over available `BenchmarkStore`/Garmin points), then handed to the brain as data — this is required by the Tier-A-vs-Tier-B "no fabricated convergence" contract (D-13 / anti-fabrication). The brain frames it; it does not arithmetic it.
- **Reactive path shape** (new thin `project_goal_progress(facet)` tool vs brain composing from `get_benchmark_history` + `dated_goals`) — leave to research/planner, but bias toward a small deterministic projection helper so the math is auditable and unfabricatable.
- **Cross-cron dedup (COACH-05):** Sunday projection lines use the `structural-critique:*` namespace (e.g. `structural-critique:projection:<facet>`), written **after send**, so the same "behind on bench" isn't re-raised by the 21:30 cron the same day (reuses the Phase-24 gate; no new dedup machinery).
- **Lift the Phase-24 fence:** replace the "PHASE 25 FENCE — ABSOLUTELY FORBIDDEN" projection prohibition in `prompts/weekly_training_review.md` (≈lines 37, 47, 147) with the projection instruction. Keep the block-relative "Week N of 16" framing **alongside** the new dated projection.
- **Tier A/B labeling:** projection output must visibly distinguish blueprint **target** (Tier A) from measured **trend** (Tier B); when the trend contradicts the target, say so plainly (no convergence fiction) — D-02 "behind" framing already covers this.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirement & scope
- `.planning/REQUIREMENTS.md` — PROG-02 (the only requirement this phase closes).
- `.planning/ROADMAP.md` §"Phase 25" — goal + 3 success criteria (reactive answer computes a trend not just the goal; Sunday pace-to-deadline line for ≥1 facet; Tier A vs Tier B distinction).
- `.planning/phases/24-strict-coaching-integration-nutrition-accountability/24-CONTEXT.md` — strict-coaching voice, COACH-05 dedup, the Phase-25 fence that this phase lifts.

### Data sources (trend inputs)
- `memory/firestore_db.py` — `BenchmarkStore` (`get_benchmark_history`, `get_block_benchmarks`, `log_benchmark`; 5-facet closed set {bench_press_1rm, squat_1rm, push_ups, pull_ups, threshold_pace}); `UserProfileStore.dated_goals` shape `[{target_date, goal_label, metrics}]`; `TrainingLogStore` (confirm NO top-set load field).
- `core/tools.py` — `get_benchmark_history(facet, n)` brain-direct tool (≈line 1790) — the strength/pace trend data source.
- `mcp_tools/garmin_tool.py` — Garmin running history for the `threshold_pace` dense trend (D-04).
- `docs/hybrid_athlete_blueprint.md` — origin of `dated_goals` Oct/Nov targets (Tier A).
- `docs/USER.md` — Amit's goals and goal dates.

### Where it surfaces
- `core/weekly_training_review.py` + `prompts/weekly_training_review.md` — Sunday projection block; the fence to lift; existing COACH-05 dedup write-after-send to reuse.
- `prompts/smart_agent.md` — reactive "am I on track?" answering behavior; Tier A/B data-presence contract (Phase 22).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `get_benchmark_history(facet, n)` tool + `BenchmarkStore` — the measured trend points (sparse).
- `UserProfileStore.dated_goals` (`{target_date, goal_label, metrics}`) — the deadlines + targets to project against.
- `core/weekly_training_review.py` compose path + its COACH-05 `structural-critique:*` dedup write-after-send (Phase 24) — extend, don't rebuild.
- Garmin running history fetch (Phase 23/Phase 24 anchor resolution already reads Garmin activities) — reuse for the pace trend.
- Phase-24 strict-coaching compose pattern in `prompts/proactive_alert.md` (one ranked rec → "your call, Sir") — mirror for the "behind" prescription.

### Established Patterns
- **Tier A (target) vs Tier B (measured)** honesty / no fabricated convergence (Phase 21/22, D-13).
- **Deterministic-numbers-then-LLM-frames** — gather/compute server-side, brain narrates (every cron in v3.0/v4.0).
- **Block-relative framing** "Week N of 16" (Phase 23) — kept alongside the new dated projection.
- **COACH-05 cross-cron dedup** with post-send write discipline (Phase 24).

### Integration Points
- Sunday `run_weekly_review` (proactive projection block).
- Reactive brain path (tool or composed) for "am I on track" queries.
- `prompts/weekly_training_review.md` fence lift (≈lines 37/47/147).

</code_context>

<specifics>
## Specific Ideas

- Canonical reactive query to satisfy: **"am I on track for my October bench target?"** → must compute a trend and project (e.g. "trend → 98kg by Oct 10, ~7kg behind the 105kg target"), not cite the goal alone.
- Example on-track phrasing: "trend → 106kg by Oct 10, ahead of the 105kg target."
- Confidence-label phrasing must name the count: "from only 2 benchmarks — low confidence."

</specifics>

<deferred>
## Deferred Ideas

- **Per-session top-set load capture** — recording the working/top-set kg (and reps) per logged strength session would give a far denser strength trend than the sparse periodic benchmarks, sharply improving projection confidence. This is a **new capture capability**, not PROG-02 — note for a future milestone/phase. (It's the single biggest lever on projection quality, so worth surfacing to the roadmap backlog.)

### Reviewed Todos (not folded)
- `coaching-query-iteration-cap-double-send` — **already resolved** in Phase 24 (plan 24-03: `MAX_TOOL_ITERATIONS=12` + last-substantive-text). Not folded; stale.
- `phase-22-code-review-advisory` (WR-02 / WR-03) — WR-02 (`read_coaching_guide` fuzzy hardening) **fixed in Phase 24-03**; WR-03 slim-core size-guard advisory is unrelated to projection. Not folded.

</deferred>

---

*Phase: 25-progress-projection-benchmark-trend-reporting*
*Context gathered: 2026-06-07*
