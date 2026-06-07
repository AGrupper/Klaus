# Phase 25: Progress Projection + Benchmark Trend Reporting — Research

**Researched:** 2026-06-07
**Domain:** Deterministic trend projection, BenchmarkStore/Garmin data, Sunday cron extension, reactive tool
**Confidence:** HIGH — all findings verified directly in the codebase

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **TrainingLogStore does NOT capture per-session top-set load** — only type/rpe/feel/quality/notes/skipped_reason. The only measured strength/pace data points are `BenchmarkStore` entries.
- **D-01 — Projection confidence:** ≥2 points → project + confidence label naming the count; 1 point → "baseline only, no trend yet"; 0 points → "no measured data — log a benchmark". Never silent.
- **D-02 — Framing:** on-track = projected number + date + gap; behind = number + gap + exactly ONE ranked recommendation + "your call, Sir". On-track does not prescribe.
- **D-03 — Facet coverage:** proactively project ONLY dated-goal facets (bench/squat/half-marathon etc.). Non-dated facets (push-ups, pull-ups) projected only on explicit reactive request.
- **D-04 — Data sources:** `threshold_pace` from dense Garmin running history; strength facets from sparse BenchmarkStore entries.
- **Numbers are computed server-side, never LLM-invented** — deterministic slope→deadline projection, then handed to the brain as data.
- **Reactive path** — bias toward a small deterministic `project_goal_progress(facet)` helper so the math is auditable.
- **Cross-cron dedup:** Sunday projection lines use `structural-critique:projection:<facet>` namespace, written after send (Phase-24 gate reused).
- **Fence lift:** replace "PHASE 25 FENCE — ABSOLUTELY FORBIDDEN" lines in `prompts/weekly_training_review.md` (lines 37, 47, 147) with the projection instruction.
- **Tier A/B labeling:** projection output visibly distinguishes blueprint target (Tier A) from measured trend (Tier B); contradictions stated plainly.

### Claude's Discretion

- Projection helper shape and signature (recommended: `project_goal_progress(facet, dated_goals, benchmark_history, today_iso)` returning a `ProjectionResult` dataclass-style dict).
- Whether the reactive path registers a new brain-direct tool `get_goal_projection` in core/tools.py vs. brain composing from `get_benchmark_history` + `get_plan`. Bias: new thin tool.
- Internal structure of the helper module (recommended: `core/projection.py` — pure function, no I/O, easily unit-testable).
- Garmin pace trend implementation detail — recommend deriving threshold_pace from the Postgres `activities` table's `avg_pace` column (running activities, last N entries) via `query_health_database`, falling back to `BenchmarkStore.get_facet_history("threshold_pace")`.

### Deferred Ideas (OUT OF SCOPE)

- Per-session top-set load capture (would give denser strength trend).
- `coaching-query-iteration-cap-double-send` — already resolved in Phase 24.
- WR-02/WR-03 phase-22 advisory items — unrelated to projection.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PROG-02 | Klaus projects strength/pace trends toward the dated Oct/Nov goals and reports on-track / behind | BenchmarkStore API verified; dated_goals shape verified; Garmin pace data path confirmed; weekly_training_review.py compose path fully mapped; fence lines located; dedup namespace confirmed; deterministic helper approach specified |
</phase_requirements>

---

## Summary

Phase 25 closes PROG-02 by (1) computing deterministic trend projections server-side from verified data sources, (2) surfacing them in the existing Sunday `run_weekly_review` cron, (3) answering reactive "am I on track?" queries through a new brain-direct tool, and (4) lifting the Phase-24 fence that blocked all projection language from the weekly review prompt.

The data reality is exactly as CONTEXT.md states. `TrainingLogStore.log_session` stores `{type, planned, completed, skipped_reason, rpe, feel, notes, quality, source, garmin_activity_id}` — there is no `load_kg`, `top_set_weight`, or any numeric strength field. The only measured strength/pace numbers are in `BenchmarkStore` (sparse: ~1 per block boundary per facet). The `threshold_pace` facet can additionally draw on Postgres `activities.avg_pace` (dense running history), which is a NUMERIC(5,2) field populated from `entry.get("averagePace")` in the Garmin zip ingest pipeline.

`UserProfileStore.dated_goals` is confirmed as a list of two dicts with `target_date` (ISO string "YYYY-MM-DD"), `goal_label`, and `metrics` (sub-dict whose keys are facet-adjacent names like `bench_press_kg`, `squat_kg`, `half_marathon_time`, `push_ups`, `pull_ups`). There is a facet-mapping step required: the BenchmarkStore facet name `bench_press_1rm` maps to the dated_goals metric key `bench_press_kg`, and `threshold_pace` (sec_per_km) maps to `half_marathon_time` (string "1:25:00") via a unit conversion. This mapping must be explicit in the helper.

The Sunday cron (`core/weekly_training_review.py`) is the correct extension point. It already gathers `BenchmarkStore` data, reads `UserProfileStore`, writes to `CoachingTopicStore` after send, and passes `coaching_topics_today` to the prompt for dedup. The Phase-25 addition is: (a) compute projection results server-side in `_gather_week_data`, (b) inject into the data dict, (c) lift the fence in the prompt, (d) write `structural-critique:projection:<facet>` keys post-send.

**Primary recommendation:** Implement `core/projection.py` as a pure-function module with a `project_goal_progress(facet, history, dated_goals, today_iso)` helper. Register `get_goal_projection` as a new brain-direct tool in `core/tools.py`. Extend `_gather_week_data` to call the helper for each dated-goal facet and inject results into the data dict. Lift the fence in the prompt.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Trend computation (slope → projection) | API/Backend (Python helper) | — | Must be deterministic + auditable; brain must not arithmetic |
| Benchmark data retrieval | API/Backend (BenchmarkStore) | — | Firestore read — no LLM involvement |
| Garmin running pace history | Database (Postgres) | API/Backend (garmin_tool fallback) | `activities.avg_pace` is the dense running history; BenchmarkStore is sparse fallback |
| Dated goal target lookup | API/Backend (UserProfileStore) | — | Firestore read; Tier A targets |
| Projection injection (Sunday) | API/Backend (weekly_training_review.py) | — | Existing cron — extend _gather_week_data |
| Brain framing of projection output | Brain (smart_agent model) | — | Narrates computed result in JARVIS voice |
| Reactive "am I on track?" | Brain-direct tool (get_goal_projection) | — | New tool registered in SMART_AGENT_DIRECT_TOOLS |
| Dedup write-after-send | API/Backend (CoachingTopicStore) | — | Exact Phase-24 pattern; no new machinery |
| Fence lift | Prompt file (weekly_training_review.md) | — | Three edit-point replacement |

