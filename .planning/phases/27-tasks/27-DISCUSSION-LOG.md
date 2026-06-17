# Phase 27: Tasks - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-17
**Phase:** 27-Tasks
**Areas discussed:** Lists & priority, Recurrence behavior, Import & reconcile, Quick-add & surfacing, Completed tasks view, Delete & undo, Klaus's task tools, Reminder gap, Task ordering

---

## Lists & priority

| Option | Description | Selected |
|--------|-------------|----------|
| Discover from TickTick | Import reveals lists; seed from those | |
| Small curated set | Proposed Inbox/Personal/Errands/Admin/Someday enum | |
| Flat + labels | Single stream + tags, no lists | |

**User's choice:** Free-text — "I want to be able to create new projects, new lists, and an inbox and also be able to assign dates, priorities and tags just like any other task manager." → user-creatable flat lists/projects + Inbox.
**Notes:** Reframed TASK-01's "fixed set of lists" into user-creatable lists. Follow-up confirmed **flat lists + Inbox** (project = list, no folder hierarchy). Priority chosen as **4-level matching TickTick** (None/Low/Med/High). Tags: **deferred** (not this phase).

---

## Recurrence behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Due-date, roll forward | Next instance on fixed calendar date | partial |
| Completion date | Next instance counts from completion | partial |
| Simple edit (travels forward) | One task holds the rule, no per-occurrence prompt | |
| This-vs-series edit | Calendar-style "this or all following" prompt | ✓ |

**User's choice:** Per-task **anchor toggle** — each recurring task can be set to *stick to schedule* OR *drift to completion date* (user's example: trash done Thursday shouldn't reappear Monday). Edit = calendar-style **"this event or all following events."**
**Notes:** Initial framing confusing; re-explained with the "take out the trash" example. The 5 locked patterns become cadence + anchor; "every-N-days-from-completion" = from-completion mode of an interval.

---

## Import & reconcile

| Option | Description | Selected |
|--------|-------------|----------|
| Open tasks only | Import incomplete tasks only | (then dropped) |
| Open + recent completed | Also last ~90 days completed | |
| Open + all completed | Full archive | |

**User's choice:** Initially "open tasks only", then **dropped the whole import** — "I'll just import it manually since I don't have many tasks on TickTick right now."
**Notes:** Descopes TASK-06 (no importer, no reconciliation report). Confirmed the safety ordering still holds: native verified → remove TickTick tools → cancel subscription. Manual re-entry instead of a script.

---

## Quick-add & surfacing

| Option | Description | Selected |
|--------|-------------|----------|
| Dates + typed shortcuts | NL dates + `#list` / `!priority` tokens | ✓ |
| Dates only | NL date only, list/priority via form | |
| Pin a 'Due today' band (timeline) | Date-only tasks pinned; timed slot inline | ✓ |
| Pinned band only (timeline) | All tasks in top band, never interleaved | |
| Glance: due today + overdue | Count both, overdue emphasized | ✓ |
| Glance: due today only | Today only | |

**User's choice:** **Dates + typed shortcuts** (client-side parser); timeline **pinned "Due today" band** (timed may also slot inline); glance rail **due-today + overdue**.
**Notes:** Parsing confirmed client-side/deterministic ("resolve while typing").

---

## Completed tasks view

| Option | Description | Selected |
|--------|-------------|----------|
| Per-list 'show completed' toggle | Reveal completed below active | |
| Separate Completed view | Global completed screen | (then dropped) |
| Auto-tuck after N days | Auto-archive | |

**User's choice:** No completed view at all — **delete completed tasks entirely** ("you can just delete the completed tasks from memory from everything, because now we have the undo feature"). The undo toast is the only recovery.
**Notes:** Revises TASK-04 / SC-4 ("completed tasks remain viewable"); micro-animation stays.

---

## Delete & undo

| Option | Description | Selected |
|--------|-------------|----------|
| Undo toast, no trash | Brief undo on complete/delete | ✓ |
| Trash bin + restore | Restorable trash | |
| Hard delete w/ confirm | Confirm then gone, no undo | |

**User's choice:** **Undo toast, no trash.**
**Notes:** Pairs with the completion micro-animation; minimal to build.

---

## Klaus's task tools

| Option | Description | Selected |
|--------|-------------|----------|
| Full task manager | create/query/complete/reschedule/edit/delete | ✓ |
| Minimal parity | add + read-today/overdue + complete (TickTick parity) | |

**User's choice:** **Full task manager** via chat.
**Notes:** Autonomous Layer-0 overdue gather repointed from TickTick → TaskStore (data-source swap only; tick behavior unchanged).

---

## Reminder gap

| Option | Description | Selected |
|--------|-------------|----------|
| Acceptable — keep order | Build Tasks now, push in P29; rely on hub + Klaus | ✓ |
| Reorder phases | Bring Web Push earlier | |

**User's choice:** **Acceptable, keep order** — "we'll finish phase 29 in a few days anyway... I don't really have tasks for the up-and-coming days." Also asked NOT to add proactive task-nudging via the autonomous tick ("leave it as it is").
**Notes:** No exact-time reminders in P27; P29 web push covers it. Autonomous tick behavior unchanged (only the data source is repointed).

---

## Task ordering

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-sort | By due date then priority, no manual | partial |
| Manual drag-reorder | Stored position + drag UI | |
| Auto-sort + manual within a day | Hybrid | |

**User's choice:** Free-text — list/project views get a **sort + group control** (by due date or priority); **day-scoped views auto-sort by priority**. No manual drag.
**Notes:** No stored position field needed.

---

## Claude's Discretion

- Asia/Jerusalem local time for date logic; optional due-time on tasks.
- Optimistic create/edit (Phase 26 chat pattern), offline write deferred (HUBX-05).
- Plain-text notes; refresh-on-focus list views; no real-time sync.
- TaskStore shape, NL-date library choice, month-end recurrence clamping, undo-toast
  duration, soft-mark→hard-delete mechanics, completion micro-animation (→ /gsd:ui-phase 27).

## Deferred Ideas

- Tags (field + filter UI).
- Automated TickTick import + reconciliation report (was TASK-06) → manual migration.
- Manual drag-reorder of tasks.
- Completed-tasks view / history.
- Exact-time task reminders / OS notifications (Phase 29).
- Offline task creation / write queue (HUBX-05).
- Proactive task-nudging via the autonomous tick.
- Subtasks / hierarchies, complex RRULE recurrence (milestone Out-of-Scope).
