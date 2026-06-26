# Phase 28: Habits & Supplements - Pattern Map

**Mapped:** 2026-06-26
**Files analyzed:** 16 new/modified files
**Analogs found:** 16 / 16

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `memory/firestore_db.py` → `HabitStore` | store | CRUD + batch | `memory/firestore_db.py::TaskStore` (lines 2500–2841) + `MealStore` (lines 711–882) | exact |
| `compute_streak_and_grid` (in `memory/firestore_db.py` or new module) | utility | transform | `memory/firestore_db.py::_next_due_date` + `_advance_once` (weekday math); `core/autonomous.py` lines 321, 347 (`_TZ` date arithmetic) | role-match |
| `interfaces/web_server.py` → `/api/habits/*` routes | route/controller | request-response | `interfaces/web_server.py` task routes (lines 1725–2028) | exact |
| `core/tools.py` → `get_habit_adherence` + `list_pending_habits` tools | utility + handler | request-response | `core/tools.py::_handle_task_list` + `_handle_task_create` (lines 1452–1565) + `_HANDLERS` (lines 2449–2510) | exact |
| `core/autonomous.py` → `_gather_habit_adherence` + jobs dict extension | service | event-driven | `core/autonomous.py::_gather_native_overdue` (lines 236–256) + `gather_situation` jobs dict (lines 443–461) + `_is_empty_signals` (lines 172–205) + `_build_triage_prompt` (lines 515–563) + `_compose_layer2` (lines 663–713) | exact |
| `core/proactive_alerts.py` → `SLOT_SUPPLEMENTS` rewire | service | request-response | `core/proactive_alerts.py::_collect_detected_topics` (lines 653–682) + `run_proactive_alerts` dedup gate (lines 875–916) | role-match |
| `frontend/src/api/habits.ts` | utility | request-response | `frontend/src/api/tasks.ts` | exact |
| `frontend/src/hooks/useHabits.ts` | hook | request-response | `frontend/src/hooks/useTasks.ts` | exact |
| `frontend/src/components/habits/HabitsPage.tsx` | component | request-response | `frontend/src/components/tasks/TasksPage.tsx` | exact |
| `frontend/src/components/habits/HabitRow.tsx` | component | request-response | `frontend/src/components/tasks/TaskRow.tsx` | exact |
| `frontend/src/components/habits/HabitDetailView.tsx` | component | request-response | `frontend/src/components/tasks/TaskDetailSheet.tsx` (lines 430–499) | exact |
| `frontend/src/components/habits/HabitCreateEditSheet.tsx` | component | request-response | `frontend/src/components/tasks/TaskDetailSheet.tsx` (lines 430–499) | exact |
| `frontend/src/components/habits/DoseEditSheet.tsx` | component | request-response | `frontend/src/components/tasks/TaskDetailSheet.tsx` (lines 430–499) — same iOS z-index/keyboard/scroll-lock/onMouseDown rules | role-match |
| `frontend/src/components/habits/ContributionGrid.tsx` | component | transform | no prior analog (no heatmap/grid component exists) — use RESEARCH.md Pattern 6 | no analog |
| `frontend/src/components/timeline/HabitsBand.tsx` | component | request-response | `frontend/src/components/timeline/DueTasksBand.tsx` | exact |
| `frontend/src/components/layout/GlanceRail.tsx` (modify) | component | request-response | `frontend/src/components/layout/GlanceRail.tsx` — Tasks card block (lines 123–189) | exact |
| `frontend/src/store/undoStore.ts` (modify) | store | event-driven | `frontend/src/store/undoStore.ts` — existing `UndoItem` + `UndoState` | exact |
| `frontend/src/App.tsx` (modify) | route | request-response | `frontend/src/App.tsx` lines 58–59 (`TasksPage` function) | exact |
| `tests/test_habit_store.py` | test | batch | `tests/test_task_store.py` (lines 1–225 — mock install + fixture pattern) | exact |
| `tests/test_habits_api.py` | test | request-response | `tests/test_task_store.py` + `tests/test_hub_auth.py` | role-match |

---

## Pattern Assignments

### `memory/firestore_db.py` → `HabitStore` (store, CRUD)

**Analog:** `memory/firestore_db.py::TaskStore` (lines 2500–2841) for class structure, `MealStore` (lines 711–882) for subcollection path.

**Class + `__init__` pattern** (TaskStore lines 2534–2538):
```python
class HabitStore:
    """Native habit/supplement store (Phase 28 — HABIT-01).

    Collection 1 — Definitions: ``habits/{habit_id}``
    Collection 2 — Completions: ``habit_completions/{YYYY-MM-DD}/records/{habit_id}``

    H-28-IV: dates are ALWAYS plain strings ("YYYY-MM-DD") — never Timestamps.
    Only ``updated_at`` uses SERVER_TIMESTAMP, stripped by _jsonsafe_doc.

    Read discipline: list/get/get_pending_today never raise — return []/None on error.
    Write discipline: create/update/log_completion/soft_delete/delete re-raise after
    logger.error so callers know the operation failed.
    """

    _COLLECTION = "habits"
    _COMPLETIONS = "habit_completions"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)
```

