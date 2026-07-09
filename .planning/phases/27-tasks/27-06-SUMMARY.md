---
phase: 27-tasks
plan: 06
subsystem: frontend-tasks-ui
tags: [react, quick-add, FAB, N-key, DueTasksBand, GlanceRail, useTaskSummary, wave-4]
dependency_graph:
  requires: [27-04, 27-05]
  provides: [QuickAddBar, TaskFAB, DueTasksBand, GlanceRail-Tasks-section]
  affects: [timeline-today, glance-rail, tasks-page]
tech_stack:
  added: []
  patterns: [parseTaskInput-live-chip, react-query-dedup-shared-key, fuzzy-list-match, micro-animation-reuse]
key_files:
  created:
    - frontend/src/components/tasks/QuickAddBar.tsx
    - frontend/src/components/tasks/TaskFAB.tsx
    - frontend/src/components/timeline/DueTasksBand.tsx
  modified:
    - frontend/src/components/tasks/TasksPage.tsx
    - frontend/src/components/timeline/TimelineDay.tsx
    - frontend/src/components/layout/GlanceRail.tsx
    - frontend/src/components/timeline/TimelineDay.test.tsx
decisions:
  - "QuickAddBar uses parseTaskInput on every keystroke with refDate=new Date() for live chip resolution"
  - "Fuzzy list match: exact-name → prefix/contains → inbox fallback (unmatched #list token → inbox)"
  - "TaskFAB renders the full FAB + bottom-sheet QuickAddBar as a self-contained component; old hard-coded FAB button in TasksPage removed"
  - "Desktop N-key listener guards activeElement.tagName + isContentEditable before opening inline QuickAddBar"
  - "DueTasksBand uses useTaskSummary() as the zero-count guard (shared key with GlanceRail → one fetch) plus useTasks(undefined) for actual task rows filtered client-side"
  - "TimelineDay.test.tsx extended with vi.mock for useTaskSummary + useTasks to avoid QueryClientProvider requirement (Rule 1 auto-fix)"
  - "GlanceRail aside now uses flexDirection:column + gap:12px to stack Nutrition + Tasks cards"
requirements-completed: [TASK-03, TASK-07]
metrics:
  duration: "~6 minutes"
  completed: "2026-06-19"
  tasks_completed: 2
  files_modified: 7
---

# Phase 27 Plan 06: Quick-Add + Due Tasks Band + GlanceRail Tasks Summary

## One-liner

Quick-add (FAB bottom sheet on phone, N-key inline bar on desktop) with live `parseTaskInput` chip resolution, plus a pinned "Due today" band on the timeline and a Tasks card on the glance rail — both reading the shared `useTaskSummary` fetch (TASK-03 + TASK-07 closed).

## What Was Built

### Task 1: QuickAddBar (live parse) + TaskFAB + N-key shortcut

**`QuickAddBar.tsx`** — single-line input with `parseTaskInput` live chip rendering:
- Input placeholder: `"Add a task…  #list  !priority  date"` (verbatim per UI-SPEC)
- Calls `parseTaskInput(value, new Date())` on every keystroke — resolves tokens to inline chips:
  - Date chip: `"D Mon"` format (e.g. `"19 Jun"`) with accent border
  - Priority chip: `"High"` / `"Medium"` / `"Low"` in their semantic colors (red/amber/grey)
  - List chip: shows resolved list name (fuzzy-matched to existing lists or `"Inbox"`)
- Submit: fuzzy-match `list_name → list_id` (exact → prefix/contains → `inbox`); `useCreateTask` with `{title, due_date, priority, list_id}`; clears input for next entry
- Escape key / blur dismisses without saving
- `"Add task"` button disabled (dim accent) when title is empty

**`TaskFAB.tsx`** — phone-only self-contained FAB + bottom sheet:
- 56px diameter, `backgroundColor: accent` (`#6366F1`), `aria-label="Add task"`, fixed `bottom: 76px`
- Tapping opens `QuickAddBar` as a slide-up bottom sheet with a drag handle, over a scrim
- Tapping the scrim dismisses the sheet; `QuickAddBar.onClose` also dismisses
- `className="md:hidden"` on both the FAB and the sheet (phone-only)

**`TasksPage.tsx`** (updated):
- Replaced the old hard-coded 56px FAB button with `<TaskFAB defaultListId={activeListId} />`
- Added `useEffect` keyboard listener for `N` / `n` key:
  - Guards: `document.activeElement.tagName === 'input' | 'textarea'` or `isContentEditable`; also guards `e.metaKey || e.ctrlKey || e.altKey`
  - Opens `quickAddOpen` state → renders desktop `<QuickAddBar>` inline above `TaskListView`
- Desktop task column wrapped in a flex column so the inline QuickAddBar stacks above the list
- Added `useState` import alongside the existing `useState` (changed from `useState` to `useState, useEffect`)

### Task 2: DueTasksBand + GlanceRail Tasks section

**`DueTasksBand.tsx`** — pinned band on the Today timeline:
- `useTaskSummary()` for the count guard (returns null if `due_today + overdue === 0`)
- `useTasks(undefined)` for actual task rows; filtered client-side: `status === 'active' && due_date !== null && due_date <= todayISO`; sorted overdue-first (highest days first), then alphabetically
- Section header: 4px×32px accent stripe + `"Due today"` label (13px, textSecondary)
- Each row: 44px-target checkbox → micro-animation (same 150/150/200ms pattern as TaskRow) + `undoStore.show()` → title button → `useNavigate('/tasks')` → overdue chip `"Nd overdue"` (destructive when `overdueDays > 0`)
- `getTodayISO()` uses `new Date().toLocaleDateString('en-CA')` for YYYY-MM-DD in local timezone
- No render when count is 0 — strict `if (totalCount === 0 || dueTasks.length === 0) return null`

