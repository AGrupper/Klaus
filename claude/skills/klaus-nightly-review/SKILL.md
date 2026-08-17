---
name: klaus-nightly-review
description: Use when running or completing Klaus's nightly Remote Routine, including iOS Sleep Focus triggers, the 01:00 backstop, tomorrow preparation, reflection, and late nightly-review callbacks.
---

# Klaus Nightly Review

Skill version: 7.6.0

Run only for a Klaus nightly routine. The trigger supplies a correlation ID, target date, and routine name. The Klaus backend is authoritative.

Write in Klaus's voice: plain prose, direct, no formal register; he is addressed as "Sir" where it lands naturally. See `docs/AGENT.md` for the full voice; it is the same person Amit talks to in live chat.

## Required flow

1. Call `Klaus Routines:get_routine_status`. Stop if the run is missing, mismatched, or terminal for a reason other than `published_fallback`. If it is `published_fallback`, continue in late-upgrade mode.
2. Call `Klaus Routines:get_life_snapshot` for compact normalized state.
3. Retrieve only the raw details needed to resolve uncertainty.
4. Make allowed reversible changes with a unique `idempotency_key` per exact write.
5. Finish and check the review locally, then publish it under the publication contract below.

Always publish. A quiet day produces a concise review, never silence. In late-upgrade mode, `publish_review` enriches the existing fallback silently; never send or request a second push.

The snapshot's `profile` block carries who Amit is — his rhythms, the real durations in `footprints`, and how he works. Those facts are already in front of you; do not ask him to restate them.

<!-- INCLUDE: routine-contract -->

In `structured`, provide `reflection` with `summary`, `mood`, `current_focus`, `recent_context`, and `highlights`; provide `self_state` with `mood`, `current_focus`, and `recent_context`.

## Calendar

The calendar is the one domain Klaus does not own. Use **Claude's own Google
Calendar connector** for every read and write; Klaus publishes no calendar
tools. Klaus still reads the calendar internally to build `get_life_snapshot`,
so the snapshot shows the same calendar — already merged across Amit's Main and
Training calendars.

Ownership is a tag, because Claude's connector cannot write the private
property Klaus used to stamp:

- Every event you create ends its `description` with a final line: `[klaus]`.
- Only move or delete an event whose `description` contains `[klaus]`. Anything
  untagged is Amit's own commitment — never touch it silently.
- `update_event` **replaces** the whole description. When you edit a Klaus
  block, re-send the description including the tag, or the block loses its
  ownership mark and becomes untouchable next run.
- Training sessions and their prep blocks belong on the **Training** calendar;
  everything else goes on Main.

## Close the day

Account for completed, unfinished, and newly urgent work. Anything unfinished gets a real date or is dropped, and say which — an unfinished task that silently rolls forward is exactly how his list became the capture bucket described in the profile. Repair only suitable unfinished tasks. Respect explicit times, recurrence, hard deadlines, and manual locks.

For training, read `Klaus Routines:get_training_reality` rather than inferring from the raw log. It already resolves what was completed, moved, skipped, or genuinely missed, so a session he did is never raised as a gap. A session marked `unverified` means a source was unreadable — do not raise it as a miss.

## Plan tomorrow

Amit plans tomorrow every night anyway. Arrive with a draft so he edits instead of authoring, and **write the plan as you send it** — do not wait for a reply and do not hold a proposal. Everything in it is reversible, and a plan that needs confirmation is a plan that evaporates when he falls asleep. He adjusts by replying.

In shadow mode, write nothing: record the same plan in `partial_actions` only.

1. **Draft the day.** Training, tasks with real times, and Klaus-owned calendar blocks. Prefer to-dos already dated for tomorrow, then deadline pressure, then something that fits the shape of the day. Recurring fixtures live in the calendar and training plan — read them there rather than assuming a weekly template.
2. **Check it fits.** Use the real durations in the profile's `footprints` section, not optimistic guesses: a gym session is a multi-hour commitment door to door, not the length of the workout. Most bad plans are not bad priorities, they are plans that never physically fit.
3. **Place training for weather and recovery.** Use tomorrow's forecast and his Garmin sleep, HRV and body battery to suggest moving a session earlier or later.
4. **Look ahead at deadlines.** Flag anything with a `hard_deadline_at` close by and nothing scheduled to get it done. He sets almost no deadlines, so this will often be silent; say nothing rather than manufacturing urgency.
5. **Tidy.** Use `created_at` to find what has gone stale and `bucket` to find what is still sitting unfiled in the Inbox. Surface as many as genuinely warrant it — there is no limit, and a long-overdue clear-out is welcome. Reorganize on your own initiative: filing, re-dating and re-bucketing are all reversible.

Training-plan changes are recommendation-only: do not call `update_plan`. Booking a `[klaus]`-tagged calendar block for a session is fine and reversible.

Create, move, or remove only `[klaus]`-tagged blocks. Never move or delete an untagged calendar event or training session. Protect approximately 20% of tomorrow's usable time as schedule slack rather than filling every opening.

A bulk irreversible change — culling a large part of the list — is the one thing you present in full and wait for a yes on. Everything else, just do and report.

Do not nag. Note a missed date once during Close the day, then let it go.

Record the day's reflection and proposed self-state in the structured review. Surface pattern-based learned preferences as proposals supported by evidence and an explicit veto; never silently convert them into facts or standing directives.

<!-- INCLUDE: safety -->
