---
phase: 27-tasks
plan: 05
subsystem: frontend-tasks-ui
tags: [react, tasks-page, micro-animation, undo-toast, recurrence, wave-3]
dependency_graph:
  requires: [27-04]
  provides: [TasksPage, TaskListView, TaskRow, TaskDetailSheet, TaskListSidebar, TaskListSelector, RecurrenceSelector, SortGroupControl, UndoToast]
  affects: [27-06-quickadd-surfacing]
tech_stack:
  added: []
  patterns: [timeline-inline-style, dockchat-bottomsheet-translateY, zustand-undo-single-item, react-query-optimistic-mutations]
key_files:
  created:
    - frontend/src/components/tasks/TasksPage.tsx
    - frontend/src/components/tasks/TaskListView.tsx
    - frontend/src/components/tasks/TaskRow.tsx
    - frontend/src/components/tasks/TaskDetailSheet.tsx
    - frontend/src/components/tasks/TaskListSidebar.tsx
    - frontend/src/components/tasks/TaskListSelector.tsx
    - frontend/src/components/tasks/RecurrenceSelector.tsx
    - frontend/src/components/tasks/SortGroupControl.tsx
    - frontend/src/components/tasks/UndoToast.tsx
  modified:
    - frontend/src/App.tsx
decisions:
  - "App.tsx keeps a thin local TasksPage() wrapper that renders <TasksPageComponent /> (imported as alias) — minimal route-table churn, ComingSoon body removed for Tasks only"
  - "activeListId managed via useState in TasksPage (no per-list route) per UI-SPEC"
  - "Completion micro-animation = 150ms circle fill + 150ms checkmark stroke-dashoffset + 200ms max-height collapse, exactly per UI-SPEC"
  - "4s undo timer is a browser setTimeout (NEVER a server BackgroundTask) — CLAUDE.md §6 / T-27-REP"
  - "undoStore last-action-wins: a new action immediately resolves the prior item's hard-delete (single active toast)"
  - "Auto-sort only (D-18) — Sort (Due date/Priority) + Group (On/Off); no drag-reorder code"
  - "No delete confirmation modal (D-14) — delete routes through the same UndoToast flow as completion"
  - "Recurring-edit gated by a 2-choice sheet ('This occurrence only' / 'This and following') forwarding scope per D-07"
requirements-completed: [TASK-01, TASK-04]
metrics:
  duration: "~12 minutes executor + orchestrator-completed tail"
  completed: "2026-06-19"
  tasks_completed: 3
  files_modified: 10
---

# Phase 27 Plan 05: Tasks Page UI Summary

## One-liner

The real `/tasks` page — sidebar + list view with auto sort/group, satisfying completion micro-animation, 4s last-action-wins undo toast driving client-side soft-mark→hard-delete, and a create/edit detail sheet with full recurrence + recurring-edit dialog — rendered to the 27-UI-SPEC contract, replacing the ComingSoon placeholder.

## What Was Built

### Task 1: TasksPage + TaskListView + sidebar/selector + SortGroupControl + route swap