**`create` pattern** (TaskStore lines 2540–2570):
```python
def create(self, habit: dict) -> dict:
    import uuid
    from datetime import datetime, timezone

    habit_id = habit.get("id") or uuid.uuid4().hex
    payload = {
        "slot": "Morning",
        "status": "active",
        **habit,
        "id": habit_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    try:
        self._col.document(habit_id).set(payload)
    except Exception:
        logger.error("HabitStore.create failed (name=%r)", habit.get("name"), exc_info=True)
        raise
    result = {k: v for k, v in payload.items() if k != "updated_at"}
    return result
```

**`list` pattern** (TaskStore lines 2583–2598):
```python
def list_active(self) -> list[dict]:
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = self._col.where(filter=FieldFilter("status", "==", "active"))
        return [_jsonsafe_doc(snap.to_dict() or {}) for snap in query.stream()]
    except Exception:
        logger.warning("HabitStore.list_active failed", exc_info=True)
        return []
```

**`update` pattern** (TaskStore lines 2600–2618):
```python
def update(self, habit_id: str, fields: dict) -> dict | None:
    try:
        self._col.document(habit_id).update(
            {**fields, "updated_at": firestore.SERVER_TIMESTAMP}
        )
    except Exception:
        logger.error("HabitStore.update(%r) failed", habit_id, exc_info=True)
        raise
    return self.get(habit_id)
```

**`soft_delete` pattern** (TaskStore lines 2620–2637):
```python
def soft_delete(self, habit_id: str) -> None:
    try:
        self._col.document(habit_id).update({
            "status": "completing",
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
    except Exception:
        logger.error("HabitStore.soft_delete(%r) failed", habit_id, exc_info=True)
        raise
```

**`log_completion` pattern** (MealStore subcollection path, lines 758–775):
```python
def log_completion(
    self, date_str: str, habit_id: str, done: bool, dose_taken: str | None = None
) -> None:
    from datetime import datetime, timezone
    doc_ref = (
        self._client.collection(self._COMPLETIONS)
        .document(date_str)
        .collection("records")
        .document(habit_id)
    )
    if not done:
        try:
            doc_ref.delete()
        except Exception:
            logger.error("HabitStore.log_completion: delete failed (%r, %r)", date_str, habit_id, exc_info=True)
            raise
        return
    payload = {
        "habit_id": habit_id,
        "date": date_str,
        "done": True,
        "dose_taken": dose_taken,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    try:
        doc_ref.set(payload, merge=True)
    except Exception:
        logger.error("HabitStore.log_completion failed (%r, %r)", date_str, habit_id, exc_info=True)
        raise
```

**`get_completions_for_date` pattern** (MealStore.get_day lines 777–816):
```python
def get_completions_for_date(self, date_str: str) -> dict[str, dict]:
    """Return {habit_id: completion_doc} for a date. Never raises."""
    try:
        snaps = (
            self._client.collection(self._COMPLETIONS)
            .document(date_str)
            .collection("records")
            .stream()
        )
        return {
            snap.id: _jsonsafe_doc(snap.to_dict() or {})
            for snap in snaps
        }
    except Exception:
        logger.warning("HabitStore.get_completions_for_date(%r) failed", date_str, exc_info=True)
        return {}
```

**`_jsonsafe_doc` usage rule** (line 885, and TaskStore.get line 2578):
Every read method that returns a document dict must apply `_jsonsafe_doc`. `updated_at` is `DatetimeWithNanoseconds` after a Firestore read — `json.dumps` raises on it without this call. See also MealStore pitfall note at line 724.

---

### `compute_streak_and_grid` (utility, transform)

**Analog:** `core/autonomous.py` lines 321, 347 (`_TZ` local-date pattern); `memory/firestore_db.py::_advance_once` (weekday int arithmetic, lines 2415–2454).

**`_TZ` date arithmetic pattern** (autonomous.py lines 39–45, 321):
```python
from zoneinfo import ZoneInfo
_TZ = ZoneInfo("Asia/Jerusalem")

# Pattern for "today in Jerusalem":
today_iso = now.astimezone(_TZ).date().isoformat()

# Pattern for N days back:
d = (now.astimezone(_TZ).date() - timedelta(days=days_back)).isoformat()
```

**Weekday int convention** (from `_advance_once` in firestore_db.py lines 2415–2454): Python `datetime.date.weekday()` — Mon=0, Sun=6. The schedule `days` field uses the same convention (list of ints or `"daily"`).

**`_is_scheduled` helper pattern** — no existing analog for effective-dated schedule lookup; implement fresh following the RESEARCH.md Pattern 2 algorithm. Key: `sorted(schedule_history, key=lambda r: r["effective_from"])` then find `max(rev for rev in revisions if rev["effective_from"] <= target_date.isoformat())`.

**DST safety rule:** Pass `datetime.date` objects (no time component) into `compute_streak_and_grid`. Convert `now` to local date at the call site via `datetime.now(_TZ).date()` before calling the function. Inside the function use only `date` arithmetic (`timedelta(days=N)`) — DST transitions are invisible at the `datetime.date` level.

---

### `interfaces/web_server.py` → `/api/habits/*` routes (route, request-response)

