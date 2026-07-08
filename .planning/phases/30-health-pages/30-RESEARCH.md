# Phase 30: Health Pages - Research

**Researched:** 2026-07-06
**Domain:** Read-only data-visualization pages in an existing React/FastAPI hub (charting introduced for the first time), reading from established Firestore stores + a Postgres biometrics table
**Confidence:** HIGH

## Summary

Phase 30 is almost entirely an *integration* phase, not a new-technology phase. Every
data source it needs (`StrengthSessionStore`, `RunDetailStore`, `BenchmarkStore`,
`BlockStore`, `MealStore`, Postgres `daily_biometrics`) already exists and is populated
by crons shipped in v3.0/v4.0 and the post-v4.0 increments. The only genuinely new
piece of infrastructure is a small hand-rolled SVG chart toolkit — the UI-SPEC has
**already decided** (D-04 discretion, resolved) to build `LineChart`/`BarChart`/
`ChartTooltip`/`ChartCard` from scratch rather than add a dependency, matching the
hub's established "no external UI libraries" philosophy (`ContributionGrid.tsx` did
the same for the habit grid in Phase 28). This means **no new npm package is added
in this phase** — the Package Legitimacy Audit is a no-op.

The three backend read paths differ in maturity: (1) Training history has three
mature per-record stores but **`BenchmarkStore` has no date-range query method** —
only `get_facet_history(facet, n)` and `get_block_benchmarks(block_id)` — a new
`get_range(start, end)` method (or equivalent) must be added. (2) Nutrition has a
ready-made server-computed precedent (`_handle_fetch_nutrition_trend` in
`core/tools.py`) but it loops **one Firestore read per calendar day** capped at 60
days — this does not scale to the phase's 90d/1y presets and must be re-architected
(batch reads or accept the cost, see Pitfall 1). (3) Sleep/recovery's data source,
Postgres `daily_biometrics`, is fully built and column-complete, but the Cloud
Scheduler job that feeds it (`klaus-biometric-sync`) may not yet be registered in
production — the UI-SPEC already designed a "pipeline isn't syncing yet" guard for
exactly this contingency, so this is a known, already-mitigated risk, not a blocker.

**Primary recommendation:** Build three new `/api/health/*` endpoints under
`interfaces/web_server.py` following the `/api/today` aggregator pattern exactly
(`run_in_executor` + `asyncio.gather`, `_jsonsafe_doc` on all Firestore output,
never block the event loop on the Postgres read), each returning pre-aggregated
`{x, y}` series (daily for ≤90d, weekly-bucketed for >90d per D-07) so the new
hand-rolled `LineChart`/`BarChart` components can render without any client-side
math — mirroring the `fetch_nutrition_trend` "server computes, client renders"
precedent the project has already established and re-learned the cost of violating
(the 2026-06-09 drifting-numbers incident).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Segmented sub-tabs + range toggles (client state) | Browser / Client | — | Pure UI state (`localStorage` for tab, `useState` for range) — no server round-trip needed for the toggle itself |
| Training/nutrition/sleep aggregate series computation | API / Backend | — | Server-computed aggregates (weekly bucketing, averages, gap markers) — mirrors `fetch_nutrition_trend`; client must never re-derive totals (drifting-numbers lesson) |
| Chart rendering (SVG line/bar, tooltips, gap rendering) | Browser / Client | — | Pure presentation of already-aggregated `{x,y}` points; D-08 gap semantics implemented in the SVG path-splitting logic |
| Strength/run/benchmark/block reads | API / Backend | Database / Storage | Firestore stores already exist; API composes/interleaves them (mirrors `/api/today` composition) |
| Sleep/recovery reads | API / Backend | Database / Storage | Postgres `daily_biometrics` — new typed read function needed (extend `recovery_metrics.fetch_biometric_rows` pattern with date-range + full column set), run via executor |
| Session auth | API / Backend | — | `require_hub_session` (existing HUB-01 dependency) gates all new `/api/health/*` routes — no new auth logic |
| Biometric ingest (out of scope) | API / Backend (cron) | Database / Storage | `core/biometric_ingest.py` / `/cron/biometric-sync` already ships the data; this phase only reads it |

## Standard Stack

### Core

No new runtime dependencies. The phase extends the existing stack:

| Library | Version (installed) | Purpose | Why Standard (for this codebase) |
|---------|---------|---------|--------------|
| React | ^19.2.7 | UI | Already the hub's framework (Phase 26) |
| TypeScript | ^6.0.3 | Type safety | Already project-wide |
| Vite | ^8.0.16 | Build/dev server | Already project-wide |
| Tailwind CSS | ^4.3.1 | Utility layout only (no component classes for colors — inline styles from `tokens.ts`) | Established Phase 26 convention |
| @tanstack/react-query | ^5.101.0 | Server-state fetching/caching for the three new endpoints | Established pattern (`useToday`, `useHabits`, `useTaskSummary`) |
| lucide-react | ^1.18.0 | Icons (modality badges etc.) | Already a dependency |
| FastAPI | (existing, see `interfaces/web_server.py`) | New `/api/health/*` routes | Existing hub API framework |
| psycopg2 | (existing, used by `mcp_tools/garmin_tool.py`, `mcp_tools/database_tool.py`) | Postgres reads for the sleep/recovery page | Already the project's only Postgres driver |

