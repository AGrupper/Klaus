---
phase: 27-tasks
plan: 04
subsystem: frontend-data-layer
tags: [react-query, zustand, chrono-node, tdd, wave-2]
dependency_graph:
  requires: [27-01]
  provides: [parseTaskInput, api/tasks, api/task-lists, useTasks, useTaskLists, useTaskSummary, undoStore]
  affects: [27-05-tasks-page, 27-06-timeline-surfacing]
tech_stack:
  added: [chrono-node@2.9.1]
  patterns: [useChat-optimistic-mutation, useToday-refetch-on-focus, zustand-single-item-store]
key_files:
  created:
    - frontend/src/utils/parseTaskInput.ts
    - frontend/src/api/tasks.ts
    - frontend/src/api/task-lists.ts
    - frontend/src/hooks/useTasks.ts
    - frontend/src/hooks/useTaskLists.ts
    - frontend/src/hooks/useTaskSummary.ts
    - frontend/src/store/undoStore.ts
  modified:
    - frontend/package.json
    - frontend/package-lock.json
    - frontend/src/utils/parseTaskInput.test.ts
    - frontend/src/hooks/useTaskSummary.test.ts
decisions:
  - "Token stripping (LIST_TOKEN_RE + PRIORITY_TOKEN_RE) runs BEFORE chrono.parse to prevent misparses (Pitfall 6)"
  - "due_date formatted via toLocaleDateString('en-CA', {timeZone:'Asia/Jerusalem'}) — zero UTC drift"
  - "TASK_SUMMARY_QUERY_KEY = ['tasks','summary'] — shared key enables cache dedup across GlanceRail + DueTasksBand"
  - "undoStore holds single activeItem (no array) — last-action-wins per UI-SPEC"
  - "useTaskSummary.test.ts kept as .ts using createElement instead of JSX to avoid .tsx rename"
  - "Tests run from worktree's own frontend/ with separate node_modules install (worktree isolation)"
requirements-completed: [TASK-03]
metrics:
  duration: "~20 minutes"
  completed: "2026-06-18"
  tasks_completed: 2
  files_modified: 11
---

# Phase 27 Plan 04: Frontend Data Layer Summary

## One-liner

chrono-node@2.9.1 deterministic quick-add parser (Asia/Jerusalem, token-strip-first) + apiFetch wrappers for all task/list CRUD + optimistic react-query hooks (useTasks/useTaskLists/useTaskSummary) + zustand undoStore with last-action-wins semantics.

## What Was Built

### Task 1: chrono-node install + parseTaskInput (TDD)

**`frontend/src/utils/parseTaskInput.ts`** — pure deterministic function implementing D-10:

- `parseTaskInput(raw, refDate?)` → `ParsedTask { title, due_date, list_name, priority }`
- `LIST_TOKEN_RE` (`#[a-zA-Z0-9_-]+`) and `PRIORITY_TOKEN_RE` (`!(high|medium|low|none|[123])`) strip BEFORE `chrono.parse()` — prevents token text from confusing the date parser
- `PRIORITY_MAP`: `!high|!1→high`, `!medium|!2→medium`, `!low|!3→low`, `!none→none`
- Date formatted with `toLocaleDateString('en-CA', {timeZone:'Asia/Jerusalem'})` — YYYY-MM-DD in Israel time, zero UTC drift
- Near-midnight timezone correctness: 23:30 Israel time yields the Israel calendar date, not the UTC date (Pitfall 6 guard)

