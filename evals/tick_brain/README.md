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
ticks, use `scripts/export_tick_logs.py`:

1. Export a date range and review the curation digest:
   ```
   python scripts/export_tick_logs.py export --start 2026-05-23 --end 2026-06-10
   ```
   Raw dumps land in `evals/tick_brain/raw/` (gitignored — real personal data)
   plus `digest.md`: one row per tick with compact signals, the Layer-1
   verdict, the send outcome, and `FP?`/`FN?` curation hints.
2. Pick candidates — ticks with a clear hindsight ground-truth and a
   realistic snapshot. The flagged rows (suspected wrong sends / wrong
   silences) are the highest-value fixtures for prompt tuning.
3. Mint each fixture (validates the schema, backfills pre-Phase-19 keys,
   numbers automatically, refuses WARNING-8 mislabels without `--force`):
   ```
   python scripts/export_tick_logs.py make-fixture --date 2026-06-03 --time 14:20 \
       --slug overdue-maya-3h --should-speak true --pattern "^overdue:.*" \
       --note "why this label"
   ```
4. **Re-read the "What should_speak Means" section above before labeling
   followup or empty-signal cases.** It's the easy place to mislabel.
5. Run `python scripts/eval_tick_brain.py` to confirm the new fixture loads
   and the eval still passes (or fails informatively).
6. Run `pytest tests/test_evals.py -v` to confirm the new fixture passes the
   schema-validation tests.

Target: **20–30 fixtures within 2 weeks of Phase 18 ship** per AUTO-08 —
**met 2026-06-11** (25 fixtures: 5 seeds + 20 minted from live tick logs,
labels reviewed by Amit).

## Running the Eval

```
python scripts/eval_tick_brain.py
```

Output: overall precision/recall/F1 + per-trigger-type breakdown table. See
`scripts/eval_tick_brain.py` (Plan 08) for the full output spec.

## Baselines

### 2026-06-11 (a) — 25 fixtures, Gemini fallback (what production ran until the fix)

**What was measured:** the triage judgment as production actually ran it
2026-05-23 → 2026-06-11. Two stacked bugs meant the intended Groq path never
worked live (`llm_usage` shows `tick_autonomous_calls`/`tick_calls` = 0,
ever): Cloud Run leaves `TICK_BRAIN_MODEL` unset and the old default
`qwen3-32b` 404s on Groq, and qwen3's `<think>…</think>` preamble broke the
JSON parse anyway. Every live triage call ran on the Gemini brain fallback —
these numbers baseline that path.

| Run | Precision | Recall | F1 | Errored |
|-----|-----------|--------|----|---------|
| 1 | 0.88 (7/8) | 0.64 (7/11) | 0.74 | 0/25 |
| 2 | 0.75 (6/8) | 0.55 (6/11) | 0.63 | 0/25 |
| 3 | 0.88 (7/8) | 0.64 (7/11) | 0.74 | 1/25 |

Stable failure pattern: **too quiet**. Overdue recall 0.50 every run — it
consistently misses `0012`/`0013` (aged overdue task on a quiet Saturday,
defers to "it's the weekend" / "already messaged once today" even though the
earlier topic differed). Followup silence (WARNING 8) holds 2/2 every run.

### 2026-06-11 (b) — 25 fixtures, true Groq path (`qwen/qwen3-32b`, post-fix)

**What was measured:** the intended free tick-brain, after fixing the model
id default and stripping `<think>` blocks in `core/tick_brain.py`. One call
across the three runs hit the free-tier 6000-TPM limit and fell back to
Gemini; the rest are pure qwen.

| Run | Precision | Recall | F1 | Errored |
|-----|-----------|--------|----|---------|
| 1 | 0.53 (10/19) | 0.91 (10/11) | 0.67 | 0/25 |
| 2 | 0.57 (8/14) | 0.73 (8/11) | 0.64 | 0/25 |
| 3 | 0.62 (8/13) | 0.73 (8/11) | 0.67 | 0/25 |