**`TimelineDay.tsx`** (updated):
- Added `import { DueTasksBand } from './DueTasksBand'`
- Inserted `<DueTasksBand />` between Section 3 (all-day events) and Section 4 (timed events + NowLine)

**`GlanceRail.tsx`** (updated):
- Imports `useNavigate` from `react-router-dom` and `useTaskSummary` from the shared hook
- Added Tasks card (stacked below Nutrition via `flexDirection: column, gap: 12px` on the aside)
- Tasks card: role=button, onClick → `navigate('/tasks')`, keyboard accessible (Enter/Space)
- "N due today" row always rendered; "N overdue" row only rendered when `overdue > 0`
- Overdue value: `color: '#EF4444'` (destructive, per UI-SPEC)

**`TimelineDay.test.tsx`** (updated — Rule 1 auto-fix):
- Added `vi.mock('../../hooks/useTaskSummary', ...)` + `vi.mock('../../hooks/useTasks', ...)` to avoid `No QueryClient set` errors when `DueTasksBand` renders inside `TimelineDay` during tests

## Verification

```
npm run build                                       → tsc -b + vite build green (2076 modules, PWA)
npx vitest run                                      → 74 passed (10 files, 0 skipped)
grep parseTaskInput QuickAddBar.tsx                 → import + live call on input change
grep 'aria-label="Add task"' TaskFAB.tsx            → present (line 58)
grep '56px' TaskFAB.tsx                             → width/height 56px present
grep 'activeElement\|tagName\|isContentEditable' TasksPage.tsx → N-key guard present
grep 'Add a task' QuickAddBar.tsx                   → verbatim placeholder present
grep "'inbox'" QuickAddBar.tsx                      → fallback to inbox present
grep useTaskSummary DueTasksBand.tsx GlanceRail.tsx → both consumers confirmed
grep DueTasksBand TimelineDay.tsx                   → import + render present
grep 'totalCount === 0.*return null' DueTasksBand.tsx → guard present
grep 'overdue > 0\|EF4444' GlanceRail.tsx          → destructive + hidden-when-0 present
grep 'Due today' DueTasksBand.tsx                   → literal label on line 275
grep 'overdue.*d overdue' DueTasksBand.tsx          → chip format present
dangerouslySetInnerHTML in any new component        → none (T-27-TI)
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `8f6b07e` | feat | QuickAddBar live-parse + TaskFAB bottom sheet + N-key shortcut |
| `da67fef` | feat | DueTasksBand on timeline + Tasks section on GlanceRail |

## Deviations from Plan

### Rule 1 — TimelineDay tests needed mock hooks

**Found during:** Task 2 verification (`npx vitest run`).

**Issue:** Adding `DueTasksBand` (which calls `useTaskSummary()` and `useTasks()`) as a child of `TimelineDay` broke 6 existing TimelineDay tests with `No QueryClient set, use QueryClientProvider to set one`. The tests mock `useToday` but render the component without a `QueryClientProvider`.

**Fix:** Added `vi.mock` stubs for `useTaskSummary` (returns `{ due_today: 0, overdue: 0 }`) and `useTasks` (returns `[]`) in `TimelineDay.test.tsx`. The mocks return zero counts, so `DueTasksBand` renders nothing and the existing test assertions are unaffected.

**Files modified:** `frontend/src/components/timeline/TimelineDay.test.tsx`

**Commit:** Included in `da67fef`.

**Rule:** Rule 1 (auto-fix bug — tests broke due to changes in this task).

## Known Stubs

None. All components are wired to real hooks and real data. The `DueTasksBand` uses client-side filtering of `useTasks(undefined)` for the actual rows; `useTaskSummary` provides the count guard. GlanceRail reads the real `useTaskSummary`. Quick-add submits via the real `useCreateTask` mutation.

## Threat Flags

- **T-27-TI** (XSS): mitigated — task titles rendered as plain React text children in `DueTasksBand` (`BandTaskRow` title button is plain text, not HTML); `QuickAddBar` chip labels are static strings or the parsed token value (safe charset `[a-zA-Z0-9_-]` from parseTaskInput). No `dangerouslySetInnerHTML` in any new component.
- **T-27-IV**: mitigated — `QuickAddBar` passes parsed values to `useCreateTask`; server-side Pydantic re-validates (27-02).
- **T-27-AC**: mitigated — `/api/tasks/summary` is session-gated (27-02).

## Self-Check: PASSED

Files created:
- `frontend/src/components/tasks/QuickAddBar.tsx` ✓ (parseTaskInput on input change, placeholder verbatim, inbox fallback)
- `frontend/src/components/tasks/TaskFAB.tsx` ✓ (aria-label="Add task", 56px, accent, md:hidden)
- `frontend/src/components/timeline/DueTasksBand.tsx` ✓ (useTaskSummary guard, "Due today" label, "Nd overdue" chip, return null when count=0)

Files modified:
- `frontend/src/components/tasks/TasksPage.tsx` ✓ (N-key listener with activeElement guard, TaskFAB + inline QuickAddBar)
- `frontend/src/components/timeline/TimelineDay.tsx` ✓ (DueTasksBand imported + inserted between Section 3 and 4)
- `frontend/src/components/layout/GlanceRail.tsx` ✓ (Tasks card with useTaskSummary, overdue #EF4444, hidden when 0)
- `frontend/src/components/timeline/TimelineDay.test.tsx` ✓ (vi.mock stubs added; 8 tests still pass)

Commits verified: `8f6b07e`, `da67fef` ✓
Full frontend suite: 74 passed, 0 failed ✓
Build: tsc -b + vite build green, 2076 modules, PWA generated ✓
All Task 1 + Task 2 acceptance-criteria greps: pass ✓
