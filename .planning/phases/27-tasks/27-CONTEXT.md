# Phase 27: Tasks - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Native task management inside the Klaus Hub — a Firestore `TaskStore` that **replaces
TickTick**. Delivers:

- A real task manager in the hub `/tasks` page (currently a `ComingSoon` placeholder):
  user-creatable lists/projects + an Inbox, tasks with title/notes/due/priority,
  create/edit/complete/delete, recurrence, quick-add, and a completion micro-animation.
- Klaus's **tool swap** — the TickTick tools come out of `core/tools.py` and are replaced
  by native `TaskStore` tools; the autonomous Layer-0 overdue gather is repointed off
  TickTick onto `TaskStore`.
- Tasks surfaced on the existing **Today timeline** (pinned "Due today" band) and the
  **glance rail** (due + overdue count).
- Migration off TickTick — **manual re-entry** of the few open tasks (the automated import
  + reconciliation report originally in TASK-06 is descoped, see D-08), in the preserved
  safety order: native tasks live + verified → remove TickTick tools → cancel subscription.

**This CONTEXT revises three locked requirements** (the visionary's decisions this session
win over the originally-written requirement text — REQUIREMENTS.md/ROADMAP.md should be
updated to match):
- **TASK-01** "a fixed set of lists" → **user-creatable lists/projects + Inbox** (D-02).
- **TASK-04 / SC-4** "completed tasks remain viewable in a completed view" → **completed
  tasks are not retained**, undo toast is the only recovery (D-13). The micro-animation
  part of TASK-04 stays.
- **TASK-06 / SC-6** "one-time TickTick import + reconciliation report" → **manual
  migration, no importer** (D-08).

**NOT in this phase:** tags (D-04, deferred), OS/push reminders (Phase 29), habits
(Phase 28), health pages (Phase 30). **Visual/pixel design** is handled separately by
`/gsd:ui-phase 27` (UI hint = yes) — this file captures product/behavior, not layout.

</domain>

<decisions>
## Implementation Decisions

### Task model — lists, priority, fields
- **D-01:** `TaskStore` task fields = **title, notes (plain text), due (optional date +
  optional time), priority, list, recurrence rule** (see Recurrence). No subtasks /
  hierarchies (milestone Out-of-Scope).
- **D-02:** **Lists are user-creatable** (create / rename / delete). "Project" and "list"
  are the same thing — a **single flat level** — plus a default **Inbox** for unfiled tasks.
  Tags cross-cutting is deferred (D-04). **Supersedes TASK-01's "fixed set of lists"** — the
  planner builds list CRUD + an Inbox, not a hardcoded enum.