**Analog:** `interfaces/web_server.py` task routes (lines 1725–2028).

**Route registration block pattern** (lines 1725–1732):
```python
# Habit routes — /api/habits/*
# Plan 28-02, HABIT-01 / HABIT-02
#
# All routes are behind Depends(require_hub_session) (T-27-AC).
# All sync Firestore calls run via loop.run_in_executor (Pitfall 2).
# All Firestore output passes through _jsonsafe_doc (Pitfall 4).
# Place BEFORE the SPA mount so these routes are reachable (Pitfall 1).
```

**Pydantic validation pattern** (lines 1750–1782):
```python
from pydantic import BaseModel, Field
from typing import Literal

class CreateHabitInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    type: Literal["habit", "supplement"] = "habit"
    dose: str | None = Field(None, max_length=200)
    slot: Literal["Morning", "Noon", "Evening", "Bedtime"] = "Morning"
    days: str | list[int] = "daily"  # "daily" | [0..6] weekday ints

class CheckinInput(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    done: bool = True
    dose_taken: str | None = Field(None, max_length=200)
```

**Route handler pattern** — GET list (lines 1855–1877):
```python
@app.get("/api/habits")
async def api_list_habits(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    from memory.firestore_db import HabitStore, _jsonsafe_doc

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    habits = await loop.run_in_executor(None, store.list_active)
    return JSONResponse(content=_jsonsafe_doc({"habits": habits}))
```

**Route handler pattern** — POST checkin (analog: lines 1912–1935):
```python
@app.post("/api/habits/{habit_id}/checkin")
async def api_habit_checkin(
    habit_id: str,
    body: CheckinInput,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    from memory.firestore_db import HabitStore
    from zoneinfo import ZoneInfo

    # D-11 backfill gate: date must be today or yesterday
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    yesterday_iso = (datetime.now(ZoneInfo("Asia/Jerusalem")).date() - timedelta(days=1)).isoformat()
    if body.date not in (today_iso, yesterday_iso):
        raise HTTPException(status_code=400, detail={"error": "date must be today or yesterday"})

    loop = asyncio.get_running_loop()
    store = HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    await loop.run_in_executor(
        None, store.log_completion, body.date, habit_id, body.done, body.dose_taken
    )
    return JSONResponse(content={"ok": True})
```

**Hard-delete gate pattern** (lines 2011–2027) — enforce `status="completing"` before deleting:
```python
habit = await loop.run_in_executor(None, store.get, habit_id)
if habit is None or habit.get("status") != "completing":
    raise HTTPException(
        status_code=409,
        detail={"error": "habit not in completing state"},
    )
await loop.run_in_executor(None, store.delete, habit_id)
```

**`run_in_executor` rule** (line 1817, 1822): All sync Firestore calls MUST use `loop.run_in_executor(None, fn, *args)` — not inline `await` calls on sync functions (Cloud Run single-worker Pitfall 2; same class as slow-reply incident 2026-06-12).

---

### `core/tools.py` → `get_habit_adherence` + `list_pending_habits` tools (utility + handler, request-response)

**Analog:** `core/tools.py::_handle_task_list` (lines 1497–1515), `_get_task_store` singleton (lines 1452–1458), `_HANDLERS` dict entry (lines 2460–2461), `task_list` schema (lines 249–277).

**Singleton accessor pattern** (lines 1452–1458):
```python
def _get_habit_store():
    """Return a HabitStore instance using env-driven project/database config."""
    from memory.firestore_db import HabitStore
    return HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )

def _habit_today_iso() -> str:
    """Return today's date in Asia/Jerusalem as YYYY-MM-DD."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
```

**Tool schema pattern** (lines 249–277 — `task_list`):
```python
{
    "name": "get_habit_adherence",
    "description": (
        "Read today's pending habits and supplements with streak info. "
        "Returns list of items not yet checked off today with their current streak. "
        "Use to assess adherence or to prepare a coaching note."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "slot": {
                "type": "string",
                "enum": ["Morning", "Noon", "Evening", "Bedtime"],
                "description": "Filter by time slot. Omit for all slots.",
            },
            "type": {
                "type": "string",
                "enum": ["habit", "supplement"],
                "description": "Filter by item type. Omit for both.",
            },
        },
        "required": [],
    },
},
```

**`_HANDLERS` registration pattern** (lines 2459–2465):
```python
# Phase 28 Plan 03 — native HabitStore tools (HABIT-05)
"get_habit_adherence":    lambda args: _handle_get_habit_adherence(**args),
"list_pending_habits":    lambda args: _handle_list_pending_habits(**args),
```

**Handler implementation pattern** (lines 1497–1515):
```python
def _handle_get_habit_adherence(
    slot: str | None = None,
    type: str | None = None,
) -> str:
    """Return pending habits/supplements for today with streaks."""
    store = _get_habit_store()
    today_iso = _habit_today_iso()
    pending = store.get_pending_today(today_iso)
    if slot:
        pending = [h for h in pending if h.get("slot") == slot]
    if type:
        pending = [h for h in pending if h.get("type") == type]
    return json.dumps(pending)
```

---

### `core/autonomous.py` → `_gather_habit_adherence` + jobs dict extension (service, event-driven)