**No `npm install` / `pip install` command is needed for this phase.** [VERIFIED: repo inspection — `frontend/package.json` has zero chart/graphing packages as of this research; confirmed via `git diff` that the only pending frontend dependency change in the working tree (react-markdown/remark-*) is for an unrelated in-flight feature, not charting]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| react-router-dom | ^7.17.0 | `/health` route already registered (`frontend/src/App.tsx` line ~192) | No change needed — swap `ComingSoon` for the real page component |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled SVG chart toolkit (chosen, per UI-SPEC) | Recharts (~90KB+ gzip) | More features (zoom/pan) not needed per D-04; adds PWA precache weight for a single phase; contradicts the hub's zero-new-dependency precedent set by `ContributionGrid` |
| Hand-rolled SVG chart toolkit (chosen) | visx (d3-wrapper) | Steeper API, heavier than needed for 3 chart types with no interactivity beyond tap/hover tooltips |
| One `get_range`-style method per Firestore store | A single generic "query any store by date range" helper | Each store's ID scheme differs (workout_id vs activity_id vs `{date}_{facet}`) — a generic helper would need per-store branching anyway; adding a typed method per store (matching `StrengthSessionStore.get_range` / `RunDetailStore.get_range` convention already in the codebase) is more consistent with existing code style |

**Installation:** none required.

## Package Legitimacy Audit

**Not applicable this phase.** No external packages are being installed — the UI-SPEC
(§ Design System, "Chart library decision") has already resolved Claude's Discretion
item on chart library choice in favor of a hand-rolled internal SVG toolkit with zero
new dependencies, extending the same pattern `ContributionGrid.tsx` established in
Phase 28. If the planner later decides a chart library is truly needed after all,
re-run this gate before adding it — but per the locked UI-SPEC, that should not happen
in this phase.

## Architecture Patterns

### System Architecture Diagram

```
Browser (React SPA, /health route)
  │
  ├─ HealthPage → SubTabs (Training|Nutrition|Sleep, localStorage-persisted)
  │     │
  │     ├─ TrainingHistoryPage ──┐
  │     ├─ NutritionDetailPage ──┼─ each owns its own RangeToggle (7d/30d/90d/1y,
  │     └─ SleepRecoveryPage    ─┘  NOT persisted, default 30d) + react-query
  │
  │  useQuery(['health', <tab>, <range>]) via apiFetch()
  ▼
FastAPI (interfaces/web_server.py, same Cloud Run service)
  │
  ├─ GET /api/health/training?range=30d  (Depends(require_hub_session))
  │     │  asyncio.gather(run_in_executor(...) × N)
  │     ├─ StrengthSessionStore.get_range(start,end)   [Firestore]
  │     ├─ RunDetailStore.get_range(start,end)         [Firestore]
  │     ├─ BenchmarkStore.get_range(start,end)  ← NEW METHOD NEEDED [Firestore]
  │     └─ BlockStore.get_all()  (resolve block dividers by date overlap) [Firestore]
  │     → merge, sort reverse-chronological, weekly-bucket the 2 trend series (D-07),
  │       _jsonsafe_doc, return
  │
  ├─ GET /api/health/nutrition?range=30d
  │     │  run_in_executor
  │     ├─ MealStore.get_day_aggregate(d) looped per day IN RANGE  [Firestore]
  │     │    (mirrors _handle_fetch_nutrition_trend — needs re-architecture
  │     │     for 90d/1y ranges, see Pitfall 1)
  │     └─ UserProfileStore.load().nutrition_targets              [Firestore]
  │     → per-day series (or weekly-bucketed for >90d) + slot-adherence grid +
  │       averages + protein g/kg, _jsonsafe_doc, return
  │
  └─ GET /api/health/sleep?range=30d
        │  run_in_executor (event-loop-blocking guard — CLAUDE.md invariant)
        └─ NEW typed Postgres reader (extends recovery_metrics.fetch_biometric_rows
           pattern: date range not just "last N days"; full column set including
           body_battery_max, sleep_duration, training_readiness, vo2_max)
              [Postgres daily_biometrics]
        → daily or weekly-bucketed series per metric + "pipeline never populated"
          flag (distinct from "no rows in range") + header-stat row from the
          latest row, return
```

### Recommended Project Structure

```
frontend/src/
├── components/
│   ├── charts/                    # NEW — shared across all 3 pages
│   │   ├── LineChart.tsx
│   │   ├── BarChart.tsx
│   │   ├── ChartTooltip.tsx
│   │   ├── ChartCard.tsx
│   │   └── ChartEmptyState.tsx
│   └── health/                    # NEW
│       ├── SubTabs.tsx
│       ├── RangeToggle.tsx
│       ├── training/
│       │   ├── TrainingHistoryPage.tsx
│       │   ├── TrainingTrendCharts.tsx
│       │   ├── TrainingLog.tsx
│       │   ├── TrainingLogEntry.tsx
│       │   ├── BlockDivider.tsx
│       │   ├── StrengthDrilldownSheet.tsx
│       │   ├── RunDrilldownSheet.tsx
│       │   └── BenchmarkDrilldownSheet.tsx
│       ├── nutrition/
│       │   ├── NutritionDetailPage.tsx
│       │   ├── MacroChipRow.tsx
│       │   ├── MacroTrendChart.tsx
│       │   ├── SlotAdherenceGrid.tsx
│       │   └── DayDrilldownSheet.tsx
│       └── sleep/
│           ├── SleepRecoveryPage.tsx
│           ├── HeaderStatRow.tsx
│           ├── HRVChart.tsx
│           ├── SleepChart.tsx
│           └── BodyBatteryChart.tsx
├── api/
│   └── health.ts                  # NEW — fetchTrainingHistory/fetchNutritionDetail/fetchSleepRecovery
└── hooks/
    └── useHealth.ts               # NEW — useTrainingHistory/useNutritionDetail/useSleepRecovery (react-query)

interfaces/web_server.py           # + 3 new route handlers, + 3 private composition functions
                                    # (mirroring _today_* helper functions already in this file)
memory/firestore_db.py             # + BenchmarkStore.get_range(start, end) [new method]
core/recovery_metrics.py           # (reference pattern only — do not modify; new Postgres
                                    # reader for the health page lives alongside it or in
                                    # a new small module, e.g. core/health_reads.py)
```

