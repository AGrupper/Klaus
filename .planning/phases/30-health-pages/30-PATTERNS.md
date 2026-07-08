# Phase 30: Health Pages - Pattern Map

**Mapped:** 2026-07-06
**Files analyzed:** 27 (3 backend routes/aggregators, 1 store method addition, 1 Postgres reader module, 22 frontend files)
**Analogs found:** 27 / 27 (all have a strong existing-codebase analog — this is an integration phase, no genuinely novel architecture)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `interfaces/web_server.py` — `GET /api/health/training` + `_health_training_*` helpers | route + service (composition) | request-response (multi-store aggregate) | `interfaces/web_server.py` `api_today()` + `_today_*` helpers (~1039-1509) | exact |
| `interfaces/web_server.py` — `GET /api/health/nutrition` + `_health_nutrition_*` helpers | route + service | request-response (aggregate + trend) | `core/tools.py::_handle_fetch_nutrition_trend` (~2302) + `api_today()` composition shape | exact |
| `interfaces/web_server.py` — `GET /api/health/sleep` + `_health_sleep_*` helpers | route + service | request-response (Postgres read, executor-wrapped) | `interfaces/web_server.py` `/cron/biometric-sync` handler (~866-893) + `core/recovery_metrics.fetch_biometric_rows` | exact |
| `memory/firestore_db.py` — `BenchmarkStore.get_range(start, end)` | model (store method) | CRUD (range read) | `memory/firestore_db.py` `RunDetailStore.get_range` (~1303) / `StrengthSessionStore.get_range` (~1151) | exact |
| `core/health_reads.py` (new, small module) — `fetch_biometric_range(start, end)` | service (Postgres reader) | request-response (parameterized SQL) | `core/recovery_metrics.fetch_biometric_rows` (~39) + `mcp_tools/database_tool.py::query_health_database` (read-only session convention) | exact |
| `frontend/src/App.tsx` (modify) — `/health` route swap | route (React Router) | request-response | Same file, `/habits` → `HabitsPage` swap (already done, Phase 28) | exact |
| `frontend/src/components/health/HealthPage.tsx` (new, root) | component (page) | request-response | `frontend/src/components/habits/HabitsPage.tsx` (root page owning sub-nav + persisted tab) | role-match |
| `frontend/src/components/health/SubTabs.tsx` | component (segmented control) | request-response (client state only) | `frontend/src/components/tasks/SortGroupControl.tsx` `SegmentedGroup` (~48-102) | exact |
| `frontend/src/components/health/RangeToggle.tsx` | component (segmented control) | request-response (client state only) | `frontend/src/components/tasks/SortGroupControl.tsx` `SegmentedGroup` (~48-102) | exact |
| `frontend/src/api/health.ts` | utility (api client functions) | request-response | `frontend/src/api/today.ts` (type contract + `fetchToday`) | exact |
| `frontend/src/hooks/useHealth.ts` | hook (react-query) | request-response | `frontend/src/hooks/useToday.ts` | exact |
| `frontend/src/components/charts/LineChart.tsx` | component (SVG primitive) | transform (render pre-aggregated points) | `frontend/src/components/habits/ContributionGrid.tsx` (hand-rolled SVG/CSS-grid precedent, no library) | role-match (new primitive, same "hand-roll, no library" philosophy) |
| `frontend/src/components/charts/BarChart.tsx` | component (SVG primitive) | transform | `frontend/src/components/habits/ContributionGrid.tsx` | role-match |
| `frontend/src/components/charts/ChartTooltip.tsx` | component (overlay) | event-driven (tap/hover) | `frontend/src/components/tasks/TaskDetailSheet.tsx` (tooltip has same `#1A1A1A`/`#2A2A2A` bubble chrome as the sheet header) | partial-match (chrome only) |
| `frontend/src/components/charts/ChartCard.tsx` | component (card wrapper) | request-response | `frontend/src/components/timeline/TimelineHeader.tsx` `GarminStatsRows`/card sections + `HabitRow`/`GlanceRail` card convention | role-match |
| `frontend/src/components/charts/ChartEmptyState.tsx` | component (empty state) | request-response | `frontend/src/components/timeline/PlaceholderCard.tsx` | exact |
| `frontend/src/components/health/training/TrainingHistoryPage.tsx` | component (page) | request-response | `frontend/src/components/habits/HabitsPage.tsx` (RangeToggle-equivalent + list composition) | role-match |
| `frontend/src/components/health/training/TrainingLog.tsx` + `TrainingLogEntry.tsx` | component (list/row) | request-response | `frontend/src/components/tasks/TaskListView`/`TaskRow` pattern (interleaved rows, left-border accent stripe) — same convention as `DueTasksBand`/`HabitsBand` | role-match |
| `frontend/src/components/health/training/BlockDivider.tsx` | component (section divider) | request-response | `DueTasksBand`/`HabitsBand` band-header padding convention | role-match |
| `frontend/src/components/health/training/{Strength,Run,Benchmark}DrilldownSheet.tsx` | component (modal/sheet) | request-response | `frontend/src/components/tasks/TaskDetailSheet.tsx` (z:190/191, phone-sheet/desktop-modal, `useVisualViewport`-free since no text inputs) | exact |
| `frontend/src/components/health/nutrition/NutritionDetailPage.tsx` | component (page) | request-response | `frontend/src/components/habits/HabitsPage.tsx` | role-match |
| `frontend/src/components/health/nutrition/MacroChipRow.tsx` | component (toggle chips) | event-driven (client state) | `frontend/src/components/tasks/SortGroupControl.tsx` `SegmentedGroup` (adapted to 5-way, per-metric color instead of accent) | role-match |
| `frontend/src/components/health/nutrition/MacroTrendChart.tsx` | component (chart + summary) | request-response | New `ChartCard`+`LineChart` combo; summary row mirrors `TimelineHeader.tsx` `GarminStatsRows` label/value styling | role-match |
| `frontend/src/components/health/nutrition/SlotAdherenceGrid.tsx` | component (grid) | request-response | `frontend/src/components/habits/ContributionGrid.tsx` (12px/2px-gap cell convention, `role="grid"`/`role="gridcell"`) | exact (explicitly directed by UI-SPEC) |
| `frontend/src/components/health/nutrition/DayDrilldownSheet.tsx` | component (modal/sheet) | request-response | `frontend/src/components/tasks/TaskDetailSheet.tsx` | exact |
| `frontend/src/components/health/sleep/SleepRecoveryPage.tsx` | component (page) | request-response | `frontend/src/components/habits/HabitsPage.tsx` | role-match |
| `frontend/src/components/health/sleep/HeaderStatRow.tsx` | component (stat strip) | request-response | `frontend/src/components/timeline/TimelineHeader.tsx` `NutritionStrip` (~119-199) | exact |
| `frontend/src/components/health/sleep/{HRV,Sleep,BodyBattery}Chart.tsx` | component (chart) | request-response | New `ChartCard`+`LineChart`/`BarChart` combos | role-match |
| `tests/test_health_training_api.py`, `test_health_nutrition_api.py`, `test_health_sleep_api.py` | test (integration) | request-response | `tests/test_api_today.py` (`_stub_web_server_imports` pattern, `_ENV` dict, monkeypatched per-source helpers) | exact |

