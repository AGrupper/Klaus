# Phase 23: Block + Benchmark Tracking - Context

**Gathered:** 2026-06-05
**Status:** Ready for planning

<domain>
## Phase Boundary

**What this phase delivers (BLOCK-01, BLOCK-02, BLOCK-03):**

Klaus gains a persistent notion of *where Amit is in the 16-week cycle* and uses it everywhere:

1. **Block tracking** — `BlockStore` + `BenchmarkStore` (dedicated Firestore stores), with `get_current()` resolving the active block by date from `plan_start_date` (2026-06-21). Crons surface "Week N of 16, [phase name]" framing.
2. **End-of-block benchmark trigger** — at deload weeks (W4/W8/W12) Klaus prompts a standardized benchmark session behind a biometric validity gate, via the **existing 21:30 cron** (no 8th scheduler job). The `benchmark_due` flag on the block doc is the trigger state.
3. **Per-facet benchmark recording + cross-block comparison** — `log_benchmark` records results; Klaus surfaces a facet's history across blocks ("bench press: 80kg Block 1 → 85kg Block 2").
4. **7 brain-direct tools** (per research ARCHITECTURE): `get_plan`, `get_block_status`, `update_plan`, `log_benchmark`, `get_benchmark_history`, `start_block`, `end_block`.
5. **Block state surfaced in existing crons** (morning briefing, 21:30 alert, Sunday weekly review) — best-effort gather, never breaks the cron if the store is empty.

**Out of scope (later v4.0 phases — do NOT build here):**
- Strict skip/off-plan pushback, recovery-vs-plan option framing, cross-cron dedup, nutrition/supplement accountability → Phase 24 (COACH-03/04/05, NUTR).
- Pace-to-deadline trend *projection* against Oct/Nov goals, per-facet improvement *trajectory* reporting in the weekly review → Phase 25 (PROG-02). *(This phase records benchmarks and can show raw block-over-block deltas; it does not project trends.)*
- Session-quality annotation at log time (PROG-04) → Phase 24.
- Any new crons, backends, or dependencies.

</domain>

<decisions>
## Implementation Decisions

### Block model & seeding (BLOCK-01)
- **D-01 — Auto-seed all 4 mesocycle blocks at cycle start.** When the cycle anchor (`plan_start_date` = 2026-06-21) arrives, Klaus auto-creates the four 4-week blocks derived from the blueprint §4 table. `get_current()` always resolves the active block by date (no manual `start_block` needed for the normal flow). This makes `benchmark_due` firing and "Block 1 → Block 2" comparison work automatically.
  - Block 1: W1–4 **Aerobic Base**, end 2026-07-18 (deload W4)
  - Block 2: W5–8 **Capacity Build**, end 2026-08-15 (deload W8)
  - Block 3: W9–12 **Deep Waters → Peak Engine**, end 2026-09-12 (deload W12)
  - Block 4: W13–16 **Race Specificity → Taper → Race Week**, end 2026-10-10 (race W16)
- **D-02 — Benchmarks fire at W4 / W8 / W12 deloads only; W16 is the race.** Blocks 1–3 get the standardized benchmark prompt at their deload. Block 4's terminal "test" is the actual half-marathon (the dated October goal) — Klaus frames race week as the terminal test, **not** a separate benchmark session. So `benchmark_due` is only ever set on Blocks 1–3. (Honors the blueprint's "test at block ends + deadlines, never during taper" philosophy.)
- **D-03 — Week number is always derived, never stored as truth.** `week_num = (today - plan_start_date).days // 7 + 1` (locked v4.0 research). Phase name per week comes from the blueprint §4 table. The block doc holds `start_date`/`end_date`/`label`/`focus_facets`/`benchmark_due`; the *current week* is computed at read time.
- **D-04 — Pre-cycle behavior = light countdown note.** Before 2026-06-21, `get_current()` returns `None` and **no benchmark logic runs**, but crons surface a light line where block framing would go: *"Pre-cycle, Sir — your 16-week build begins in N days (Sun 2026-06-21)."* (No "Week N of 16" until the cycle actually starts.)

### Benchmark composition (BLOCK-02, BLOCK-03)
- **D-05 — Mixed capture method by facet** (least fatiguing, still comparable):
  - **Push-ups / pull-ups** → a real **fresh max-rep set** Amit performs and reports (logged via `log_benchmark`, unit `reps`).
  - **Bench / squat** → **Epley estimate from the heaviest logged top-set that block** (`1RM ≈ w × (1 + reps/30)`). **No fresh 1RM test** — avoids a maximal lift during a deload.
  - **Threshold pace** → **average of the last 3 threshold sessions** from Garmin (Postgres), unit `sec`/km.
