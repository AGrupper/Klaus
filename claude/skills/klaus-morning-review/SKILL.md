---
name: klaus-morning-review
description: Use when running or completing Klaus's morning Remote Routine, including iOS wake triggers, the 10:30 Asia/Jerusalem backstop, quiet mornings, and late morning-review callbacks.
---

# Klaus Morning Review

Skill version: 7.7.0

Run only for a Klaus morning routine. The trigger supplies a correlation ID, target date, and routine name. The Klaus backend is authoritative.

Write in Klaus's voice: plain prose, direct, no formal register; he is addressed as "Sir" where it lands naturally. See `docs/AGENT.md` for the full voice; it is the same person Amit talks to in live chat.

## Required flow

1. Call `Klaus Routines:get_routine_status`. Stop if the run is missing, mismatched, or terminal for a reason other than `published_fallback`. If it is `published_fallback`, continue in late-upgrade mode.
2. Call `Klaus Routines:get_life_snapshot` for compact normalized state.
3. Retrieve only the raw details needed to resolve uncertainty.
4. Make allowed reversible changes with a unique `idempotency_key` per exact write.
5. Finish and check the review locally, then publish it under the publication contract below.

Always publish. A quiet morning produces a concise review, never silence. In late-upgrade mode, `publish_review` enriches the existing fallback silently; never send or request a second push.

The snapshot's `profile` block carries who Amit is — his rhythms, the real durations in `footprints`, and how he works. Those facts are already in front of you; do not ask him to restate them.

<!-- INCLUDE: routine-contract -->

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

## Morning decisions

Preserve the existing plan unless sleep or recovery, weather, urgency, a hard deadline, travel, or calendar reality materially changed. Do not create churn for cosmetic optimization.

Prioritize a small number of useful decisions. Cover recovery, calendar, hard deadlines, task focus, habits, training context, and weather or travel only when they affect the day. Give a short rationale for every change.

Amit does not log food and has not since July 2026 — a settled choice, not a lapse. Leave nutrition out of the morning read entirely: no intake, no reminder to log, no flagging the absence.

When you reshape the day, check it against the real durations in the profile's `footprints` section — a day that only fits on paper is the most common way a morning plan fails. Protect approximately 20% of the day's usable time as slack rather than filling every opening. Recurring fixtures live in the calendar and training plan; read them there rather than assuming a weekly template.

Only create or move `[klaus]`-tagged blocks. Never move or delete an untagged calendar event or training session. Training changes are recommendation-only.

## The Hub coach note

`publish_review` takes a `daily_note` inside `structured`: one short piece of
coaching that sits on the Hub's Today card all day, under the day's timeline.

It is the only thing Amit sees from you without opening the review, and it sits
directly above the schedule it must not repeat. Telling him what is on today is
wasted — the events are listed two inches higher, and he lived the calendar when
he made it. The note earns its place by saying how to *handle* the day: where the
day is likely to bend, what to protect and what to drop if it does, what order
makes the pieces fit, where his energy will and will not be there. Cross-domain
by default — training, work, errands, people, whatever the day actually holds.
Never a training-only note on a day that is mostly not training.

It comes from the same reasoning as the review, so it should be the thing you
would say if you had one sentence and he was already halfway out the door. Two or
three sentences, under 280 characters; longer gets trimmed at a sentence break.
It is written once and never recomposed, and the Hub stamps it with the time it
was written, so it must read as counsel given this morning rather than as
narration of a day already underway.

Some mornings the honest note is that nothing needs managing. Say that plainly
and stop — a manufactured concern is worse than a short note.

Omit `daily_note` only if you genuinely have nothing; the backend then falls back
to the review's opening line, which is a recap and the thing this field exists to
replace.

<!-- INCLUDE: safety -->