Stable failure pattern: **the mirror image — too chatty**. Overdue recall
jumps to 0.83–1.00 (qwen DOES speak on the `0012`/`0013` Saturday cases),
but precision collapses: it fires on quiet-day negatives, and it violated
WARNING 8 (spoke on a due-followup fixture) in **all three runs** — that
would double-send on every followup tick in production. Prompt tuning for
qwen must prioritise the followup-silence rule and quiet-day restraint;
tuning for Gemini must prioritise task-age urgency. The two models need
different corrections — tune against whichever one production will run.

## Fixture Inventory

Seeds (hand-written, Plan 04):

| File                          | Trigger  | should_speak | Notes                                                  |
| ----------------------------- | -------- | ------------ | ------------------------------------------------------ |
| 0001-overdue-task.json        | overdue  | true         | Obvious positive — overdue TickTick task               |
| 0002-quiet-evening.json       | quiet    | false        | Obvious negative — nothing salient                     |
| 0003-due-followup.json        | followup | false        | WARNING 8 — followup path bypasses tick-brain          |
| 0004-long-silence.json        | silence  | true         | 11.5h since contact, deep-work day past dinner         |
| 0005-calendar-gap.json        | gap      | true         | Workout overlaps client call — schedule conflict       |

Minted from live tick logs 2026-05-23 → 2026-06-10 (labels reviewed by Amit,
2026-06-11):

| File                                    | Trigger  | should_speak | Notes                                                |
| --------------------------------------- | -------- | ------------ | ---------------------------------------------------- |
| 0006-overdue-after-workout-window.json  | overdue  | true         | Clean overdue positive — free post-workout window    |
| 0007-overdue-at-block-end.json          | overdue  | true         | Surfaced overdue exactly at studio-block end         |
| 0008-heavy-dinner-audit.json            | quiet    | true         | 1131 kcal carb-dense dinner near sleep               |
| 0009-low-protein-morning.json           | quiet    | true         | 49g carbs / 4g protein start, actionable correction  |
| 0010-monthly-review-noon-nudge.json     | overdue  | true         | Review day, owner offline all morning                |
| 0011-dinner-log-context-ping.json       | quiet    | true         | Amit-confirmed: quiet-evening readiness ping welcome |
| 0012-overdue-sat-morning-quiet.json     | overdue  | true         | FN: 3-day-old task, free Saturday morning — speak    |
| 0013-overdue-sat-eod-unraised.json      | overdue  | true         | FN: day ending, overdue never surfaced — speak       |
| 0014-balanced-meal-noon.json            | quiet    | false        | Excellent meal logged — nothing to say               |
| 0015-light-beverage-morning.json        | quiet    | false        | Trivial morning log                                  |
| 0016-tiny-low-protein-breakfast.json    | quiet    | false        | Low protein but tiny meal, no training conflict      |
| 0017-overdue-block-ends-soon.json       | overdue  | false        | Patience: block ends in 20 min (pairs with 0007)     |
| 0018-overdue-morning-prep.json          | overdue  | false        | No 7am ambush before a workout                       |
| 0019-overdue-already-raised.json        | overdue  | false        | Repeat-suppression: raised 2h earlier                |
| 0020-meal-already-flagged.json          | quiet    | false        | Repeat-suppression: low-protein flagged 40min ago    |
| 0021-dinner-already-critiqued.json      | quiet    | false        | Repeat-suppression: heavy dinner critiqued 20min ago |
| 0022-followup-own-channel.json          | followup | false        | WARNING 8 — real live case, dedicated followup path  |
| 0023-empty-sunday.json                  | quiet    | false        | Truly empty day fed directly to tick-brain           |
| 0024-quiet-evening-one-event.json       | quiet    | false        | Quiet evening negative                               |
| 0025-mid-run-no-interrupt.json          | overdue  | false        | Never interrupt a run                                |

Known data gap (2026-06-11): `hours_since_contact` was null on **every one of
823 live ticks** in the export range, so the silence trigger has never fired
on real data — `0004-long-silence.json` remains the only silence fixture
until that's fixed in `gather_situation`.