---

## Standard Stack

This phase is code-only within the existing Klaus Python stack. No new packages are installed.

### Core (existing, reused)

| Component | Location | Purpose |
|-----------|----------|---------|
| `BenchmarkStore.get_facet_history(facet, n)` | `memory/firestore_db.py:1910` | Strength/pace benchmark trend points |
| `UserProfileStore.load()` | `memory/firestore_db.py:162` | Reads `dated_goals` (Tier A targets) |
| `query_health_database(sql)` | `mcp_tools/database_tool.py:21` | Postgres `activities` table for pace trend |
| `CoachingTopicStore.has_topic / add_topic` | `memory/firestore_db.py:1443/1467` | COACH-05 dedup gate |
| `_gather_week_data` | `core/weekly_training_review.py:42` | Sunday cron data gather — extend here |
| `run_weekly_review` | `core/weekly_training_review.py:359` | Sunday cron entry — post-send dedup write here |

### New (this phase)

| Component | Location | Purpose |
|-----------|----------|---------|
| `core/projection.py` | new file | Pure-function projection helper module |
| `project_goal_progress(...)` | `core/projection.py` | Deterministic trend + projection computation |
| `get_goal_projection` tool | `core/tools.py` | Brain-direct reactive tool |

### No New Packages

Installation command: none required.

---

## Package Legitimacy Audit

No external packages are introduced in this phase. N/A.

---

## Architecture Patterns

### System Architecture Diagram

```
Reactive path:
  Amit → Telegram → Brain → get_goal_projection tool
                              ↓
                     core/projection.py::project_goal_progress()
                              ↓ (reads)
                     BenchmarkStore.get_facet_history()    ←  Firestore benchmarks
                     UserProfileStore.load()["dated_goals"] ←  Firestore users/amit
                     query_health_database(running SQL)     ←  Postgres activities
                              ↓ (returns ProjectionResult dict)
                     Brain frames result in JARVIS voice → Telegram response

Sunday proactive path:
  Cloud Scheduler → /cron/weekly-training-review
                              ↓
                     _gather_week_data()
                              ├── [existing] TrainingLogStore, Garmin, Biometrics, Meals, Block
                              └── [NEW] per dated-goal facet:
                                    project_goal_progress(facet, history, dated_goals, today)
                                    → projection_results dict injected into week_data
                              ↓
                     _compose_review(week_data) → brain with lifted fence prompt
                              ↓
                     send_and_inject()
                              ↓ (post-send)
                     CoachingTopicStore.add_topic(date, "structural-critique:projection:<facet>")
```

### Recommended Project Structure

```
core/
├── projection.py          # NEW — pure-function projection helper
├── weekly_training_review.py  # MODIFIED — extend _gather_week_data, run_weekly_review
└── tools.py               # MODIFIED — add get_goal_projection to SMART_AGENT_DIRECT_TOOLS + TOOL_SCHEMAS + _HANDLERS
prompts/
└── weekly_training_review.md  # MODIFIED — lift 3 fence lines, add projection block instruction
```

### Pattern 1: Deterministic Projection Helper

**What:** A pure function that takes benchmark history + dated goals + today's date and returns a typed result dict. No I/O, no LLM calls, easily unit-testable.

**When to use:** Called from both the Sunday cron gather step and the reactive `get_goal_projection` tool handler. Shared helper ensures math is identical across both surfaces.

**Recommended signature:**

```python
# core/projection.py

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional

# Facet → direction: True = higher-is-better, False = lower-is-better
FACET_DIRECTION: dict[str, bool] = {
    "bench_press_1rm": True,   # kg, higher = better
    "squat_1rm":       True,   # kg, higher = better
    "push_ups":        True,   # reps, higher = better
    "pull_ups":        True,   # reps, higher = better
    "threshold_pace":  False,  # sec/km, lower = better
}

# Maps dated_goals.metrics keys to BenchmarkStore facet names
# (The dated_goals metrics dict uses human-readable keys, not BenchmarkStore facet names)
GOAL_METRIC_TO_FACET: dict[str, str] = {
    "bench_press_kg":    "bench_press_1rm",
    "squat_kg":          "squat_1rm",
    "push_ups":          "push_ups",
    "pull_ups":          "pull_ups",
    # half_marathon_time → needs conversion to sec/km for threshold_pace
    # 3k_time, 400m_time → no direct benchmark facet mapping (speed facets)
}

@dataclass
class ProjectionResult:
    facet: str
    confidence: str          # "high" | "medium" | "low" | "baseline_only" | "no_data"
    data_point_count: int
    projected_value: Optional[float]  # None when < 2 points
    target_value: Optional[float]     # None when no dated goal
    target_date: Optional[str]        # ISO YYYY-MM-DD
    gap: Optional[float]              # projected_value - target_value (signed, direction-aware)
    on_track: Optional[bool]          # None when can't project
    unit: str
    confidence_label: str             # human-readable, e.g. "from only 2 benchmarks — low confidence"

def project_goal_progress(
    facet: str,
    history: list[dict],          # from BenchmarkStore.get_facet_history (date-desc)
    dated_goals: list[dict],      # from UserProfileStore.load()["dated_goals"]
    today_iso: str,
) -> ProjectionResult:
    """
    Compute a linear trend projection from sparse benchmark history.
    
    Confidence tiers:
      >=2 points: linear least-squares slope → project to deadline
      1 point:    baseline_only — cannot project
      0 points:   no_data
      
    Direction:
      higher-is-better facets: on_track = projected >= target
      lower-is-better facets:  on_track = projected <= target
    """
    ...
```

**Linear projection math (for ≥2 points):**

