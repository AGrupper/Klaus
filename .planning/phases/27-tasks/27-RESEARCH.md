# Phase 27: Tasks — Research

**Researched:** 2026-06-17
**Domain:** Native Firestore task management + React/Vite SPA task UI + Klaus tool swap
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** TaskStore task fields = title, notes (plain text), due (optional date + optional time), priority, list, recurrence rule. No subtasks.
- **D-02:** Lists are user-creatable (create/rename/delete). Single flat level + default Inbox. Tags deferred (D-04). Supersedes TASK-01's "fixed set of lists."
- **D-03:** Priority is 4-level: None / Low / Medium / High (maps 1:1 with TickTick's 0/1/3/5).
- **D-04:** Tags deferred — no tag field, UI, or filter this phase.
- **D-05:** Recurrence = cadence (daily / weekdays / weekly / monthly / every-N-days) + per-task anchor toggle: "stick to schedule" vs "from completion". No RRULE.
- **D-06:** Single open instance per recurring series. Schedule-anchored next landing in the past rolls forward to the next future occurrence. Never materialize a past-due "next."
- **D-07:** Editing a recurring task offers "this occurrence only" vs "this and following." "This & following" edits the rule; "this only" overrides the current instance.
- **D-08:** No automated import script and no reconciliation report. Manual re-entry. Descopes TASK-06 + ROADMAP SC-6.
- **D-09:** Migration safety order: build native → Amit re-enters tasks → UAT → remove TickTick tools → cancel subscription.
- **D-10:** Quick-add uses a client-side deterministic parser (no LLM). NL dates + Todoist-style tokens (#list, !priority). FAB on phone, N-key on desktop.
- **D-11:** Due/overdue tasks appear on the Today timeline as a pinned "Due today" band (date-only tasks grouped there; overdue flagged). Tasks with due-time slot inline at that time.
- **D-12:** Glance rail counts due-today + overdue combined; overdue visually emphasized.
- **D-13:** Completed tasks are NOT retained. Completing removes the task; undo toast (few-second window) is the only recovery. No completed view. Soft-mark then hard-delete after the undo window — mechanics are Claude's discretion.
- **D-14:** Delete = undo toast, no Trash bin. Hard removal after the window.
- **D-15:** For recurring tasks, completion generates the next instance, then clears the current one. Undo reverses both.
- **D-16:** Klaus gets a full native task toolset: create, list/query (by list/date/priority/overdue), complete, reschedule, edit, delete. Replaces TickTick add_task/get_today_tasks (removed per D-09 order).
- **D-17:** Autonomous tick behavior unchanged. _gather_ticktick_overdue + ticktick_overdue situation key repointed from ticktick_tool to TaskStore — pure data-source swap.
- **D-18:** Auto-sort, no manual drag-reorder. Sort + group control (by due date or priority). Day-scoped views auto-sort by priority.
- **D-19:** No exact-time task reminders / OS notifications in Phase 27. Phase 29 (Web Push) brings them.

### Claude's Discretion
- Date logic in Asia/Jerusalem local time.
- Optimistic create/edit following Phase 26's react-query pattern, with rollback on failure. Offline task creation deferred.
- Plain-text notes; list views refresh-on-focus; no real-time sync.
- TaskStore document/collection shape.
- NL-date library choice (e.g. chrono-node).
- Month-end clamping for monthly recurrence.
- Exact undo-toast duration.
- Soft-mark → hard-delete mechanics.
- Completion micro-animation specifics (handled by UI-SPEC).

### Deferred Ideas (OUT OF SCOPE)
- Tags (field + filter UI).
- Automated TickTick import + reconciliation report.
- Manual drag-reorder of tasks.
- Completed-tasks view / history.
- Exact-time task reminders / OS notifications — Phase 29.
- Offline task creation (write queue) — HUBX-01/05, v2.
- Proactive task-nudging via the autonomous tick.
- Subtasks / hierarchies, complex RRULE recurrence.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TASK-01 | Create, edit, complete, delete tasks with title/notes/due/priority, user-creatable lists + Inbox, Firestore TaskStore | Covered by TaskStore schema (Unknown 4), /api/* CRUD endpoints (Phase 26 pattern) |
| TASK-02 | Simple recurrence: daily/weekdays/weekly/monthly/every-N-days-from-completion | Covered by recurrence engine (Unknown 2) — server-side next-instance computation |
| TASK-03 | Quick-add (FAB/N-key) parses NL dates while typing | Covered by chrono-node recommendation (Unknown 1) |
| TASK-04 | Completion micro-animation + undo toast; completed tasks not retained | Covered by soft-mark/hard-delete mechanic (Unknown 3); UI-SPEC has animation spec |
| TASK-05 | Klaus native tools replace TickTick; autonomous Layer-0 gather reads native overdue | Covered by tool swap map (Unknown 5) |
| TASK-06 | Manual TickTick migration in safety order | Research-free (no code to build for import); migration steps documented |
| TASK-07 | Due/overdue on glance rail + Today timeline | Covered by /api/tasks/summary endpoint + useTaskSummary hook pattern |
</phase_requirements>

---

## Summary

Phase 27 builds a native Firestore task manager to replace TickTick across three surfaces: a `/tasks` hub page (currently a ComingSoon placeholder), an extension of the Today timeline and glance rail, and a tool swap inside the Klaus agent loop. The work touches all three tiers (Python FastAPI backend, Firestore datastore, and React/Vite SPA) but follows well-established Phase 26 patterns throughout — every new pattern has a concrete Phase 26 analog to mirror.

The backend requires a new `TaskStore` + `TaskListStore` in `memory/firestore_db.py`, a set of `/api/tasks/*` and `/api/task-lists/*` CRUD endpoints in `interfaces/web_server.py` (session-cookie auth, _jsonsafe_doc on all reads), and native tool schemas + handlers in `core/tools.py` with an autonomous gather repoint in `core/autonomous.py`. The frontend requires a full `components/tasks/` component tree (ten new components per the UI-SPEC), a `useTaskSummary` + `useTaskLists` + `useTasks` hook layer, a client-side NL-date parser for quick-add, and extensions to `GlanceRail.tsx` and `TimelineDay.tsx`.

The five technical unknowns raised in the brief are all resolved below with concrete recommendations. The most consequential is the recurrence engine: computation must be server-side (inside `TaskStore.complete()`) to ensure Klaus's tool calls and the autonomous gather produce the correct next-instance — purely client-side recurrence would leave the agent blind to the generated task.

**Primary recommendation:** Build server-side TaskStore with explicit recurrence-math helpers, use chrono-node 2.9.1 for client-side quick-add parsing, and implement a 4-second client-side undo-window timer with server-side hard-delete at expiry via a dedicated `/api/tasks/{id}/hard-delete` POST endpoint.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Task CRUD persistence | Backend (Firestore TaskStore) | — | All task data lives in Firestore; single source of truth |
| Task CRUD HTTP API | Backend (FastAPI /api/tasks/*) | — | Session-cookie auth required; backend enforces ownership |
| List/project CRUD | Backend (Firestore TaskListStore + /api/task-lists/*) | — | Same auth pattern as task CRUD |
| NL-date token parsing | Frontend (chrono-node + token regex) | — | D-10 explicitly requires client-side deterministic parser; no LLM |
| Recurrence next-instance math | Backend (TaskStore.complete()) | Frontend (display-only derived fields) | Agent tools must trigger next-instance; server is the authority |
| Undo-toast timer countdown | Frontend | Backend (hard-delete endpoint) | Timer is a UI concern; hard-delete is a backend operation |
| Soft-mark (hide from list) | Frontend (optimistic state) | Backend (deleted_at field or status flag) | Immediate UX response; backend is ground truth after confirmation |
| Completion micro-animation | Frontend only | — | Pure CSS/JS; no backend state |
| Overdue count + due-today count | Backend (/api/tasks/summary) | Frontend (useTaskSummary) | Firestore query with server-side date comparison in Asia/Jerusalem |
| Glance rail task section | Frontend (GlanceRail.tsx extension) | — | Consumes useTaskSummary which dedupes the fetch |
| Today timeline due-tasks band | Frontend (DueTasksBand.tsx in TimelineDay) | — | Consumes same useTaskSummary hook |
| Klaus agent task tools | Backend (core/tools.py TaskStore-backed) | — | Agent runs server-side; all tool calls are Python |
| Autonomous overdue gather | Backend (core/autonomous.py repoint) | — | Layer-0 is backend-only; pure data-source swap |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-cloud-firestore | (already installed) | TaskStore + TaskListStore persistence | Project-standard; all stores use it; _jsonsafe_doc pattern established |
| @tanstack/react-query | ^5.101.0 (already installed) | Task data fetching + optimistic mutation | Already in frontend/package.json; useChat/useToday pattern to mirror |
| chrono-node | 2.9.1 | Client-side NL-date parsing for quick-add | 1M+ weekly downloads, MIT, 14-year track record, has ESM, timezone + reference date support via `instant`/`timezone` params |
| lucide-react | 1.18.0 (already installed) | Task UI icons (CheckCircle2, Flag, CalendarDays, etc.) | Already installed per UI-SPEC §Registry Safety |
| zustand | ^5.0.14 (already installed) | Local undo-toast state (active task ID, countdown) | Already in frontend/package.json; same pattern as auth store |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| zoneinfo (Python stdlib 3.9+) | stdlib | Asia/Jerusalem date logic in TaskStore | Already used throughout codebase (ticktick_tool.py line 27: `from zoneinfo import ZoneInfo`) |
| uuid (Python stdlib) | stdlib | Auto-generate task IDs and list IDs | Already used in FollowupStore.add() (`import uuid; uuid.uuid4().hex`) |
| vitest | ^3.2.4 (already installed) | Frontend test framework | Already in devDependencies; useChat.test.tsx pattern to mirror |
| @testing-library/react | ^16.3.2 (already installed) | React hook + component testing | Already used; renderHook pattern from useChat.test.tsx |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| chrono-node | sugar.js | Sugar is 4× larger, more general-purpose; chrono-node is purpose-built for NL dates with cleaner API |
| chrono-node | date-fns parse | date-fns has no NL understanding — it requires strict format strings, not "tomorrow" |
| Client-side 4s timer | Cloud Tasks delayed delete | Cloud Tasks adds significant complexity; 4s is short enough that page-reload risk is acceptable (see Unknown 3) |
| Flat `tasks` Firestore collection | Sub-collection per list | Flat collection with `list_id` field enables cross-list queries (overdue, due-today) without collectionGroup indexes |

**Installation (frontend only — chrono-node is the only new dependency):**
```bash
npm install chrono-node@2.9.1
```

**Version verification:**
```bash
npm view chrono-node version   # 2.9.1 (verified 2026-06-17)
```

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| chrono-node | npm | 14 years (2012-08-20) | ~1M/week | github.com/wanasit/chrono | unavailable | [ASSUMED] — manual check: 14-year history, MIT license, single maintainer (wanasit), active commits through May 2026, no postinstall network call (prepare script is build-only), used by hundreds of well-known projects |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck could not be installed (sandbox restriction). `chrono-node` is tagged `[ASSUMED]` per the package name provenance rule. Manual verification indicates no risk: 14-year npm history, ~1M weekly downloads (per npm trends), MIT license, public GitHub with active maintainer, no network postinstall script. The planner should add a `checkpoint:human-verify` before the `npm install chrono-node` task.*

---

## Architecture Patterns

### System Architecture Diagram

```
Telegram / Hub UI
       │
       ▼
FastAPI /api/tasks/* + /api/task-lists/*         [require_hub_session]
  POST /api/tasks           → TaskStore.create()
  GET  /api/tasks           → TaskStore.list(list_id, ...)
  PATCH /api/tasks/{id}     → TaskStore.update()
  POST /api/tasks/{id}/complete → TaskStore.complete()  ← generates next instance for recurrers
  POST /api/tasks/{id}/hard-delete → TaskStore.delete()  ← called after 4s undo window
  GET  /api/tasks/summary   → TaskStore.get_summary()   ← due_today + overdue counts
  POST /api/task-lists      → TaskListStore.create()
  GET  /api/task-lists      → TaskListStore.list()
  PATCH /api/task-lists/{id}
  DELETE /api/task-lists/{id}
       │
       ▼
memory/firestore_db.py
  TaskStore       → Firestore collection: "tasks"
  TaskListStore   → Firestore collection: "task_lists"
       │
       ├──────────────────────────────────────────────────┐
       ▼                                                  ▼
core/tools.py                                  core/autonomous.py
  Native task tool schemas                       _gather_native_overdue()  [renamed]
  _HANDLERS: task_create, task_list,             → TaskStore.get_overdue()
             task_complete, task_reschedule,     situation key: "ticktick_overdue"
             task_edit, task_delete              (key name unchanged → zero prompt changes)
       │
       ▼
Klaus Brain (gemini-3.5-flash) ← sees tasks via tool results
```

```
Browser (React SPA)
  /tasks route → TasksPage.tsx
    TaskListSidebar (desktop) ←→ useTaskLists()
    TaskListView ←→ useTasks(listId)
      TaskRow × N → tap checkbox → completion flow
        1. Optimistic: remove row (opacity-0 collapse)
        2. Start UndoToast countdown (4s)
        3. POST /api/tasks/{id}/complete (immediate)
        4. If undo: restore row, cancel hard-delete
        5. After 4s: POST /api/tasks/{id}/hard-delete
      TaskDetailSheet (edit/create modal)
        RecurrenceSelector → cadence + anchor
    QuickAddBar ← chrono-node parser runs on every keystroke
    TaskFAB (phone) | N key (desktop) → open QuickAddBar

  GlanceRail.tsx (extended) ← useTaskSummary()
  TimelineDay.tsx (extended) → DueTasksBand ← useTaskSummary()
```

### Recommended Project Structure
```
memory/
├── firestore_db.py          # Add TaskStore + TaskListStore classes here
mcp_tools/
├── ticktick_tool.py         # (removed in Wave 4 per D-09 migration order)
core/
├── tools.py                 # Replace add_task schema + handler; add 6 new task schemas
├── autonomous.py            # Rename _gather_ticktick_overdue → _gather_native_overdue; repoint
interfaces/
├── web_server.py            # Add /api/tasks/* + /api/task-lists/* routes
frontend/src/
├── api/
│   ├── tasks.ts             # apiFetch wrappers for all task endpoints
│   └── task-lists.ts        # apiFetch wrappers for list CRUD
├── hooks/
│   ├── useTasks.ts          # useQuery + useMutation for task list per list_id
│   ├── useTaskSummary.ts    # useQuery for /api/tasks/summary (due_today+overdue count)
│   └── useTaskLists.ts      # useQuery + useMutation for list CRUD
├── components/tasks/
│   ├── TasksPage.tsx
│   ├── TaskListView.tsx
│   ├── TaskRow.tsx
│   ├── TaskDetailSheet.tsx
│   ├── TaskListSidebar.tsx
│   ├── TaskListSelector.tsx
│   ├── RecurrenceSelector.tsx
│   ├── SortGroupControl.tsx
│   ├── QuickAddBar.tsx       # uses parseTaskInput() from utils/parseTaskInput.ts
│   ├── TaskFAB.tsx
│   └── UndoToast.tsx
├── components/timeline/
│   └── DueTasksBand.tsx      # new; inserted into TimelineDay.tsx
├── components/layout/
│   └── GlanceRail.tsx        # extended (Tasks section added below Nutrition)
└── utils/
    └── parseTaskInput.ts     # Wraps chrono-node + token regex; pure function, easy to test
tests/
└── test_task_store.py        # Python: TaskStore + TaskListStore unit tests (Firestore mock)
frontend/src/utils/
└── parseTaskInput.test.ts    # Vitest: NL-date + token parsing unit tests
```

### Pattern 1: TaskStore — mirrors existing store classes

Model directly on `memory/firestore_db.py` `StrengthSessionStore` (lines 1087–1223) and `FollowupStore` (lines 1517–1614). Key conventions to follow:

- `__init__` takes `project_id: str, database: str = "(default)"` and stores `self._client` + `self._col`.
- Reads never raise — return `[]` / `None` / `{}` on any error with `logger.warning(..., exc_info=True)`.
- Writes re-raise after `logger.error(..., exc_info=True)`.
- Every write stamps `"updated_at": firestore.SERVER_TIMESTAMP`.
- Use `merge=True` on `set()` for idempotent upserts.
- `_jsonsafe_doc()` on every dict returned from a read (strips `DatetimeWithNanoseconds` before `json.dumps`).
- Server-side filters via `_where(query, field, op, value)` — never stream the full collection and filter in Python.

```python
# Source: memory/firestore_db.py — StrengthSessionStore pattern (lines 1087–1223)
# and FollowupStore.list_due composite-index pattern (lines 1588–1614)

class TaskStore:
    _COLLECTION = "tasks"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def create(self, task: dict) -> dict:
        """Create a task. Returns the stored dict with id. Re-raises on failure."""
        import uuid
        task_id = task.get("id") or uuid.uuid4().hex
        payload = {**task, "id": task_id, "updated_at": firestore.SERVER_TIMESTAMP}
        self._col.document(task_id).set(payload)
        return {**task, "id": task_id}

    def list(self, list_id: str | None = None, ...) -> list[dict]:
        """List tasks by list. Never raises."""
        ...  # _where filter + _jsonsafe_doc on results

    def get_overdue(self, today_iso: str) -> list[dict]:
        """Return incomplete tasks with due_date < today_iso. Never raises."""
        ...  # server-side filter: status==active, due_date < today_iso

    def get_summary(self, today_iso: str) -> dict:
        """Return {due_today: int, overdue: int}. Never raises."""
        ...
```

[VERIFIED: memory/firestore_db.py lines 1087–1223 (StrengthSessionStore); lines 1517–1614 (FollowupStore)]

### Pattern 2: _HANDLERS dispatch — mirrors existing tool registration

The `add_task` schema lives at `core/tools.py` lines 212–247 and its handler at lines 1357–1364. The `_HANDLERS` dispatch entry is at line 2258.

```python
# Source: core/tools.py lines 212–247 (add_task schema), line 2258 (dispatch)
# New task tools replace add_task with 6 entries:

TOOL_SCHEMAS += [
    {
        "name": "task_create",
        "description": "Create a task in Klaus's native task store. ...",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "notes": {"type": "string"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD"},
                "due_time": {"type": "string", "description": "HH:MM (optional)"},
                "priority": {"type": "string", "enum": ["none", "low", "medium", "high"]},
                "list_id": {"type": "string", "description": "list ID; omit for Inbox"},
            },
            "required": ["title"],
        },
    },
    # task_list, task_complete, task_reschedule, task_edit, task_delete ...
]

# Remove "add_task" from _HANDLERS (and its schema from TOOL_SCHEMAS) per D-09.
# Add:
_HANDLERS["task_create"] = lambda args: _handle_task_create(**args)
_HANDLERS["task_list"]   = lambda args: _handle_task_list(**args)
# etc.
```

[VERIFIED: core/tools.py lines 212–247, 1357–1364, 2258]

### Pattern 3: React Query optimistic mutation — mirrors useChat.ts

```typescript
// Source: frontend/src/hooks/useChat.ts lines 61–99 (useMutation with onMutate/onError/onSettled)
// Mirror for task creation:

export function useCreateTask() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (task: CreateTaskInput) => createTask(task),

    onMutate: async (task) => {
      await queryClient.cancelQueries({ queryKey: TASKS_QUERY_KEY })
      const previous = queryClient.getQueryData<Task[]>(TASKS_QUERY_KEY)
      // Optimistic: append with status:'saving'
      queryClient.setQueryData<Task[]>(TASKS_QUERY_KEY, (old) => [
        ...(old ?? []),
        { ...task, id: `optimistic-${Date.now()}`, status: 'saving' },
      ])
      return { previous }
    },

    onError: (_err, _task, context) => {
      // Roll back
      if (context?.previous !== undefined) {
        queryClient.setQueryData(TASKS_QUERY_KEY, context.previous)
      }
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: TASKS_QUERY_KEY })
    },
  })
}
```

[VERIFIED: frontend/src/hooks/useChat.ts lines 61–99]

### Pattern 4: useTaskSummary — mirrors useToday.ts (deduped fetch)

```typescript
// Source: frontend/src/hooks/useToday.ts (refetchOnWindowFocus, no timer polling)
// GlanceRail.tsx line 35-36: const { data } = useToday() — read from shared cache

export const TASK_SUMMARY_QUERY_KEY = ['tasks', 'summary'] as const

export function useTaskSummary() {
  return useQuery<TaskSummary, Error>({
    queryKey: TASK_SUMMARY_QUERY_KEY,
    queryFn: fetchTaskSummary,   // GET /api/tasks/summary
    refetchOnMount: true,
    refetchOnWindowFocus: true,
    // No refetchInterval — same discipline as useToday (D-05 philosophy)
  })
}
```

[VERIFIED: frontend/src/hooks/useToday.ts; frontend/src/components/layout/GlanceRail.tsx line 35]

### Pattern 5: /api/* route — mirrors api_today

```python
# Source: interfaces/web_server.py lines 1415–1478 (api_today pattern)
# New route mirrors: @app.get, Depends(require_hub_session), asyncio.gather for
# concurrent Firestore reads, _jsonsafe_doc on all output.

@app.get("/api/tasks/summary")
async def api_tasks_summary(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    from memory.firestore_db import TaskStore, _jsonsafe_doc
    from zoneinfo import ZoneInfo
    loop = asyncio.get_running_loop()
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    store = TaskStore(project_id=..., database=...)
    summary = await loop.run_in_executor(None, store.get_summary, today_iso)
    return JSONResponse(content=_jsonsafe_doc(summary))
```

[VERIFIED: interfaces/web_server.py lines 1415–1478; interfaces/web_server.py line 1436 (_jsonsafe_doc import pattern)]

### Anti-Patterns to Avoid
- **Missing _jsonsafe_doc on Firestore reads:** `due_date` stored as a Python `datetime` or `DatetimeWithNanoseconds` breaks `json.dumps`. Store due dates as plain ISO strings (`"2026-06-20"`) to eliminate this risk entirely.
- **Streaming full collection then filtering in Python:** Use `_where()` + Firestore server-side filters. Existing code at `memory/firestore_db.py` line 22 documents exactly this pitfall.
- **Recurrence math client-side only:** The autonomous gather (Layer-0) reads from TaskStore directly — if next-instance generation is only in the frontend, the agent is blind to the generated task until a user refreshes.
- **Using `_ticktick_add_task` in the handler:** Investigation found that `_ticktick_add_task` is referenced in `_handle_add_task` (tools.py line 1361) but is never imported or assigned anywhere in the file — this handler is likely dead/broken code. The native tool handler must not replicate this pattern; it should import directly from `memory.firestore_db`.
- **Undo timer in a BackgroundTask:** Starlette BackgroundTasks run after the HTTP response, and Cloud Run throttles CPU once no request is in flight. The hard-delete call must arrive as a new tracked request from the client.
- **Putting `completed_at` in the task doc then soft-filtering:** D-13 explicitly says completed tasks are not retained. Write clean: hard-delete from Firestore, no archive field.

---

## Open Unknown Resolutions

### Unknown 1: NL-date parser library for quick-add (D-10)

**Recommendation: chrono-node 2.9.1** [ASSUMED per package provenance rule]

**Rationale:**
- Handles "tomorrow", "friday", "next week", "next month" out of the box via `chrono.casual.parseDate()`.
- Reference date + timezone passed as `{ instant: new Date(), timezone: "Asia/Jerusalem" }` — resolves to the correct Asia/Jerusalem local date for "tomorrow" and "friday" regardless of browser locale.
- Ships dual CJS + ESM (`"sideEffects":false` in both package.json manifests) — Vite tree-shakes it cleanly.
- No postinstall network call (the `prepare` script runs `npm run build` which is a dev-time TypeScript compile; it does not execute at consumer install time).
- ~1M weekly downloads, 14-year history, MIT, single maintainer (wanasit), actively maintained (2.9.1 released May 2026).
- Unpacked size 3.5 MB (source maps + type declarations account for most of it); the ESM bundle Vite actually ships is substantially smaller.
- No transitive production dependencies.

**Alternative rejected:** Building a hand-rolled regex parser for "tomorrow"/"friday"/"next week" risks missing edge cases (DST transitions, "next friday" when today IS friday, "in 3 days"). chrono-node handles all of these correctly.

**Concrete parse approach:**

```typescript
// Source: chrono-node README (wanasit/chrono) — parseDate API with reference config
// frontend/src/utils/parseTaskInput.ts

import * as chrono from 'chrono-node'

interface ParsedTask {
  title: string
  due_date: string | null     // "YYYY-MM-DD" in Asia/Jerusalem local
  list_name: string | null    // matched from #token
  priority: 'none' | 'low' | 'medium' | 'high' | null
}

const PRIORITY_MAP: Record<string, ParsedTask['priority']> = {
  '!high': 'high', '!1': 'high',
  '!medium': 'medium', '!2': 'medium',
  '!low': 'low', '!3': 'low',
}

export function parseTaskInput(raw: string, refDate: Date = new Date()): ParsedTask {
  // 1. Extract #list and !priority tokens BEFORE NL parsing to avoid confusion
  let title = raw
  let list_name: string | null = null
  let priority: ParsedTask['priority'] = null

  // #list token (first match wins)
  const listMatch = title.match(/#(\S+)/)
  if (listMatch) {
    list_name = listMatch[1]
    title = title.replace(listMatch[0], '').trim()
  }

  // !priority token
  for (const [token, prio] of Object.entries(PRIORITY_MAP)) {
    if (title.toLowerCase().includes(token)) {
      priority = prio
      title = title.replace(new RegExp(token, 'i'), '').trim()
      break
    }
  }

  // 2. Parse NL date from remaining text; resolve in Asia/Jerusalem
  const parsed = chrono.parseDate(title, {
    instant: refDate,
    timezone: 'Asia/Jerusalem',
  })

  let due_date: string | null = null
  if (parsed) {
    // Format as YYYY-MM-DD in Asia/Jerusalem (not UTC)
    const [datePart] = parsed.toLocaleDateString('en-CA', {
      timeZone: 'Asia/Jerusalem',
    }).split('T')
    due_date = datePart

    // Remove date phrase from title for clean display
    const results = chrono.parse(title, { instant: refDate, timezone: 'Asia/Jerusalem' })
    if (results.length > 0) {
      title = title.replace(results[0].text, '').trim()
    }
  }

  return { title: title || raw, due_date, list_name, priority }
}
```

**Token parsing note:** Strip `#list` and `!priority` tokens before passing to chrono-node, not after. Otherwise chrono-node may try to parse them as dates.

### Unknown 2: Recurrence engine (D-05/D-06/D-07)

**Recommendation: Server-side computation in `TaskStore.complete()`** [ASSUMED]

**Data model for recurrence rule (stored as a dict/map field in the task doc):**

```json
{
  "cadence": "weekly",
  "every_n_days": null,
  "anchor": "schedule"
}
```

- `cadence`: `"daily"` | `"weekdays"` | `"weekly"` | `"monthly"` | `"every_n_days"`
- `every_n_days`: integer (only used when cadence = "every_n_days")
- `anchor`: `"schedule"` (stick-to-schedule) | `"completion"` (from-completion)

**Next-instance computation:**

```python
# Pure helper in memory/firestore_db.py (alongside TaskStore)
from datetime import date, timedelta
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Jerusalem")


def _advance_once(base: date, rule: dict) -> date:
    """Advance `base` by exactly one cadence step (no roll-forward)."""
    cadence = rule.get("cadence", "daily")

    if cadence == "daily":
        return base + timedelta(days=1)
    elif cadence == "weekdays":
        candidate = base + timedelta(days=1)
        while candidate.weekday() >= 5:  # 5=Sat, 6=Sun
            candidate += timedelta(days=1)
        return candidate
    elif cadence == "weekly":
        return base + timedelta(weeks=1)
    elif cadence == "monthly":
        # Month-end clamping: the 31st in a 30-day month clamps to the last day
        import calendar
        year = base.year + (base.month // 12)
        month = (base.month % 12) + 1
        max_day = calendar.monthrange(year, month)[1]
        return base.replace(year=year, month=month, day=min(base.day, max_day))
    elif cadence == "every_n_days":
        n = int(rule.get("every_n_days") or 1)
        return base + timedelta(days=n)
    else:
        return base + timedelta(days=1)


def _next_due_date(
    current_due: date,
    completed_on: date,
    rule: dict,
) -> date:
    """Compute the next due date for a recurring task.

    Args:
        current_due:   The task's current due_date (YYYY-MM-DD as date object).
        completed_on:  Today in Asia/Jerusalem when complete() was called.
        rule:          The recurrence rule dict.

    Returns:
        The next due date as a date object (always strictly > completed_on).
    """
    anchor = rule.get("anchor", "schedule")
    base = current_due if anchor == "schedule" else completed_on

    candidate = _advance_once(base, rule)

    # D-06: a schedule-anchored next that lands on/before today rolls forward
    # to the next FUTURE occurrence. This must be a real loop — a task several
    # cadences in the past (e.g. weekly current_due far behind completed_on)
    # needs multiple steps to clear `completed_on`, not a single advance.
    if anchor == "schedule":
        while candidate <= completed_on:
            candidate = _advance_once(candidate, rule)

    return candidate
```

**Why server-side:**
- Klaus's `task_complete` tool must trigger next-instance generation — the agent cannot rely on the browser being open.
- The autonomous gather calls `TaskStore.get_overdue()` which must see the current open instance to correctly report overdue tasks.
- Firestore is the single source of truth; client-side-only generation would create inconsistency after every Klaus-initiated completion.

**D-07 "This occurrence only" vs "This and following":**
- Given the single-open-instance model (D-06), "this occurrence only" = create a one-off task (no recurrence rule), mark the current instance done without generating a next, leave the series untouched.
- "This and following" = update the recurrence rule on the current task document in place.
- No separate exceptions store is needed.

**Month-end clamping:** The `min(base.day, max_day)` pattern in the code above. E.g., Jan 31 → next is Feb 28 (or 29 in a leap year).

**Weekdays wrapping:** Saturday (weekday=5) → Monday; Sunday (weekday=6) → Monday.

**"From completion" semantics:** If trash day is Thursday and anchor="completion", completing on Thursday → next Thursday; the original schedule date is irrelevant. The base shifts to `completed_on`.

### Unknown 3: Completion/delete with undo (D-13/D-14/D-15)

**Recommendation: 4-second client-side countdown, soft-mark in optimistic state, hard-delete via a tracked HTTP request from the client** [ASSUMED]

**The problem with alternatives:**
- Cloud Tasks delayed delete: adds a queue round-trip, message delivery is not guaranteed within exactly 4s, and cancellation (undo) requires a task-cancel API call — significant complexity.
- Server-side soft-mark + TTL field: requires a Firestore TTL policy or a separate cleanup cron; TaskStore.list() must filter out soft-deleted docs; they accumulate until the TTL fires.
- BackgroundTask (Starlette): CLAUDE.md §6 invariant explicitly forbids this — Cloud Run throttles CPU after the response.

**Recommended mechanic:**

```
1. User taps checkbox / delete:
   a. Immediately remove task row from UI (optimistic removal — setQueryData filter out task).
   b. Start a 4-second countdown in zustand undo-toast store.
   c. POST /api/tasks/{id}/complete (or /delete) — marks status='completing' in Firestore
      and (for complete) generates the next recurring instance.
      (This is the "soft-mark": the task is still in Firestore but status excludes it
       from TaskStore.list() and get_overdue() queries.)
   d. Display UndoToast with countdown.

2a. If undo tapped (< 4s):
   a. Cancel the countdown timer.
   b. POST /api/tasks/{id}/undo — reverts status='active';
      for recurring completion, also deletes the generated next instance.
   c. Re-insert task into query cache (or invalidate to refetch).

2b. If 4s elapses without undo:
   a. Browser fires POST /api/tasks/{id}/hard-delete.
   b. Server calls TaskStore.delete(task_id).
   c. Dismisses toast.
```

**Page reload during undo window:** If the user reloads mid-window, the task (with status='completing') will not appear in the list (filtered by status) — it effectively disappears. The undo window is lost. This is acceptable per D-13 ("undo toast is the only recovery") and is standard behavior in apps like Gmail's undo-send. The 4-second window is short enough that a reload is unlikely.

**Toast stacking (per UI-SPEC §Interaction Contracts):** If a second completion fires before the first toast expires, extend the countdown for the new item. The hard-delete POST for the FIRST item fires immediately (abandon its countdown), the new item gets a fresh 4s window. Only one toast at a time.

**Status field approach (simplest):**
```python
# TaskStore document fields (active task)
{
  "id": "...",
  "status": "active",     # "active" | "completing" | "deleted"
  ...
}
# TaskStore.list() always filters: status == "active"
# TaskStore.get_overdue() always filters: status == "active"
# TaskStore.complete() sets status = "completing" + creates next instance (for recurrers)
# TaskStore.undo_complete() sets status = "active" + deletes next instance (for recurrers)
# TaskStore.delete() (hard) calls Firestore .delete() on the document
```

**For recurring tasks (D-15):**
- `POST /api/tasks/{id}/complete` sets current task `status="completing"`, then creates the next instance as a new Firestore doc with `status="active"`.
- `POST /api/tasks/{id}/undo`: sets current task back to `status="active"`, deletes the generated next-instance doc.
- Hard-delete: same as a non-recurring task — just remove the current doc.

### Unknown 4: TaskStore Firestore document/collection shape

**Recommended collection layout:**

```
Firestore (database: "klaus-firestore")
├── tasks/{task_id}
│   ├── id: str               (uuid4 hex — doc ID)
│   ├── title: str
│   ├── notes: str | null     (plain text)
│   ├── due_date: str | null  ("YYYY-MM-DD" in Asia/Jerusalem local — plain string, not Timestamp)
│   ├── due_time: str | null  ("HH:MM" in Asia/Jerusalem local — plain string)
│   ├── priority: str         ("none" | "low" | "medium" | "high")
│   ├── list_id: str          (task_list doc ID, or "inbox" for the default Inbox)
│   ├── status: str           ("active" | "completing")  — "deleted" docs are .delete()d
│   ├── recurrence: dict | null
│   │   ├── cadence: str      ("daily" | "weekdays" | "weekly" | "monthly" | "every_n_days")
│   │   ├── every_n_days: int | null
│   │   └── anchor: str       ("schedule" | "completion")
│   ├── series_id: str | null (uuid4 hex shared by all instances of a recurring series)
│   ├── created_at: str       (ISO-8601 UTC — plain string, not Timestamp)
│   └── updated_at: SERVER_TIMESTAMP  (stripped by _jsonsafe_doc before json.dumps)
│
└── task_lists/{list_id}
    ├── id: str               (uuid4 hex — doc ID)
    ├── name: str
    ├── created_at: str       (ISO-8601 UTC)
    └── updated_at: SERVER_TIMESTAMP
```

**Why plain string for due_date (not Firestore Timestamp):**
- `DatetimeWithNanoseconds` requires `_jsonsafe_doc()` to serialize. A plain `"YYYY-MM-DD"` string eliminates this risk entirely and makes date comparison trivial (ISO string comparison is lexicographically correct for dates).
- The codebase already uses ISO string dates in `JournalStore` (doc_id = "YYYY-MM-DD"), `TrainingLogStore` (date field), and `StrengthSessionStore` (date field). This is the established pattern.

**Why `list_id = "inbox"` for unfiled tasks:**
- Avoids `null` in queries — `_where(col, "list_id", "==", "inbox")` works without special handling.
- The TaskListStore has no "inbox" document (Inbox is implicit); the app treats `list_id = "inbox"` as a UI constant.

**Why `series_id` field:**
- Required for the "This and following" edit (D-07): to find all future instances of a series, query `series_id == X` (though with single-open-instance model there will be at most one).
- Also provides an audit trail if a series history is ever needed.

**Firestore indexes needed:**

| Collection | Fields indexed | Query |
|-----------|---------------|-------|
| tasks | `status ASC`, `due_date ASC` | Get overdue: status==active, due_date < today |
| tasks | `status ASC`, `due_date ASC`, `list_id ASC` | List by list, filter active, sort by due |
| tasks | `status ASC`, `priority ASC` | Sort by priority within a list |
| tasks | `series_id ASC`, `created_at ASC` | "This and following" lookup |
| task_lists | none (single-collection scan is fine — few docs) | List all lists |

Firestore automatically creates single-field indexes. Composite indexes for the multi-field queries above must be created manually in the GCP Console or via `firebase.json` index definitions. The `(status, due_date)` composite index is the most critical — it powers the autonomous overdue gather and the glance rail summary. It mirrors the `(status, due_at)` pattern already documented for `FollowupStore.list_due` in `memory/firestore_db.py` line 1594.

**Authz note (ASVS V4):** The `/api/tasks/*` routes are behind `require_hub_session` which verifies that the request comes from Amit's session. Since Klaus is a single-user system (one allowed Google account), the session check is sufficient. No per-task owner_id field is needed — all tasks belong to Amit.

### Unknown 5: Klaus tool swap and autonomous gather wiring (D-16/D-17)

**Exact existing wiring to replace:**

| Item | File | Location | What Changes |
|------|------|----------|--------------|
| `add_task` schema | `core/tools.py` | lines 212–247 | Remove; add 6 native task schemas |
| `_handle_add_task` | `core/tools.py` | lines 1357–1364 | Remove; add 6 `_handle_task_*` functions |
| `_HANDLERS["add_task"]` | `core/tools.py` | line 2258 | Remove; add 6 entries |
| `_ticktick_add_task` reference | `core/tools.py` | line 1361 | Remove (see dead-code finding below) |
| `_gather_ticktick_overdue` | `core/autonomous.py` | lines 236–244 | Rename to `_gather_native_overdue`; replace ticktick_tool call with TaskStore.get_overdue() |
| `"ticktick_overdue"` key in `jobs` dict | `core/autonomous.py` | line 433 | Keep key name unchanged (see note below) |
| `ticktick_overdue` references in triage/compose | `core/autonomous.py` | lines 180, 463, 487–493, 516, 598, 684, 729 | Zero changes — key name preserved |

**Dead-code finding:** `_ticktick_add_task` is referenced in `_handle_add_task` (line 1361) but is never imported, assigned, or defined anywhere in `core/tools.py`. This handler would raise `NameError` at runtime if called. Investigation found no top-level import or assignment. The native tool handler must import `TaskStore` directly and not attempt to reuse this broken reference.

**Why keep "ticktick_overdue" key name unchanged:**
- The key appears in 8+ locations in `core/autonomous.py` (lines 180, 463, 487, 493, 516, 598, 684, 729) plus in `evals/tick_brain/` fixtures and `tests/test_autonomous.py`.
- Renaming the key would require touching 5+ files and updating eval fixtures.
- D-17 explicitly calls this a "pure data-source swap" — the situation key is part of the prompt contract, not the data source.
- Rename only the function: `_gather_ticktick_overdue` → `_gather_native_overdue`.

**New native task tool set for Klaus:**

```python
# 6 new schemas in TOOL_SCHEMAS (replace the single add_task schema):
# task_create, task_list, task_complete, task_reschedule, task_edit, task_delete

# Corresponding _HANDLERS entries:
"task_create":    lambda args: _handle_task_create(**args),
"task_list":      lambda args: _handle_task_list(**args),
"task_complete":  lambda args: _handle_task_complete(**args),
"task_reschedule": lambda args: _handle_task_reschedule(**args),
"task_edit":      lambda args: _handle_task_edit(**args),
"task_delete":    lambda args: _handle_task_delete(**args),

# All 6 are worker-delegatable (not brain-direct) since they're CRUD operations.
# Do NOT add to SMART_AGENT_DIRECT_TOOLS unless there's a specific reason.
```

**Autonomous gather repoint:**
```python
# core/autonomous.py — line 236 today:
def _gather_ticktick_overdue() -> list:
    """(b) TickTick overdue (BLOCKER 1)."""
    try:
        from mcp_tools import ticktick_tool
        tasks = ticktick_tool.get_today_tasks() or {}
        return tasks.get("overdue", []) or []
    except Exception:
        ...

# After swap (rename function, repoint source, keep same return shape):
def _gather_native_overdue() -> list:
    """(b) Native task overdue — reads TaskStore instead of TickTick. Same return shape."""
    try:
        from memory.firestore_db import TaskStore
        import os
        from datetime import datetime
        from zoneinfo import ZoneInfo
        today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        store = TaskStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        tasks = store.get_overdue(today_iso)
        # Return same shape as TickTick: [{"title": str, "due": str}, ...]
        return [{"title": t["title"], "due": t.get("due_date", "")} for t in tasks]
    except Exception:
        logger.warning("autonomous: native task gather failed", exc_info=True)
        return []

# In jobs dict (line 433 area) — rename the function reference only:
jobs = {
    ...
    "ticktick_overdue": _gather_native_overdue,   # key name unchanged
    ...
}
```

[VERIFIED: core/autonomous.py lines 236–244, 433, 180, 463, 487–493, 516, 598, 684, 729]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NL date parsing ("tomorrow", "friday", "next week") | Custom regex date parser | chrono-node 2.9.1 | Edge cases: "next friday" when today is friday, DST transitions, locale — all handled |
| Month-end clamping | Ad-hoc month arithmetic | Python's `calendar.monthrange()` (stdlib) | `monthrange(year, month)[1]` returns the last valid day cleanly |
| Firestore timestamp → JSON serialization | Custom stringify | `_jsonsafe_doc()` / `_jsonsafe_value()` already in `memory/firestore_db.py` (lines 885–913) | Established project pattern; already handles nested dicts/lists |
| Server-side Firestore date filters | Python list filtering | `_where()` helper in `memory/firestore_db.py` (lines 22–38) | Same performance pitfall documented in the helper's docstring |
| Optimistic UI update pattern | Custom fetch + state management | TanStack Query `useMutation` with `onMutate/onError/onSettled` | Phase 26 `useChat.ts` pattern is already in the codebase; exact code to mirror |
| Completion animation | Custom CSS keyframes from scratch | Tailwind `transition` + `max-height: 0` collapse + SVG `stroke-dashoffset` | UI-SPEC §Interaction Contracts specifies the exact animation (150ms fill + 150ms checkmark + 200ms collapse) |

**Key insight:** The recurrence engine tempts hand-rolling because the requirements seem simple — don't. Month-end clamping (31st in a 30-day month), weekday wrapping across weekends, and DST-safe date arithmetic are all handled correctly by Python's stdlib `calendar` and `timedelta`. The logic is small enough to write and test directly without a library.

---

## Common Pitfalls

### Pitfall 1: `due_date` stored as Firestore Timestamp

**What goes wrong:** If `due_date` is stored as a Python `datetime` or via `firestore.SERVER_TIMESTAMP`, it reads back as `DatetimeWithNanoseconds`. `json.dumps(doc)` raises `TypeError`. `/api/tasks/` returns a 500.

**Why it happens:** Developers copy the `updated_at: firestore.SERVER_TIMESTAMP` pattern to all fields.

**How to avoid:** Store `due_date` as a plain ISO string `"YYYY-MM-DD"` (never a Timestamp). Only `updated_at` and `created_at` (write-metadata) use `SERVER_TIMESTAMP`. Even `created_at` is safer as `datetime.now(timezone.utc).isoformat()` (plain string).

**Warning signs:** `/api/tasks/` returns 500; `TypeError: Object of type DatetimeWithNanoseconds is not JSON serializable` in Cloud Run logs.

[VERIFIED: memory/firestore_db.py lines 885–913 (_jsonsafe_doc); STATE.md §Notes (Firestore SERVER_TIMESTAMP note)]

### Pitfall 2: Recurrence generates a past-due "next" (D-06 violation)

**What goes wrong:** A weekly task due last Monday, completed today (Wednesday), generates next Monday (6 days ago) — still in the past.

**Why it happens:** `_next_due_date` adds 7 days from `current_due` without checking if the result is in the future.

**How to avoid:** After computing `candidate`, roll forward with a real loop — `while candidate <= completed_on: candidate = _advance_once(candidate, rule)` — NOT a single `break`-guarded step. A task several cadences in the past (e.g. weekly `current_due` weeks behind `completed_on`) needs multiple advances to clear today; one step is not enough. The implementation in Unknown 2 above uses the loop form.

**Warning signs:** Glance rail shows perpetual overdue tasks; autonomous tick fires every 20 minutes about the same task.

### Pitfall 3: Autonomous gather returns wrong shape and breaks triage scoring

**What goes wrong:** The triage prompt (`prompts/autonomous_triage.md`) expects `ticktick_overdue` to be a list of `{"title": str, "due": str}` dicts. If `_gather_native_overdue()` returns raw TaskStore docs (which have different field names), the triage prompt gets confused.

**Why it happens:** Returning raw TaskStore docs instead of normalizing to the TickTick-compatible shape.

**How to avoid:** In `_gather_native_overdue()`, explicitly map to `{"title": t["title"], "due": t.get("due_date", "")}` before returning (as shown in Unknown 5 above).

**Warning signs:** Test `test_autonomous.py` failures; triage prompt hallucinating overdue task titles.

[VERIFIED: core/autonomous.py lines 486–490 (overdue extraction); tests/test_autonomous.py]

### Pitfall 4: `POST /api/tasks/{id}/hard-delete` called from a Starlette BackgroundTask

**What goes wrong:** The hard-delete fires after the HTTP response; Cloud Run throttles CPU; the Firestore write may be delayed or aborted, leaving `status="completing"` tasks permanently in the datastore.

**Why it happens:** Using Starlette `BackgroundTask` for the timer callback.

**How to avoid:** The 4-second countdown lives entirely in the browser. After 4 seconds, the browser makes a new HTTP request to `POST /api/tasks/{id}/hard-delete`. This is a regular tracked request — Cloud Run keeps CPU active during it.

[VERIFIED: CLAUDE.md §6 Invariants — "Agent turns must run INSIDE a tracked request... never in a Starlette BackgroundTask"]

### Pitfall 5: `_ticktick_add_task` NameError on first task tool call

**What goes wrong:** If any code path still routes through `_handle_add_task` after the Phase 27 swap, it will raise `NameError: name '_ticktick_add_task' is not defined` at runtime.

**Why it happens:** The existing handler has a reference to `_ticktick_add_task` that was apparently never imported (dead code). During the swap, if the handler is only partially updated, the old reference persists.

**How to avoid:** Remove the `add_task` entry from both `TOOL_SCHEMAS` and `_HANDLERS` completely; delete `_handle_add_task`. Do not leave any path back to the old handler.

**Warning signs:** Klaus responds with an internal error on any task creation attempt; Cloud Run logs show `NameError`.

### Pitfall 6: chrono-node "next week" resolves to UTC date instead of Asia/Jerusalem

**What goes wrong:** "next week" parsed without a timezone resolves in UTC, which is 2–3 hours behind Asia/Jerusalem. Near midnight, "tomorrow" in UTC is "today" in Jerusalem.

**Why it happens:** Not passing `timezone: "Asia/Jerusalem"` to chrono-node's reference config.

**How to avoid:** Always pass `{ instant: new Date(), timezone: "Asia/Jerusalem" }` as the second argument to `chrono.parseDate()`. See the `parseTaskInput.ts` example in Unknown 1.

**Warning signs:** Tasks created near midnight appear with yesterday's date; "tomorrow" creates a task for today.

### Pitfall 7: Task list queries missing composite Firestore index cause 400 errors

**What goes wrong:** Querying `WHERE status == "active" AND due_date < "2026-06-17" ORDER BY due_date` requires a composite index. Without it, Firestore returns a 400 with a URL to create the index.

**Why it happens:** Composite indexes are not auto-created; they must be defined before the query runs.

**How to avoid:** Create composite indexes in Wave 0 or as a deployment task. Required indexes documented in Unknown 4 above. The `FollowupStore.list_due` docstring (line 1594) documents this same pitfall for the `(status, due_at)` index.

[VERIFIED: memory/firestore_db.py line 1594 (FollowupStore.list_due NOTE about composite index)]

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (backend) | pytest (Python, run per-file due to grpc/protobuf segfault on full suite) |
| Framework (frontend) | Vitest 3.2.4 (`npm test` in `frontend/`) |
| Backend config | `tests/` directory; Firestore mocked via `_install_firestore_mock()` pattern |
| Frontend config | `frontend/vitest.config.*` (inferred from package.json `"test": "vitest"`) |
| Backend quick run | `pytest tests/test_task_store.py -x` |
| Frontend quick run | `cd frontend && npm test -- --run src/utils/parseTaskInput.test.ts` |
| Full suite | `pytest tests/test_task_store.py tests/test_tools.py tests/test_autonomous.py -x` + `cd frontend && npm test` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File |
|--------|----------|-----------|-------------------|------|
| TASK-01 | TaskStore.create/update/delete | unit (Python) | `pytest tests/test_task_store.py::TestTaskStoreCRUD -x` | Wave 0 gap |
| TASK-01 | TaskListStore.create/list/delete | unit (Python) | `pytest tests/test_task_store.py::TestTaskListStore -x` | Wave 0 gap |
| TASK-01 | /api/tasks CRUD returns 200 + correct shape | integration (Python) | `pytest tests/test_web_server.py::TestTaskRoutes -x` | Wave 0 gap |
| TASK-02 | _next_due_date: daily/weekdays/weekly/monthly/every-N-days | unit (Python) | `pytest tests/test_task_store.py::TestNextDueDate -x` | Wave 0 gap |
| TASK-02 | Month-end clamping (Jan 31 → Feb 28) | unit (Python) | `pytest tests/test_task_store.py::TestMonthEndClamping -x` | Wave 0 gap |
| TASK-02 | Weekday wrapping (Fri → Mon, Sat → Mon) | unit (Python) | `pytest tests/test_task_store.py::TestWeekdayWrapping -x` | Wave 0 gap |
| TASK-02 | Past-due roll-forward (D-06) | unit (Python) | `pytest tests/test_task_store.py::TestPastDueRollForward -x` | Wave 0 gap |
| TASK-02 | Recurring complete generates next + clears current (D-15) | unit (Python) | `pytest tests/test_task_store.py::TestRecurringComplete -x` | Wave 0 gap |
| TASK-03 | parseTaskInput("Buy milk tomorrow") → {due_date: "YYYY-MM-DD"} | unit (TS) | `cd frontend && npm test -- --run src/utils/parseTaskInput.test.ts` | Wave 0 gap |
| TASK-03 | parseTaskInput("meeting #work !high friday") → correct tokens | unit (TS) | same file | Wave 0 gap |
| TASK-03 | Near-midnight timezone: "tomorrow" in Asia/Jerusalem | unit (TS) | same file (refDate stub) | Wave 0 gap |
| TASK-04 | TaskStore.complete() sets status='completing' | unit (Python) | `pytest tests/test_task_store.py::TestSoftComplete -x` | Wave 0 gap |
| TASK-04 | Undo reverts status; recurring undo deletes generated next | unit (Python) | `pytest tests/test_task_store.py::TestUndoComplete -x` | Wave 0 gap |
| TASK-04 | Completion micro-animation present in TaskRow | manual (visual) | n/a (animation timing) | manual-only |
| TASK-05 | Native task tool schemas present in TOOL_SCHEMAS | unit (Python) | `pytest tests/test_tools.py::TestNativeTaskTools -x` | Wave 0 gap |
| TASK-05 | _gather_native_overdue() returns [{title, due}, ...] | unit (Python) | `pytest tests/test_autonomous.py::TestNativeOverdueGather -x` | Wave 0 gap |
| TASK-05 | "ticktick_overdue" key still in jobs dict | unit (Python) | `pytest tests/test_autonomous.py::TestJobsDict -x` | Wave 0 gap |
| TASK-06 | Migration order: native verified before TickTick tools removed | manual | n/a | manual-only |
| TASK-07 | /api/tasks/summary returns {due_today, overdue} | unit (Python) | `pytest tests/test_task_store.py::TestGetSummary -x` | Wave 0 gap |
| TASK-07 | useTaskSummary hook fetches /api/tasks/summary | unit (TS) | `cd frontend && npm test -- --run src/hooks/useTaskSummary.test.ts` | Wave 0 gap |

### Sampling Rate
- **Per task commit:** `pytest tests/test_task_store.py -x` + `cd frontend && npm test -- --run src/utils/parseTaskInput.test.ts`
- **Per wave merge:** All test files listed in the table above + `pytest tests/test_tools.py -x tests/test_autonomous.py -x`
- **Phase gate:** Full task test suite green + existing 1153+ baseline holds (run `pytest tests/test_autonomous.py tests/test_ticktick_tool.py tests/test_tools.py -x` to verify tool-swap regressions)

### Wave 0 Gaps
- [ ] `tests/test_task_store.py` — covers TASK-01/02/04/07 (Firestore mock per `_install_firestore_mock()` in `tests/test_firestore_db.py`)
- [ ] `tests/test_web_server.py` extensions — covers TASK-01/07 API routes
- [ ] `tests/test_tools.py` extensions — `TestNativeTaskTools`: verify native task schemas registered; verify `add_task` removed
- [ ] `tests/test_autonomous.py` extensions — `TestNativeOverdueGather`: verify return shape; verify `jobs["ticktick_overdue"]` still present
- [ ] `frontend/src/utils/parseTaskInput.test.ts` — covers TASK-03 (pure function, no DOM needed; 8 test cases minimum)
- [ ] `frontend/src/hooks/useTaskSummary.test.ts` — covers TASK-07 frontend hook (mirrors `useChat.test.tsx` pattern)

*(Existing test infrastructure covers the surrounding code; new files are needed only for the new TaskStore + tool swap + parseTaskInput.)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (session) | `require_hub_session` already in place (Phase 26); all `/api/tasks/*` routes must use `Depends(require_hub_session)` |
| V3 Session Management | yes | Inherited from Phase 26 — no new session state |
| V4 Access Control | yes (single-user, but still applies) | Session check = owner check (one Google account allowed); no per-task owner_id needed |
| V5 Input Validation | yes | title: non-empty, max 500 chars; notes: max 10,000 chars; due_date: ISO date regex; priority: enum validation; list_id: UUID or "inbox" |
| V6 Cryptography | no | No new crypto in this phase |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via task title/notes rendered as HTML | Tampering | React's default text rendering escapes strings; never use `dangerouslySetInnerHTML` for task content (same rule as chat — `MessageBubble.tsx` reference) |
| Quick-add token injection (e.g., `#<script>`) | Tampering | Token regex strips only alphanumeric-ish characters; title is always plain text |
| CSRF on task mutation endpoints | Elevation of Privilege | `SameSite=Strict` cookie (Phase 26) + `credentials: 'include'` + same-origin-only (no CORS) |
| Overdue gather leaking tasks from TaskStore before tools are fully swapped | Information Disclosure | D-09 migration order: native verified first, then TickTick removed; no overlap window |
| Hard-delete request forgeable by replaying a captured POST | Repudiation | Session cookie validates identity; task_id must belong to an existing `status="completing"` doc — server rejects a hard-delete for an `"active"` task |

**Input validation for task CRUD endpoints (V5):**
```python
# In web_server.py task route handlers (pattern from /api/chat validation):
class CreateTaskInput(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    notes: str | None = Field(None, max_length=10_000)
    due_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    due_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    priority: Literal["none", "low", "medium", "high"] = "none"
    list_id: str | None = None   # None → Inbox
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TickTick Open API for task storage | Native Firestore TaskStore | Phase 27 | Eliminates external API dependency, OAuth token management, and subscription cost |
| TickTick OAuth 2 tokens in Secret Manager | Removed entirely (per D-09 migration order) | Phase 27 Wave 4 | Simplifies secret management |
| `add_task` single-schema tool | 6 native task tools (create/list/complete/reschedule/edit/delete) | Phase 27 | Klaus gains full task management capability, not just add |

**Deprecated after Phase 27:**
- `mcp_tools/ticktick_tool.py`: removed (D-09 wave 4)
- `mcp_tools/ticktick_auth.py`: removed (D-09 wave 4)
- `core/tools.py` `add_task` schema + `_handle_add_task`: removed
- `TICKTICK_ACCESS_TOKEN`, `TICKTICK_REFRESH_TOKEN`, `TICKTICK_CLIENT_ID`, `TICKTICK_CLIENT_SECRET` env vars: can be removed from Secret Manager after subscription cancelled

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | chrono-node 2.9.1 handles Asia/Jerusalem timezone correctly via the `timezone` param | Unknown 1, Standard Stack | Wrong timezone → "tomorrow" creates tasks for wrong date; must be caught in unit tests with refDate stubs |
| A2 | chrono-node's `prepare` script (npm build) does NOT run at consumer install time (only at publish time) | Package Legitimacy Audit | No risk at runtime; would only matter during `npm install` |
| A3 | The 4-second undo window is short enough that a page reload mid-window is acceptable (task effectively disappears) | Unknown 3 | If Amit frequently reloads, tasks could silently vanish; mitigated by the very short window and the fact that a reload is unlikely mid-animation |
| A4 | The `_ticktick_add_task` symbol in `core/tools.py` line 1361 is indeed dead code (never imported or assigned) | Unknown 5, Pitfall 5 | If there is a dynamic import somewhere not found by grep, removing the handler may break a working code path; the planner should add a test that imports `core.tools` and verifies `_HANDLERS` keys |
| A5 | TaskStore reads using `_where(col, "status", "==", "active")` will work without requiring a composite index when combined with other filters, OR the composite index can be created in Wave 0 | Unknown 4 | Composite index missing → Firestore returns 400 on overdue query; mitigated by Wave 0 index-creation task |
| A6 | Keeping `"ticktick_overdue"` as the situation key name (renaming only the gather function) means zero changes to `prompts/autonomous_triage.md`, eval fixtures, and triage prompt tests | Unknown 5 | If the prompt or eval fixtures reference a "ticktick" label in a way that confuses the model (unlikely), triage quality may degrade; low risk |

---

## Open Questions (RESOLVED)

1. **GCP Project ID and Firestore database name in task CRUD routes**
   - What we know: Existing routes in `web_server.py` use env vars `GCP_PROJECT_ID` and `FIRESTORE_DATABASE` via helper functions already in the file.
   - What's unclear: The exact helper function signature used by Phase 26 routes to instantiate stores — needs to be confirmed before writing the task route handlers.
   - Recommendation: Read `interfaces/web_server.py` lines 1415–1478 (`api_today`) for the exact pattern before writing task routes.
   - **RESOLVED:** Pattern extracted inline into 27-02's `<interfaces>` block — task route handlers instantiate the store as `store = TaskStore(project_id=os.environ.get("GCP_PROJECT_ID", ""), database=os.environ.get("FIRESTORE_DATABASE", "(default)"))`, mirroring the FollowupStore/StrengthSessionStore `__init__(self, project_id, database="(default)")` convention. No further investigation needed at execution time.

2. **TICKTICK_* Secret Manager secrets — operator cleanup timing**
   - What we know: D-09 specifies: native verified → remove TickTick tools → cancel subscription. Secret Manager cleanup follows subscription cancellation.
   - What's unclear: Whether the planner should emit a deployment-operator task to remove the secrets from Secret Manager, or leave it as a manual step.
   - Recommendation: Include as a Wave 5 deployment task (after subscription cancelled) — planner should note it as an operator action, not a code change.
   - **RESOLVED:** Sequenced in 27-07 as a post-cutover operator action — the "TickTick Retirement" subsection of `docs/DEPLOYMENT.md` (27-07 Task 2) documents removing `TICKTICK_ACCESS_TOKEN`/`TICKTICK_REFRESH_TOKEN`/`TICKTICK_CLIENT_ID`/`TICKTICK_CLIENT_SECRET` AFTER the subscription is cancelled. It is an operator action, not a Claude code change.

3. **Frontend vitest config file path**
   - What we know: `frontend/package.json` has `"test": "vitest"`. An existing `useChat.test.tsx` test file works.
   - What's unclear: The exact vitest config file name and location (not read during research).
   - Recommendation: Not blocking — run `ls frontend/vitest.config*` in Wave 0; if absent, vitest auto-configures from `vite.config.*`.
   - **RESOLVED (non-blocking):** vitest auto-discovers its config from `vite.config.*`; no separate `vitest.config.*` is required. Existing `useChat.test.tsx` already runs under this setup, so the Wave 0 frontend stubs (27-01 Task 3) run without additional config.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js / npm | `npm install chrono-node` | ✓ | (Docker build stage) | — |
| google-cloud-firestore (Python) | TaskStore | ✓ | (already installed) | — |
| Firestore (GCP) | TaskStore persistence | ✓ | (live, confirmed by Phase 26) | — |
| Composite Firestore indexes | Task overdue/list queries | requires creation | — | 400 errors on multi-field queries |
| vitest | Frontend tests | ✓ | ^3.2.4 (in package.json) | — |

**Missing dependencies with no fallback:**
- Firestore composite indexes for `(status, due_date)` and `(list_id, status, due_date)` — must be created before the overdue endpoint can run in production. Create in Wave 0 / deployment task.

**Missing dependencies with fallback:**
- none

---

## Sources

### Primary (HIGH confidence)
- `memory/firestore_db.py` — store class patterns, `_jsonsafe_doc`, `_where`, `_make_firestore_client`, `FollowupStore.list_due` composite-index note [VERIFIED: lines 22–38, 885–913, 1087–1223, 1517–1614]
- `core/tools.py` — `add_task` schema (lines 212–247), `_handle_add_task` (lines 1357–1364), `_HANDLERS` (lines 2248–2303) [VERIFIED: read directly]
- `core/autonomous.py` — `_gather_ticktick_overdue` (lines 236–244), `jobs` dict (line 433), `ticktick_overdue` key usage (lines 180, 463, 487–493, 516, 598, 684, 729) [VERIFIED: read directly]
- `interfaces/web_server.py` — `require_hub_session` pattern, `api_today` (lines 1415–1478), `_jsonsafe_doc` import pattern [VERIFIED: read directly]
- `frontend/src/hooks/useChat.ts` — `useMutation` with `onMutate/onError/onSettled` (lines 61–99) [VERIFIED: read directly]
- `frontend/src/hooks/useToday.ts` — `useQuery` with `refetchOnWindowFocus` pattern [VERIFIED: read directly]
- `frontend/src/api/client.ts` — `apiFetch` with `credentials: 'include'` [VERIFIED: read directly]
- `frontend/src/components/layout/GlanceRail.tsx` — extension point for Tasks section [VERIFIED: read directly]
- `frontend/src/App.tsx` — `/tasks` ComingSoon placeholder at line 57–59 [VERIFIED: read directly]
- `mcp_tools/ticktick_tool.py` — `get_today_tasks()` return shape (lines 174–236) [VERIFIED: read directly]
- `.planning/phases/27-tasks/27-CONTEXT.md` — all 19 locked decisions [VERIFIED: read directly]
- `.planning/phases/27-tasks/27-UI-SPEC.md` — component inventory, interaction contracts [VERIFIED: read directly]
- `npm view chrono-node` — version 2.9.1, created 2012-08-20, MIT, github.com/wanasit/chrono [VERIFIED: npm registry]
- Python `calendar.monthrange`, `timedelta` — stdlib date arithmetic [VERIFIED: Python stdlib]

### Secondary (MEDIUM confidence)
- chrono-node README (wanasit/chrono GitHub) — `parseDate(text, { instant, timezone })` API [CITED: github.com/wanasit/chrono]
- npm trends — ~1M weekly downloads for chrono-node [CITED: npmtrends.com/chrono-node]
- chrono-node package.json `scripts` — `prepare` is build-only, no network postinstall [VERIFIED: npm view chrono-node scripts]

### Tertiary (LOW confidence)
- None — all major claims verified against codebase or npm registry.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages confirmed in existing codebase or via npm view; chrono-node is [ASSUMED] per provenance rule but manually verified as legitimate
- Architecture: HIGH — all patterns cite specific file:line from existing code
- Pitfalls: HIGH — most are verified from existing code invariants (CLAUDE.md, firestore_db.py docstrings, test patterns)
- Recurrence engine: MEDIUM — logic is correct Python stdlib, but month-end and weekday-wrap edge cases need comprehensive test coverage to confirm

**Research date:** 2026-06-17
**Valid until:** 2026-07-17 (stable dependencies; chrono-node is actively maintained but changes infrequently)