- **D-06 — Deload benchmark covers strength + calisthenics + threshold pace; speed (3k / 400m) is deferred to the November-deadline window.** The five facets that progress block-over-block (bench, squat, push-ups, pull-ups, threshold pace) are benchmarked at each deload. Maximal-sprint speed tests (3k @ 9:30, 400m @ 55s) are **not** run inside an aerobic-recovery deload — Klaus prompts those only as the November deadline approaches. *(The 3k/400m terminal prompts are out-of-scope-to-build here beyond noting the deferral; this phase wires the deload benchmark for the five facets.)*

### Validity gate & deferral (BLOCK-02)
- **D-07 — Gate thresholds (from ROADMAP SC-3):** defer the benchmark when **HRV < 70% of 7-day baseline OR ACWR > 1.2**. Garmin recovery is always treated as fresh (Phase 22 D-06).
- **D-08 — On gate failure: defer + auto-re-prompt when biometrics clear.** Klaus explains the hold with the number ("HRV 61 — 78% of baseline; a test today reads fatigue, not fitness, Sir"), keeps `benchmark_due = True`, and the 21:30 cron re-checks each evening, re-prompting the moment HRV ≥ 70% baseline **and** ACWR ≤ 1.2. Amit never has to chase it.
- **D-09 — Stale-window fallback.** If the deload week ends still red (gate never clears in the window), Klaus prompts **once** with an explicit stale-conditions caveat so a result can still be recorded (annotated as tested-under-fatigue), rather than silently skipping the block's benchmark.

### Claude's Discretion
- Exact `BlockStore` / `BenchmarkStore` schema field names and the lazy-singleton + never-raises read discipline (mirror existing stores per research ARCHITECTURE §IP4).
- Whether the auto-seed (D-01) runs as a one-time idempotent ingest (like `scripts/ingest_blueprint.py`) or lazily on first `get_current()` after the anchor — planner's call, as long as it's idempotent and derives dates from `plan_start_date`.
- Exact "Week N of 16, [phase]" wording and where it sits in each cron message.
- Whether to additionally apply the research's optional "not preceded by a heavy training day" validity criterion on top of the two ROADMAP gate thresholds (D-07) — nice-to-have, not required by SC-3.
- Epley vs. Brzycki for the strength estimate; how many decimal places / rounding for displayed benchmark numbers.
- `get_block_status` payload shape (current block + its benchmarks + raw delta vs prior block) and the `_HANDLERS` wiring for all 7 tools.
- How the re-prompt cadence (D-08) is expressed in the `proactive_alert.md` prompt without spamming.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked architecture for this phase (read FIRST)
- `.planning/research/ARCHITECTURE.md` § "Integration Point 4: Block and Benchmark Tracking" — the locked `BlockStore` (`training_blocks/{block_id}`) and `BenchmarkStore` (`benchmarks/{YYYY-MM-DD}_{facet}`) schemas, the 7-tool table, the cron-surfacing plan (morning briefing / proactive alerts / weekly review gather hooks), and the `benchmark_due`-flag trigger state machine (no new cron).
- `.planning/research/PITFALLS.md` § "Pitfall 7: Block and Benchmark Ambiguity" — explicit `block_start_date`/`block_end_date`, the 3-day benchmark window, the validity checklist (HRV > 70% baseline, ACWR < 1.2), and the rule that the 16-week table is a *prescription lookup, not a benchmark schedule*.

### The plan data this phase reads from
- `docs/hybrid_athlete_blueprint.md` §4 (16-Week Aerobic Engine Progression) — the per-week phase names (Aerobic Base / Capacity Build / Deep Waters / Peak Engine / Race Specificity / Taper / Race Week) and deload weeks (4/8/12) that define the 4 auto-seeded blocks (D-01). §1 dated goals = the benchmark facet targets.
- `.planning/REQUIREMENTS.md` — BLOCK-01/02/03 full text; "Milestone anchor" (Week 1 = Sun 2026-06-21); the Out-of-Scope rows (periodic/mid-block testing; coach-override).

### Existing code to extend
- `memory/firestore_db.py` — add `BlockStore` + `BenchmarkStore` following the established lazy-singleton, never-raises, `_jsonsafe_doc` discipline of the existing stores (`TrainingLogStore` at line 764, `MealStore` at 574, `OutreachLogStore` at 1289). **Firestore SERVER_TIMESTAMP → DatetimeWithNanoseconds breaks `json.dumps`** — ISO-convert in any read path (recalled feedback; `_jsonsafe_doc` helper).
- `memory/firestore_db.py` `UserProfileStore` — `current_block_id` FK field (research schema line 76); `start_block`/`end_block` set/clear it.
- `core/tools.py` — add the 7 brain-direct tools to `TOOL_SCHEMAS`, register in `SMART_AGENT_DIRECT_TOOLS`, exclude from `WORKER_TOOL_SCHEMAS`, dispatch in `_HANDLERS` (mirror `get_training_profile` / `read_coaching_guide` brain-direct pattern from Phase 21/22). Note `update_plan` already exists (Phase 21) — coexists with `update_training_profile` on the same doc.
- `core/proactive_alerts.py` — `run_proactive_alerts()` (line 91): after the training check-in (~line 103) add the best-effort block-end check + `benchmark_due` set + re-prompt logic (D-08/09). Runs BEFORE the dedup gate (existing pattern, line 99).
- `core/morning_briefing.py` `_gather_data()` and `core/weekly_training_review.py` `_gather_week_data()` — add best-effort `BlockStore.get_current()` (+ `get_block_benchmarks` for the weekly review) to the gather dicts.
- `prompts/proactive_alert.md`, `prompts/morning_briefing.md`, `prompts/weekly_training_review.md` — surface the block/benchmark keys.