**Analog:** `core/autonomous.py::_gather_native_overdue` (lines 236–256); `gather_situation` jobs dict (lines 443–461); `_is_empty_signals` (lines 172–205); `_build_triage_prompt` (lines 515–563); `_compose_layer2` (lines 663–713).

**Gather function pattern** (lines 236–256):
```python
def _gather_habit_adherence(now: datetime, project_id: str, database: str) -> list[dict]:
    """Layer-0 gather: today's pending habits/supplements with streak (D-15/D-16).

    Returns list of pending items: [
      {"habit_id", "name", "type", "slot", "streak", "dose"},
      ...
    ]
    Filtered by CoachingTopicStore dedup (D-17): items already nudged today
    are excluded. Empty list on any error (sentinel pattern).
    """
    try:
        from zoneinfo import ZoneInfo
        from memory.firestore_db import HabitStore, CoachingTopicStore
        today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        store = HabitStore(project_id=project_id, database=database)
        pending = store.get_pending_today(today_iso)
        # D-17: filter out items already nudged today
        cts = CoachingTopicStore(project_id=project_id, database=database)
        return [
            h for h in pending
            if not cts.has_topic(today_iso, f"habit-nudge:{h['habit_id']}:{today_iso}")
        ]
    except Exception:
        logger.warning("autonomous: habit_adherence gather failed", exc_info=True)
        return []
```

**`jobs` dict extension pattern** (lines 443–461):
```python
jobs: dict[str, callable] = {
    "calendar":               lambda: _gather_calendar(now),
    "ticktick_overdue":       _gather_native_overdue,
    # ... existing keys ...
    # Phase 28 — add:
    "habit_pending":          lambda: _gather_habit_adherence(now, project_id, database),
}
```

**`_is_empty_signals` extension pattern** (lines 172–205):
```python
# Add after existing checks, before final return True:
if situation.get("habit_pending"):
    return False   # pending habits are a valid tick trigger (D-15: per-slot salience)
```

**`_build_triage_prompt` snap dict extension** (lines 526–538):
```python
snap = {
    "calendar":             situation.get("calendar", []),
    "ticktick_overdue":     situation.get("ticktick_overdue", []),
    # ... existing keys ...
    # Phase 28 — add:
    "habit_pending":        situation.get("habit_pending", []),
}
```

**`_compose_layer2` snap_summary extension** (lines 694–705):
```python
snap_summary = json.dumps({
    "calendar":             situation.get("calendar", []),
    "ticktick_overdue":     situation.get("ticktick_overdue", []),
    # ... existing keys ...
    # Phase 28 — add:
    "habit_pending":        situation.get("habit_pending", []),
}, indent=2, ensure_ascii=False)
```

**CoachingTopicStore dedup write pattern** (analog: proactive_alerts.py lines 906–914) — write `add_topic` ONLY after `send_and_inject` succeeds:
```python
topic_key = f"habit-nudge:{habit_id}:{today_iso}"
# After send succeeds:
_cts.add_topic(today_iso, topic_key)
# Topic key must be a plain string — NOT a dict (Pitfall 4 / ArrayUnion deep-equality)
```

---

### `core/proactive_alerts.py` → `SLOT_SUPPLEMENTS` rewire (service, request-response)

**Analog:** `core/proactive_alerts.py::_collect_detected_topics` (lines 653–682); `run_proactive_alerts` dedup gate (lines 875–916); existing `SLOT_SUPPLEMENTS` dict (lines 90–94).

**Existing `SLOT_SUPPLEMENTS`** (lines 86–94 — keep as fallback):
```python
SLOT_SUPPLEMENTS: dict[str, str] = {
    "post-am-run": "D3+K2/Omega-3",
    "pm-post-lift": "Creatine",
    "pre-bed": "Mg-Glycinate/Zinc/Copper",
}
```

**New helper to add after `SLOT_SUPPLEMENTS`**:
```python
_HABIT_SLOT_TO_FUELING: dict[str, list[str]] = {
    "Morning":  ["post-am-run"],
    "Noon":     ["pm-post-lift"],
    "Evening":  ["pm-post-lift"],
    "Bedtime":  ["pre-bed"],
}

def _get_supplement_checkoffs(today_iso: str) -> dict:
    """Query HabitStore for supplement check-off state for today (D-01/D-02).

    Returns {fueling_slot: {"name": str, "done": bool}} for all active
    supplements scheduled today, keyed by their mapped fueling slot.
    Falls back to empty dict on any error (non-fatal — prompt degrades gracefully).
    """
    try:
        from memory.firestore_db import HabitStore
        store = HabitStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        active_supplements = [
            h for h in store.list_active()
            if h.get("type") == "supplement"
        ]
        completions = store.get_completions_for_date(today_iso)
        result = {}
        for sup in active_supplements:
            slot = sup.get("slot", "")
            for fueling_slot in _HABIT_SLOT_TO_FUELING.get(slot, []):
                result[fueling_slot] = {
                    "name": sup.get("name", ""),
                    "done": sup["id"] in completions,
                    "habit_id": sup["id"],
                }
        return result
    except Exception:
        logger.warning("proactive_alerts: supplement checkoff query failed", exc_info=True)
        return {}
```