### Pattern 1: Server-side aggregation, client-side pure rendering

**What:** Every number the chart displays (averages, weekly buckets, gap markers,
targets) is computed in the FastAPI handler. The React chart components receive
`{x: string, y: number | null}[]` and render exactly that — no summing, averaging,
or bucketing in the browser.

**When to use:** All three health pages, all charts, all summary rows.

**Example (existing precedent to extend, not reinvent):**
```python
# Source: core/tools.py, _handle_fetch_nutrition_trend (~line 2302)
for i in range(days - 1, -1, -1):  # oldest → newest
    d = (today - timedelta(days=i)).isoformat()
    agg = ms.get_day_aggregate(d)
    if agg:
        series.append({"date": d, **{k: agg["totals"].get(k) for k in macro_keys}})
    else:
        missing_dates.append(d)  # D-08: never a zero-fill
```

### Pattern 2: `/api/today`-style executor composition for a new aggregator route

**What:** FastAPI route handler resolves the event-loop-safety invariant (CLAUDE.md
§6: never block the event loop in request handlers) by running every synchronous
Firestore/Postgres call through `loop.run_in_executor(None, fn, *args)`, gathered
with `asyncio.gather`.

**When to use:** All 3 new `/api/health/*` handlers.

**Example:**
```python
# Source: interfaces/web_server.py, api_today() (~line 1446)
loop = asyncio.get_running_loop()
(calendar_data, garmin_data, ...) = await asyncio.gather(
    loop.run_in_executor(None, _today_calendar, today_iso),
    loop.run_in_executor(None, _today_garmin),
    ...
)
payload = _jsonsafe_doc({...})
return JSONResponse(content=payload)
```

### Pattern 3: Hand-rolled SVG grid (contribution-grid precedent for D-13's slot-adherence grid)

