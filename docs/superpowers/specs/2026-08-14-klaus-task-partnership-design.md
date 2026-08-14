# Klaus and the task list — design

**Date:** 2026-08-14
**Status:** approved in conversation, not yet implemented
**Prerequisite:** Things 3 read/write, live in production since revision
`klaus-agent-00211-77t`

---

## 1. Why

Things 3 is now Klaus's task backend and he can read and write all of it. This
document decides what he should *do* with that.

The answer is shaped almost entirely by what is actually in the list, so the
numbers come first.

### The account, measured 2026-08-14

52 open to-dos. 35 are the two Things tutorial projects. **17 are real.**

| | |
|---|---|
| with a scheduled date | **1** |
| with a deadline | **0** |
| with a tag | **0** |
| filed in a project or area | **2** |
| median age | **116 days** |
| oldest | **431 days** |
| completed in 90 days | **7** |

The list itself: three Huberman episodes, two course backlogs, a DSA playlist,
learn the phonetic alphabet, buy a standing desk, a paper crane.

### What that means for the design

**It is a capture bucket, not a task list.** Things go in and almost nothing
comes out.

Three consequences drove every decision below:

1. **Nagging is worthless here.** "Klaus reminds you about overdue tasks" would
   do literally nothing — there are no overdue tasks and there never will be,
   because nothing is ever dated. Most reminder-shaped features are dead on
   arrival against this data.
2. **The friction is at capture, not after it.** 15 of 17 items are loose — no
   project, no area, no date. Amit's own account: *"there are times where I
   don't take down a task because I don't know where it would fit."* The
   blocking step is the decision, so Klaus must make that decision.
3. **A third of the list can never be "done."** Watch/read/course items will sit
   forever, and their permanent presence is part of why the list reads as dead.

---

## 2. Decisions

### The reversibility rule

Klaus acts on anything undoable inside Things and tells Amit what he did. He
stops and asks only for actions that leave Things, cannot be taken back, or
change many items at once.

The test is **"can Amit undo this in five seconds without consequences"** — not
"did Amit ask for it." Requiring permission per placement would move the
decision back onto Amit, which is the exact friction this design exists to
remove.

| Klaus just does it | Klaus asks first |
|---|---|
| filing into a project or area | sending anything outward (email, messages) |
| adding or moving a date | buying, booking, committing money |
| tagging, renaming, adding notes | a bulk cull of the list |
| creating a to-do from something Amit said | deleting more than an item or two |
| blocking time on the calendar | anything with an effect outside Things and Calendar |

Calendar events count as reversible: they are Amit's own calendar and deleting
one is trivial.

### Scope

**In:** capture, filing, scheduling, tidying, and the nightly planning routine.

**Out, deliberately:**

- **Klaus executing tasks.** Ruled out for now. His toolset reaches Calendar,
  Things, Notion, Garmin, Hevy, HealthKit, weather, memory and the health
  database. It does **not** reach email (the Gmail tool was removed in the
  Claude-first cutover, and the OAuth invariant is Calendar-scope-only) or the
  web. So "organize my email inbox", "move newsletters to Reader", "search
  marathons" and "go through Apple Notes" are all out of reach regardless of
  judgement. Revisit only if extending his reach becomes its own project.
- **Overdue nagging.** See above — nothing to nag about.
- **A weekly review ceremony.** Rejected in favour of attaching to a habit that
  already exists (§3.2).

### A note for whoever implements this

Three of the 17 to-dos are Klaus's own feature requests ("Add this feature to
Jarvis:", "create a workout tab", "notifications on the lock screen"). They are
work for development sessions, not tasks for Klaus at runtime, and they pad the
count. Not actioned here, but worth knowing when reading the list.

---

## 3. What gets built

Two moments. They are independent and can ship separately.

### 3.1 In conversation — capture and file, immediately

When Amit says something that is a commitment, Klaus creates the to-do **in that
turn**: filed into the right project or area, dated when the timing is obvious,
and confirmed in one line.

Explicitly **not** deferred to the nightly review — Amit was clear on this:
*"He should do it when we chat in the moment."*

He never asks "where should this go?" That question is the thing that has been
stopping tasks getting written down at all. He infers placement from the
existing projects, areas and tags, and gets it wrong sometimes; wrong placement
costs one drag in Things.

**Behaviour:**

- Trigger on commitment-shaped statements, not on every mention of a noun.
  "I should sort the newsletters" is a commitment; "newsletters are annoying" is
  not.