**Insertion point in `run_proactive_alerts`** (after line 873, inside the `try` block that gathers nutrition):
```python
# D-01: query HabitStore for real supplement check-off state
try:
    supplement_checkoffs = _get_supplement_checkoffs(today_iso)
    if supplement_checkoffs:
        alerts_context["supplement_checkoffs"] = supplement_checkoffs
except Exception:
    logger.warning("proactive_alerts: supplement checkoff gather failed", exc_info=True)
```

**Backward compatibility rule**: Keep `SLOT_SUPPLEMENTS` dict unchanged. The prompt template uses `supplement_checkoffs` when present; falls back to its existing hardcoded supplement names when not. The existing `test_slot_supplements_constant_exists` test continues to pass.

---

### `frontend/src/api/habits.ts` (utility, request-response)

**Analog:** `frontend/src/api/tasks.ts` (entire file).

**`apiFetch` import pattern** (tasks.ts line 17):
```typescript
import { apiFetch } from './client'
```

**Type definitions pattern** (tasks.ts lines 23–55):
```typescript
export type HabitType = 'habit' | 'supplement'
export type HabitSlot = 'Morning' | 'Noon' | 'Evening' | 'Bedtime'
export type GridState = 'done' | 'missed' | 'not-scheduled' | 'pending'

export interface ScheduleRevision {
  effective_from: string   // YYYY-MM-DD plain string
  days: 'daily' | number[] // "daily" or weekday ints (Mon=0)
}

export interface Habit {
  id: string
  name: string
  type: HabitType
  dose: string | null
  slot: HabitSlot
  schedule_history: ScheduleRevision[]
  status: 'active' | 'completing'
  created_at: string
}

export interface GridCell {
  date: string      // YYYY-MM-DD
  state: GridState
}

export interface HabitHistory {
  streak: number
  grid: GridCell[]
}

export interface HabitSummary {
  pending_today: number
  streak_leaders: Array<{ id: string; name: string; streak: number }>
}
```

**API function pattern** (tasks.ts lines 65–146):
```typescript
export async function fetchHabits(): Promise<Habit[]> {
  const data = await apiFetch<{ habits: Habit[] }>('/api/habits')
  return data.habits
}

export async function checkinHabit(
  id: string,
  date: string,
  done: boolean,
  dose_taken?: string | null,
): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/habits/${id}/checkin`, {
    method: 'POST',
    body: JSON.stringify({ date, done, dose_taken }),
  })
}

export async function fetchHabitHistory(id: string): Promise<HabitHistory> {
  return apiFetch<HabitHistory>(`/api/habits/${id}/history`)
}

export async function softDeleteHabit(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/habits/${id}/soft-delete`, { method: 'POST' })
}

export async function hardDeleteHabit(id: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/api/habits/${id}/hard-delete`, { method: 'POST' })
}
```

---

### `frontend/src/hooks/useHabits.ts` (hook, request-response)

**Analog:** `frontend/src/hooks/useTasks.ts` (entire file).

**Query key factory + useQuery pattern** (useTasks.ts lines 29–49):
```typescript
export const HABITS_QUERY_KEY = ['habits'] as const

export function useHabits() {
  return useQuery<Habit[], Error>({
    queryKey: HABITS_QUERY_KEY,
    queryFn: fetchHabits,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
  })
}
```

**Optimistic toggle mutation pattern** (useTasks.ts lines 154–186 — `useCompleteTask`):
```typescript
export function useCheckOffHabit() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ habitId, date, done, doseTaken }: CheckOffArgs) =>
      checkinHabit(habitId, date, done, doseTaken),

    onMutate: async ({ habitId, done }) => {
      await queryClient.cancelQueries({ queryKey: HABITS_QUERY_KEY })
      const prev = queryClient.getQueryData<Habit[]>(HABITS_QUERY_KEY)
      // Optimistic: flip done_today state
      queryClient.setQueryData<Habit[]>(HABITS_QUERY_KEY, (old) =>
        (old ?? []).map((h) => h.id === habitId ? { ...h, done_today: done } : h)
      )
      return { prev }
    },

    onError: (_err, _vars, ctx) => {
      if (ctx?.prev !== undefined) {
        queryClient.setQueryData<Habit[]>(HABITS_QUERY_KEY, ctx.prev)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: HABITS_QUERY_KEY })
    },
  })
}
```

**Undo delete pattern** (useTasks.ts `useSoftDeleteTask` lines 197–224): identical structure; replace `softDeleteTask` with `softDeleteHabit`, `tasksQueryKey` with `HABITS_QUERY_KEY`.

---

### `frontend/src/components/habits/HabitRow.tsx` (component, request-response)

**Analog:** `frontend/src/components/tasks/TaskRow.tsx` (entire file).

**Imports pattern** (TaskRow.tsx lines 23–48):
```typescript
import { useState, useRef } from 'react'
import { Circle, CheckCircle2, MoreHorizontal } from 'lucide-react'
import { useCheckOffHabit, useSoftDeleteHabit } from '../../hooks/useHabits'
import { useUndoStore } from '../../store/undoStore'
import { hardDeleteHabit } from '../../api/habits'
import type { Habit } from '../../api/habits'
import {
  accent, border, dominant, secondary, success,
  textPrimary, textSecondary, typography, fontFamily,
} from '../../tokens'
```

**Check-off toggle pattern** (TaskRow.tsx lines 171–210 — `handleComplete`):
- Habit type: immediate toggle (no dose sheet). Circle fills `#6366F1` for 150ms.
- Supplement type: open `DoseEditSheet` instead of immediate toggle.
- No row collapse after toggle (unlike tasks — the row stays visible).
- Touch target: 44px × 44px centered hit area.