With N benchmark entries `[(t_i, v_i)]` where `t_i = (date_i - plan_start).days` (integer days from a fixed epoch), the least-squares slope is:

```python
# Degenerate case: if all t_i are equal (same-day retests), slope = 0
import statistics

def _linear_project(points: list[tuple[float, float]], target_t: float) -> float:
    """Least-squares projection of (t, value) points to target_t.
    
    Falls back to simple two-point slope when only 2 points (identical result).
    Safe for irregular spacing — no assumption of uniform intervals.
    """
    n = len(points)
    if n == 1:
        return points[0][1]  # no trend — return last value
    ts = [p[0] for p in points]
    vs = [p[1] for p in points]
    t_mean = sum(ts) / n
    v_mean = sum(vs) / n
    num = sum((ts[i] - t_mean) * (vs[i] - v_mean) for i in range(n))
    den = sum((ts[i] - t_mean) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0
    return v_mean + slope * (target_t - t_mean)
```

**Why linear, not polynomial:** With ≤3 data points and a ~16-week cycle, linear extrapolation is the appropriate-complexity model. Polynomial overfits single outlier points. Least-squares generalizes naturally from 2-point (simple slope) to 3+ points without a code branch.

**Confidence label examples:**
- 3 points: "from 3 benchmarks"
- 2 points: "from only 2 benchmarks — low confidence"
- 1 point: "baseline only, no trend yet"
- 0 points: "no measured data"

### Pattern 2: Facet → Dated-Goal Mapping

**What:** The `dated_goals` list uses human-readable metric keys (`bench_press_kg`, `squat_kg`, `half_marathon_time`) that don't match BenchmarkStore facet names. A mapping table is needed.

**Complication — `half_marathon_time` and `threshold_pace`:**
- `dated_goals.metrics["half_marathon_time"]` = `"1:25:00"` (string HH:MM:SS)
- `BenchmarkStore` facet `threshold_pace` stores `unit = "sec_per_km"`, `value` = float sec/km
- Conversion: `"1:25:00"` HM target → `(85 * 60) / 21.1 ≈ 241.7 sec/km` target

The helper should parse the HM time string to total seconds and divide by 21.1km for comparison. When projecting, lower `threshold_pace` = faster = on-track.

**Complication — 3k/400m speed facets:**
The November dated goal metrics (`3k_time`, `400m_time`) have no corresponding BenchmarkStore facet in the 5-facet closed set. These cannot be projected. Phase 25 should project only the mappable facets. Document this as a known gap — these are non-dated for the proactive path anyway (D-03 says only dated-goal facets fire proactively).

**Concrete facets with dated goals to project:**
| BenchmarkStore Facet | Dated Goal Metric Key | Target Value | Target Date | Direction |
|---------------------|----------------------|--------------|-------------|-----------|
| `bench_press_1rm` | `bench_press_kg` | 100 kg | 2026-10-31 | higher |
| `squat_1rm` | `squat_kg` | 120 kg | 2026-10-31 | higher |
| `threshold_pace` | `half_marathon_time` → convert | ~241.7 sec/km | 2026-10-31 | lower |
| `push_ups` | `push_ups` | 125 reps | 2026-11-30 | higher |
| `pull_ups` | `pull_ups` | 35 reps | 2026-11-30 | higher |

### Pattern 3: Garmin Running Pace — Dense Trend Path

**What:** For `threshold_pace`, the Postgres `activities` table provides denser running history (all recorded activities, not just block-end benchmarks). This gives a real trend line with more confidence than the 1-per-block BenchmarkStore entries.

**Postgres schema (verified in `scripts/ingest_garmin_zip.py:36–46`):**

```sql
activities (
    activity_id BIGINT PRIMARY KEY,
    date        TIMESTAMP WITH TIME ZONE NOT NULL,
    type        VARCHAR(50) NOT NULL,
    duration_sec INTEGER NOT NULL,
    distance_m  NUMERIC(8,2),
    avg_hr      INTEGER,
    max_hr      INTEGER,
    avg_pace    NUMERIC(5,2),   -- from entry.get("averagePace") — unit unknown, see below
    training_effect NUMERIC(3,1),
    training_load REAL,
    perceived_exertion SMALLINT,
    feel        SMALLINT
)
```

**avg_pace unit caveat:** The field is populated verbatim from Garmin's `averagePace` export key. The Garmin export format typically stores `averagePace` in `min/km` as a float (e.g. `4.03` = 4:03 min/km). However the BenchmarkStore unit for `threshold_pace` is `sec_per_km`. The pace trend query for Sunday gather should:
1. Query running activities (`type IN ('running', 'trail_running', 'treadmill_running')`) for the last 90 days.
2. Filter out activities with `distance_m < 3000` (short/warmup runs are not threshold indicators).
3. Compute `avg_pace` (or derive from `duration_sec / distance_m * 1000` if `avg_pace` is unreliable).
4. Convert to sec/km to match `BenchmarkStore.unit = "sec_per_km"` for a unified comparison.

The projection helper should accept a pre-fetched list of `(date_iso, pace_sec_per_km)` tuples for the threshold_pace facet, allowing the cron's gather step to supply either Postgres-derived dense history or BenchmarkStore sparse history (whichever has more data points).

**Recommended SQL for pace trend:**

```sql
SELECT date::date AS activity_date, avg_pace,
       duration_sec, distance_m
FROM activities
WHERE type IN ('running', 'trail_running', 'treadmill_running')
  AND date >= NOW() - INTERVAL '90 days'
  AND distance_m >= 3000
ORDER BY date DESC
LIMIT 20
```

[ASSUMED] — avg_pace units are min/km as a float (Garmin convention); verified that the field name `averagePace` is used in ingest but the exact numeric unit from Garmin's export was not confirmed by authoritative docs in this session. The gather step should log the raw value for the first few runs and include a conversion safety check.

### Pattern 4: Timezone-Safe Date Arithmetic (Phase-24 CR-01 lesson)

**The CR-01 bug:** Phase 24 had a timezone bug in date arithmetic. The safe pattern is:

```python
from datetime import date
from zoneinfo import ZoneInfo

# Safe: always derive today in Israel time, then work with date objects only
_TZ = ZoneInfo("Asia/Jerusalem")
today_date = date.fromisoformat(today_iso)   # today_iso already provided as IL date string

# Weeks to deadline (safe integer arithmetic, no timezone involved):
deadline = date.fromisoformat(target_date_iso)
weeks_to_deadline = (deadline - today_date).days / 7.0

# NEVER use datetime.now().date() inline inside a helper — it reads UTC
# The cron always passes today_iso as Asia/Jerusalem date; use that
```

The projection helper must accept `today_iso: str` rather than calling `date.today()` internally. This mirrors the `get_week_num(plan_start_date, today)` pattern in `memory/firestore_db.py:1608` which also takes `today` as a string argument.

### Pattern 5: Reactive Tool Registration

**What:** Register `get_goal_projection` as a brain-direct tool (not worker-delegated).

**Location in core/tools.py:**
- Add to `SMART_AGENT_DIRECT_TOOLS` frozenset (after `"get_benchmark_history"` at line 66).
- Add schema to `TOOL_SCHEMAS` list (after the `get_benchmark_history` schema at line 985).
- Add handler `_handle_get_goal_projection(facet)` near `_handle_get_benchmark_history` (line 1790).
- Add to `_HANDLERS` dict near `"get_benchmark_history"` (line 1868).
- Exclude from `WORKER_TOOL_SCHEMAS` (add to the exclusion set at lines 1043–1050).

**Handler pattern:**

```python
def _handle_get_goal_projection(facet: str) -> str:
    """PROG-02 brain-direct: project one facet toward its dated goal."""
    import json
    from datetime import date
    from zoneinfo import ZoneInfo
    from core.projection import project_goal_progress
    from memory.firestore_db import _jsonsafe_doc

    today_iso = date.today().isoformat()  # UTC is fine for date; no time comparison
    _blocks, benchmarks, profiles = _block_stores()
    history = benchmarks.get_facet_history(facet, n=10)
    profile = _jsonsafe_doc(profiles.load())
    dated_goals = profile.get("dated_goals") or []
    result = project_goal_progress(facet, history, dated_goals, today_iso)
    # result is a dict (or dataclass asdict) — JSON-serializable
    return json.dumps(result)
```

### Pattern 6: Sunday Gather Extension

**What:** Extend `_gather_week_data` to compute projection results for all facets that have dated goals.

**Insertion point:** After the existing block #7 (CoachingTopicStore gather, line 232+). New block #8:

```python
    # ------------------------------------------------------------------ #
    # 8. Progress projections — PROG-02 (Phase 25)                       #
    #    Computed server-side for each dated-goal facet. Best-effort;    #
    #    fail-open to {} on any error.                                   #
    # ------------------------------------------------------------------ #
    try:
        from core.projection import project_goal_progress, FACET_DIRECTION
        from memory.firestore_db import BenchmarkStore, UserProfileStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        benchmarks = BenchmarkStore(project_id, database)
        profile_data = UserProfileStore(project_id, database).load()
        dated_goals = profile_data.get("dated_goals") or []
        projections: dict = {}
        for facet in ["bench_press_1rm", "squat_1rm", "threshold_pace", "push_ups", "pull_ups"]:
            history = benchmarks.get_facet_history(facet, n=10)
            result = project_goal_progress(facet, history, dated_goals, today_iso)
            projections[facet] = result
        data["projections"] = projections
    except Exception:
        logger.warning("weekly_review: projection gather failed", exc_info=True)
        data["projections"] = {}
```

### Pattern 7: Post-Send Dedup Write for Projection Topics

**What:** Mirror the existing Phase-24 COACH-05 post-send pattern exactly. In `run_weekly_review`, after `send_and_inject`, write `structural-critique:projection:<facet>` for each facet that was projected (had ≥1 data point — even baseline-only projections are surfaced to Amit and should be deduped).

**Namespace confirmed:** `CoachingTopicStore.add_topic(date_str, "structural-critique:projection:bench_press_1rm")` etc. Plain string, no dict, no SERVER_TIMESTAMP inside the string (see the class-level NOTE in `CoachingTopicStore`).

**CONTEXT.md decision D-03:** The Sunday review does NOT project non-dated-goal facets (push-ups, pull-ups) unless they happen to have dated goals (which they do in Nov 2026 blueprint). So all 5 facets in the closed set have dated goals and all should be deduped post-send.

### Anti-Patterns to Avoid

- **LLM computing the slope or gap number:** The brain must receive a pre-computed JSON result dict. It narrates; it does not arithmetic.
- **`date.today()` inside `project_goal_progress()`:** Breaks testability and timezone safety. Always pass `today_iso` as a parameter.
- **Asserting avg_pace unit without validation:** The Garmin export `averagePace` field unit is not confirmed authoritative — include a conversion safety check.
- **Writing to CoachingTopicStore before send:** Phase-24 D-10 pattern — write-after-send only. A write before send creates a false-positive block if delivery fails.
- **Inventing a convergence number for a 0-point facet:** When history is empty, the projection result must be `{"confidence": "no_data", "projected_value": None}`. The brain then says "no measured data — log a benchmark."
- **Projecting non-dated-goal facets proactively:** D-03 — push-ups and pull-ups have dated goals (Nov), so they ARE projected proactively. But e.g. a hypothetical `deadlift_1rm` (not in the 5-facet set) would not be.
- **Removing the "Week N of 16" framing from the weekly review:** The prompt lift replaces the fence line but keeps the within-block framing alongside the new dated projection.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Trend projection math | Custom cubic interpolation | Simple linear least-squares | Sparse data (≤3 pts); LSQ generalises from 2 to N without branching |
| Running pace history | New Garmin API endpoint | `query_health_database` on existing `activities` table | Table already populated by ingest; no new auth needed |
| Post-send dedup | New dedup store | `CoachingTopicStore.add_topic` (Phase 24) | Already built, tested, and used by weekly review |
| Dated-goal lookup | Re-parsing USER.md | `UserProfileStore.load()["dated_goals"]` | Structured Firestore data, always current |

---

## Data Reality — Verified Signatures

### BenchmarkStore (verified in `memory/firestore_db.py:1824–1965`)