### Phase governance
- `.planning/ROADMAP.md` Phase 23 section — the 4 success criteria (week-N framing; benchmark fires within 3 days of `block_end_date` via 21:30 cron; the HRV/ACWR gate; `log_benchmark` + facet history).
- `.planning/STATE.md` § Accumulated Context — the locked v4.0 research decisions for blocks/benchmarks (dedicated stores; `benchmark_due` flag; week-math; no 8th cron).
- `.planning/phases/22-expert-coaching-knowledge-d-13-release/22-CONTEXT.md` — Tier A/B recency contract (D-06: Garmin recovery always fresh) the validity gate relies on; `read_coaching_guide` / brain-direct tool pattern.
- `.planning/phases/21-living-plan-ingestion/21-CONTEXT.md` — `UserProfileStore` structured schema (`plan_start_date`, `weekly_split`) and `scripts/ingest_blueprint.py` idempotent-ingest pattern (template for D-01 seeding).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Existing Firestore stores in `memory/firestore_db.py` (`TrainingLogStore`, `MealStore`, `OutreachLogStore`) — direct template for `BlockStore`/`BenchmarkStore`: lazy-singleton accessor, never-raises reads, `_jsonsafe_doc` for timestamp serialization.
- `scripts/ingest_blueprint.py` (Phase 21) — idempotent, dry-run/force blueprint→Firestore ingest; the pattern for auto-seeding the 4 blocks (D-01) if planner chooses a script over lazy-seed.
- Brain-direct tool pattern (`get_training_profile`, `read_coaching_guide`, self-inspect) in `core/tools.py` — template for the 7 new tools.
- `run_proactive_alerts()` "runs BEFORE the dedup gate" structure (`core/proactive_alerts.py:99`) — the slot for the benchmark trigger + re-prompt without being blocked by same-evening dedup.

### Established Patterns
- Week/block math is always *derived* from `plan_start_date`, never stored as ground truth (D-03) — matches the v4.0 invariant.
- Crons gather block state best-effort and degrade silently when the store is empty (pre-cycle, D-04) — mirrors how `{training_profile}` omits cleanly when the profile is empty.
- Garmin recovery (HRV/ACWR) treated as always-fresh (Phase 22 D-06) — the validity gate (D-07) reads it directly without a staleness check.

### Integration Points
- New: `BlockStore` + `BenchmarkStore` in `memory/firestore_db.py`; `current_block_id` on `UserProfileStore`.
- New: 7 brain-direct tools in `core/tools.py`.
- Modified: gather steps + prompts in `proactive_alerts.py`, `morning_briefing.py`, `weekly_training_review.py` (+ their prompt files).

</code_context>

<specifics>
## Specific Ideas

- Auto-seeded block table (Amit-confirmed): B1 W1-4 Aerobic Base · B2 W5-8 Capacity Build · B3 W9-12 Deep Waters→Peak · B4 W13-16 Race Spec→Taper; benchmarks at W4/8/12, race at W16.
- Benchmark capture method (Amit-confirmed): fresh max-rep for push-ups/pull-ups; Epley-from-top-set for bench/squat; 3-session average for threshold pace.
- Defer-and-auto-re-prompt example (Amit-endorsed preview): *"HRV 61, 78% of baseline — a test today reads fatigue, not fitness, Sir."* Re-checks nightly, fires when clear; one stale-caveat prompt if the window closes red.
- Pre-cycle countdown example (Amit-endorsed preview): *"Pre-cycle, Sir — your 16-week build begins in 9 days (Sun Jun 21). Use this window to bank easy aerobic volume and arrive fresh."*

</specifics>

<deferred>
## Deferred Ideas

- 3k (@ 9:30) / 400m (@ 55s) maximal-sprint benchmarks → prompted only near the November deadline, not at deloads (D-06). Wiring the November speed-test trigger is out of scope for this phase's deload benchmark.
- Pace-to-deadline trend projection + per-facet improvement *trajectory* in the Sunday review → Phase 25 (PROG-02). This phase records and can show raw deltas; it does not project.
- Session-quality annotation at log time → Phase 24 (PROG-04).
- Cross-cron coaching dedup / strict skip pushback / nutrition accountability → Phase 24.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 23-block-benchmark-tracking*
*Context gathered: 2026-06-05*