**Slot chip pattern** (new for habits — no task analog):
```typescript
function SlotChip({ slot }: { slot: HabitSlot }) {
  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '3px 8px',
      borderRadius: '6px',
      backgroundColor: border,  // #2A2A2A
      color: textSecondary,
      fontSize: typography.label.fontSize,
      fontFamily,
      flexShrink: 0,
    }}>
      {slot}
    </div>
  )
}
```

**Kebab menu pattern** (TaskRow.tsx lines 159–161 + kebab open/close logic): copy exactly; replace `aria-label="Task options"` with `aria-label="Habit options"`.

---

### `frontend/src/components/habits/HabitCreateEditSheet.tsx` + `HabitDetailView.tsx` (component, request-response)

**Analog:** `frontend/src/components/tasks/TaskDetailSheet.tsx` (lines 430–499 — iOS sheet pattern).

**iOS sheet z-index + keyboard pattern** (TaskDetailSheet.tsx lines 430–487):
```typescript
// Scrim: z:190 (beats BottomTabs z:100)
// Sheet: z:191
// keyboardInset from useVisualViewport() — tracks iOS soft keyboard
// maxHeight: `calc(100dvh - ${keyboardInset}px - 24px)` — keeps footer visible
// scroll-lock: document.body.style.overflow = 'hidden' on open
// No autoFocus on phone — iOS pans viewport mid-animation
// onMouseDown={e => e.preventDefault()} on dismiss buttons — prevents blur-before-click eating submit
```

**Phone vs desktop render pattern** (TaskDetailSheet.tsx lines 454–479):
```typescript
...(isPhone
  ? {
      left: 0, right: 0,
      bottom: keyboardInset,
      maxHeight: `calc(100dvh - ${keyboardInset}px - 24px)`,
      borderRadius: '16px 16px 0 0',
      transform: slideIn ? 'translateY(0)' : 'translateY(100%)',
      transition: 'transform 0.25s ease-out',
    }
  : {
      left: '50%', top: '50%',
      transform: slideIn ? 'translate(-50%, -50%)' : 'translate(-50%, calc(-50% + 20px))',
      transition: 'transform 0.25s ease-out, opacity 0.25s ease-out',
      maxWidth: '480px', width: '100%',
      maxHeight: '90dvh', borderRadius: '16px',
    }),
```

**`DoseEditSheet` extra z-index**: z:192 (above HabitDetailView z:191). Same iOS rules apply; add `useVisualViewport` for keyboard tracking.

**Responsive show/hide rule** (GlanceRail.tsx line 64 — `className="hidden md:flex md:flex-col"`):
```typescript
// NEVER use style={{ display: 'none' }} for responsive visibility —
// inline display overrides Tailwind md:hidden / hidden md:block.
// Phone-only FAB wrapper:
<div className="md:hidden">   {/* Tailwind class ONLY — no inline display */}
  <TaskFAB />
</div>
```

---

### `frontend/src/components/habits/ContributionGrid.tsx` (component, transform)

**No existing analog** — first grid/heatmap component in the codebase.

**Use RESEARCH.md Pattern 6 directly:**
```typescript
const CELL_COLORS = {
  done:            '#6366F1',  // accent
  missed:          '#3A1A1A',  // muted destructive tint
  'not-scheduled': '#1F1F1F',  // skeleton color
  pending:         '#2A2A2A',  // border color
} as const

function ContributionGrid({ cells }: { cells: GridCell[] }) {
  return (
    <div
      role="grid"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(52, 12px)',
        gridTemplateRows: 'repeat(7, 12px)',
        gap: '2px',     // named exception: 2px not 4px (preserves GitHub-grid density)
        overflowX: 'auto',  // phone: horizontal scroll
      }}
    >
      {cells.map(cell => (
        <div
          key={cell.date}
          role="gridcell"
          aria-label={`${cell.date}: ${cell.state}`}
          style={{
            width: 12, height: 12, borderRadius: 2,
            backgroundColor: CELL_COLORS[cell.state],
          }}
        />
      ))}
    </div>
  )
}
```

**Color token source**: `frontend/src/tokens.ts` — `accent`, `border`, `skeleton` values. Do NOT use hardcoded strings; import from tokens.

---

### `frontend/src/components/timeline/HabitsBand.tsx` (component, request-response)

**Analog:** `frontend/src/components/timeline/DueTasksBand.tsx` (entire file).