- **D-03:** Priority is **4-level: None / Low / Medium / High** (1:1 with TickTick's 0/1/3/5).
- **D-04:** **Tags deferred** — no tag field, UI, or filter this phase. A later pass can add
  them. (Import is manual/descoped, so there's no imported tag data to preserve.)

### Recurrence (the 5 locked patterns, expressed cleanly)
- **D-05:** Recurrence = **cadence** (daily / weekdays / weekly / monthly / every-N-days)
  **+ a per-task anchor toggle**: **"stick to schedule"** (next instance on the fixed
  calendar date — rent on the 1st) vs **"from completion"** (next due counts from when you
  tick it — trash done Thursday → next a week from Thursday, not Monday). The locked TASK-02
  "every-N-days-from-completion" pattern is just the *from-completion* mode of an interval.
  **No RRULE.**
- **D-06:** **Single open instance** per recurring series. Completing an instance generates
  the next per its anchor; a schedule-anchored next that would land in the past **rolls
  forward to the next future occurrence** (never materialize a past-due "next").
- **D-07:** Editing a recurring task offers **"this occurrence only" vs "this and
  following"** (calendar-style). "This & following" edits the recurrence rule; "this only"
  overrides the current instance without touching the rule. (Light to build given the
  single-open-instance model — no separate exceptions store.)

### TickTick migration (import descoped → manual)
- **D-08:** **No automated import script and no reconciliation report.** Amit manually
  re-creates his few open TickTick tasks in the hub. **Descopes TASK-06 + ROADMAP SC-6.**
- **D-09:** **Migration ordering preserved (TickTick stays live until native is proven):**
  build native `TaskStore` + hub task UI + Klaus native tools → Amit manually re-enters
  open tasks → UAT verifies everything works → **then** remove the TickTick tools from
  `core/tools.py` + cancel the TickTick subscription.

### Quick-add (TASK-03)
- **D-10:** Quick-add uses a **client-side deterministic parser (no LLM)**, resolving while
  typing: **NL dates** ("tomorrow", "friday", "next week") **+ Todoist-style tokens** —
  `#list` selects the list, `!1` / `!high` sets priority. No tag token (tags deferred).
  **FAB on phone, keyboard shortcut on desktop.** Unparsed input → defaults to Inbox.

### Surfacing on the hub (TASK-07)
- **D-11:** Due/overdue tasks appear on the **Today timeline as a pinned "Due today" band**
  (date-only tasks grouped there, like all-day events; overdue flagged). Tasks that carry a
  due-*time* may also slot inline at that time.
- **D-12:** The **glance rail counts due-today + overdue** combined, with **overdue
  visually emphasized**.

### Completion, delete, undo
- **D-13:** **Completed tasks are NOT retained.** Completing removes the task from storage;
  the **undo toast (few-second window) is the only recovery**. **No completed view.**
  Revises TASK-04 / SC-4 — only the micro-animation survives. (Implementation: soft-mark
  then hard-delete after the undo window — Claude's discretion on mechanics.)
- **D-14:** **Delete = undo toast, no Trash bin.** Both complete and delete surface a brief
  undo toast; hard removal after the window. No restorable Trash.
- **D-15:** For recurring tasks, completion **generates the next instance, then clears the
  current one**; undo reverses both.

### Klaus tools + autonomous tick (TASK-05)
- **D-16:** Klaus gets a **full native task toolset** in `core/tools.py`: create,
  list/query (by list, date, priority, overdue), complete, reschedule, edit, delete —
  so the UAT "ask Klaus to reschedule it" works and tasks are fully manageable via chat.
  Replaces the TickTick `add_task` / `get_today_tasks` tools (removed per D-09 order).
- **D-17:** **Autonomous tick behavior unchanged** — no new proactive task-nudging. The
  existing Layer-0 overdue gather (`core/autonomous.py::_gather_ticktick_overdue` + the
  `ticktick_overdue` situation key) is **repointed from `ticktick_tool` to `TaskStore`** —
  a pure data-source swap that keeps it working and satisfies TASK-05 ("autonomous Layer-0
  gather reads native overdue tasks"). The tick acts exactly as it does today.

### Ordering / sort
- **D-18:** **Auto-sort, no manual drag-reorder** (no stored position field). List/project
  views get a **sort + group control** (by due date or by priority). **Day-scoped views**
  (Today / a chosen day) **auto-sort by priority.**

### Reminder gap (interim)
- **D-19:** **No exact-time task reminders / OS notifications in Phase 27** — accepted.
  Those arrive in **Phase 29 (Web Push)**, days away; Amit has no upcoming-day tasks, so
  the interim is a non-issue. No stopgap nudging is built (consistent with D-17).

### Claude's Discretion
- Date logic in **Asia/Jerusalem** local time ("today"/"tomorrow"/overdue) — matches
  codebase invariants.
- Optimistic create/edit following Phase 26's chat optimistic-update + react-query pattern,
  with rollback on failure. **Offline task creation deferred (HUBX-05, v2).**
- Plain-text notes; list views refresh-on-focus (react-query); no real-time sync.
- `TaskStore` document/collection shape; the deterministic NL-date library choice
  (e.g. chrono-node); month-end clamping for monthly recurrence (e.g. the 31st in a
  30-day month); exact undo-toast duration; soft-mark→hard-delete mechanics; the
  completion micro-animation specifics (→ `/gsd:ui-phase 27`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements (locked source of truth — with this session's revisions)
- `docs/superpowers/specs/2026-06-13-klaus-hub-design.md` — v5.0 design spec: § Architecture
  (`TaskStore` fields, Klaus tool swap, autonomous Layer-0 extension), § Layout (Tasks tab),
  § Build phases (Phase 2 = Tasks), § Verification (Phase-2 UAT). Where it conflicts with the
  decisions above (lists, completed view, import), **the decisions here win**.
- `.planning/REQUIREMENTS.md` — TASK-01..07 + Out-of-Scope table (no RRULE, no subtasks, no
  nutrition entry). **Revised this session:** TASK-01 (→ user-creatable lists+Inbox, D-02),
  TASK-04 (→ completed view dropped, D-13), TASK-06 (→ manual migration, D-08) — the
  requirements doc should be updated to match.
- `.planning/ROADMAP.md` § Phase 27 — goal + 6 success criteria (SC-4 and SC-6 revised per
  D-13 and D-08).

### Prior-phase context (patterns to follow)
- `.planning/phases/26-hub-shell/26-CONTEXT.md` — Phase 26 decisions: `/api/*` session auth,
  Firestore store + `_jsonsafe_doc` JSON-safety, single-worker, Cloud Tasks full-CPU path,
  optimistic + react-query patterns, glance-rail/timeline structure.

### Backend integration points
- `memory/firestore_db.py` — store-class patterns + `_jsonsafe_doc` (ISO-convert
  `DatetimeWithNanoseconds` before `json.dumps`); add `TaskStore` here.
- `mcp_tools/ticktick_tool.py` — the tool being **removed** (`add_task`, `get_today_tasks`);
  reference for what the native tools replace.
- `core/tools.py` — TickTick tool schemas + `_HANDLERS` dispatch (≈ lines 214–235, 1360);
  swap to native `TaskStore` tools (D-16).
- `core/autonomous.py` — Layer-0 gather `_gather_ticktick_overdue` (≈ line 236) + the
  `ticktick_overdue` situation key threaded through triage/compose; repoint data source to
  `TaskStore` (D-17).
- `interfaces/web_server.py` — FastAPI `/api/*` routes + `require_hub_session`; add task CRUD
  endpoints here without touching existing routes (HUB-04 invariant).

### Frontend integration points
- `frontend/src/App.tsx` — routing; `/tasks` is currently a `ComingSoon` placeholder owned
  by P27.
- `frontend/src/components/layout/{GlanceRail,Sidebar,BottomTabs}.tsx` — glance rail gains
  the due+overdue task count (D-12); Tasks tab nav.
- `frontend/src/components/timeline/TimelineDay.tsx` — add the pinned "Due today" task band
  (D-11).
- `frontend/src/api/*`, `frontend/src/hooks/*` (`useToday`, `useChat`, `api/client.ts`
  `apiFetch`) — react-query data-fetching + optimistic-update pattern to mirror for tasks.

### Project invariants
- `CLAUDE.md` § 6 Invariants — single uvicorn worker, agent turns inside tracked Cloud Tasks
  requests (never Starlette BackgroundTask), lowercase `klaus-` naming,
  `load_dotenv(override=True)`, JSON-safe Firestore reads.
- `.planning/STATE.md` § Notes — Asia/Jerusalem time; Python 3.11/3.13 (NEVER 3.14);
  1153+ test baseline must hold; run pytest per-file (full-suite segfault).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `memory/firestore_db.py` store classes + `_jsonsafe_doc` — model `TaskStore` directly on
  these.
- Phase 26 `/api/*` routes + `require_hub_session` — task CRUD endpoints reuse the same auth.
- `frontend/src/hooks/useToday.ts` / `useChat.ts` + `api/client.ts` (`apiFetch`) —
  react-query + optimistic-update pattern for the new task hooks.
- `frontend/src/components/timeline/TimelineDay.tsx` + `layout/GlanceRail.tsx` — extend for
  the TASK-07 surfacing (pinned band + count).
- `core/tools.py` `_HANDLERS` dispatch + tool-schema convention — native task tools register
  the same way the TickTick ones did.

### Established Patterns
- Firestore `SERVER_TIMESTAMP` reads back as `DatetimeWithNanoseconds` → ISO-convert before
  `json.dumps` in every `/api/*` response (`_jsonsafe_doc`).
- `/api/*` = session-cookie auth (P26); `/cron|/internal` = OIDC — the new routes must not
  weaken the existing OIDC routes.
- Single uvicorn worker, in-process state, SPA served from the same container.
- react-query + zustand on the front; optimistic send with rollback (chat), refresh-on-focus
  (timeline) — reuse for tasks.

### Integration Points
- New `TaskStore` in `memory/firestore_db.py`.
- New task CRUD endpoints under `/api/*` in `interfaces/web_server.py`.
- Native task tools replace TickTick in `core/tools.py`; autonomous gather repointed in
  `core/autonomous.py`.
- `/tasks` route in `frontend/src/App.tsx` (ComingSoon → real Tasks page); glance rail +
  Today timeline gain task surfacing.

</code_context>

<specifics>
## Specific Ideas

- Amit wants a **real task-manager feel** — user-creatable lists/projects + Inbox, a
  sort/group control, and a one-line power-capture (`#list` / `!priority`) — not a minimal
  hardcoded list. This explicitly stretched TASK-01's "fixed set" wording.
- The **trash example** ("done it Thursday, the trash won't be full by Monday") is what
  drove the per-task *from-completion* recurrence anchor (D-05). Fixed-date things (rent)
  use *stick-to-schedule*.
- He **does not review completed tasks** and wants them gone after the undo window — the
  undo toast is the safety net, not a completed archive (D-13/D-14).
- He has **few current TickTick tasks**, so manual migration beats building an importer
  (D-08), and the interim **reminder gap is acceptable** because Phase 29 push is days away
  and he has no upcoming-day tasks (D-19).

</specifics>

<deferred>
## Deferred Ideas

- **Tags** (field + filter UI) — deferred to a later pass (D-04).
- **Automated TickTick import + reconciliation report** (was TASK-06) — descoped; manual
  re-entry instead (D-08). If Amit ever wants the completed archive, a one-off TickTick
  export is the fallback.
- **Manual drag-reorder** of tasks — rejected in favour of auto-sort + a sort/group control
  (D-18).
- **Completed-tasks view / history** — explicitly not retained (D-13).
- **Exact-time task reminders / OS notifications** — Phase 29 (Web Push); no stopgap in P27
  (D-19).
- **Offline task creation (write queue)** — HUBX-01/05, v2.
- **Proactive task-nudging via the autonomous tick** — explicitly not added; tick behavior
  is unchanged beyond the data-source repoint (D-17).
- **Subtasks / hierarchies, complex RRULE recurrence** — milestone-level Out-of-Scope.

</deferred>

---

*Phase: 27-Tasks*
*Context gathered: 2026-06-17*
