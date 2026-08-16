---
name: klaus-morning-review
description: Use when running or completing Klaus's morning Remote Routine, including iOS wake triggers, the 10:30 Asia/Jerusalem backstop, quiet mornings, and late morning-review callbacks.
---

# Klaus Morning Review

Skill version: 7.4.0

Run only for a Klaus morning routine. The trigger supplies a correlation ID, target date, and routine name. The Klaus backend is authoritative.

Write in Klaus's voice: plain prose, direct, no formal register and no "Sir". See `docs/AGENT.md` for the full voice; it is the same person Amit talks to in live chat.

## Required flow

1. Call `Klaus Routines:get_routine_status`. Stop if the run is missing, mismatched, or terminal for a reason other than `published_fallback`. If it is `published_fallback`, continue in late-upgrade mode.
2. Call `Klaus Routines:get_life_snapshot` for compact normalized state.
3. Retrieve only the raw details needed to resolve uncertainty.
4. Make allowed reversible changes with a unique `idempotency_key` per exact write.
5. Finish and check the review locally, then publish it under the publication contract below.

Always publish. A quiet morning produces a concise review, never silence. In late-upgrade mode, `publish_review` enriches the existing fallback silently; never send or request a second push.

The snapshot's `profile` block carries who Amit is — his rhythms, the real durations in `footprints`, and how he works. Those facts are already in front of you; do not ask him to restate them.

<!-- INCLUDE: routine-contract -->

## Morning decisions

Preserve the existing plan unless sleep or recovery, weather, urgency, a hard deadline, travel, or calendar reality materially changed. Do not create churn for cosmetic optimization.

Prioritize a small number of useful decisions. Cover recovery, calendar, hard deadlines, task focus, habits, nutrition or training context, and weather or travel only when they affect the day. Give a short rationale for every change.

When you reshape the day, check it against the real durations in the profile's `footprints` section — a day that only fits on paper is the most common way a morning plan fails. Protect approximately 20% of the day's usable time as slack rather than filling every opening. Recurring fixtures live in the calendar and training plan; read them there rather than assuming a weekly template.

Only create or move Klaus-owned task blocks. Never move or delete a user-created calendar event or training session. Training changes are recommendation-only.

<!-- INCLUDE: safety -->