**`log_benchmark(date, facet, value, unit, block_id, notes="")`**
- Writes doc `benchmarks/{date}_{facet}` with merge=True
- Validates facet against `_BENCHMARK_FACETS` frozenset; raises `ValueError` for unknown facet
- Stored doc fields: `{date: str, facet: str, value: float, unit: str, block_id: str, notes: str, updated_at: SERVER_TIMESTAMP}`
- Timestamp field: `updated_at` (SERVER_TIMESTAMP → DatetimeWithNanoseconds on read, stripped by `_jsonsafe_doc`)
- Value field: `value` (float)
- Unit field: `unit` (str — `"kg"`, `"reps"`, or `"sec_per_km"`)

**`get_facet_history(facet, n=10)`** → `list[dict]` sorted date-desc, each with `doc_id`
- Streams all docs, filters by `facet`, sorts, caps
- Returns `[]` on any error — never raises

**`get_block_benchmarks(block_id)`** → `list[dict]` sorted date-desc, each with `doc_id`
- Server-side `FieldFilter("block_id", "==", block_id)` query
- Returns `[]` on any error — never raises

**5-facet closed set (`_BENCHMARK_FACETS`, verified at `memory/firestore_db.py:1632`):**
`{"bench_press_1rm", "squat_1rm", "push_ups", "pull_ups", "threshold_pace"}`

**Typical benchmark entry shape (from test fixtures):**
```json
{
  "date": "2026-07-18",
  "facet": "bench_press_1rm",
  "value": 92.5,
  "unit": "kg",
  "block_id": "2026-06-21_aerobic_base",
  "notes": "Epley estimate from 85kg×5",
  "doc_id": "2026-07-18_bench_press_1rm"
}
```

### `UserProfileStore.dated_goals` (verified in `scripts/ingest_blueprint.py:62–82`)

**Exact stored structure:**
```json
[
  {
    "target_date": "2026-10-31",
    "goal_label": "October Peak — Absolute Strength + Half Marathon",
    "metrics": {
      "bench_press_kg": 100,
      "squat_kg": 120,
      "half_marathon_time": "1:25:00"
    }
  },
  {
    "target_date": "2026-11-30",
    "goal_label": "November Peak — Calisthenics + Speed",
    "metrics": {
      "push_ups": 125,
      "pull_ups": 35,
      "3k_time": "9:30",
      "400m_time": "55s"
    }
  }
]
```

**`target_date` format:** ISO date string `"YYYY-MM-DD"` — safe for `date.fromisoformat()` directly.

**Facet → goal metric mapping:**
- `bench_press_1rm` → `metrics["bench_press_kg"]` (Oct, target 100, unit kg)
- `squat_1rm` → `metrics["squat_kg"]` (Oct, target 120, unit kg)
- `threshold_pace` → `metrics["half_marathon_time"]` (Oct, "1:25:00" → 241.7 sec/km, lower-is-better)
- `push_ups` → `metrics["push_ups"]` (Nov, target 125, unit reps)
- `pull_ups` → `metrics["pull_ups"]` (Nov, target 35, unit reps)
- `3k_time`, `400m_time` → NO corresponding BenchmarkStore facet — not projectable in Phase 25

**`target_date` timezone discipline:** `target_date` is a date string (no time component). Computing weeks-to-deadline as `(date.fromisoformat(target_date) - date.fromisoformat(today_iso)).days` is pure date arithmetic with no timezone ambiguity — safe to do in the helper.

### `TrainingLogStore` confirmed NO top-set load field (verified at `memory/firestore_db.py:797–848`)

`log_session` stores: `date, slot, type, planned, completed, skipped_reason, rpe, feel, notes, quality, source, garmin_activity_id, updated_at`. No `load_kg`, `weight`, `top_set`, or numeric strength field exists. The CONTEXT.md decision is confirmed correct.

---

## Garmin Pace Trend — Data Path (D-04)

### Dense path (recommended for threshold_pace)

**Source:** Postgres `activities` table, populated by `scripts/ingest_garmin_zip.py` (zip backfill) and `mcp_tools/garmin_tool.py:fetch_garmin_activities` (live Cloud Run pull). The live pull does NOT write to Postgres directly — it returns a list. Only the zip ingest and `write_today_biometrics_to_postgres` write to Postgres. The `activities` table receives data from the zip ingest only (3-year backfill done).

**Implication for Sunday gather:** `query_health_database(sql)` is the correct read path for dense pace history. `fetch_garmin_activities(days=90)` from the live garminconnect API is an alternative for recency but less dense for long-trend projection.

**`activities.avg_pace` column:** `NUMERIC(5,2)`, populated from `entry.get("averagePace")` in the Garmin export. The NUMERIC(5,2) schema allows values like `4.03` (likely min/km) or `243.0` (sec/km). The exact unit is [ASSUMED] min/km based on Garmin's common export format; the planner should include a unit-validation step in Wave 0 that queries a known activity and compares against expected pace.

**Alternative derivation (more reliable):** `avg_pace_sec_km = duration_sec / distance_m * 1000` when both fields are present. This is unit-unambiguous and does not depend on the `avg_pace` field interpretation.

**Recommended gather SQL (safe derivation):**
```sql
SELECT
    date::date AS activity_date,
    duration_sec,
    distance_m,
    CASE WHEN distance_m > 0
         THEN ROUND((duration_sec::numeric / distance_m * 1000), 1)
         ELSE NULL
    END AS pace_sec_per_km
FROM activities
WHERE type IN ('running', 'trail_running', 'treadmill_running')
  AND date >= NOW() - INTERVAL '90 days'
  AND distance_m >= 3000
  AND duration_sec > 0
ORDER BY date DESC
LIMIT 20
```

This avoids the `avg_pace` unit ambiguity entirely by computing from `duration_sec / distance_m`.

### Sparse fallback for threshold_pace

If Postgres is unavailable, fall back to `BenchmarkStore.get_facet_history("threshold_pace", n=10)`. Same projection logic applies.

---

## Weekly Review Integration — Fence Lift (Verified Line Numbers)

### Lines containing the Phase-25 fence (verified in `prompts/weekly_training_review.md`)