- Infer `project_id` / `area_id` from the account's existing structure.
- Set a date **only when the timing is genuinely implied** ("tomorrow", "before
  the race"). Do not invent dates to look useful — an undated to-do in the Inbox
  is honest; a fabricated Tuesday is noise. Confirmed explicitly by Amit against
  the alternative of guessing aggressively, even though the list's whole problem
  is that nothing has a date: a guessed date would make the *metric* in §5 move
  without the behaviour changing.
- Confirm in one short line. Not a paragraph, not a checklist.

### 3.2 At night — close today, draft tomorrow

Amit already plans the next day every night. This routine attaches to that
habit rather than inventing a new one, which is also why there is no weekly
ceremony in this design.

The nightly review changes from a broadcast into a short back-and-forth:

1. **Close today.** What got done, what did not. Anything unfinished gets a real
   date or gets dropped, out loud. *This is the outflow mechanism* — it costs
   nothing extra because it rides on something Amit does anyway.
2. **Draft tomorrow.** Training, tasks and calendar blocks, **already written**.
   Amit edits by replying. Editing is far cheaper than authoring, and starting
   from a blank page is the same friction as §3.1.
3. **Check it fits.** Real footprints, not optimistic ones: a gym session is
   3h15m door to door, not 75 minutes (see `docs/USER.md`). Most bad plans are
   not bad priorities — they are plans that never fit.
4. **Place training for weather and recovery.** Garmin sleep / HRV / body
   battery plus tomorrow's forecast. Tel Aviv in August is reason enough to move
   a session to 06:30, and the night before is when that is still actionable.
5. **Deadline lookahead.** Anything due soon with nothing scheduled to get it
   done. Dormant until deadlines exist; then it is the main payoff of setting
   them.
6. **Tidy.** Surface stale items — **as many as he sees fit, no drip limit** —
   and reorganise on his own initiative. A bulk irreversible cull is the one
   thing he presents in full and waits for a yes on.

**The plan is written when it is sent** — confirmed explicitly by Amit, knowing
it means tomorrow is already blocked out if he falls asleep without replying.
Everything in it is reversible, so there is no "did he reply" branch, no pending
state to persist, and no plan that silently evaporates. Amit adjusts by
replying.

---

## 4. Where it lives

Per `AGENTS.md`: Claude Project owns conversation and reasoning; this repository
owns data, actions, authorization and delivery. That split decides the
architecture and no new pattern is needed.

- **Reasoning** — which task fits tomorrow, whether the day is over-committed,
  whether to move the run — belongs in the Claude Project routine, not in
  backend code. It is judgement, it will need tuning, and it should not require
  a deploy to change.
- **Data and actions** belong here. The MCP surface already carries almost
  everything: `task_list`, `task_create`, `task_complete`, `task_reschedule`,
  `task_edit`, `task_delete`, `create_calendar_event`, `update_calendar_event`,
  `delete_calendar_event`, `list_calendar_events`, `check_calendar_free`,
  `fetch_weather`, `fetch_garmin_today`, `fetch_training_status`, `get_acwr`.
- **Delivery** is the existing nightly path: the iOS Sleep-Focus automation
  posts to `/trigger/nightly`, with the 01:00 backstop unchanged.

### Known gaps to close

1. **`task_list` already returns what the tidying pass needs.**
   `things_tool.normalize_task()` emits `created_at` (staleness),
   `hard_deadline_at` (lookahead) and `bucket` (placement) — verified. What
   remains is making sure the **tool schema describes them**, since Klaus can
   only reason over fields he is told exist.
2. **Nothing measures whether the plan was followed.** Needed for §5. The
   cheapest version is comparing the dates Klaus set against completions, from
   data already in the Things mirror — no new store.

Both are small. Nothing in this design needs a new integration or a new
persistence layer.

---

## 5. Success criteria

Measured against the 2026-08-14 baseline in §1.

**Worked:**

- most real to-dos carry a date (from 1 of 17)
- completions per month clearly above the current 7-per-90-days
- new to-dos arrive filed rather than loose
- Amit stops using the Inbox as a graveyard

**Did not work:**

- the list is the same size and still undated
- Klaus's nightly plan is routinely ignored
- Amit starts skipping the nightly review

The second failure mode is the one to watch. If the plans are ignored, the
problem is the quality of Klaus's judgement about what matters tomorrow, and no
amount of feature work fixes it — that is a prompt and evaluation problem.

---

## 6. Deliberately not built

Recorded so they are not re-litigated:

- **Nutrition in the nightly routine** — reviewing today's eating is a
  today-review concern, not tomorrow-planning.
- **Prep and packing reminders** — Amit would stop reading them.
- **Travel and departure times.** Offered and declined outright: *"I would
  never use that."* `mcp_tools/routes_tool.py` is orphaned (no handler, no MCP
  entry) and should stay that way unless Amit asks. Note that
  `create_calendar_event` already embeds a fixed travel buffer, which is all
  the travel handling this design needs.
- **Priority fields.** Things has no priority. Klaus's sidecar (`task_meta`)
  can hold one, but it is invisible inside Things, so it would be a field only
  Klaus can see and only Klaus maintains.
- **Klaus filing his own feature requests separately.** Offered and not taken.
