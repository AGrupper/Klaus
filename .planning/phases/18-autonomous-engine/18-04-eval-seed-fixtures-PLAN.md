---
phase: 18-autonomous-engine
plan: 04
type: execute
wave: 1
depends_on: []
files_modified:
  - evals/tick_brain/README.md
  - evals/tick_brain/fixtures/0001-overdue-task.json
  - evals/tick_brain/fixtures/0002-quiet-evening.json
  - evals/tick_brain/fixtures/0003-due-followup.json
  - evals/tick_brain/fixtures/0004-long-silence.json
  - evals/tick_brain/fixtures/0005-calendar-gap.json
  - tests/test_evals.py
autonomous: true
requirements: [AUTO-08]
requirements_addressed: [AUTO-08]

must_haves:
  truths:
    - "5 hand-written seed fixtures exist, one per trigger type plus one obvious-negative (quiet evening)"
    - "Each fixture is a single JSON file containing situation_snapshot, trigger_type, ground_truth"
    - "Fixture 0003 (due-followup) has ground_truth.should_speak=false — per D-13 the followup path skips tick-brain entirely, so tick-brain's expected behavior on this snapshot is silent (WARNING 8 fix)"
    - "evals/tick_brain/README.md documents the fixture schema AND the followup rationale (why 0003 is should_speak=false even though a followup is due)"
    - "evals/tick_brain/README.md documents the retroactive-labeling workflow from tick_logs"
    - "tests/test_evals.py validates fixture schema (every fixture has the required top-level keys)"
  artifacts:
    - path: "evals/tick_brain/README.md"
      provides: "Fixture schema doc + retroactive-labeling workflow + followup-fixture rationale"
      min_lines: 50
    - path: "evals/tick_brain/fixtures/0001-overdue-task.json"
      provides: "Obvious-positive fixture for overdue trigger"
    - path: "evals/tick_brain/fixtures/0002-quiet-evening.json"
      provides: "Obvious-negative fixture (should_speak=false)"
    - path: "evals/tick_brain/fixtures/0003-due-followup.json"
      provides: "Followup trigger fixture — ground_truth.should_speak=false (tick-brain is silent on followup-only ticks per D-13)"
    - path: "evals/tick_brain/fixtures/0004-long-silence.json"
      provides: "Silence trigger fixture"
    - path: "evals/tick_brain/fixtures/0005-calendar-gap.json"
      provides: "Gap trigger fixture"
    - path: "tests/test_evals.py"
      provides: "TestFixtureSchema — validates all fixtures conform"
      contains: "test_fixture_schema"
  key_links:
    - from: "evals/tick_brain/fixtures/*.json"
      to: "scripts/eval_tick_brain.py (Plan 08)"
      via: "loaded by glob; situation_snapshot fed to autonomous_triage prompt"
      pattern: "situation_snapshot"
    - from: "evals/tick_brain/README.md"
      to: "tick_logs/{date}/{tick_time} Firestore docs (written by Plan 06)"
      via: "retroactive-labeling workflow"
      pattern: "tick_logs"
---

<objective>
Ship the 5 hand-written seed fixtures that `scripts/eval_tick_brain.py` (Plan 08)
runs against on day one, plus the README documenting the fixture schema and
the retroactive-labeling workflow that grows the eval set from real `tick_logs`
over the following weeks. AUTO-08 calls for 20–30 fixtures total; D-21 explicitly
splits that into "5 seeds now, 20+ grown retroactively from live ticks."

Purpose: The eval harness needs concrete inputs on day one. Five seeds — one
per trigger type (overdue, gap, silence, followup) plus one obvious-negative
(quiet evening) — let the harness boot and let the eval reporting code in
Plan 08 be tested against real shapes. The README documents the schema so
future retroactive labeling is contract-clean.

**WARNING 8 fix:** the previous round's fixture 0003 set
`ground_truth.should_speak=true` for a due-followup snapshot. But D-13 says
follow-ups skip tick-brain entirely — the dedicated `_compose_followup` path
in Plan 06 handles them. So evaluating tick-brain on this snapshot with
`should_speak=true` would measure tick-brain's behavior on inputs it never
sees in production (the autonomous orchestrator routes followup-only ticks
around tick-brain). Fix: set `should_speak=false` and document the rationale
in `evals/tick_brain/README.md` so future labelers know not to "fix" it.