| Line | Content (verbatim excerpt) |
|------|---------------------------|
| **37** | `**PHASE 25 FENCE — ABSOLUTELY FORBIDDEN:** Do NOT compute, state, or imply any dated projection...` |
| **47** | `...never a dated projection:` (the section heading for the Per-Facet Within-Block Status) |
| **147** | `- Never project to a deadline — report current/within-block movement only (Phase 25 fence)` |

**Precise edit required:**
- Line 37: Replace the entire PHASE 25 FENCE paragraph with the projection instruction block (one paragraph: project each dated-goal facet per D-01 confidence tiers, format per D-02).
- Line 47: Remove the `never a dated projection:` clause from the section heading; add a note that projection block follows the scorecard.
- Line 147: Replace `Never project to a deadline — report current/within-block movement only (Phase 25 fence)` with `Project to deadline per D-01 confidence tiers; on-track does not prescribe; behind = one ranked recommendation + "your call, Sir".`

### `_gather_week_data` phase-25 extension

The `_gather_week_data` function currently gathers 7 data sources (lines 75–250). The projection results become source #8. The `week_data` dict passed to `_compose_review` (line 326 `json.dumps(week_data)`) will include `"projections"` key which the brain reads.

### `_derive_structural_topics` extension

The `_derive_structural_topics` function (lines 255–272) currently derives only `structural-critique:session-quality`. It should be extended to also emit `structural-critique:projection:<facet>` for each facet that has projection data with ≥1 data point (baseline-only or better). These are written post-send via `CoachingTopicStore`.

### `run_weekly_review` post-send dedup write

The existing post-send loop (lines 376–391) iterates `week_data.get("coaching_topics_included")`. The projection topic keys should be included in `coaching_topics_included` so the same loop writes them without a new code path.

### `_compose_review` — no changes needed

The brain receives `week_data` as a JSON user message (line 326). The `"projections"` key will be visible to the brain. The prompt changes (fence lift) drive the behavior; the compose function itself does not need modification.

---

## `prompts/smart_agent.md` — Reactive Path

The `smart_agent.md` already contains (verified in the file):

1. **Tier A/B data-presence contract** — `dated_goals` are citable as targets; measured data requires recency windows.
2. **`get_benchmark_history` is already in `SMART_AGENT_DIRECT_TOOLS`** — the brain can call it directly.
3. **Reactive strict-pushback format** — the COACH-03/04 format is already documented.
4. **Current language:** "No dated 'N weeks behind' projection — directional only ('Oct pace slips', 'bench target gap widens')." This line must be updated in Phase 25 to permit the computed projection.

**Required smart_agent.md changes:**
- Update the "No dated 'N weeks behind' projection" restriction to: "When `get_goal_projection` data is available, cite the computed projection number. When data is absent, directional language only."
- Add a description of `get_goal_projection` tool to the TRAINING & ATHLETIC COACHING section (mirrors how `get_benchmark_history` is used).

---

## Phase-24 Strict-Coaching Compose Pattern (for "behind" prescription)

Verified in `prompts/proactive_alert.md` (Recovery-vs-Plan Conflict section, lines 103–117):

```
Format rules — exactly one ranked recommendation:
1. Cite the biometric fact with the literal number.
2. State the plan conflict plainly.
3. Give exactly ONE ranked recommendation — Klaus commits to the single best expert call.
4. End with "your call, Sir".
5. Never present a menu of options.
6. Never dictate. The form is "I'd do X — your call, Sir".
```

**Mirror for "behind" prescription in Phase 25:**
```
"behind" framing:
1. State projected number + gap in concrete units: "trend → 98kg by Oct 10, ~7kg behind the 105kg target."
2. Give exactly ONE ranked recommendation: "Closer: [one specific structural change]."
3. End with "your call, Sir."
4. On-track: state projected number only. Do NOT prescribe.
```

This is already specified in CONTEXT.md D-02 — Phase 25 mirrors it in the projection instruction block in the weekly review prompt.

---

## Common Pitfalls

### Pitfall 1: avg_pace Unit Ambiguity
**What goes wrong:** `activities.avg_pace` may be in min/km (Garmin convention) rather than sec/km (BenchmarkStore convention), causing a 60× error in the pace projection.
**Why it happens:** The field is stored verbatim from Garmin's `averagePace` export key without unit documentation in the codebase.
**How to avoid:** Derive pace from `duration_sec / distance_m * 1000` instead of reading `avg_pace`. This is always in sec/km and is unambiguous.
**Warning signs:** Computed `threshold_pace` projection gives a value like `4.03` instead of `241.7` — exactly a 60× discrepancy.

### Pitfall 2: Negative or Infinite Slope from Identical Timestamps
**What goes wrong:** If two benchmark entries share the same date (e.g., a correction rewrite), `(t_i - t_mean)^2 = 0` for all points → denominator = 0 → division by zero in LSQ slope.
**Why it happens:** `BenchmarkStore.log_benchmark` is idempotent on `{date}_{facet}` doc id, so duplicate-date entries are collapsed to one. But the pre-filtered history list from `get_facet_history` could theoretically return two entries with the same date from different blocks.
**How to avoid:** Deduplicate by date (keep most recent `value`) before fitting. Add a `den != 0` guard (already noted in the code example above).
**Warning signs:** `projected_value = NaN` or infinite float in the result JSON.

### Pitfall 3: Applying Projection to Non-Mapped Facets
**What goes wrong:** `3k_time` and `400m_time` appear in `dated_goals[1].metrics` but have no BenchmarkStore facet. Trying to project them throws a KeyError or produces silently incorrect results.
**Why it happens:** The `GOAL_METRIC_TO_FACET` mapping table doesn't include them — by design.
**How to avoid:** The projection helper iterates over the 5 known BenchmarkStore facets, not over `dated_goals.metrics` keys. Unmapped metrics are silently ignored.
**Warning signs:** `get_goal_projection("3k_time")` is called → BenchmarkStore raises ValueError for unknown facet.

### Pitfall 4: Writing CoachingTopicStore Before send_and_inject
**What goes wrong:** A false-positive block on later same-day crons if delivery failed.
**Why it happens:** Phase-24 D-10 invariant — write-after-send only.
**How to avoid:** The `_derive_structural_topics` function computes the keys at gather time for inclusion in `coaching_topics_included`, but the `CoachingTopicStore.add_topic` calls happen only inside `run_weekly_review` after `await send_and_inject()` succeeds.
**Warning signs:** The 21:30 cron silently skips a projection topic that wasn't actually sent.