**Band header pattern** (DueTasksBand.tsx lines 246–277 — copy exactly, change label):
```typescript
{/* Section header: accent left-border stripe + "Habits" label */}
<div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 14px 6px' }}>
  {/* Accent stripe: 4px × 32px */}
  <div style={{ width: '4px', height: '32px', borderRadius: '2px', backgroundColor: accent, flexShrink: 0 }} aria-hidden="true" />
  <span style={{ fontSize: typography.label.fontSize, fontWeight: typography.label.fontWeight, lineHeight: typography.label.lineHeight, color: textSecondary, fontFamily }}>
    Habits
  </span>
</div>
{/* Rows */}
<div style={{ padding: '0 14px 10px' }}>
  {habitsDueToday.map(h => <HabitsBandRow key={h.id} habit={h} />)}
</div>
```

**Guard pattern** (DueTasksBand.tsx line 236): `if (habitsDueToday.length === 0) return null`

**No title-tap navigation** (divergence from DueTasksBand): habit name in the band is NOT a link. Do not add `useNavigate` + `onClick` on the title row.

**Supplement dose chip pattern** (new for habits band): supplement items show a dose pill badge ("5g") at Label (13px) in `border` background beside the name — not present in DueTasksBand. Tapping a supplement in the band opens `DoseEditSheet` (D-09).

---

### `frontend/src/components/layout/GlanceRail.tsx` (modify, request-response)

**Analog:** `frontend/src/components/layout/GlanceRail.tsx::Tasks card` (lines 123–189).

**Add "Habits" card below "Tasks" card** — copy the Tasks card block (lines 123–189) replacing:
- Navigation: `navigate('/habits')`
- `aria-label`: `"Habits overview — navigate to habits"`
- Heading: `"Habits"`
- Body rows: one row per streak leader (up to 4), label = habit name (13px/400 textSecondary), value = `"[N]-day streak"` (13px/600 textPrimary)
- Empty state: `"No habits defined."` (13px textSecondary)

**`useHabitSummary` hook**: new hook analogous to `useTaskSummary` — fetches `GET /api/habits/summary` → `{ pending_today: N, streak_leaders: [...] }`.

**Font size warning** (GlanceRail.tsx line 166 shows `fontSize: '14px'`): 14px is NOT a declared token in `tokens.ts`. Use `typography.label.fontSize` (13px) for values, `typography.label.fontSize` + `fontWeight: 600` for emphasis — matching the rail's compact-metric pattern.

---

### `frontend/src/store/undoStore.ts` (modify, event-driven)

**Analog:** `frontend/src/store/undoStore.ts` (entire file).

**Extend `UndoItem` type** (undoStore.ts lines 24–42):
```typescript
/** The kind of resource the undo applies to. */
export type UndoResourceType = 'task' | 'habit'

export interface UndoItem {
  id: string
  action: UndoAction
  listId: string          // task list id OR 'habits' for habits
  nextId: string | null
  resourceType: UndoResourceType  // NEW: discriminates task vs habit delete
}
```

**`UndoToast` dispatch**: when `resourceType === 'habit'`, call `hardDeleteHabit(id)` instead of `hardDeleteTask(id)`. The `UndoToast` component reads `activeItem.resourceType` to dispatch the correct hard-delete.

---

### `frontend/src/App.tsx` (modify, request-response)

**Analog:** `frontend/src/App.tsx` lines 58–60 (TasksPage function pattern).

**Replace `ComingSoon` with real page** (lines 76–78):
```typescript
// Before:
function HabitsPage() {
  return <ComingSoon label="Habits" />
}

// After:
import { HabitsPage as HabitsPageComponent } from './components/habits/HabitsPage'
function HabitsPage() {
  return <HabitsPageComponent />
}
```

---

### `tests/test_habit_store.py` (test, batch)

**Analog:** `tests/test_task_store.py` (entire file — Firestore mock installation + test class structure).

**Mock installation pattern** (test_task_store.py lines 39–131): copy `_install_firestore_mock()` verbatim. The function installs `google.cloud.firestore`, `FieldFilter`, `ArrayUnion`, `Increment`, `SERVER_TIMESTAMP` stubs into `sys.modules` before any `memory.firestore_db` import.

**`autouse` fixture pattern** (test_task_store.py lines 137–143):
```python
@pytest.fixture(autouse=True)
def _refresh_firestore_mock(isolated_modules):
    global firestore_db
    import importlib
    _install_firestore_mock()
    firestore_db = importlib.import_module("memory.firestore_db")
```

**Test class structure pattern** (test_task_store.py lines 150–225):
```python
class TestHabitStoreCRUD:
    def test_create_returns_doc_without_updated_at(self): ...
    def test_list_active_filters_status(self): ...
    def test_update_refreshes_updated_at(self): ...
    def test_soft_delete_sets_completing(self): ...

class TestHabitCompletion:
    def test_log_completion_done_writes_subcollection(self): ...
    def test_log_completion_undone_deletes_record(self): ...
    def test_get_completions_for_date_applies_jsonsafe(self): ...

class TestStreakComputation:
    def test_pure_reset_on_missed_day(self): ...
    def test_nonscheduled_days_neutral(self): ...
    def test_pending_does_not_break_streak(self): ...
    def test_yesterday_backfill_repairs_streak(self): ...

class TestDST:
    def test_streak_survives_spring_forward_dst(self): ...
    def test_streak_survives_fall_back_dst(self): ...

class TestGridDerivation:
    def test_four_state_mapping(self): ...
    def test_rolling_year_length(self): ...
```

