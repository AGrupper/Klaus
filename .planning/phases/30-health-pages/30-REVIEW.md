---
phase: 30-health-pages
reviewed: 2026-07-09T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - core/health_reads.py
  - interfaces/web_server.py
  - memory/firestore_db.py
  - core/tools.py
  - frontend/src/App.tsx
  - frontend/src/api/health.ts
  - frontend/src/hooks/useHealth.ts
  - frontend/src/components/charts/LineChart.tsx
  - frontend/src/components/charts/BarChart.tsx
  - frontend/src/components/charts/ChartTooltip.tsx
  - frontend/src/components/charts/ChartEmptyState.tsx
  - frontend/src/components/health/HealthPage.tsx
  - frontend/src/components/health/SubTabs.tsx
  - frontend/src/components/health/RangeToggle.tsx
  - frontend/src/components/health/training/TrainingHistoryPage.tsx
  - frontend/src/components/health/training/TrainingTrendCharts.tsx
  - frontend/src/components/health/training/TrainingLog.tsx
  - frontend/src/components/health/training/RunDrilldownSheet.tsx
  - frontend/src/components/health/nutrition/NutritionDetailPage.tsx
  - frontend/src/components/health/nutrition/MacroTrendChart.tsx
  - frontend/src/components/health/nutrition/SlotAdherenceGrid.tsx
  - frontend/src/components/health/nutrition/DayDrilldownSheet.tsx
  - frontend/src/components/health/sleep/SleepRecoveryPage.tsx
  - frontend/src/components/health/sleep/SleepChart.tsx
  - frontend/src/components/health/sleep/HRVChart.tsx
  - frontend/src/components/health/sleep/HeaderStatRow.tsx
  - frontend/src/components/health/sleep/BodyBatteryChart.tsx
findings:
  critical: 1
  warning: 5
  total: 6
status: issues_found
---

# Phase 30: Code Review Report

**Reviewed:** 2026-07-09
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Phase 30 wires three read-only `/api/health/{training,nutrition,sleep}` routes (all
correctly behind `require_hub_session`, all sync Postgres/Firestore reads correctly
wrapped in `run_in_executor`, range param correctly allowlisted not `int()`-parsed,
slot-label invariant honored — never a clock time on the wire) over a hand-rolled
inline-SVG chart toolkit and three health sub-pages. The auth/executor/injection
invariants are clean. The security posture is sound.

The dominant defect is a **broken D-08 gap contract on the nutrition trend chart**:
the backend deliberately omits unlogged days from the macro series and reports them
separately in `missing_dates`, but no frontend component ever consumes `missing_dates`
to re-insert null gaps — so `LineChart` bridges straight across unlogged days,
producing a continuous line that misrepresents intermittent logging as continuous.
This is exactly the "never an interpolated bridge" behavior `LineChart`'s own header
comment promises it will not do, and D-08 is a stated cross-cutting invariant for this
phase. Five WARNINGs follow (error negative-caching, chart-overlay x-misalignment,
weekly-range drill-down breakage, multi-series length assumption, pace formatting).

## Critical Issues

### CR-01: Nutrition macro chart bridges unlogged-day gaps — D-08 violated (`missing_dates` fetched but never used)

**File:** `frontend/src/components/health/nutrition/NutritionDetailPage.tsx:115`, `frontend/src/components/health/nutrition/MacroTrendChart.tsx:8-9,73-77`, `interfaces/web_server.py:1953-1962`

**Issue:** The backend builds the per-macro series from `day_records`, which contains
**only days that had logged meals** (`interfaces/web_server.py:1830-1841`). Unlogged
days are pushed to a separate `missing_dates` list, never emitted as `{"x": date, "y": null}`
points. `api/health.ts:191-194` even documents the contract: *"A date absent from a
series is a gap (D-08) — see `missing_dates`."*

But `missing_dates` is referenced **nowhere in the frontend** except its type
declaration (verified: `grep -rn missing_dates frontend/src` returns only `api/health.ts`).
`NutritionDetailPage` passes `data.series[metric]` verbatim into `MacroTrendChart`, which
passes it verbatim into `LineChart`. Because the series has no `null` entries for the
unlogged days, `LineChart.buildSegments` never splits the path — it draws one continuous
line connecting the last logged day to the next logged day across the gap.

`MacroTrendChart`'s header comment (`:8-9`) even asserts the opposite of what happens:
*"the caller passes the metric's TrendPoint[] verbatim (with null y-values for unlogged
days)"* — but the series contains no such null entries. Result: logging breakfast Monday
then again Friday renders as an unbroken trend line, directly contradicting the D-08
invariant ("null data points render as gaps, never zero-filled / never bridged"). This
is the most likely-hit case in the whole phase (unlogged days are routine) and it
silently misrepresents the user's nutrition history.