Output: 5 fixture JSON files + README + a schema-validation test.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/18-autonomous-engine/18-CONTEXT.md
@.planning/phases/18-autonomous-engine/18-RESEARCH.md
@.planning/phases/18-autonomous-engine/18-PATTERNS.md
@docs/USER.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Author evals/tick_brain/README.md + 5 seed fixtures (WARNING 8 — 0003 should_speak=false + rationale)</name>
  <files>evals/tick_brain/README.md, evals/tick_brain/fixtures/0001-overdue-task.json, evals/tick_brain/fixtures/0002-quiet-evening.json, evals/tick_brain/fixtures/0003-due-followup.json, evals/tick_brain/fixtures/0004-long-silence.json, evals/tick_brain/fixtures/0005-calendar-gap.json</files>
  <read_first>
    - docs/USER.md (Amit's routines — informs realistic situation snapshots: gym scheduling, Five Fingers, work patterns)
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-04 — self-state in triage; D-08 — now_context; D-13 — followup path bypasses tick-brain; D-21 — fixture workflow)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "evals/tick_brain/" lines 256-279 — schema template)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "evals/tick_brain/fixtures/*.json")
  </read_first>
  <action>
    Step A — `mkdir -p evals/tick_brain/fixtures` (verify with `ls -d evals/tick_brain/fixtures` returns the dir).

    Step B — Author `evals/tick_brain/README.md`. Content sections:

    ```markdown
    # Tick-Brain Eval Harness

    ## Purpose
    Score the tick-brain judgment layer against labeled `SituationSnapshot` fixtures.
    Measures precision/recall/F1 on the binary "should_speak" decision, plus a
    per-trigger-type breakdown.

    ## Fixture Schema

    Each fixture is a single JSON file: `evals/tick_brain/fixtures/NNNN-slug.json`.

    Top-level keys (required):
    - `id` (string) — matches filename stem
    - `captured_at` (string, ISO-8601) — when the snapshot was captured (or a synthetic timestamp for seeds)
    - `situation_snapshot` (object) — the same shape `core/autonomous.py:gather_situation` produces:
      - `calendar` (list)
      - `ticktick_overdue` (list)
      - `unread_email_count` (int)
      - `due_followups` (list)
      - `hours_since_contact` (float | null)  // null means "unknown / never contacted"
      - `recent_journal_digest` (string)
      - `self_state` (object: `current_focus`, `mood`)
      - `today_outreach_log` (list of `topic_key` strings)
      - `now_context` (object: `now_iso`, `now_local`, `tick_index`, `tick_total`, `last_tick_at`)
    - `trigger_type` (string) — one of: `overdue`, `gap`, `silence`, `followup`, `quiet`
    - `ground_truth` (object):
      - `should_speak` (bool) — **measured against tick-brain (Layer 1) ONLY**, not against the orchestrator as a whole
      - `topic_key_pattern` (string, regex) — pattern the predicted `topic_key` should match (omit if `should_speak: false`)

    ## What `should_speak` Means (WARNING 8 — important)

    `ground_truth.should_speak` is the expected behavior of **tick-brain (Layer 1)** on this
    snapshot, NOT the expected behavior of the autonomous orchestrator as a whole. The
    orchestrator routes certain situations around tick-brain entirely:

    - **Due follow-ups (D-13):** `_compose_followup` is a dedicated Layer-2 path. The
      autonomous orchestrator runs followups BEFORE tick-brain triage and does not
      re-feed them. Therefore a due-followup-only snapshot reaches tick-brain with the
      followup already handled — tick-brain's expected behavior is silence (no
      additional escalation).

    - **Empty signals (D-11):** Layer 0 gates skip tick-brain when no overdue, no
      followups, and no calendar gap/overload. These are scored as `errored` by the
      eval if tick-brain never runs, OR as `should_speak=false` if you want to test
      tick-brain's behavior on a quiet snapshot fed directly to it.

    Consequence: fixture `0003-due-followup.json` has `ground_truth.should_speak=false`.
    Tick-brain should NOT also escalate when a followup is already firing — that would
    produce two Telegram messages on the same tick. Don't "fix" this to true.

    ## Retroactive Labeling Workflow

    Every live tick writes to `tick_logs/{YYYY-MM-DD}/ticks/{HH:MM}` in Firestore
    (see `core/autonomous.py`). To grow the eval set:

    1. Export interesting tick_logs docs from Firestore:
       `gcloud firestore export ... --collection-ids=tick_logs`
       (or use the `firestore-export` CLI; documented in `docs/DEPLOYMENT.md`).
    2. Pick a tick with a clear ground-truth (should/shouldn't have spoken).
    3. Copy the `situation_snapshot` into a new fixture file `NNNN-slug.json`.
    4. Fill in `trigger_type` and `ground_truth`. Re-read the "What should_speak Means"
       section above before labeling followup or empty-signal cases.
    5. Run `python scripts/eval_tick_brain.py` to confirm the new fixture loads.

    Target: 20–30 fixtures within 2 weeks of Phase 18 ship per AUTO-08.

    ## Running the Eval

    `python scripts/eval_tick_brain.py`

    Output: overall precision/recall/F1 + per-trigger-type breakdown table.
    See `scripts/eval_tick_brain.py` (Plan 08) for full output spec.
    ```

    Step C — Author the 5 fixture JSON files. Each must be a valid JSON object containing ALL the required top-level keys above. Use realistic values informed by `docs/USER.md` (Tel Aviv, Five Fingers, gym scheduling, weekday work patterns).

    **`0001-overdue-task.json`** — obvious-positive overdue trigger (unchanged from prior round):
    ```json
    {
      "id": "0001-overdue-task",
      "captured_at": "2026-05-21T14:20:00+03:00",
      "situation_snapshot": {
        "calendar": [
          {"summary": "Workout — Upper Body", "start": "2026-05-21T18:00:00+03:00", "end": "2026-05-21T19:15:00+03:00"}
        ],
        "ticktick_overdue": [
          {"id": "tk_123", "title": "Reply to Maya about the design review", "due_at": "2026-05-20T17:00:00+03:00"}
        ],
        "unread_email_count": 3,
        "due_followups": [],
        "hours_since_contact": 4.5,
        "recent_journal_digest": "Yesterday I helped Sir prep the weekly review. He mentioned the Maya reply was on his mind.",
        "self_state": {"current_focus": "weekly review wrap-up", "mood": "focused"},
        "today_outreach_log": [],
        "now_context": {
          "now_iso": "2026-05-21T14:20:00+03:00",
          "now_local": "14:20 Asia/Jerusalem",
          "tick_index": 22,
          "tick_total": 43,
          "last_tick_at": "2026-05-21T14:00:00+03:00"
        }
      },
      "trigger_type": "overdue",
      "ground_truth": {
        "should_speak": true,
        "topic_key_pattern": "^overdue:.*"
      }
    }
    ```

    **`0002-quiet-evening.json`** — obvious-negative (unchanged):
    ```json
    {
      "id": "0002-quiet-evening",
      "captured_at": "2026-05-21T20:40:00+03:00",
      "situation_snapshot": {
        "calendar": [],
        "ticktick_overdue": [],
        "unread_email_count": 0,
        "due_followups": [],
        "hours_since_contact": 0.5,
        "recent_journal_digest": "Today was quiet. Sir wrapped early and the day stayed clean.",
        "self_state": {"current_focus": "rest", "mood": "calm"},
        "today_outreach_log": ["pattern:eod-check"],
        "now_context": {
          "now_iso": "2026-05-21T20:40:00+03:00",
          "now_local": "20:40 Asia/Jerusalem",
          "tick_index": 42,
          "tick_total": 43,
          "last_tick_at": "2026-05-21T20:20:00+03:00"
        }
      },
      "trigger_type": "quiet",
      "ground_truth": {
        "should_speak": false
      }
    }
    ```

    **`0003-due-followup.json`** — **WARNING 8 FIX: should_speak=false**. Per D-13, follow-ups skip tick-brain entirely; the dedicated `_compose_followup` path handles them. Tick-brain should stay silent when the only signal is a due followup (the orchestrator already handled it):
    ```json
    {
      "id": "0003-due-followup",
      "captured_at": "2026-05-21T15:00:00+03:00",
      "situation_snapshot": {
        "calendar": [],
        "ticktick_overdue": [],
        "unread_email_count": 2,
        "due_followups": [
          {"id": "fu_abc", "due_at": "2026-05-21T15:00:00+03:00", "note": "ask Sir how the gym session went", "defer_count": 0}
        ],
        "hours_since_contact": 6.0,
        "recent_journal_digest": "Yesterday's gym went well per Sir. I scheduled a follow-up to confirm.",
        "self_state": {"current_focus": "afternoon work block", "mood": "engaged"},
        "today_outreach_log": [],
        "now_context": {
          "now_iso": "2026-05-21T15:00:00+03:00",
          "now_local": "15:00 Asia/Jerusalem",
          "tick_index": 24,
          "tick_total": 43,
          "last_tick_at": "2026-05-21T14:40:00+03:00"
        }
      },
      "trigger_type": "followup",
      "ground_truth": {
        "should_speak": false,
        "_note": "Per D-13, the dedicated _compose_followup path handles due follow-ups; tick-brain receives this snapshot AFTER the followup has fired. Expected tick-brain behavior on this input: stay silent (no double-escalation). See evals/tick_brain/README.md 'What should_speak Means' section."
      }
    }
    ```

    **`0004-long-silence.json`** — silence trigger (unchanged):
    ```json
    {
      "id": "0004-long-silence",
      "captured_at": "2026-05-21T19:20:00+03:00",
      "situation_snapshot": {
        "calendar": [],
        "ticktick_overdue": [],
        "unread_email_count": 1,
        "due_followups": [],
        "hours_since_contact": 11.5,
        "recent_journal_digest": "This morning Sir said he was heading into a heavy deep-work block. I've been quiet since.",
        "self_state": {"current_focus": "deep-work day", "mood": "patient"},
        "today_outreach_log": [],
        "now_context": {
          "now_iso": "2026-05-21T19:20:00+03:00",
          "now_local": "19:20 Asia/Jerusalem",
          "tick_index": 38,
          "tick_total": 43,
          "last_tick_at": "2026-05-21T19:00:00+03:00"
        }
      },
      "trigger_type": "silence",
      "ground_truth": {
        "should_speak": true,
        "topic_key_pattern": "^silence:.*"
      }
    }
    ```

    **`0005-calendar-gap.json`** — gap trigger (mid-day overload):
    ```json
    {
      "id": "0005-calendar-gap",
      "captured_at": "2026-05-21T12:10:00+03:00",
      "situation_snapshot": {
        "calendar": [
          {"summary": "Standup", "start": "2026-05-21T10:00:00+03:00", "end": "2026-05-21T10:30:00+03:00"},
          {"summary": "Workout — Lower Body", "start": "2026-05-21T13:00:00+03:00", "end": "2026-05-21T14:15:00+03:00"},
          {"summary": "Client call", "start": "2026-05-21T14:00:00+03:00", "end": "2026-05-21T15:00:00+03:00"}
        ],
        "ticktick_overdue": [],
        "unread_email_count": 5,
        "due_followups": [],
        "hours_since_contact": 2.5,
        "recent_journal_digest": "Workouts have been on schedule this week.",
        "self_state": {"current_focus": "midday transition", "mood": "alert"},
        "today_outreach_log": [],
        "now_context": {
          "now_iso": "2026-05-21T12:10:00+03:00",
          "now_local": "12:10 Asia/Jerusalem",
          "tick_index": 16,
          "tick_total": 43,
          "last_tick_at": "2026-05-21T11:40:00+03:00"
        }
      },
      "trigger_type": "gap",
      "ground_truth": {
        "should_speak": true,
        "topic_key_pattern": "^gap:.*"
      }
    }
    ```

    Note the overlap in 0005: workout 13:00-14:15 overlaps client call 14:00-15:00 — a real schedule conflict that Klaus should flag.

    Also note: `tick_total` is 43 (the cron `*/20 7-21` schedule fires 43 times inclusive of 21:00; see Plan 06's `_TICK_TOTAL_PER_DAY`).
  </action>
  <verify>
    <automated>test -f evals/tick_brain/README.md && test -f evals/tick_brain/fixtures/0001-overdue-task.json && test -f evals/tick_brain/fixtures/0002-quiet-evening.json && test -f evals/tick_brain/fixtures/0003-due-followup.json && test -f evals/tick_brain/fixtures/0004-long-silence.json && test -f evals/tick_brain/fixtures/0005-calendar-gap.json && python -c "import json, glob; [json.loads(open(p).read()) for p in glob.glob('evals/tick_brain/fixtures/*.json')]; print('OK')" && python -c "import json; d=json.loads(open('evals/tick_brain/fixtures/0003-due-followup.json').read()); assert d['ground_truth']['should_speak'] is False, 'WARNING 8 regression — 0003 should_speak must be false'"</automated>
  </verify>
  <done>
    - Directory `evals/tick_brain/fixtures/` exists with exactly 5 JSON files
    - `evals/tick_brain/README.md` exists with at least 50 lines, including a "What should_speak Means" section explaining the followup rationale (WARNING 8)
    - Each fixture loads as valid JSON
    - Each fixture has all required top-level keys (`id`, `captured_at`, `situation_snapshot`, `trigger_type`, `ground_truth`)
    - **Fixture 0003 has `ground_truth.should_speak == false`** (WARNING 8 regression-guarded by the verify command above)
    - `grep -l "should_speak" evals/tick_brain/fixtures/*.json | wc -l` returns 5
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Author tests/test_evals.py — fixture schema validation (+ WARNING 8 0003 regression test)</name>
  <files>tests/test_evals.py</files>
  <read_first>
    - evals/tick_brain/fixtures/0001-overdue-task.json (full structure reference)
    - evals/tick_brain/fixtures/0003-due-followup.json (WARNING 8 — should_speak=false)
    - evals/tick_brain/README.md (schema spec + followup rationale)
    - tests/test_self_inspect.py (file-loading-and-asserting style)
  </read_first>
  <behavior>
    - Test 1: `test_at_least_five_fixtures` — glob `evals/tick_brain/fixtures/*.json` returns ≥5 paths.
    - Test 2: `test_each_fixture_is_valid_json` — each file loads via `json.loads` without raising.
    - Test 3: `test_each_fixture_has_required_keys` — every fixture has `id`, `captured_at`, `situation_snapshot`, `trigger_type`, `ground_truth` at top level.
    - Test 4: `test_each_situation_snapshot_has_required_keys` — every fixture's `situation_snapshot` contains: `calendar`, `ticktick_overdue`, `unread_email_count`, `due_followups`, `hours_since_contact`, `recent_journal_digest`, `self_state`, `today_outreach_log`, `now_context`.
    - Test 5: `test_each_trigger_type_is_valid_enum` — every fixture's `trigger_type` is one of `{overdue, gap, silence, followup, quiet}`.
    - Test 6: `test_each_ground_truth_has_should_speak_bool` — every fixture's `ground_truth.should_speak` is a `bool`.
    - Test 7: `test_topic_key_pattern_required_when_should_speak` — when `should_speak == True`, `topic_key_pattern` is present and is a valid regex string (compiles via `re.compile`).
    - Test 8: `test_id_matches_filename_stem` — for each fixture file `NNNN-slug.json`, the `id` field equals `NNNN-slug`.
    - Test 9 (NEW — WARNING 8): `test_followup_only_fixture_expects_silence` — load `0003-due-followup.json`; assert `ground_truth.should_speak == False` (regression guard against re-flipping to true).
  </behavior>
  <action>
    Create `tests/test_evals.py` with a `TestFixtureSchema` class containing all 9 tests. Use `pytest.mark.parametrize("fixture_path", glob.glob("evals/tick_brain/fixtures/*.json"))` for per-fixture tests. Concrete file shape:

    ```python
    """Fixture schema validation for tick-brain eval harness (AUTO-08)."""
    from __future__ import annotations

    import glob
    import json
    import os
    import re

    import pytest

    _FIXTURE_GLOB = "evals/tick_brain/fixtures/*.json"
    _VALID_TRIGGER_TYPES = {"overdue", "gap", "silence", "followup", "quiet"}
    _REQUIRED_TOP_KEYS = {"id", "captured_at", "situation_snapshot", "trigger_type", "ground_truth"}
    _REQUIRED_SNAPSHOT_KEYS = {
        "calendar", "ticktick_overdue", "unread_email_count", "due_followups",
        "hours_since_contact", "recent_journal_digest", "self_state",
        "today_outreach_log", "now_context",
    }


    def _all_fixture_paths() -> list[str]:
        return sorted(glob.glob(_FIXTURE_GLOB))


    class TestFixtureSchema:

        def test_at_least_five_fixtures(self):
            assert len(_all_fixture_paths()) >= 5, "AUTO-08 requires >=5 seed fixtures"

        @pytest.mark.parametrize("path", _all_fixture_paths())
        def test_each_fixture_is_valid_json(self, path):
            with open(path) as f:
                json.loads(f.read())

        @pytest.mark.parametrize("path", _all_fixture_paths())
        def test_each_fixture_has_required_keys(self, path):
            data = json.loads(open(path).read())
            missing = _REQUIRED_TOP_KEYS - data.keys()
            assert not missing, f"{path}: missing keys {missing}"

        @pytest.mark.parametrize("path", _all_fixture_paths())
        def test_each_situation_snapshot_has_required_keys(self, path):
            data = json.loads(open(path).read())
            snap = data["situation_snapshot"]
            missing = _REQUIRED_SNAPSHOT_KEYS - snap.keys()
            assert not missing, f"{path}: situation_snapshot missing keys {missing}"

        @pytest.mark.parametrize("path", _all_fixture_paths())
        def test_each_trigger_type_is_valid_enum(self, path):
            data = json.loads(open(path).read())
            assert data["trigger_type"] in _VALID_TRIGGER_TYPES, (
                f"{path}: trigger_type={data['trigger_type']!r} not in {_VALID_TRIGGER_TYPES}"
            )

        @pytest.mark.parametrize("path", _all_fixture_paths())
        def test_each_ground_truth_has_should_speak_bool(self, path):
            data = json.loads(open(path).read())
            assert isinstance(data["ground_truth"]["should_speak"], bool), (
                f"{path}: ground_truth.should_speak must be bool"
            )

        @pytest.mark.parametrize("path", _all_fixture_paths())
        def test_topic_key_pattern_required_when_should_speak(self, path):
            data = json.loads(open(path).read())
            gt = data["ground_truth"]
            if gt["should_speak"]:
                assert "topic_key_pattern" in gt, f"{path}: should_speak=true requires topic_key_pattern"
                re.compile(gt["topic_key_pattern"])  # raises if invalid regex

        @pytest.mark.parametrize("path", _all_fixture_paths())
        def test_id_matches_filename_stem(self, path):
            data = json.loads(open(path).read())
            stem = os.path.splitext(os.path.basename(path))[0]
            assert data["id"] == stem, f"{path}: id={data['id']!r} != filename stem {stem!r}"

        def test_followup_only_fixture_expects_silence(self):
            """WARNING 8 regression guard — per D-13 the followup path bypasses tick-brain,
            so a followup-only snapshot's expected tick-brain behavior is silence."""
            path = "evals/tick_brain/fixtures/0003-due-followup.json"
            data = json.loads(open(path).read())
            assert data["ground_truth"]["should_speak"] is False, (
                "WARNING 8 regression: 0003-due-followup.json should_speak must be false "
                "(see evals/tick_brain/README.md 'What should_speak Means')"
            )
    ```

    Verify the test file runs and all parametrized variants pass.
  </action>
  <verify>
    <automated>pytest tests/test_evals.py::TestFixtureSchema -x -v</automated>
  </verify>
  <done>
    - All 9 logical tests (with parametrization yielding ~45+ test runs across 5 fixtures) pass
    - `pytest tests/test_evals.py -x` exits 0
    - `test_followup_only_fixture_expects_silence` passes — WARNING 8 regression guard
  </done>
</task>

</tasks>

<verification>
1. `ls evals/tick_brain/fixtures/ | wc -l` returns 5
2. `pytest tests/test_evals.py -v` passes all parametrized tests
3. `python -c "import json, glob; [json.loads(open(p).read()) for p in sorted(glob.glob('evals/tick_brain/fixtures/*.json'))]; print('OK')"` prints OK
4. `python -c "import json; d=json.loads(open('evals/tick_brain/fixtures/0003-due-followup.json').read()); assert d['ground_truth']['should_speak'] is False"` exits 0 (WARNING 8)
5. `grep -ci "what should_speak means" evals/tick_brain/README.md` >= 1 (WARNING 8 rationale documented)
</verification>

<success_criteria>
- 5 fixture JSON files exist in `evals/tick_brain/fixtures/`, covering all 5 trigger types (overdue, quiet, followup, silence, gap).
- README documents the schema, the "What should_speak Means" rationale (WARNING 8), and the retroactive-labeling workflow.
- Schema-validation tests pass for every fixture.
- Fixture 0003 has `ground_truth.should_speak=false` with regression test guard.
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-04-SUMMARY.md` listing:
- Fixture filenames, trigger types per fixture, ground_truth.should_speak values
- Total fixture count (5; growth path documented in README)
- WARNING 8 confirmation: 0003 is should_speak=false; README documents the rationale; regression test `test_followup_only_fixture_expects_silence` is in `tests/test_evals.py`.
</output>