## Pattern Assignments

### `interfaces/web_server.py` — `GET /api/health/training` (+ nutrition, sleep)

**Analog:** `interfaces/web_server.py::api_today()` and its `_today_*` helper functions (lines 1039–1509)

**Module-level comment banner + cache pattern** (lines 1039-1050):
```python
# TIME-08). Behind require_hub_session (HUB-01). All sync tool calls run via  #
# run_in_executor + asyncio.gather (Pitfall 2). Every Firestore-derived value #
# passes through _jsonsafe_doc before JSONResponse (Pitfall 4).               #
#                                                                              #
# MUST be registered BEFORE the SPA mount (Pitfall 1).                        #
# --------------------------------------------------------------------------- #

# Module-level in-process cache for Routes API results (TIME-05 / T-26-04-04).
_routes_cache: dict = {}
_ROUTES_CACHE_TTL_SECONDS = 1800  # 30 minutes
```
Apply the same banner + module docstring convention above each new `_health_*` helper block; if the nutrition >90d path needs a cache (Pitfall 1 in RESEARCH.md), reuse this exact TTL-dict-with-opportunistic-eviction shape rather than inventing a new cache primitive.

**Per-source helper — never-raise, degrade gracefully** (lines 1111-1130, `_today_garmin`):
```python
def _today_garmin() -> dict | None:
    """Fetch today's Garmin morning stats — sleep, HRV, body battery, resting HR.
    ...
    """
    try:
        from mcp_tools.garmin_tool import fetch_garmin_today  # lazy import
        data = fetch_garmin_today()
        return {
            "sleep": data.get("sleep_hours"),
            "hrv": data.get("hrv_overnight"),
            "body_battery": data.get("body_battery_morning"),
            "resting_hr": data.get("resting_hr"),
        }
    except Exception:
        logger.warning("_today_garmin() failed — Garmin may not have synced yet", exc_info=True)
        return None
```
Each new `_health_training_strength(start, end)` / `_health_training_runs(...)` / `_health_training_benchmarks(...)` / `_health_training_blocks(...)` helper (and the nutrition/sleep equivalents) should follow this exact shape: lazy import, try/except Exception, log at WARNING with the args in the message, return a safe default (`[]`/`None`/`{}`) — never raise out of a helper.

