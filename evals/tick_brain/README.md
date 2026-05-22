# Tick-Brain Eval Harness

## Purpose

Score the tick-brain judgment layer (Layer 1 of the autonomous engine) against
labeled `SituationSnapshot` fixtures. The harness measures precision/recall/F1
on the binary `should_speak` decision, plus a per-trigger-type breakdown so the
triage prompt can be tuned for specific failure modes (over-eager on silence,
under-eager on overdue, etc.).

This directory ships with **5 hand-written seed fixtures** so
`scripts/eval_tick_brain.py` (Plan 08) has something to run on day one. The
eval set grows retroactively from real `tick_logs` Firestore docs — see the
workflow below.

Requirement: **AUTO-08** (20–30 labeled fixtures, judgment scored on precision /
recall / F1).

## Fixture Schema

Each fixture is a single JSON file: `evals/tick_brain/fixtures/NNNN-slug.json`.

Top-level keys (required):

- `id` (string) — matches the filename stem
- `captured_at` (string, ISO-8601) — when the snapshot was captured (or a
  synthetic timestamp for seeds)
- `situation_snapshot` (object) — the same shape `core/autonomous.py:gather_situation`
  produces:
  - `calendar` (list of `{summary, start, end}` objects)
  - `ticktick_overdue` (list of `{id, title, due_at}` objects)
  - `unread_email_count` (int)
  - `due_followups` (list of `{id, due_at, note, defer_count}` objects)
  - `hours_since_contact` (float | null) — null means "unknown / never contacted"
  - `recent_journal_digest` (string) — last ~3 entries condensed
  - `self_state` (object with `current_focus`, `mood`)
  - `today_outreach_log` (list of `topic_key` strings already raised today)
  - `now_context` (object with `now_iso`, `now_local`, `tick_index`,
    `tick_total`, `last_tick_at`)
- `trigger_type` (string) — one of: `overdue`, `gap`, `silence`, `followup`,
  `quiet`
- `ground_truth` (object):
  - `should_speak` (bool) — **measured against tick-brain (Layer 1) ONLY**, NOT
    against the autonomous orchestrator as a whole (see next section)
  - `topic_key_pattern` (string, regex) — pattern the predicted `topic_key`
    should match (omit if `should_speak: false`)
  - `_note` (string, optional) — labeler's notes; never read by the eval

## What `should_speak` Means (WARNING 8 — important)

`ground_truth.should_speak` is the expected behavior of **tick-brain (Layer 1)**
on this snapshot, NOT the expected behavior of the autonomous orchestrator as a
whole. The orchestrator routes certain situations around tick-brain entirely:

- **Due follow-ups (D-13):** `_compose_followup` is a dedicated Layer-2 path.
  The autonomous orchestrator runs followups BEFORE tick-brain triage and does
  not re-feed them. Therefore a due-followup-only snapshot reaches tick-brain
  with the followup already handled — tick-brain's expected behavior is
  silence (no additional escalation).

- **Empty signals (D-11):** Layer 0 gates skip tick-brain when no overdue, no
  followups, and no calendar gap/overload. These are scored as `errored` by
  the eval if tick-brain never runs, OR as `should_speak=false` if you want to
  test tick-brain's behavior on a quiet snapshot fed directly to it (which is
  what fixture `0002-quiet-evening.json` does).

Consequence: fixture `0003-due-followup.json` has
`ground_truth.should_speak=false`. Tick-brain should NOT also escalate when a
followup is already firing — that would produce two Telegram messages on the
same tick. Don't "fix" this to true. A regression test
(`tests/test_evals.py::TestFixtureSchema::test_followup_only_fixture_expects_silence`)
guards against this.

## Retroactive Labeling Workflow

Every live tick writes to `tick_logs/{YYYY-MM-DD}/ticks/{HH:MM}` in Firestore
(see `core/autonomous.py`, produced by Plan 06). To grow the eval set from real
ticks:

1. Export interesting `tick_logs` docs from Firestore. Either:
   - `gcloud firestore export gs://<bucket>/<prefix> --collection-ids=tick_logs`
     (managed export), or
   - The `firestore-export` CLI (documented in `docs/DEPLOYMENT.md`).
2. Inspect candidates — look for ticks with a clear ground-truth where you
   (a) know in hindsight whether Klaus should have spoken and (b) the input
   snapshot is realistic / not a degenerate edge case.
3. Copy the `situation_snapshot` block out of the exported tick log into a new
   fixture file `evals/tick_brain/fixtures/NNNN-slug.json` with the next
   available `NNNN`.
4. Fill in:
   - `id` to match the filename stem
   - `captured_at` from the original tick's `now_context.now_iso`
   - `trigger_type` based on which signal dominated
   - `ground_truth.should_speak` based on your hindsight judgment
   - `ground_truth.topic_key_pattern` (regex, only if `should_speak=true`)
   - `_note` if anything subtle deserves explanation for future labelers
5. **Re-read the "What should_speak Means" section above before labeling
   followup or empty-signal cases.** It's the easy place to mislabel.
6. Run `python scripts/eval_tick_brain.py` to confirm the new fixture loads
   and the eval still passes (or fails informatively).
7. Run `pytest tests/test_evals.py -v` to confirm the new fixture passes the
   schema-validation tests.

Target: **20–30 fixtures within 2 weeks of Phase 18 ship** per AUTO-08.

## Running the Eval

```
python scripts/eval_tick_brain.py
```

Output: overall precision/recall/F1 + per-trigger-type breakdown table. See
`scripts/eval_tick_brain.py` (Plan 08) for the full output spec.

## Fixture Inventory (seeds)

| File                          | Trigger  | should_speak | Notes                                                  |
| ----------------------------- | -------- | ------------ | ------------------------------------------------------ |
| 0001-overdue-task.json        | overdue  | true         | Obvious positive — overdue TickTick task               |
| 0002-quiet-evening.json       | quiet    | false        | Obvious negative — nothing salient                     |
| 0003-due-followup.json        | followup | false        | WARNING 8 — followup path bypasses tick-brain          |
| 0004-long-silence.json        | silence  | true         | 11.5h since contact, deep-work day past dinner         |
| 0005-calendar-gap.json        | gap      | true         | Workout overlaps client call — schedule conflict       |