**Fix:** Splice the missing dates back into each series as null gaps on the server before
weekly-bucketing (simplest, keeps "server computes, client renders"), e.g. in
`api_health_nutrition`:

```python
# Build a null-filled dense daily series so unlogged days are D-08 gaps, not bridges.
by_date = {r["date"]: r for r in day_records}
dense = [
    {"x": d, "y": (by_date[d].get(key) if d in by_date else None)}
    for d in _iter_dates(start_iso, end_iso)   # inclusive daily walk
]
pts = _weekly_bucket_points(dense, agg="avg") if days > _WEEKLY_BUCKET_THRESHOLD_DAYS else dense
points_by_key[key] = pts
```

(Alternatively splice on the client from `missing_dates`.) Also correct the now-false
docstring in `MacroTrendChart.tsx:8-9`. Note: the same "dropped point, not null" pattern
affects any series where `_weekly_bucket_points` omits an empty week and the sleep series
when a whole day has no `daily_biometrics` row — verify those render as gaps too.

## Warnings

### WR-01: `_health_nutrition_daily` negatively caches errors for 30 minutes

**File:** `interfaces/web_server.py:1854-1859`

**Issue:** On any exception the helper sets `result = {"day_records": [], "missing_dates": [], "slot_records": []}`
and then unconditionally writes it into `_nutrition_daily_cache[cache_key] = (now_epoch, result)`
(the cache write is outside the `try/except`, on the success and failure path alike). A
transient Firestore error therefore poisons the nutrition page with an all-empty result
for the full `_ROUTES_CACHE_TTL_SECONDS` (30 min), even after Firestore recovers — the
user sees "No nutrition data" for half an hour. This is the opposite of the deliberate
choice made in `_resolve_hub_user_id` (`:2196`, "A failed resolution is NOT cached").

**Fix:** Only cache on the success path; return the empty degraded result without storing it.

```python
    except Exception:
        logger.warning("_health_nutrition_daily(%r, %r) failed", start, end, exc_info=True)
        return {"day_records": [], "missing_dates": [], "slot_records": []}  # do NOT cache

    _nutrition_daily_cache[cache_key] = (now_epoch, result)
    return result
```

### WR-02: SleepChart overlay — bars and score line use different x-position math, so they don't align by date

**File:** `frontend/src/components/health/sleep/SleepChart.tsx:75-88`; `frontend/src/components/charts/BarChart.tsx:50`; `frontend/src/components/charts/LineChart.tsx:98-101`

**Issue:** `SleepChart` absolutely-overlays a `BarChart` (duration) under a `LineChart`
(score), relying on both sharing the "same VIEW_WIDTH/height coordinate system." But their
per-index x formulas differ: `BarChart.xForIndex(i) = PADDING + slotWidth*i + slotWidth/2`
(slot-centered) whereas `LineChart.xForIndex(i) = PADDING + (i/(n-1))*(VIEW_WIDTH - 2*PADDING)`
(edge-to-edge). For the same date index the bar and the score dot land up to `slotWidth/2`
apart horizontally, and the last bar sits ~`slotWidth/2` left of the last line point. The
line owns the tooltip, so the value shown corresponds to a bar that is visually offset from
the tapped position — a subtle but real misread of a recovery chart.

**Fix:** Make the two primitives share one x-mapping (e.g. give `LineChart` a slot-centered
mode, or plot bars edge-to-edge), or render duration+score as a single combined chart
component rather than two independently-scaled overlays.

### WR-03: Nutrition day-drilldown is broken for the 1y (weekly-bucketed) range

**File:** `frontend/src/components/health/nutrition/NutritionDetailPage.tsx:53-72,113-145`

**Issue:** At `range='1y'` the server returns weekly-bucketed series whose `x` values are
**week-start labels**, not individual dates (`_weekly_bucket_points`, `web_server.py:1570-1577`).
But `dayTotalsFor(date, series)` looks up `series[metric].find(p => p.x === date)` using a
concrete YYYY-MM-DD date, and the slot grid (`slot_adherence`) always uses concrete dates.
Two failure modes:
1. Tapping a **chart point** in 1y calls `onDaySelect(point.x)` with a week label; the sheet
   title reads e.g. "2026-05-04 — Meals", `mealsFor` finds no slot cell matching that label
   ("No meals logged this day"), and `dayTotalsFor` returns the **weekly-averaged** totals
   mislabeled as "Day total".
2. Tapping a **slot cell** (real date) in 1y calls `dayTotalsFor(realDate, series)` which
   finds no matching week-label point → all totals null → "Day total — " with an empty macro
   string.

Either way the drill-down shows wrong or empty data for the 1y range.