### Pitfall 5: Removing the "Week N of 16" Framing
**What goes wrong:** Lifting the fence removes the block-relative framing that was there before it, losing the existing PROG-01 behavior.
**Why it happens:** The fence paragraph is adjacent to the within-block status section heading.
**How to avoid:** The fence line at line 37 is a standalone paragraph — remove just it. The "Week N of 16" framing in the section title above it is separate and must be preserved.

### Pitfall 6: `date.today()` Inside the Projection Helper
**What goes wrong:** During Sunday cron in Jerusalem at 10:00, `datetime.now(timezone.utc).date()` could return Saturday (UTC = 07:00 on Sunday in Israel). This is the CR-01 pattern from Phase 24.
**Why it happens:** UTC vs. Asia/Jerusalem offset.
**How to avoid:** The helper takes `today_iso: str` as a parameter. The caller (cron, tool handler) provides the Israel-time date string. The helper never calls `date.today()` or `datetime.now()`.

---

## Validation Architecture

`nyquist_validation: true` — this section is required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing, same as Phases 20–24) |
| Config file | pyproject.toml or pytest.ini (existing) |
| Quick run command | `python3 -m pytest tests/test_projection.py -x` |
| Full suite command | `python3 -m pytest tests/ -x` (per-file, not all-at-once — grpc GC issue with Python 3.13) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROG-02-A | `project_goal_progress` with 0 points → no_data result | unit | `pytest tests/test_projection.py::test_project_0_points -x` | ❌ Wave 0 |
| PROG-02-B | `project_goal_progress` with 1 point → baseline_only result | unit | `pytest tests/test_projection.py::test_project_1_point -x` | ❌ Wave 0 |
| PROG-02-C | `project_goal_progress` with 2 points → linear projection | unit | `pytest tests/test_projection.py::test_project_2_points -x` | ❌ Wave 0 |
| PROG-02-D | `project_goal_progress` with 3 points → least-squares | unit | `pytest tests/test_projection.py::test_project_3_points -x` | ❌ Wave 0 |
| PROG-02-E | Lower-is-better direction (threshold_pace) → on_track when projected <= target | unit | `pytest tests/test_projection.py::test_lower_is_better -x` | ❌ Wave 0 |
| PROG-02-F | Higher-is-better direction (bench) → on_track when projected >= target | unit | `pytest tests/test_projection.py::test_higher_is_better -x` | ❌ Wave 0 |
| PROG-02-G | HM time string "1:25:00" → correct sec/km target | unit | `pytest tests/test_projection.py::test_hm_time_conversion -x` | ❌ Wave 0 |
| PROG-02-H | `_gather_week_data` includes `projections` key (happy path, mocked) | integration | `pytest tests/test_weekly_training_review.py -x -k projection` | ❌ Wave 0 |
| PROG-02-I | `_gather_week_data` fails projection gracefully (returns `{}` key) | integration | `pytest tests/test_weekly_training_review.py::test_projection_gather_fails_open -x` | ❌ Wave 0 |
| PROG-02-J | `get_goal_projection` tool handler returns valid JSON | unit | `pytest tests/test_tool_registration_phase25.py -x` | ❌ Wave 0 |
| PROG-02-K | `get_goal_projection` in SMART_AGENT_DIRECT_TOOLS and not in WORKER_TOOL_SCHEMAS | unit | `pytest tests/test_tool_registration_phase25.py::test_tool_registration -x` | ❌ Wave 0 |
| PROG-02-L | Weekly review prompt no longer contains "PHASE 25 FENCE" text | unit | `pytest tests/test_prompts.py::test_no_phase25_fence -x` | ❌ Wave 0 |
| PROG-02-M | Projection topic keys derived by `_derive_structural_topics` for ≥1 benchmark facets | unit | `pytest tests/test_weekly_training_review.py::test_derive_projection_topics -x` | ❌ Wave 0 |
| PROG-02-N | Identical-date benchmark entries deduplicated before LSQ fit | unit | `pytest tests/test_projection.py::test_dedup_same_date -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python3 -m pytest tests/test_projection.py -x`
- **Per wave merge:** `python3 -m pytest tests/test_projection.py tests/test_weekly_training_review.py tests/test_tool_registration_phase25.py tests/test_prompts.py -x`
- **Phase gate:** Full suite (per-file) green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_projection.py` — covers PROG-02-A through PROG-02-G, PROG-02-N (pure function tests, no Firestore mock needed)
- [ ] `tests/test_tool_registration_phase25.py` — covers PROG-02-J, PROG-02-K (mirrors `test_tool_registration_phase23.py` pattern)
- [ ] `tests/test_prompts.py::test_no_phase25_fence` — new test added to existing file, covers PROG-02-L
- [ ] `tests/test_weekly_training_review.py` — new tests PROG-02-H, PROG-02-I, PROG-02-M added to existing file

---

## Security Domain

`security_enforcement` is not set to false — this section is required.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Internal cron; no new auth surface |
| V3 Session Management | No | No new sessions |
| V4 Access Control | No | Firestore read-only; same credentials as existing stores |
| V5 Input Validation | Yes | `facet` parameter validated against `_BENCHMARK_FACETS` frozenset (T-23-01 already enforces this in `BenchmarkStore.log_benchmark`; the tool handler must also validate before passing to the projection helper) |
| V6 Cryptography | No | No crypto operations |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM-injected facet name triggers invalid Firestore query | Tampering | Validate `facet` in `_handle_get_goal_projection` against `_BENCHMARK_FACETS` frozenset before calling projection helper or BenchmarkStore |
| Malformed `today_iso` causes date arithmetic exception | Tampering | Wrap `date.fromisoformat(today_iso)` in a try/except in the helper; return a no_data result rather than raising |
| Postgres SQL in pace trend gather uses no interpolation | Tampering | The SQL uses only hardcoded strings and Python date arithmetic on server-confirmed dates — no user input reaches the SQL query |
| Output to Telegram contains fabricated numbers | Information Disclosure | Numbers come only from the computed projection dict; brain receives JSON and frames it — does not re-compute |

**Overall threat surface:** Low. This phase reads internal stores and Garmin/Postgres historical data; output is Telegram text through the existing `send_and_inject` path. No new auth, no new secrets, no new network endpoints.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `activities.avg_pace` is stored in min/km (Garmin convention) — derives from common Garmin export format but not confirmed by authoritative docs in this session | Garmin Pace Trend section | 60× unit error in any code that reads avg_pace directly; mitigated by recommending derived pace from duration_sec/distance_m instead |
| A2 | The Garmin zip ingest `averagePace` field (from `entry.get("averagePace")`) is populated for running activities in real export data | Garmin Pace Trend section | If NULL for most runs, the dense pace trend fallback becomes sparse; project from BenchmarkStore instead |

**Risk mitigation for A1/A2:** The research recommends deriving pace as `duration_sec / distance_m * 1000` (always sec/km, unit-unambiguous) rather than reading `avg_pace`. If the planner follows this recommendation, both assumptions become irrelevant.

---

## Open Questions

1. **Garmin `avg_pace` units in real export data**
   - What we know: the column exists, is NUMERIC(5,2), populated from `entry.get("averagePace")`
   - What's unclear: whether real Garmin exports produce min/km (e.g. 4.03) or sec/km (e.g. 241.8) for the `averagePace` JSON key
   - Recommendation: use the derived formula `duration_sec / distance_m * 1000` and skip reading `avg_pace` entirely — resolves the ambiguity without needing to probe live data

2. **Block end dates for projection timeline context**
   - What we know: blocks have `end_date` in BlockStore; the projection needs the deadline date (Oct 31 / Nov 30) from `dated_goals`
   - What's unclear: whether the Sunday review prompt should also note "Block 1 ends 2026-07-18 → benchmark due" alongside "Oct target ~7kg away"
   - Recommendation: the per-deadline projection is independent of block boundaries; the within-block framing already handles block end dates; the planner should not merge the two

3. **`3k_time` and `400m_time` November goals**
   - What we know: these appear in `dated_goals[1].metrics` but have no BenchmarkStore facet
   - What's unclear: whether the user expects Klaus to project these in Phase 25
   - Recommendation: explicitly out of scope per CONTEXT.md ("no new benchmark facets" is deferred); Klaus should acknowledge the November speed goals exist but note they require a benchmark facet to project — flag in the weekly review prompt instruction

---

## Environment Availability

No new external dependencies. All existing infrastructure confirmed operational (Phase 24 live, 1027 tests passing, deployed at image f25042f).

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Firestore (BenchmarkStore) | Projection data source | ✓ | Existing | — |
| Postgres (`activities` table) | Pace trend dense path | ✓ | Existing | BenchmarkStore sparse path |
| CoachingTopicStore | Post-send dedup | ✓ | Phase 24 | — |
| Python `statistics` / built-ins | LSQ computation | ✓ | stdlib | — |

---

## Sources

### Primary (HIGH confidence — verified directly in codebase)

- `memory/firestore_db.py:1824–1965` — `BenchmarkStore` class: `log_benchmark`, `get_facet_history`, `get_block_benchmarks`, doc schema, `_BENCHMARK_FACETS` frozenset, verified 2026-06-07
- `memory/firestore_db.py:93–205` — `UserProfileStore`: `dated_goals` scaffold + `load()` signature, verified 2026-06-07
- `memory/firestore_db.py:766–930` — `TrainingLogStore.log_session`: confirmed NO load/weight field, verified 2026-06-07
- `memory/firestore_db.py:1413–1524` — `CoachingTopicStore`: `has_topic`, `add_topic`, `topics_today` API + write-after-send discipline, verified 2026-06-07
- `scripts/ingest_blueprint.py:62–82` — exact `dated_goals` stored shape (target_date ISO string, metric keys, values), verified 2026-06-07
- `scripts/ingest_garmin_zip.py:36–65` — Postgres `activities` table schema (`avg_pace NUMERIC(5,2)`, `duration_sec`, `distance_m`, `type`), verified 2026-06-07
- `core/weekly_training_review.py` — full `_gather_week_data`, `_compose_review`, `run_weekly_review` compose path; dedup write-after-send pattern (lines 376–391), verified 2026-06-07
- `prompts/weekly_training_review.md` — fence line locations (37, 47, 147), prompt structure, verified 2026-06-07
- `core/tools.py:40–69` — `SMART_AGENT_DIRECT_TOOLS` frozenset; `get_benchmark_history` registration; `_HANDLERS` at line 1868; worker exclusion set 1019–1051, verified 2026-06-07
- `prompts/proactive_alert.md:103–117` — COACH-04 exactly-one-ranked-rec compose pattern, verified 2026-06-07
- `prompts/smart_agent.md` — Tier A/B contract; current "no dated projection" language to update; `get_benchmark_history` usage, verified 2026-06-07
- `mcp_tools/garmin_tool.py:297–348` — `fetch_garmin_activities`: confirmed returns `duration_sec`, `distance_m`, NO derived `avg_pace`; running type strings `"running"`, `"trail_running"`, `"treadmill_running"`, verified 2026-06-07
- `tests/test_benchmark_store.py` — test fixture shapes (doc fields, facet names), verified 2026-06-07
- `.planning/phases/24-strict-coaching-integration-nutrition-accountability/24-CONTEXT.md` — COACH-05 dedup decisions, CR-01 tz bug pattern, verified 2026-06-07

### Tertiary (LOW confidence — flagged as ASSUMED)

- `avg_pace` unit in Garmin export (min/km assumed from Garmin convention, not confirmed) — see A1

---

## Metadata

**Confidence breakdown:**
- Data reality (BenchmarkStore, dated_goals, TrainingLogStore): HIGH — verified in code
- Weekly review integration path: HIGH — verified line by line
- Projection math approach (linear LSQ): HIGH — standard statistics, appropriate for sparse data
- Garmin pace dense path (Postgres): HIGH — schema verified; avg_pace unit ASSUMED
- Security threat surface: HIGH — low surface area, existing patterns cover it

**Research date:** 2026-06-07
**Valid until:** 2026-07-07 (stable codebase; valid until next milestone cycle)