- **`TasksPage.tsx`** — root `/tasks` component. Desktop = `TaskListSidebar` (200px) + `TaskListView` (flex-1); phone = current-list header (opens `TaskListSelector` bottom sheet) + `TaskListView`. `activeListId`/`detailTask`/`detailOpen`/`listPickerOpen` via `useState`. Renders the global `UndoToast` (fixed) so it's visible regardless of scroll.
- **`TaskListView.tsx`** — consumes `useTasks(listId)`; `SortGroupControl` header + a `TaskRow` per task; loading skeleton, error, and verbatim empty states ("Your Inbox is clear." / "This list is empty."). Sort by due date (null last) or priority; Group On buckets into Today/This week/Later/No date (D-18).
- **`TaskListSidebar.tsx`** (desktop) — Inbox first with accent (#6366F1) active state; user lists from `useTaskLists`; "New list" inline input → `createList`.
- **`TaskListSelector.tsx`** — shared phone list-picker sheet.
- **`SortGroupControl.tsx`** — two segmented groups (Sort Due date/Priority, Group On/Off), local state only; no drag-reorder.
- **`App.tsx`** — `/tasks` now renders the real component (thin `TasksPage()` wrapper → `<TasksPageComponent />`); ComingSoon removed for Tasks (Habits/Health untouched).

### Task 2: TaskRow + completion micro-animation + UndoToast + soft-mark→hard-delete

- **`TaskRow.tsx`** — 44px checkbox (Circle→CheckCircle2), title, priority chip (Flag; High #F87171 / Med #FBBF24 / Low text-only / None hidden), due chip (CalendarDays; overdue → #EF4444 + AlertCircle "Nd overdue"), recurrence indicator (RotateCcw), list name. Phone swipe-left → 72px destructive Delete; desktop kebab (`MoreHorizontal`, `aria-label="Task options"`) → Edit/Delete. Completion animation 150/150/200ms exactly per UI-SPEC.
- **`UndoToast.tsx`** — driven by `undoStore`; phone above BottomTabs, desktop bottom-center; copy "Task completed." / "Task deleted." + accent "Undo"; 4s auto-dismiss.
- **Flow** — on action: `completeTask`/delete fires, `undoStore.show`, browser `setTimeout` starts; "Undo" → `undoTask` + restore + cancel timer; expiry → `hardDeleteTask`. Last-action-wins resolves the prior item immediately. Timer is client-side only (T-27-REP / CLAUDE.md §6).

### Task 3: TaskDetailSheet + RecurrenceSelector + recurring-edit dialog

- **`TaskDetailSheet.tsx`** — phone bottom sheet (translateY mirroring DockChat), desktop centered modal (max-width 480px). Fields in UI-SPEC order: Title, Notes, Due date, "Add time" toggle → time, Priority, List, RecurrenceSelector. Context-aware CTA ("Add task" create / "Save changes" edit) via `useCreateTask`/`useUpdateTask` optimistic mutations. Existing task: destructive "Delete task" routing through the UndoToast flow (no confirmation modal — D-14).
- **`RecurrenceSelector.tsx`** — cadence ("Does not repeat"/"Daily"/"Weekdays"/"Weekly"/"Monthly"/"Every N days") + anchor toggle ("Stick to schedule"/"From completion") + every-N input, mapped to the `{cadence, every_n_days, anchor}` rule shape from 27-01.
- **Recurring-edit** — 2-choice action sheet (heading "Edit recurring task", options "This occurrence only" / "This and following") forwarding the choice as `scope` per D-07.

## Verification

```
cd frontend && npx vitest run   → 74 passed (10 files, 0 skipped)
cd frontend && npm run build     → tsc -b + vite build green (1832 modules, PWA generated)
grep 'ComingSoon label="Tasks"' App.tsx          → none (placeholder removed)
grep components/tasks/TasksPage App.tsx          → import present
empty states "Your Inbox is clear."/"This list is empty." → present
no drag-reorder (onDrop/draggable/onDrag)        → none
TaskRow CheckCircle2 + 150/200ms timings         → present
kebab aria-label="Task options"                  → present
UndoToast "Task completed."/"Task deleted."/"Undo" → verbatim
setTimeout (client undo timer) + hardDeleteTask + undoTask → wired
CTA "Add task"/"Save changes"                    → present
RecurrenceSelector cadence + anchor labels       → all verbatim
recurring-edit "This occurrence only"/"This and following"/"Edit recurring task" → present
useCreateTask/useUpdateTask                       → used
dangerouslySetInnerHTML in components/tasks       → none (T-27-TI)
```

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `cf8ccda` | feat | TasksPage + TaskListView + list sidebar/selector + sort/group control |
| `c29bb9f` | feat | TaskRow completion micro-animation + UndoToast soft-mark→hard-delete |
| `71e98e0` | feat | TaskDetailSheet + RecurrenceSelector — detail/edit sheet + recurrence picker |
| `3b62807` | docs | Reword T-27-TI security comments to drop literal API token (no behavior change) |

## Deviations from Plan

### Session-limit interruption — orchestrator-completed tail

**Found during:** Task 3 execution.

**Issue:** The executor agent hit a provider session/usage limit after committing Tasks 1–2 (commits `cf8ccda`, `c29bb9f`) and writing `RecurrenceSelector.tsx` + `TaskDetailSheet.tsx` (uncommitted) — before its final commit and SUMMARY. App.tsx wiring was already committed and the worktree typechecked cleanly.

**Fix:** The execute-phase orchestrator spot-checked the worktree (per the quota-failure safe-resume path), confirmed the two uncommitted components were complete and the full suite + build were green, committed them (`71e98e0`), ran the plan's acceptance-criteria greps (all pass), reworded the T-27-TI comments (`3b62807`), and authored this SUMMARY. No work was lost or duplicated.

**Rule:** Rule 3 (orchestrator recovery — finish a verifiably-complete plan tail rather than re-dispatch).

### T-27-TI comment rewording

**Found during:** orchestrator acceptance-criteria verification.

**Issue:** Three components carried security-note comments that mentioned the literal forbidden API name, which would trip the phase-verification grep ("no dangerouslySetInnerHTML in components/tasks") as a false positive — there was never any actual usage.

**Fix:** Reworded the comments to "rendered as plain text React children — never via raw HTML injection," preserving intent and making the grep unambiguous.

**Rule:** Rule 3 (auto-fix — verification-grep false positive).

## Known Stubs

None. All 10 components are implemented and wired; `/tasks` renders the real page. Quick-add (FAB / `N` shortcut) and Today/glance-rail surfacing are intentionally deferred to 27-06 per the plan split.

## Threat Flags

- **T-27-TI** (XSS): mitigated — task title/notes rendered as plain text React children; no raw HTML injection anywhere in `components/tasks`.
- **T-27-REP** (hard-delete timing): mitigated — the 4s timer is a browser `setTimeout`; hard-delete is a tracked client fetch; server still rejects hard-delete of non-`completing` docs (27-02).
- **T-27-SC** (npm installs): accepted — no new installs (chrono-node was added in 27-04).

## Self-Check: PASSED

Files created (9 components):
- `TasksPage.tsx` ✓ · `TaskListView.tsx` ✓ · `TaskRow.tsx` ✓ · `TaskDetailSheet.tsx` ✓ · `TaskListSidebar.tsx` ✓ · `TaskListSelector.tsx` ✓ · `RecurrenceSelector.tsx` ✓ · `SortGroupControl.tsx` ✓ · `UndoToast.tsx` ✓

Files modified:
- `frontend/src/App.tsx` ✓ (route renders real TasksPage; ComingSoon removed for Tasks)

Commits verified: `cf8ccda`, `c29bb9f`, `71e98e0`, `3b62807` ✓
Full frontend suite: 74 passed, 0 failed ✓
Build: tsc -b + vite build green, PWA generated ✓
All Task 1/2/3 acceptance-criteria greps: pass ✓