**Fix:** Disable/relabel the day drill-down when `days > _WEEKLY_BUCKET_THRESHOLD_DAYS`, or
have the server emit a date→week map and reconstruct day totals only for daily ranges.

### WR-04: `LineChart` assumes all series share one index space; weekly bucketing can drop weeks per-series and shift a whole line

**File:** `frontend/src/components/charts/LineChart.tsx:81,98-101,186-211`; `interfaces/web_server.py:2106-2111`

**Issue:** `LineChart` positions every series by array index against `pointCount = series[0].points.length`.
This is safe only when all series have identical length and identical x ordering. For the
HRV chart at `range='1y'`, `hrv_overnight` and `hrv_baseline` are bucketed **independently**
(`web_server.py:2100-2111`), and `_weekly_bucket_points` **omits** any week with no non-null
contributions. If the baseline is null for the first week of the range (common — the rolling-
median fallback needs prior days, and even the stored column can be sparse) that week is
dropped from the baseline array but kept in the overnight array. The baseline array is then
one element shorter, so `baseline[0]` (week 2's value) is plotted at index 0 (week 1's x) —
the entire dashed baseline shifts one week and no longer lines up with the overnight line it
is meant to be compared against (the D-18 gap-between-lines coaching signal).

**Fix:** Bucket all series on a shared week axis (union of week keys, null-filling absent
weeks) so every series is the same length with aligned indices, or key `LineChart` layout on
each point's `x` label rather than array index.

### WR-05: `RunDrilldownSheet.formatPace` can render an invalid ":60/km"

**File:** `frontend/src/components/health/training/RunDrilldownSheet.tsx:38-43`

**Issue:** `formatPace` computes `min = Math.floor(secPerKm/60)` and, independently,
`sec = Math.round(secPerKm % 60)`. When the fractional seconds round up from ≥59.5, `sec`
becomes 60 while `min` was floored from the un-rounded value, yielding strings like
"5:60/km" (e.g. `359.7 → 5:60/km`). `TrainingTrendCharts.formatPaceSecPerKm:37-42` avoids
this by rounding to whole seconds first — this helper should do the same.

**Fix:**

```ts
function formatPace(secPerKm: unknown): string {
  if (typeof secPerKm !== 'number') return '—'
  const total = Math.round(secPerKm)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}/km`
}
```

---

## Notes (not classified — out of v1 scope or confirmed non-issues)

- **Performance (out of v1 scope, flagged for awareness):** `_health_training_benchmarks`
  calls `store.get_facet_history(facet, n=1000)` inside the per-benchmark loop, and each call
  streams the *entire* benchmark collection (`firestore_db.py:2370`) — an N+1 full-scan per
  benchmark in range. `_health_sleep_pipeline_active` reads and materializes *every*
  `daily_biometrics` row (`"1970-01-01".."2099-12-31"`) on every sleep request just to test
  non-emptiness. Both are correctness-safe but wasteful; consider a `LIMIT 1`/existence probe
  and a single facet-history pre-fetch when this leaves v1 scope.
- **Confirmed clean:** all three health routes are behind `Depends(require_hub_session)`;
  the sole Postgres reader (`fetch_biometric_range`) is parameterized (no SQL injection) and
  always invoked via `run_in_executor` (Pitfall 3 honored); the `range` param is allowlisted
  via `_resolve_range` and never `int()`-parsed; the slot-label invariant holds end-to-end
  (only `_SLOT_LABELS` labels reach the wire, never the 08:00/12:00/20:00 timestamps);
  `_weekly_bucket_points` correctly skips `y=None` so gaps never contribute a zero to an
  aggregate; `BarChart`/`LineChart` correctly render `y===null` as no-bar / path-split; GCP
  resource names are unchanged/lowercase.

---

_Reviewed: 2026-07-09_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---

## Orchestrator resolution (2026-07-09, phase close-out)

- **CR-01 (BLOCKER)** — FIXED (commit 09786c6): nutrition macro series now span
  the full date range with `y: null` for unlogged days, so LineChart splits the
  gap (D-08). Regression test updated to assert null-not-absent-not-zero.
- **WR-01** — FIXED (09786c6): `_health_nutrition_daily` no longer caches the
  degraded result on the exception path.
- **WR-05** — FIXED (09786c6): `RunDrilldownSheet.formatPace` rounds total
  seconds before splitting (no more "m:60/km").
- **WR-02 / WR-03 / WR-04** — DEFERRED (documented follow-ups). WR-02 is a
  sub-pixel x-offset from overlaying two independent chart primitives on the
  Sleep card; WR-03 (nutrition day-drilldown labeling) and WR-04 (HRV baseline
  index-shift) manifest only at range=1y under weekly bucketing. None affect the
  primary 7d/30d views; fixing them touches the shared chart toolkit and is
  carried as a minor polish follow-up rather than a close-out blocker.