**`frontend/src/utils/parseTaskInput.test.ts`** — 12 green tests replacing Wave 0 skip stubs:
- Case 1: "Buy milk tomorrow" → `{title:"Buy milk", due_date:"2026-06-19"}`
- Case 2: "meeting #work !high friday" from Wednesday → `{list_name:"work", priority:"high", due_date:"2026-06-19"}`
- Cases 3-5: list-only, !medium, !low
- Case 6: "next week" relative → future date
- Case 7: near-midnight timezone edge case (23:30 Israel → next Israel day)
- Case 8: date phrase removed from title
- Case 9: absolute date "June 25" → "2026-06-25"
- Case 10: all tokens combined (Doctor #health !high next monday → "2026-06-22")
- Case 11: numeric priority shortcuts (!1/!2/!3)
- Case 12: plain task → all nulls

### Task 2: API wrappers + hooks + undoStore (TDD)

**`frontend/src/api/tasks.ts`** — apiFetch wrappers for all task endpoints:
- `fetchTasks(listId?)` → `Task[]`
- `fetchTaskSummary()` → `TaskSummary { due_today, overdue }`
- `createTask(input)`, `updateTask(id, patch)`, `completeTask(id, completedOn)`, `undoTask(id)`, `hardDeleteTask(id)`
- `Task` interface: `{id, title, notes, status, due_date, due_time, priority, list_id, recurrence, updated_at}`
- `RecurrenceRule` interface matching TaskStore (27-01)

**`frontend/src/api/task-lists.ts`** — apiFetch wrappers for list CRUD:
- `fetchLists()`, `createList(name)`, `renameList(id, name)`, `deleteList(id)`
- `TaskList` interface: `{id, name, updated_at}`

**`frontend/src/hooks/useTasks.ts`** — optimistic task mutations (mirrors useChat pattern):
- `useTasks(listId)` — `useQuery(['tasks', listId], fetchTasks)`
- `useCreateTask`, `useUpdateTask`, `useCompleteTask` — each with `onMutate` (cancelQueries + snapshot + optimistic setQueryData), `onError` (rollback), `onSettled` (invalidateQueries)
- `useCompleteTask.onSettled` also invalidates `['tasks','summary']` to refresh glance rail counts

**`frontend/src/hooks/useTaskLists.ts`** — optimistic list mutations:
- `useTaskLists()` — `useQuery(['task-lists'], fetchLists)`
- `useCreateList`, `useRenameList`, `useDeleteList` — same onMutate/onError/onSettled pattern

**`frontend/src/hooks/useTaskSummary.ts`** — refetch-on-focus summary hook (mirrors useToday):
- `TASK_SUMMARY_QUERY_KEY = ['tasks', 'summary'] as const`
- `useTaskSummary()` — `refetchOnMount: true`, `refetchOnWindowFocus: true`, NO `refetchInterval`
- `useRefreshTaskSummary()` — returns stable `invalidateQueries` callback

**`frontend/src/store/undoStore.ts`** — zustand undo store:
- `activeItem: UndoItem | null` — single item, never an array
- `UndoItem: { id, action: 'complete'|'delete', listId, nextId: string|null }`
- `show(item)` — replaces prior item (last-action-wins; prior item's hard-delete is caller's responsibility)
- `clear()` — called after undo fires or countdown expires

**`frontend/src/hooks/useTaskSummary.test.ts`** — 5 green tests:
- Data shape returned from mocked fetch
- `isLoading=true` during in-flight fetch
- Error propagation from rejected fetch
- Cache deduplication: 2 hook instances → 1 fetch call
- `TASK_SUMMARY_QUERY_KEY` shape assertion

## Verification

```
npx vitest --run src/utils/parseTaskInput.test.ts   → 12 passed
npx vitest --run src/hooks/useTaskSummary.test.ts   → 5 passed
npx vitest --run                                    → 74 passed (10 test files, 0 skipped)
npm run build                                       → tsc -b succeeded, vite built 1832 modules
grep -n "Asia/Jerusalem" parseTaskInput.ts          → lines 6, 17, 103, 109, 111 (confirmed)
grep -n "chrono-node" package.json                  → "chrono-node": "^2.9.1" (line 14)
Token extraction (lines 79+87) precedes chrono.parse (line 103)
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `857b409` | feat | Install chrono-node@2.9.1 + parseTaskInput parser (12 tests green) |
| `b2f56f9` | feat | API wrappers + react-query hooks + undoStore (5 tests green) |

## Deviations from Plan

### Worktree-local npm install required

**Found during:** Task 1 execution

**Issue:** The worktree has a separate `frontend/` directory that does not share `node_modules` with the main repo checkout. Running `npm install` in the main repo's `frontend/` installed chrono-node there but not in the worktree's `frontend/`. Vitest runs from the worktree's context and could not find the package.

**Fix:** Added `chrono-node@2.9.1` to the worktree's `frontend/package.json` and ran `npm install` inside the worktree's `frontend/`. Both `package.json` files (worktree + main repo) now list chrono-node. The main repo's change is what will be merged.

**Rule:** Rule 3 (auto-fix blocking issue — missing package in worktree context)

### useTaskSummary.test.ts kept as .ts with createElement

**Found during:** Task 2 test writing

**Issue:** The plan specifies `useTaskSummary.test.ts` (`.ts` extension). Adding JSX syntax directly in a `.ts` file causes an esbuild parse error. The Wave 0 stub was also `.ts`.

**Fix:** Used `createElement(QueryClientProvider, { client: queryClient }, children)` instead of JSX syntax in the wrapper factory. This avoids the `.tsx` rename and keeps the file name matching the plan specification.

**Rule:** Rule 3 (auto-fix blocking issue)

## Known Stubs

None. All implementations are complete and wired. The stub-free data layer is ready for the UI layer (27-05) and timeline surfacing (27-06) to consume.

## Threat Flags

None. T-27-TI (token regex strips to safe charset `[a-zA-Z0-9_-]`; React default escaping applies on render; `dangerouslySetInnerHTML` enforcement deferred to 27-05 component implementation per plan). T-27-SC (chrono-node legitimacy) was pre-approved by human verification before this execution.

## Self-Check: PASSED

Files created:
- `frontend/src/utils/parseTaskInput.ts` ✓ (contains `Asia/Jerusalem`, token strip before chrono)
- `frontend/src/api/tasks.ts` ✓ (fetchTasks, fetchTaskSummary, createTask, etc.)
- `frontend/src/api/task-lists.ts` ✓ (fetchLists, createList, renameList, deleteList)
- `frontend/src/hooks/useTasks.ts` ✓ (useQuery + 3 optimistic mutations with onMutate)
- `frontend/src/hooks/useTaskLists.ts` ✓ (useQuery + 3 optimistic mutations)
- `frontend/src/hooks/useTaskSummary.ts` ✓ (TASK_SUMMARY_QUERY_KEY, no refetchInterval)
- `frontend/src/store/undoStore.ts` ✓ (single activeItem, show/clear)

Files modified:
- `frontend/package.json` ✓ (chrono-node@^2.9.1 in dependencies)
- `frontend/package-lock.json` ✓ (updated)
- `frontend/src/utils/parseTaskInput.test.ts` ✓ (12 green tests, no .skip)
- `frontend/src/hooks/useTaskSummary.test.ts` ✓ (5 green tests, no .skip)

Commits verified: `857b409`, `b2f56f9` ✓ (confirmed in git log)
Full suite: 74 passed, 0 failed ✓
Build: tsc + vite succeeded ✓