---

## Shared Patterns

### `_jsonsafe_doc` — JSON-safe Firestore reads
**Source:** `memory/firestore_db.py` line 885
**Apply to:** All `HabitStore` read methods; all `/api/habits/*` route responses
```python
def _jsonsafe_doc(d: dict) -> dict:
    """Return a copy of a Firestore doc dict with non-JSON-serialisable values coerced."""
    return {k: _jsonsafe_value(v) for k, v in d.items()}
```
Call on every `snap.to_dict() or {}` before returning from `HabitStore` methods or API routes.

### `require_hub_session` — Session cookie auth
**Source:** `interfaces/hub_auth.py` (imported at `interfaces/web_server.py` line 41)
**Apply to:** All `/api/habits/*` routes via `Depends(require_hub_session)`
```python
_email: str = Depends(require_hub_session)
```

### `loop.run_in_executor` — Async-safe Firestore
**Source:** `interfaces/web_server.py` lines 1817, 1822, 1871–1876
**Apply to:** Every sync Firestore call inside an `async def` FastAPI route
```python
loop = asyncio.get_running_loop()
result = await loop.run_in_executor(None, store.some_method, arg1, arg2)
```

### `CoachingTopicStore` dedup — Cross-cron suppression
**Source:** `memory/firestore_db.py::CoachingTopicStore` (lines 1817–1928)
**Apply to:** `_gather_habit_adherence` (D-17 per-item-per-day suppression) + `run_proactive_alerts` (D-15 cross-cron dedup)
```python
# Check before nudge:
cts.has_topic(today_iso, f"habit-nudge:{habit_id}:{today_iso}")
# Write AFTER send succeeds (D-10 discipline):
cts.add_topic(today_iso, f"habit-nudge:{habit_id}:{today_iso}")
# Key must be a plain string — NOT a dict (Pitfall 4 / ArrayUnion)
```

### `_TZ = ZoneInfo("Asia/Jerusalem")` — Local date
**Source:** `core/autonomous.py` lines 39–45; used at lines 247, 321, 347, 369, 831, 882
**Apply to:** `compute_streak_and_grid` call site; `/api/habits/{id}/checkin` backfill gate; `_gather_habit_adherence`; proactive_alerts supplement helper
```python
from zoneinfo import ZoneInfo
_TZ = ZoneInfo("Asia/Jerusalem")
today_iso = datetime.now(_TZ).date().isoformat()
```

### `apiFetch` — Hub API client
**Source:** `frontend/src/api/client.ts` (entire file, 43 lines)
**Apply to:** `frontend/src/api/habits.ts` — import and call `apiFetch<T>` for all `/api/habits/*` calls
```typescript
import { apiFetch } from './client'
// Always include credentials: 'include' (handled by apiFetch — do not add manually)
```

### iOS bottom sheet safety
**Source:** `frontend/src/components/tasks/TaskDetailSheet.tsx` lines 430–499; `frontend/src/components/tasks/TaskFAB.tsx` lines 56–60
**Apply to:** `HabitCreateEditSheet`, `HabitDetailView`, `DoseEditSheet`
- Scrim z:190, sheet z:191, DoseEditSheet z:192 (beats BottomTabs z:100)
- No inline `display` — use Tailwind class `className="md:hidden"` for responsive visibility
- `useVisualViewport` for keyboard tracking (`keyboardInset`)
- `document.body.style.overflow = 'hidden'` while open
- No `autoFocus` on phone inputs
- `onMouseDown={e => e.preventDefault()}` on dismiss/cancel buttons

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/src/components/habits/ContributionGrid.tsx` | component | transform | No heatmap/grid component exists in the codebase. Implement from RESEARCH.md Pattern 6 (pure 52×7 CSS grid, no library). |

---

## Metadata

**Analog search scope:** `memory/`, `core/`, `interfaces/`, `frontend/src/`, `tests/`
**Files scanned:** 20 source files read (firestore_db.py, autonomous.py, proactive_alerts.py, tools.py, web_server.py, tasks.ts, useTasks.ts, client.ts, DueTasksBand.tsx, GlanceRail.tsx, TaskRow.tsx, TaskDetailSheet.tsx, TaskFAB.tsx, TasksPage.tsx, UndoToast.tsx, App.tsx, undoStore.ts, test_task_store.py + CONTEXT.md + RESEARCH.md + UI-SPEC.md)
**Pattern extraction date:** 2026-06-26
**Research verification:** All analog line numbers verified against live codebase. RESEARCH.md line references confirmed accurate for autonomous.py (gather_situation jobs dict 443–461, _gather_native_overdue 236–256, _is_empty_signals 172–205, _build_triage_prompt 515–563, _compose_layer2 663–713), proactive_alerts.py (SLOT_SUPPLEMENTS 90–94, _collect_detected_topics 653–682, run_proactive_alerts dedup gate 875–916), firestore_db.py (TaskStore 2500–2841, MealStore 711–882, _jsonsafe_doc 885, CoachingTopicStore 1817–1928).