**What:** `display: grid` CSS, no chart library, `grid-auto-flow: column` so each
column is a day (mirrors `ContributionGrid`'s "each column is a week"), 12×12px
cells with a 2px gap (named spacing exception — do not round up to 4px).

**When to use:** `SlotAdherenceGrid.tsx` (D-13) — the UI-SPEC explicitly directs
reusing this exact convention, 2-state (hit/miss) instead of 4-state.

**Example:**
```typescript
// Source: frontend/src/components/habits/ContributionGrid.tsx (Phase 28)
<div
  role="grid"
  style={{
    display: 'grid',
    gridTemplateColumns: `repeat(${numCols}, 12px)`,
    gridTemplateRows: 'repeat(7, 12px)',
    gridAutoFlow: 'column',
    gap: '2px',
  }}
>
```
Note: the slot-adherence grid's rows are *fueling slots* (not weekdays) and columns
are *days in range* (not weeks) — the layout math (leading pad, column count) needs
adapting, not copy-pasted verbatim; only the visual/density convention transfers.

### Anti-Patterns to Avoid

- **Reimplementing `fetch_nutrition_trend`'s math client-side:** the nutrition page
  must call a server endpoint that returns the same averages/targets/`missing_dates`
  shape — do not ship raw `MealStore.get_day` docs to the client and sum in
  TypeScript (this is the exact mistake the 2026-06-09 drifting-numbers incident
  was about, just relocated to the frontend).
- **A single generic Firestore date-range query helper across 3 differently-shaped
  stores:** `StrengthSessionStore`/`RunDetailStore` already have `get_range`;
  `BenchmarkStore` does not. Add the missing method in the same style as the
  existing two rather than building a generic cross-store abstraction — consistency
  with the established per-store method pattern matters more than DRY here.
- **Computing the "7-day rolling HRV baseline" (D-18) via a fresh client-side
  or ad-hoc server rolling-window calculation:** `daily_biometrics.hrv_baseline`
  is Garmin's own weekly-average field, already written by
  `write_biometrics_to_postgres` and already used as the baseline source in
  `core/recovery_metrics.py`. Reuse that column; do not recompute a rolling
  average from `hrv_overnight` unless the column is confirmed sparse (see Open
  Questions).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Server-computed nutrition averages/targets/gaps | A new from-scratch aggregation algorithm | Extract/share logic from `core/tools.py::_handle_fetch_nutrition_trend` | Already handles the missing-dates-not-zero semantics (D-08) and the protein-g/kg-bodyweight calc (D-15) correctly; a parallel reimplementation risks the two drifting apart |
| Firestore timestamp → JSON serialization | Custom per-field `isoformat()` calls scattered through new handlers | `memory.firestore_db._jsonsafe_doc` | Already recursively handles nested dicts/lists (profile's `weekly_split`/`fueling_timeline` bit this exact bug in Phase 21, WR-21-03) |
| Weekly bucketing for >90-day ranges (D-07) | A generic date-bucketing library | Simple Python `isocalendar()`-keyed grouping in the new handler (small, testable, no dependency justified for 3 call sites) | The dataset (≤365 daily points → ~52 weekly points) is small enough that a library adds more surface area than it saves |
| Chart rendering with gap semantics | A general-purpose charting library configured to suppress interpolation | Hand-rolled `LineChart`/`BarChart` (UI-SPEC-locked decision) | No common charting library treats "never zero-fill, never interpolate a `null`" as a first-class primitive without fighting its API — this is called out explicitly in the UI-SPEC's own rationale |
| Postgres connection handling for the sleep read | A new connection pool / ORM | `psycopg2.connect(dsn)` inline (mirrors `recovery_metrics.fetch_biometric_rows` and `garmin_tool.write_biometrics_to_postgres`) | Matches the existing one-connection-per-call pattern already used successfully elsewhere in this codebase; introducing pooling for a single low-QPS read endpoint is unwarranted scope |

**Key insight:** This phase's biggest risk is *inconsistency with itself* (three
pages built by re-deriving math three slightly different ways), not missing
tooling. Every "don't hand-roll" item above is really "don't hand-roll a second
time" — the correct algorithm already exists once in this codebase; the job is
extraction/reuse, not invention.

## Common Pitfalls

### Pitfall 1: `MealStore` has no range-read method — the existing trend pattern doesn't scale to 1 year

**What goes wrong:** `_handle_fetch_nutrition_trend` loops one `get_day_aggregate`
Firestore call per calendar day, clamped to a 60-day max `[VERIFIED: core/tools.py
line ~2313, "days = max(1, min(int(days), 60))"]`. The nutrition page's `1y` preset
needs ~365 day-buckets (or ~52 week-buckets per D-07, but computing those 52 weekly
averages still requires reading all 365 underlying days unless a different strategy
is used).

**Why it happens:** `MealStore` is architected per-day (`meals/{date}/timestamps/*`)
with no cross-day range query — by design, since each day is its own sub-collection.

**How to avoid:** For ranges >90 days, either (a) accept ~365 sequential Firestore
reads per request (slow but correct — consider adding a short server-side cache,
e.g. the `_routes_cache` module-level TTL pattern already used for `/api/today`'s
Routes API calls), or (b) only compute the weekly-bucketed points from a sampled
subset (e.g. one read per day is unavoidable for a true weekly average, so caching
is the more honest lever than sampling). Do NOT silently reduce accuracy by skipping
days without labeling it — D-08's "missing ≠ zero" contract must hold even under a
sampling strategy if one is chosen.

**Warning signs:** A `1y` range toggle taking multiple seconds to respond, or Cloud
Run request timeouts on the nutrition endpoint specifically (the training/sleep
endpoints don't have this problem — `StrengthSessionStore`/`RunDetailStore` support
true `get_range` queries, and the Postgres reader is one indexed query for the whole
range).

### Pitfall 2: `BenchmarkStore` cannot be queried by date range today

**What goes wrong:** Only `get_facet_history(facet, n)` (single facet, N-newest) and
`get_block_benchmarks(block_id)` exist `[VERIFIED: memory/firestore_db.py lines
2349-2403]`. The training log needs "all benchmarks in [start, end] across all 5
facets" to interleave them into the mixed log (D-09/D-12).

**Why it happens:** `BenchmarkStore` was built in Phase 23 for facet-progression
lookups (`get_facet_history`) and block-scoped review (`get_block_benchmarks`) — a
cross-facet date-range query was never a prior use case.

**How to avoid:** Add `BenchmarkStore.get_range(start_date, end_date)` following the
exact pattern already used by `StrengthSessionStore.get_range` /
`RunDetailStore.get_range` (server-side `>=`/`<=` filter on the `date` field,
`order_by("date", direction=_DESCENDING)`, never-raises/return-`[]`-on-error
discipline). This is a small, low-risk, additive change to an existing store class.

**Warning signs:** Planner writes a task that tries to reuse `get_facet_history`
in a loop over all 5 facets for the training log — this works but is 5 Firestore
scans instead of 1 range query; flag this as a code-smell during plan-check if seen.

### Pitfall 3: Blocking the event loop on the new Postgres sleep/recovery read

**What goes wrong:** A naive `@app.get("/api/health/sleep")` handler that calls
`psycopg2.connect(...)` synchronously inside `async def` blocks the single event
loop thread for the duration of the DB round-trip — this is the exact bug class
behind the documented 2026-06-24 weekly-review-500 incident (`project memory:
"blocking gather+compose on the event loop starved the Telegram send"`).

**Why it happens:** `psycopg2` (used throughout this codebase — `database_tool.py`,
`garmin_tool.py`, `recovery_metrics.py`) is a synchronous driver; there is no
async Postgres client anywhere in this project.

**How to avoid:** Wrap the Postgres read in `loop.run_in_executor(None, fn, ...)`,
exactly like `cron_biometric_sync` already does for `_biometric.run_one_batch`
`[VERIFIED: interfaces/web_server.py lines 883-893]` and exactly as the UI-SPEC's
own "Backend integration points" note already calls out ("watch connection reuse +
event-loop blocking — run DB calls in an executor").

**Warning signs:** Sleep-page endpoint response times spike specifically when
another request (chat turn, cron) is concurrently in flight — a sign the event
loop is being starved.

### Pitfall 4: `daily_biometrics` may have zero rows in production right now

**What goes wrong:** `klaus-biometric-sync` is documented in `docs/DEPLOYMENT.md`
(§19, job #12, `30 5 * * *`) but per project memory the actual `gcloud scheduler
jobs create` step may not have been run yet, and `CLAUDE.md §5`'s "live
infrastructure" list (checked as part of this research) does **not** currently
mention `klaus-biometric-sync` among the deployed jobs — only heartbeat,
morning-briefing, chat-ingest/export, nightly-backstop, autonomous-tick,
weekly-training-review, strength-sync, run-sync `[CITED: CLAUDE.md §5, this
repo's checked-in project instructions]`. If the scheduler job was never created
(or was created but the 90-day backfill hasn't drained), the sleep page's own data
source could return **zero rows entirely**, not just gaps in the selected range.

**Why it happens:** This is a genuine deploy-sequencing risk flagged by the
project's own prior session (30-CONTEXT.md canonical refs), not a research
artifact — the phase context already anticipated it.

**How to avoid:** This is **already handled** at the UI-SPEC level — the
"pipeline-not-live guard" (D-06-style) renders "Sleep & recovery data isn't
syncing yet." distinctly from the normal empty-range state. The backend endpoint
contract must expose a boolean (e.g. `pipeline_active: bool`, true once at least
one row has ever been written) alongside the series data so the frontend can
distinguish "cron never ran" from "no data in this specific 7d/30d/90d/1y window."
Confirm the scheduler job is live (`gcloud scheduler jobs list`) as an operator
step before UAT'ing the Sleep page — this is an operational verification step,
not a code task.

### Pitfall 5: `hrv_baseline` may itself be sparse if it was only ever written by the morning-briefing (not the backfill)

**What goes wrong:** `write_biometrics_to_postgres` writes whatever
`fetch_garmin_daily`/`fetch_garmin_today` returns for `hrv_baseline` — if Garmin's
own weekly-average field is frequently `None` for backfilled historical days (a
common Garmin Connect quirk: rolling averages are often only populated going
forward from when a metric starts being tracked, not retroactively), the D-18
"7-day rolling baseline" overlay series would render mostly gaps for older ranges.

**Why it happens:** Untested assumption — this research did not have live
production data to inspect the actual sparsity of `hrv_baseline` across the
~90-day backfill window.

**How to avoid:** During implementation, query the actual `daily_biometrics` table
(`SELECT date, hrv_overnight, hrv_baseline FROM daily_biometrics ORDER BY date`) to
check `hrv_baseline` fill-rate before committing to "use the column as-is." If it's
sparse, the fallback is a locally-computed rolling median of `hrv_overnight`
(the exact logic `core/recovery_metrics.compute_recovery_deviation` already uses
as its own fallback: `median(prior_hrv) if prior_hrv else None`) — reuse that
fallback logic rather than inventing new rolling-window math.

**Warning signs:** The HRV baseline line on the Sleep page renders as mostly gaps
for the 90d/1y presets even when `hrv_overnight` data is dense.

## Code Examples

### Extending a store with a range-query method (Pitfall 2 fix, matching existing convention)

```python
# Source: pattern extracted from memory/firestore_db.py RunDetailStore.get_range
# (~line 1303) — apply the identical shape to BenchmarkStore.
def get_range(self, start_date: str, end_date: str) -> list[dict]:
    """Return benchmarks with date in [start_date, end_date], newest-first.

    Never raises — returns [] on any Firestore error.
    """
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        snaps = list(
            self._col
            .where(filter=FieldFilter("date", ">=", start_date))
            .where(filter=FieldFilter("date", "<=", end_date))
            .stream()
        )
        results = [
            {**_jsonsafe_doc(snap.to_dict() or {}), "doc_id": snap.id}
            for snap in snaps
        ]
        results.sort(key=lambda d: d.get("date", ""), reverse=True)
        return results
    except Exception:
        logger.warning(
            "BenchmarkStore.get_range(%r, %r) failed", start_date, end_date, exc_info=True,
        )
        return []
```
Note: `get_block_benchmarks` already uses `FieldFilter` (not the module's `_where`
helper used by `StrengthSessionStore`/`RunDetailStore`) — either query builder works
on this Firestore SDK version; match whichever convention the immediately
surrounding class already uses for internal consistency.

### A new typed Postgres range reader for the Sleep page (extends `recovery_metrics.fetch_biometric_rows`)

```python
# Pattern source: core/recovery_metrics.py fetch_biometric_rows (~line 39) +
# mcp_tools/database_tool.py's read-only-session convention (~line 104).
def fetch_biometric_range(start_date: str, end_date: str) -> list[dict]:
    """Read daily_biometrics rows in [start_date, end_date]. Never raises."""
    try:
        import psycopg2
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")
        if not dsn:
            return []
        with psycopg2.connect(dsn, connect_timeout=5) as conn:
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date::date, resting_hr, hrv_baseline, hrv_overnight, "
                    "sleep_score, sleep_duration, body_battery_max, "
                    "training_readiness FROM daily_biometrics "
                    "WHERE date >= %s AND date <= %s ORDER BY date ASC",
                    (start_date, end_date),
                )
                rows = cur.fetchall()
        return [
            {
                "date": r[0].isoformat(),
                "resting_hr": r[1], "hrv_baseline": r[2], "hrv_overnight": r[3],
                "sleep_score": r[4], "sleep_duration": r[5],
                "body_battery_max": r[6], "training_readiness": r[7],
            }
            for r in rows
        ]
    except Exception:
        logger.warning("fetch_biometric_range failed", exc_info=True)
        return []
```

### React Query hook for a range-scoped health endpoint (mirrors `useToday`)

```typescript
// Pattern source: frontend/src/hooks/useToday.ts
export function useTrainingHistory(range: RangeKey) {
  return useQuery<TrainingHistoryData, Error>({
    queryKey: ['health', 'training', range],
    queryFn: () => fetchTrainingHistory(range),
    staleTime: 5 * 60 * 1000,       // 5 min — historical data, not intraday
    refetchOnWindowFocus: true,     // pick up newly-synced cron data
  })
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| No chart infrastructure in the hub | Hand-rolled SVG chart toolkit (`LineChart`/`BarChart`/`ChartTooltip`/`ChartCard`) | This phase (30-UI-SPEC, 2026-07-06) | First charting capability in Klaus Hub; sets the precedent future phases will likely reuse rather than adding a library later |
| `daily_biometrics` written only by the morning briefing (today-row only) | Daily `/cron/biometric-sync` backfill+delta pipeline (`core/biometric_ingest.py`) | 2026-07-05/06 (per project memory: "biometric-sync cron shipped") | Enables true historical HRV/sleep/body-battery trend charts — was not possible before this increment |

**Deprecated/outdated:** None applicable — all data sources are current, actively
maintained stores from the last 4-6 weeks of development.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The "7-day rolling HRV baseline" (D-18) should read the existing `hrv_baseline` Postgres column (Garmin's own weekly average) rather than being locally recomputed | Pitfall 5, Anti-Patterns | If `hrv_baseline` is sparse in practice, the HRV chart's second line renders mostly gaps for older ranges until a fallback (median of `hrv_overnight`) is implemented — low severity, self-evident from a quick data check during implementation |
| A2 | `klaus-biometric-sync`'s Cloud Scheduler job may not yet be live in production | Pitfall 4 | If it IS already live, this note is simply unnecessary caution and the pipeline-not-live guard never fires — no functional harm either way, since the guard is already part of the locked UI-SPEC |
| A3 | Adding `BenchmarkStore.get_range()` is a safe, additive change with no migration needed | Pitfall 2, Code Examples | Low risk — it's a new read method on an existing collection; no schema change, no write-path change |
| A4 | `nutrition_targets` includes a `calories` key (not just macro grams) sufficient for the D-15 calories target reference line | Standard Stack / D-15 | If the profile only stores macro-gram targets and not a calorie target, the calories chart's target line would need to be derived (protein×4 + carbs×4 + fat×9) rather than read directly — verify the actual `nutrition_targets` dict shape in `UserProfileStore` during implementation (this research found the schema comment `{protein_g, carbs_g, ...}` but did not enumerate a live profile document) |

**If this table is empty:** N/A — see above, 4 assumptions logged.

## Open Questions (RESOLVED)

> All three resolved during planning — each is self-mitigated in Phase 30 plans, no blocker remains:
> - Q1 (calories-key): 30-02 Task 2 reads a stored calories target if present, else derives it (protein_g*4 + carbs_g*4 + fat_g*9) and tags `calories_target_derived`. [VERIFIED during planning: `nutrition_targets` has protein_g_per_kg/protein_g_floor/fiber_g_floor, NO literal `calories` key — derivation path is the one used.]
> - Q2 (biometric-sync liveness): 30-02 Task 3 exposes `pipeline_active` and 30-07 Task 2 renders the "isn't syncing yet" placeholder; confirmed as a pre-UAT operator step in 30-08 Task 3.
> - Q3 (hrv_baseline sparsity): 30-02 Task 3 falls back to a rolling median of hrv_overnight (reusing recovery_metrics' fallback) with a dedicated `-k baseline_fallback` test.

1. **Does `nutrition_targets` in `UserProfileStore` include a `calories` key, or only macro grams?**
   - What we know: the schema docstring in `memory/firestore_db.py` (~line 183)
     says `nutrition_targets (dict) — Daily macro targets: {protein_g, carbs_g, ...}`
     — the `...` is ambiguous on whether `calories` is a stored key or a derived value.
   - What's unclear: whether the D-15 calories target reference line reads a stored
     field or must be computed from the macro targets.
   - Recommendation: read one real `UserProfileStore.load()` result during
     implementation (or grep any place that already writes `nutrition_targets`,
     e.g. the v4.0 seeding script) before wiring the calories chart's target line.

2. **Is the `klaus-biometric-sync` Cloud Scheduler job actually registered and has its backfill drained?**
   - What we know: the code path (`/cron/biometric-sync`) is deployed and correct;
     `docs/DEPLOYMENT.md` documents the `gcloud scheduler jobs create` command as
     step §19c; `CLAUDE.md`'s "live infrastructure" list does not mention it among
     the currently-running jobs.
   - What's unclear: whether the operator has actually run that `gcloud` command
     in the live project, and whether the 90-day backfill has drained (`done: true`).
   - Recommendation: this is an operator/deploy verification step, not a planning
     blocker — the UI-SPEC's pipeline-not-live guard already covers the "not yet"
     case gracefully. Flag as a pre-UAT checklist item for the Sleep page specifically.

3. **What is the actual current fill-rate of `hrv_baseline` across the ~90-day Postgres history?**
   - What we know: the column exists, is written by `write_biometrics_to_postgres`,
     and is already the DEFAULT source `core/recovery_metrics.py` uses for baseline
     math (preferred over a locally-computed median).
   - What's unclear: whether Garmin actually populates this field consistently
     across the whole backfill window or only recently.
   - Recommendation: a one-off `SELECT count(*) FILTER (WHERE hrv_baseline IS NOT
     NULL), count(*) FROM daily_biometrics` during implementation settles this in
     seconds; no code should be written speculatively for either branch until
     that's checked.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Firestore (`klaus-firestore` database) | Training + Nutrition pages | Presumed ✓ (existing prod infra, used by all prior phases) | — | — |
| Postgres (`DATABASE_URL`/`PG_CONNECTION_STRING`) | Sleep & Recovery page | Presumed ✓ (existing prod infra, used by `garmin_tool`/`database_tool`/`recovery_metrics`) | — | — |
| `klaus-biometric-sync` Cloud Scheduler job | Sleep & Recovery page's actual data freshness | ✗ or unverified — not listed in `CLAUDE.md §5`'s live-infrastructure list; documented in `docs/DEPLOYMENT.md §19c` as a deploy step that may not have been executed | — | UI-SPEC's "pipeline-not-live" placeholder (already designed, D-06-style guard) |
| Chart library (npm package) | Not needed — no new dependency added | N/A | N/A | Hand-rolled SVG toolkit (this phase builds it) |

**Missing dependencies with no fallback:**
- None. Every gap identified has either an existing fallback pattern or is a
  documented, already-designed-for contingency.

**Missing dependencies with fallback:**
- `klaus-biometric-sync` scheduler registration — the Sleep page's "pipeline isn't
  syncing yet" copy (UI-SPEC, Copywriting Contract) already covers the case where
  this job has not run; this is a pre-UAT operator checklist item, not a plan blocker.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework (backend) | pytest (repo-wide; per-file execution required — full-suite segfaults on grpc/protobuf GC per project memory) |
| Framework (frontend) | vitest + @testing-library/react (`frontend/vitest.config.ts`) |
| Config file | `pytest.ini`/`pyproject.toml` (backend, not modified this phase); `frontend/vitest.config.ts` (frontend, not modified this phase) |
| Quick run command (backend, per new test file) | `pytest tests/test_health_api.py -x` |
| Quick run command (frontend, per new test file) | `cd frontend && npx vitest run src/components/charts/LineChart.test.tsx` |
| Full suite command (backend) | Per-file loop (NOT a single `pytest tests/` invocation — segfault risk); baseline is 1720+ tests, must hold |
| Full suite command (frontend) | `cd frontend && npm test` (vitest, baseline 122+ tests, must hold) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HLTH-01 | `GET /api/health/training` returns merged/interleaved strength+run+benchmark entries + block dividers, range-filtered | integration | `pytest tests/test_health_training_api.py -x` | ❌ Wave 0 |
| HLTH-01 | `BenchmarkStore.get_range()` returns docs in [start,end], newest-first, `[]` on error | unit | `pytest tests/test_firestore_db.py -k benchmark_get_range -x` | ❌ Wave 0 (extend existing `test_firestore_db.py` if present, else new file) |
| HLTH-01 | `TrainingHistoryPage` renders mixed log with modality color-coding and drill-down on tap | component | `npx vitest run src/components/health/training/TrainingLog.test.tsx` | ❌ Wave 0 |
| HLTH-02 | `GET /api/health/nutrition` returns per-day/weekly series + `missing_dates` (never zero-filled) + targets + protein g/kg | integration | `pytest tests/test_health_nutrition_api.py -x` | ❌ Wave 0 |
| HLTH-02 | `SlotAdherenceGrid` renders hit/miss cells keyed on slot LABEL only (never a derived time) | component | `npx vitest run src/components/health/nutrition/SlotAdherenceGrid.test.tsx` | ❌ Wave 0 |
| HLTH-03 | `GET /api/health/sleep` returns HRV/sleep/body-battery series + `pipeline_active` flag distinct from empty-range | integration | `pytest tests/test_health_sleep_api.py -x` | ❌ Wave 0 |
| HLTH-03 | New Postgres range reader returns `[]` on connection failure, never raises | unit | `pytest tests/test_health_sleep_api.py -k range_reader -x` | ❌ Wave 0 |
| D-08 (cross-cutting) | `LineChart`/`BarChart` render a visible break (not a zero, not interpolated) for a `null` point | component | `npx vitest run src/components/charts/LineChart.test.tsx -t gap` | ❌ Wave 0 |
| D-07 (cross-cutting) | >90-day range requests return weekly-bucketed points; ≤90-day return daily points | unit | `pytest tests/test_health_*.py -k weekly_bucket -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** the relevant single test file (`pytest tests/test_health_X.py -x` or `npx vitest run <file>`)
- **Per wave merge:** full backend per-file loop + `npm test` (frontend)
- **Phase gate:** both full suites green (1720+ backend, 122+ frontend, both baselines must hold) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_health_training_api.py` — covers HLTH-01 (mirrors `tests/test_api_today.py`'s `_stub_web_server_imports` pattern for FastAPI TestClient + session-auth stubbing)
- [ ] `tests/test_health_nutrition_api.py` — covers HLTH-02
- [ ] `tests/test_health_sleep_api.py` — covers HLTH-03 (needs a Postgres-mock fixture — no existing test file mocks `psycopg2` for a health-style read yet; check `tests/` for any existing Postgres-mocking convention used by `garmin_tool`/`database_tool` tests and reuse it)
- [ ] `BenchmarkStore.get_range` unit tests — add to whatever file already tests `BenchmarkStore` (likely `tests/test_firestore_db.py` or a Phase-23-era file; locate via `grep -rn "BenchmarkStore" tests/`)
- [ ] `frontend/src/components/charts/LineChart.test.tsx`, `BarChart.test.tsx` — new chart primitives have zero test coverage today (they don't exist yet) — gap-rendering behavior (D-08) is the highest-value test here
- [ ] `frontend/src/components/health/**/*.test.tsx` — one smoke test per new page component at minimum, following the existing `ContributionGrid.test.tsx` component-test convention

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Indirect | No new auth logic — all 3 routes gated by the existing `Depends(require_hub_session)` (HUB-01), unchanged |
| V3 Session Management | No | No new session logic |
| V4 Access Control | Yes | Single-user allowlisted app (existing `HUB_ALLOWED_EMAIL` check inside `require_hub_session`) — no per-resource authorization needed since there is exactly one user and all health data belongs to them |
| V5 Input Validation | Yes | The `range` query param must be validated against the closed set `{7d, 30d, 90d, 1y}` server-side (never trust the client to only send valid values) — reject/clamp anything else rather than passing it into a date-arithmetic expression unchecked |
| V6 Cryptography | No | No new secrets, tokens, or crypto in this phase |
| V7 Error Handling / Logging | Yes | Follow the existing "never raise from a read, return `[]`/`None`, log at WARNING" discipline already used by every store in `memory/firestore_db.py` — do not let a malformed range param produce a raw stack trace in the JSON response |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unvalidated `range` query param used to build a date-arithmetic expression (e.g. `timedelta(days=int(range))` on unsanitized input) | Tampering | Whitelist the 4 valid range strings server-side; map to a fixed `days` int internally — never `int()`-parse an arbitrary client-supplied number into the date math (mirrors the existing `days = max(1, min(int(days), 60))` clamp pattern in `_handle_fetch_nutrition_trend`, but as an allowlist rather than a clamp, since D-05 defines a closed set) |
| SQL injection via a hand-built date-range query string for the Postgres reader | Tampering | Always use parameterized queries (`%s` placeholders via `psycopg2`, never f-string interpolation) — the existing `fetch_biometric_rows`/`write_biometrics_to_postgres` functions already do this correctly; the new range reader must follow the same convention exactly |
| Session cookie omitted on a new fetch call (frontend forgets `credentials: 'include'`) | Spoofing/DoS-of-self | Use the shared `apiFetch()` wrapper (`frontend/src/api/client.ts`) for all 3 new endpoints rather than raw `fetch()` — it already sets `credentials: 'include'` and handles the 401 redirect uniformly |

## Sources

### Primary (HIGH confidence — direct codebase inspection)
- `memory/firestore_db.py` (this repo) — `StrengthSessionStore` (~1087), `RunDetailStore` (~1226), `MealStore` (~711), `BlockStore` (~2080), `BenchmarkStore` (~2263), `_jsonsafe_doc`/`_jsonsafe_value` (~885)
- `core/tools.py` (this repo) — `_handle_fetch_nutrition_trend` (~2302)
- `interfaces/web_server.py` (this repo) — `/api/today` composition (~1038-1509), `/cron/biometric-sync` (~866-893), `require_hub_session` usage throughout
- `interfaces/hub_auth.py` (this repo) — `require_hub_session` (~265)
- `core/biometric_ingest.py` (this repo, full file read) — backfill/delta modes, `daily_biometrics` write path
- `core/recovery_metrics.py` (this repo, full file read) — `fetch_biometric_rows`, `compute_recovery_deviation`, HRV baseline fallback logic
- `mcp_tools/garmin_tool.py` (this repo) — `write_biometrics_to_postgres` (~993, confirms `daily_biometrics` columns), `normalize_run_detail`/`_extract_splits` (~846, ~649, confirms lap field names)
- `mcp_tools/hevy_tool.py` (this repo) — `normalize_workout`/`_normalize_exercise` (~230, ~172, confirms per-set field names)
- `mcp_tools/database_tool.py` (this repo, full file read) — read-only Postgres session pattern, row-cap/truncation convention
- `frontend/src/App.tsx`, `frontend/src/tokens.ts`, `frontend/src/api/client.ts`, `frontend/src/hooks/useToday.ts`, `frontend/src/components/habits/ContributionGrid.tsx`, `frontend/src/components/timeline/{TimelineHeader,PlaceholderCard}.tsx`, `frontend/src/components/tasks/{SortGroupControl,TaskDetailSheet}.tsx` (this repo) — established frontend conventions
- `frontend/package.json` (this repo, plus `git diff`) — confirms zero chart/graphing dependency exists or is pending
- `docs/DEPLOYMENT.md` §19 (this repo) — Cloud Scheduler job inventory, including `klaus-biometric-sync` (job #12)
- `CLAUDE.md` §5 "Live infrastructure" (this repo, project instructions) — current deployed cron list, does not mention `klaus-biometric-sync`
- `.planning/phases/30-health-pages/30-CONTEXT.md` and `30-UI-SPEC.md` (this repo) — all locked D-01..D-19 decisions, component inventory, copywriting contract
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md` (this repo) — HLTH-01..03 definitions, project history, test baseline counts

### Secondary (MEDIUM confidence)
- None used — all findings for this phase came from direct repo inspection (HIGH confidence); no external web research was needed since the entire phase is an integration of existing, already-documented internal systems.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; entire stack already verified live in the repo
- Architecture: HIGH — directly extends the `/api/today` pattern with full source access to the precedent
- Data source completeness: HIGH for Training/Nutrition (stores exist, gaps identified precisely — Pitfalls 1/2), MEDIUM for Sleep (data column-complete but production scheduler-liveness unverified — Pitfall 4/Open Question 2)
- Pitfalls: HIGH — five concrete, source-cited pitfalls with existing-codebase precedent for each fix

**Research date:** 2026-07-06
**Valid until:** 30 days (stable internal-integration phase; re-verify sooner only if `daily_biometrics` scheduler status or `nutrition_targets` schema changes before planning begins)