**Route composition — `asyncio.gather` + `run_in_executor`, phased dependencies** (lines 1446-1508):
```python
@app.get("/api/today")
async def api_today(_email: str = Depends(require_hub_session)) -> JSONResponse:
    from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5
    loop = asyncio.get_running_loop()
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    (calendar_data, garmin_data, weather_data, meal_data, training_data,
     nutrition_totals) = await asyncio.gather(
        loop.run_in_executor(None, _today_calendar, today_iso),
        loop.run_in_executor(None, _today_garmin),
        loop.run_in_executor(None, _today_weather),
        loop.run_in_executor(None, _today_meals, today_iso),
        loop.run_in_executor(None, _today_training, today_iso),
        loop.run_in_executor(None, _today_nutrition_totals, today_iso),
    )
    calendar_with_routes = await loop.run_in_executor(None, _today_routes, calendar_data, today_iso)
    coach_note = await loop.run_in_executor(None, _today_coach_note, today_iso)

    payload = _jsonsafe_doc({
        "today": today_iso, "calendar": calendar_with_routes, "garmin": garmin_data,
        "weather": weather_data, "meals": meal_data, "training": training_data,
        "coach_note": coach_note, "nutrition_totals": nutrition_totals,
    })
```
Copy this shape exactly for all 3 new routes: `Depends(require_hub_session)`, resolve a validated `range` query param to `(start_iso, end_iso)` FIRST (allowlist `{7d,30d,90d,1y}` per the Security Domain table — never `int()`-parse an arbitrary client value), `asyncio.gather` the independent store reads via `run_in_executor`, then a second phase for anything with an inter-dependency (e.g. training's block-divider resolution needs both the log entries AND `BlockStore.get_all()`), then wrap the final dict in `_jsonsafe_doc` before `JSONResponse`.

**Range param validation (new — allowlist, not clamp; RESEARCH.md Security Domain V5):**
```python
_VALID_RANGES = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}

def _resolve_range(range_param: str) -> int:
    """Map a client range string to a day count. Defaults to 30 on any invalid input."""
    return _VALID_RANGES.get(range_param, 30)
```
This is new code (no direct prior analog for an allowlist-style range param), but it mirrors the existing clamp-style guard already in the codebase:
```python
# Source: core/tools.py, _handle_fetch_nutrition_trend (~2313)
days = max(1, min(int(days), 60))  # clamp — each day is a Firestore read
```
Use the allowlist form (dict `.get` with a safe default), not the clamp form, since D-05 defines a closed set of 4 valid values — never feed an unvalidated client string into date arithmetic.

---

### `memory/firestore_db.py` — `BenchmarkStore.get_range(start_date, end_date)`

**Analog:** `RunDetailStore.get_range` (lines 1303-1318) / `StrengthSessionStore.get_range` (lines 1151-1166) — both in the same file, same never-raise discipline.

**Pattern to copy exactly** (from `RunDetailStore.get_range`, lines 1303-1318):
```python
def get_range(self, start_date: str, end_date: str) -> list[dict]:
    """Return runs with date in [start_date, end_date], newest-first.

    Never raises — returns ``[]`` on any Firestore error.
    """
    try:
        query = _where(
            _where(self._col, "date", ">=", start_date), "date", "<=", end_date
        ).order_by("date", direction=_DESCENDING)
        return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
    except Exception:
        logger.warning(
            "RunDetailStore.get_range(%r, %r) failed",
            start_date, end_date, exc_info=True,
        )
        return []
```
Note (RESEARCH.md flagged this): `BenchmarkStore`'s existing methods (`get_facet_history`, `get_block_benchmarks`, lines 2349-2403) use `FieldFilter` directly rather than the module's `_where` helper used by `RunDetailStore`/`StrengthSessionStore`. Either works on this Firestore SDK version — match whichever convention the immediately surrounding `BenchmarkStore` methods already use (`FieldFilter`) for internal file consistency, e.g.:
```python
from google.cloud.firestore_v1.base_query import FieldFilter
snaps = list(
    self._col
    .where(filter=FieldFilter("date", ">=", start_date))
    .where(filter=FieldFilter("date", "<=", end_date))
    .stream()
)
```
Sort in Python (`results.sort(key=lambda d: d.get("date", ""), reverse=True)`) since `BenchmarkStore`'s existing methods do client-side sort/filter rather than server-side `order_by` — follow the surrounding class's existing style.

---

### `core/health_reads.py` (new) — `fetch_biometric_range(start_date, end_date)`

**Analog:** `core/recovery_metrics.py::fetch_biometric_rows` (lines 39-72)

**Full pattern to extend** (lines 39-72):
```python
def fetch_biometric_rows(days: int = 14) -> list[dict]:
    """Read recent daily_biometrics rows from Postgres. Never raises.

    Returns newest-first [{date, resting_hr, hrv_overnight, hrv_baseline,
    sleep_score}]; [] on any failure (mirrors compute_acwr_from_db).
    """
    try:
        import psycopg2  # lazy import — keeps cold-start cheap when unused
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")
        if not dsn:
            return []
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date::date, resting_hr, hrv_overnight, hrv_baseline, sleep_score "
                    "FROM daily_biometrics "
                    "WHERE date >= CURRENT_DATE - %s::int "
                    "ORDER BY date DESC",
                    (days,),
                )
                rows = cur.fetchall()
        return [
            {
                "date": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
                "resting_hr": r[1], "hrv_overnight": r[2],
                "hrv_baseline": r[3], "sleep_score": r[4],
            }
            for r in rows
        ]
    except Exception:
        logger.warning("recovery_metrics: biometrics read failed", exc_info=True)
        return []
```
Extend to a true date-range query (not just "last N days") and the full column set (add `sleep_duration`, `body_battery_max`, `training_readiness`). Do NOT modify `recovery_metrics.py` itself (RESEARCH.md explicitly calls it out as "reference pattern only — do not modify"); put the new range reader in a new small module (`core/health_reads.py`) or alongside it, following this exact shape: lazy `psycopg2` import, `os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")`, parameterized `%s` placeholders (never f-string SQL — Security Domain V7/Tampering), try/except-return-`[]`, isoformat dates in the row-to-dict conversion.

**Read-only session variant** (also acceptable, from `mcp_tools/database_tool.py::query_health_database`, lines 80-104):
```python
conn = psycopg2.connect(conn_str, connect_timeout=5)
conn.set_session(readonly=True, autocommit=True)
with conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute(sql_query)
```
Prefer adding `connect_timeout=5` and `conn.set_session(readonly=True, autocommit=True)` to the new `fetch_biometric_range` — `recovery_metrics.fetch_biometric_rows` itself omits both, but `database_tool.py` and the RESEARCH.md code example both include them; the read-only session is free defense-in-depth for a read-only health endpoint.

**Event-loop-safety wiring (Pitfall 3 — CRITICAL):**
```python
# Source: interfaces/web_server.py, /cron/biometric-sync handler (~888)
result = await loop.run_in_executor(None, _biometric.run_one_batch)
```
The new `/api/health/sleep` route MUST wrap `fetch_biometric_range` the same way: `await loop.run_in_executor(None, fetch_biometric_range, start_date, end_date)`. This is the exact bug class behind the documented 2026-06-24 weekly-review-500 incident (project memory) — never call `psycopg2.connect(...)` synchronously inside `async def`.

---

### `frontend/src/App.tsx` (modify) — `/health` route

**Analog:** same file, `HabitsPage`/`ComingSoon` swap pattern already present for `/habits` (Phase 28)

**Current placeholder to replace** (lines ~92-97):
```typescript
function HealthPage() {
  return <ComingSoon label="Health" />
}
```
Replace with:
```typescript
import { HealthPage as HealthPageComponent } from './components/health/HealthPage'
// ...
function HealthPage() {
  return <HealthPageComponent />
}
```
No route path changes — `<Route path="/health" element={<HealthPage />} />` (line 192) stays as-is.

---

### `frontend/src/components/health/SubTabs.tsx` + `RangeToggle.tsx`

**Analog:** `frontend/src/components/tasks/SortGroupControl.tsx` — `SegmentedGroup` helper (lines 48-102)

**Core segmented-button pattern to copy** (lines 48-102):
```typescript
function SegmentedGroup({ label, buttons }: { label: string; buttons: SegBtn[] }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span style={{ ...typography.label, fontFamily, color: textSecondary, flexShrink: 0 }}>
        {label}
      </span>
      <div style={{ display: 'flex', borderRadius: '8px', border: `1px solid ${border}`, overflow: 'hidden' }}>
        {buttons.map((btn, i) => (
          <button
            key={btn.value}
            onClick={btn.onClick}
            style={{
              height: '32px', padding: '0 10px', border: 'none',
              borderLeft: i > 0 ? `1px solid ${border}` : 'none',
              backgroundColor: btn.active ? accent : secondary,
              color: btn.active ? '#FFFFFF' : textSecondary,
              fontSize: typography.label.fontSize,
              fontWeight: btn.active ? 600 : 400,
              fontFamily, cursor: 'pointer',
              transition: 'background-color 0.15s, color 0.15s',
              whiteSpace: 'nowrap', minWidth: '44px', // touch target width
            }}
            aria-pressed={btn.active}
          >
            {btn.label}
          </button>
        ))}
      </div>
    </div>
  )
}
```
`SubTabs` (3-way Training/Nutrition/Sleep, `localStorage`-persisted per D-02) and `RangeToggle` (4-way 7d/30d/90d/1y, NOT persisted per D-06) are both direct copies of this button-row shape at full width (drop the `label` span for `SubTabs` since the UI-SPEC calls for no redundant page-chrome heading). `SubTabs` adds a `useEffect` writing `localStorage.setItem('health-tab', value)` on change and reads it once via `useState(() => localStorage.getItem('health-tab') ?? 'training')`.

---

### `frontend/src/api/health.ts` + `frontend/src/hooks/useHealth.ts`

**Analog:** `frontend/src/api/today.ts` (full file) + `frontend/src/hooks/useToday.ts` (full file)

**Type contract + fetch function shape** (from `today.ts`, lines 82-108):
```typescript
export interface TodayData {
  today: string
  calendar: { all_day: string[]; timed: TimedEvent[] }
  garmin: GarminStats | null
  // ...
}

export async function fetchToday(): Promise<TodayData> {
  return apiFetch<TodayData>('/api/today')
}
```
Define `TrainingHistoryData` / `NutritionDetailData` / `SleepRecoveryData` interfaces the same way (documented field-by-field, calling out D-06/D-08-style null semantics inline as JSDoc), and `fetchTrainingHistory(range)` / `fetchNutritionDetail(range)` / `fetchSleepRecovery(range)` as thin `apiFetch<T>(\`/api/health/training?range=${range}\`)` wrappers — never raw `fetch()` (Security Domain: `apiFetch` already sets `credentials: 'include'` and handles 401 redirect).

**Hook shape** (from `useToday.ts`, lines 34-44, adapted per RESEARCH.md's own code example):
```typescript
export function useTrainingHistory(range: RangeKey) {
  return useQuery<TrainingHistoryData, Error>({
    queryKey: ['health', 'training', range],
    queryFn: () => fetchTrainingHistory(range),
    staleTime: 5 * 60 * 1000,       // 5 min — historical data, not intraday
    refetchOnWindowFocus: true,     // pick up newly-synced cron data
  })
}
```
Unlike `useToday` (which has no `staleTime` and relies on `refetchOnMount`), the health hooks add `staleTime: 5 * 60 * 1000` per the UI-SPEC's "Range toggle → data fetching" interaction contract — copy this exact value, do not add `refetchOnMount` (range changes already produce a new query key so no manual invalidation trigger is needed) and never add `refetchInterval` (no timer polling, same invariant as `useToday`).

---

### `frontend/src/components/charts/{LineChart,BarChart,ChartTooltip,ChartCard,ChartEmptyState}.tsx`

**Analog:** `frontend/src/components/habits/ContributionGrid.tsx` (full file) — the "hand-rolled visuals, zero new dependency" philosophy precedent, plus `frontend/src/components/timeline/PlaceholderCard.tsx` for the empty-state shape.

**Governing philosophy comment to echo** (`ContributionGrid.tsx`, lines 1-4):
```typescript
/**
 * ContributionGrid.tsx — GitHub-style rolling-year history grid.
 *
 * Pure CSS `display:grid` — no chart/heatmap library.
 */
```
`LineChart`/`BarChart` should carry an equivalent header: "Hand-rolled inline SVG — no chart library (D-04 discretion, resolved in 30-UI-SPEC), matching the `ContributionGrid` precedent." Token imports the same way — `import { accent, border, secondary, textSecondary, textPrimary, skeleton } from '../../tokens'` — never a hardcoded hex outside the documented modality/macro/sleep-series color additions in the UI-SPEC.

**Gap-rendering discipline (D-08 — the single highest-value implementation detail):** no direct code analog exists in this codebase (this is the first chart), but the semantics to implement are explicitly modeled on `_handle_fetch_nutrition_trend`'s never-zero-fill contract:
```python
# Source: core/tools.py, _handle_fetch_nutrition_trend (~2326-2337)
for i in range(days - 1, -1, -1):  # oldest → newest
    d = (today - timedelta(days=i)).isoformat()
    agg = ms.get_day_aggregate(d)
    if agg:
        series.append({"date": d, **{k: totals.get(k) for k in macro_keys}})
    else:
        missing_dates.append(d)  # D-08: never a zero-fill
```
`LineChart` must translate this into: split the SVG `<path>` into multiple segments at every `y === null` point (per UI-SPEC "Missing-data gaps" section) rather than a single path with `moveTo` gaps — some SVG renderers still visually connect `moveTo` gaps, so literal path-splitting is required.

**Tooltip chrome** (mirrors `TaskDetailSheet.tsx`'s dialog chrome values, not its full component):
```typescript
// backgroundColor: secondary /* #1A1A1A */, border: `1px solid ${border}` /* #2A2A2A */, borderRadius: '8px'
```

---

### `frontend/src/components/health/training/{Strength,Run,Benchmark}DrilldownSheet.tsx` + `frontend/src/components/health/nutrition/DayDrilldownSheet.tsx`

**Analog:** `frontend/src/components/tasks/TaskDetailSheet.tsx` (full file, 792 lines) — z-index scheme, phone-sheet/desktop-modal split, scroll-lock.

**Scrim + sheet/modal positional split** (lines 431-488):
```typescript
{/* Scrim — above BottomTabs (z:100) so it covers the phone tab bar too */}
<div onClick={onClose} style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(10,10,10,0.7)', zIndex: 190 }} aria-hidden="true" />

<div
  role="dialog" aria-modal="true"
  style={{
    position: 'fixed', zIndex: 191,
    ...(isPhone
      ? { left: 0, right: 0, bottom: keyboardInset, maxHeight: `calc(100dvh - ${keyboardInset}px - 24px)`,
          borderRadius: '16px 16px 0 0', transform: slideIn ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 0.25s ease-out' }
      : { left: '50%', top: '50%',
          transform: slideIn ? 'translate(-50%, -50%)' : 'translate(-50%, calc(-50% + 20px))',
          transition: 'transform 0.25s ease-out, opacity 0.25s ease-out',
          maxWidth: '480px', width: '100%', maxHeight: '90dvh', borderRadius: '16px' }),
    backgroundColor: secondary, border: `1px solid ${border}`,
    overflow: 'hidden', display: 'flex', flexDirection: 'column',
  }}
>
```
**Scroll-lock** (lines 292-299):
```typescript
useEffect(() => {
  if (!open) return
  const prev = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  return () => { document.body.style.overflow = prev }
}, [open])
```
Per the UI-SPEC's own note, the health drill-down sheets contain no text inputs, so `useVisualViewport`'s `keyboardInset` tracking is unnecessary — use `bottom: 0` (not `keyboardInset`) on phone. The `onMouseDown={preventDefault}` close-button trap (from the memory note "blur-before-click eats submits") still applies to the close/chevron button even without text inputs, since a tap elsewhere on the sheet could still blur focus before the click registers — apply defensively.

---

### `frontend/src/components/health/nutrition/SlotAdherenceGrid.tsx`

**Analog:** `frontend/src/components/habits/ContributionGrid.tsx` (full file, 147 lines) — explicitly directed reuse per RESEARCH.md Pattern 3 and UI-SPEC Component Inventory.

**Grid CSS to copy nearly verbatim** (lines 106-146):
```typescript
<div ref={scrollRef} style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
  <div
    role="grid"
    aria-label="..."
    style={{
      display: 'grid',
      gridTemplateColumns: `repeat(${numCols}, 12px)`,
      gridTemplateRows: 'repeat(7, 12px)',   // → repeat(numSlots, 12px) for the health grid
      gridAutoFlow: 'column',
      gap: '2px',                             // named exception — do not round to 4px
      width: 'max-content',
    }}
  >
    {cells.map((cell) => (
      <div
        key={cell.date}
        role="gridcell"
        aria-label={`${cell.date}: ${cell.state}`}
        style={{ width: 12, height: 12, borderRadius: 2, backgroundColor: CELL_COLORS[cell.state], flexShrink: 0 }}
      />
    ))}
  </div>
</div>
```
**Auto-scroll-to-newest on mount** (lines 101-104):
```typescript
useEffect(() => {
  const el = scrollRef.current
  if (el) el.scrollLeft = el.scrollWidth
}, [cells])
```
Adapt: rows = fueling slots (not weekdays — `gridTemplateRows: repeat(numSlots, 12px)`), columns = days-in-range (not weeks — no `mondayIndex`/`leadingPad` logic needed since a day-based grid has no weekday-alignment requirement). 2-state fill (`CELL_COLORS = { hit: '#38BDF8', miss: skeleton }` per the UI-SPEC color table) instead of 4-state. `aria-label="{date}, {slot}: {logged/not logged}"` per the UI-SPEC Component Inventory row.

---

### `frontend/src/components/health/sleep/HeaderStatRow.tsx`

**Analog:** `frontend/src/components/timeline/TimelineHeader.tsx` — `NutritionStrip` (lines 119-199) and `GarminStatsRows` (lines 71-113)

**Horizontal-scroll stat strip pattern** (lines 145-199, `NutritionStrip`):
```typescript
<div
  className="flex md:hidden"   // health page: inline on desktop per D-19, scroll on phone
  style={{ overflowX: 'auto', gap: '12px', paddingTop: '8px', paddingBottom: '4px' }}
  aria-label="..."
>
  {items.map(({ label, value }) => (
    <div key={label} style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
      <span style={{ fontSize: typography.body.fontSize, fontWeight: 600, color: textPrimary, fontFamily }}>{value}</span>
      <span style={{ fontSize: typography.label.fontSize, color: textSecondary, fontFamily }}>{label}</span>
    </div>
  ))}
</div>
```
Note the responsive-display gotcha called out in the source comment (line 149-151): "Layout driven by classes only — inline `display` would override `md:hidden`." `HeaderStatRow` must use `className="flex md:hidden"` (phone) / a plain non-`display`-touching wrapper for desktop's inline row — never `style={{ display: ... }}` on the responsive wrapper (Phase 27 UAT lesson, bit 4× per project memory).

**Defensive null-coercion pattern** (lines 125-135, `NutritionStrip`):
```typescript
const kcal = totals?.kcal ?? 0
// ...
if (!kcal && !protein && !carbs && !fat && !fiber) return null
```
Apply the equivalent null-coalescing to `HeaderStatRow`'s 5 stats (HRV/sleep/body battery/resting HR/readiness) since the sleep endpoint's `pipeline_active: false` case means all 5 could be `null` — render nothing (or the pipeline-not-live placeholder) rather than a row of dashes with `.toFixed()` crashes.

---

## Shared Patterns

### Auth — `require_hub_session`
**Source:** `interfaces/hub_auth.py` (~line 265), used throughout `interfaces/web_server.py`
**Apply to:** All 3 new `/api/health/*` route handlers
```python
@app.get("/api/health/training")
async def api_health_training(
    range: str = "30d",
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    ...
```
No new auth logic — HUB-04 invariant (do NOT touch OIDC `/cron|/internal|/trigger` routes).

### Event-loop safety — `run_in_executor` for every sync call
**Source:** `interfaces/web_server.py` (used 40+ times throughout the file, e.g. line 888 `await loop.run_in_executor(None, _biometric.run_one_batch)`)
**Apply to:** Every Firestore AND Postgres read in all 3 new routes — this is the single most safety-critical pattern in the phase (Pitfall 3 in RESEARCH.md, the documented 2026-06-24 weekly-review-500 incident class).
```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, some_sync_fn, arg1, arg2)
```

### JSON-safety — `_jsonsafe_doc`
**Source:** `memory/firestore_db.py` (~line 885), imported lazily in every `/api/*` route (e.g. `interfaces/web_server.py` line 1467)
**Apply to:** Every Firestore-derived dict/list before it goes into a `JSONResponse` — strips `DatetimeWithNanoseconds` (SERVER_TIMESTAMP) fields that break `json.dumps`/FastAPI serialization.
```python
from memory.firestore_db import _jsonsafe_doc  # lazy import — Shared Pattern 5
payload = _jsonsafe_doc({...})
return JSONResponse(content=payload)
```

### Server-computes / client-renders (never re-derive totals in the browser)
**Source:** `core/tools.py::_handle_fetch_nutrition_trend` (~2302-2372); explicitly re-stated as the phase's #1 anti-pattern-to-avoid in RESEARCH.md.
**Apply to:** All 3 backend endpoints (averages, weekly bucketing, gap markers, targets all computed server-side) AND all frontend chart/summary components (render `{x, y}` points and pre-computed averages exactly as received — no summing/averaging in TypeScript).

### Slot label ≠ eating time (CLAUDE.md §6 invariant)
**Source:** `interfaces/web_server.py::_today_meals` (~1170-1213), `frontend/src/api/today.ts` `MealItem` JSDoc (~48-60)
```python
# NOTE: deliberately no `slot_time` field on the wire — ... the HH:MM slot
# identifier must never be surfaced as (or risk being rendered as) an eating time.
```
**Apply to:** `_health_nutrition_*` handlers, `SlotAdherenceGrid`, `DayDrilldownSheet` — never emit or render a clock time derived from the canonical 08:00/12:00/20:00 slot timestamps; slot LABELS only ("Breakfast"/"Post-lift"/etc.).

### Responsive display — class-driven, never inline `style={{ display }}`
**Source:** `frontend/src/components/timeline/TimelineHeader.tsx` (lines 149-151, 259-261) — documented Phase-27 UAT gotcha, reconfirmed in project memory as bit 4× and flagged for re-sweep on Phase 30.
**Apply to:** Every phone-vs-desktop wrapper in all new health components (SubTabs full-width vs sidebar-relative, HeaderStatRow scroll-strip vs inline row, chart card 2-column-grid vs stacked).

### Bottom-sheet / modal chrome (z-index, scroll-lock, animation)
**Source:** `frontend/src/components/tasks/TaskDetailSheet.tsx` (full file) — z:190 scrim / z:191 sheet, 250ms ease-out slide, `document.body.style.overflow = 'hidden'` scroll-lock.
**Apply to:** All 4 new drill-down sheets (Strength/Run/Benchmark/DayDrilldown).

## No Analog Found

None. Every file in this phase has at least a role-match analog in the existing codebase — this is consistent with RESEARCH.md's framing of Phase 30 as "almost entirely an integration phase, not a new-technology phase."

The closest thing to a novel component is the SVG chart toolkit (`LineChart`/`BarChart`/`ChartTooltip`), which has no *chart-rendering* analog (this is the first chart in the hub) but does have a strong *philosophy* analog (`ContributionGrid.tsx`'s "hand-rolled, no library" precedent) and a strong *semantics* analog for the one genuinely hard part — gap rendering (`_handle_fetch_nutrition_trend`'s `missing_dates` contract). Both are captured above under the chart primitives' Pattern Assignment.

## Metadata

**Analog search scope:** `interfaces/web_server.py`, `memory/firestore_db.py`, `core/tools.py`, `core/recovery_metrics.py`, `mcp_tools/database_tool.py`, `frontend/src/App.tsx`, `frontend/src/api/*.ts`, `frontend/src/hooks/*.ts`, `frontend/src/components/{habits,tasks,timeline}/*.tsx`, `frontend/src/tokens.ts`, `tests/test_api_today.py`
**Files scanned:** 16 read in full or by targeted section, plus grep sweeps across `memory/firestore_db.py` (2400+ lines) and `interfaces/web_server.py` (2500+ lines) to locate store classes / route registrations without loading the whole file
**Pattern extraction date:** 2026-07-06
