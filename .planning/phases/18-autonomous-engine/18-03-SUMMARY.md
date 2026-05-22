---
phase: 18-autonomous-engine
plan: 03
subsystem: prompts
tags: [autonomous-engine, prompts, tick-brain, layer-2, JARVIS-C3PO, AUTO-07, WARNING-6]

# Dependency graph
requires:
  - phase: 18-autonomous-engine
    provides: FollowupStore + outreach_log + 3 brain-direct follow-up tools (Plans 18-01, 18-02)
provides:
  - prompts/autonomous_triage.md — Layer 1 tick-brain system prompt (judgment with self-state)
  - prompts/autonomous.md — Layer 2 main-brain compose system prompt (polish-and-ship)
  - JSON output schema {should_act, reason, draft, topic_key} — extends tick-brain contract (D-07)
  - Follow-up structured output spec {action: "send" | "defer"} — D-13/D-14 fire variant
  - Placeholder contract for AgentOrchestrator.render_smart_system (Plan 18-06 Task 0)
affects:
  - 18-05-tick-brain-extension (consumes new triage prompt + topic_key field)
  - 18-06-autonomous-orchestrator (loads both prompts; _build_triage_prompt substitutes
    {situation_snapshot}/{self_state_block}/{journal_digest}/{now_context}/{outreach_log_today};
    render_smart_system substitutes {self_md}/{self_state}/{journal_digest}/{today_date})
  - 18-08-eval-runner (eval fixtures execute against the triage prompt)

# Tech tracking
tech-stack:
  added: []   # No new dependencies — both files are LLM system prompts (markdown) + a test module
  patterns:
    - "First-person 'I am Klaus' framing (matches prompts/reflection.md, diary voice)"
    - "Placeholder-token contract: {self_md}/{self_state}/{journal_digest}/{today_date} mirror prompts/smart_agent.md top-of-file block — substitutable by Plan 06's render_smart_system step (WARNING 6 fix)"
    - "JSON-only output contract with explicit code-fence allowance (```json ... ```) — extends tick-brain _TICK_SYSTEM_PROMPT pattern"
    - "Key-phrase test assertions on prompt files (style: tests/test_self_inspect.py 'load file, assert string' pattern)"

key-files:
  created:
    - prompts/autonomous_triage.md (95 lines — Layer 1 triage prompt)
    - prompts/autonomous.md (110 lines — Layer 2 compose prompt with follow-up fire variant)
    - tests/test_prompts.py (167 lines — 11 TestAutonomousPrompts assertions)
  modified: []

key-decisions:
  - "autonomous.md DECLARES {self_md}/{self_state}/{journal_digest}/{today_date} placeholders rather than embedding SELF.md content inline — WARNING 6 fix; Plan 06's render_smart_system will substitute them before _run_smart_loop"
  - "Test test_autonomous_md_contains_self_md_placeholder REPLACES the old no_self_md_duplication assertion — verifies positive presence of placeholders instead of the previous false-confidence absence check"
  - "Defensive guard test_autonomous_md_does_not_inline_smart_agent_identity uses the distinctive 25-word identity sentence from smart_agent.md:9 as the forbidden substring — a narrow, intentional copy-paste trigger that won't false-fire on incidental JARVIS/C-3PO mentions"
  - "topic_key examples cover all 5 categories from D-07 (overdue:/silence:/gap:/followup:/pattern:) plus a regex hint (^[a-z]+(:[a-z0-9-]+)?$) so the tick-brain has a clear style contract"
  - "informative-not-blocking phrasing (D-06) uses 'Topics I've already raised today are listed above as information, not a block.' — the test matches on 'block' within 30 chars of 'not' to allow rephrasing while still catching regression"
  - "Force-fire rule for follow-ups (D-14) appears in BOTH human-readable prose AND machine-checkable phrasing ('defer_count >= 3' AND 'MUST send') — test assertions catch either drift"

patterns-established:
  - "Layer 1 / Layer 2 prompt split — triage prompt as JSON-only judge, compose prompt as full smart_agent tool-loop"
  - "Placeholder-presence test (assert {placeholder} in content) at the prompt level, paired with a future placeholder-resolution test at the orchestrator level (test_layer2_smart_system_has_placeholders_resolved — to be added in tests/test_autonomous.py in Plan 06)"

requirements-completed: [AUTO-07]

# Metrics
duration: 5min
completed: 2026-05-22
---

# Phase 18 Plan 03: Autonomous Prompts Summary

**Two new LLM system prompts (Layer 1 triage + Layer 2 compose) authored in first-person Klaus voice, encoding the locked Phase 18 decisions D-02/03/04/05/06/07/08/13/14/16/17/20 — with a placeholder contract that fixes WARNING 6 by declaring (not inlining) the {self_md} / {self_state} / {journal_digest} / {today_date} tokens that Plan 06's render_smart_system will substitute.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-22T20:37:12Z
- **Completed:** 2026-05-22T20:39:37Z
- **Tasks:** 2 (no TDD — prompt authoring + test scaffold)
- **Files created:** 3 (`prompts/autonomous_triage.md`, `prompts/autonomous.md`, `tests/test_prompts.py`)
- **Files modified:** 0

## Line counts

| File | Lines | Min required |
|---|---|---|
| `prompts/autonomous_triage.md` | 95 | 40 (PASS) |
| `prompts/autonomous.md`        | 110 | 30 (PASS) |
| `tests/test_prompts.py`        | 167 | n/a |

## Accomplishments

### prompts/autonomous_triage.md (Layer 1 — tick-brain judge)

- First-person framing: "I am Klaus's judgment layer. Twenty minutes ago, the autonomous tick fired."
- Wide-latitude block (D-02 / D-05 / AUTO-07): "There is no cadence cap." and "There is no hard floor on hours_since_contact."
- Voice block (D-03): "Action when there is one. Observation when there isn't. Mixed register."
- Inputs block declares 5 runtime placeholders (substituted by `core/autonomous.py:_build_triage_prompt` in Plan 06)
- Repeat-suppression as info, not block (D-06)
- JSON output contract with 4 keys: `should_act`, `reason`, `draft`, `topic_key` (D-07 extends the existing `_TICK_SYSTEM_PROMPT` 3-key schema in `core/tick_brain.py:30`)
- All 5 example topic_key slug prefixes present: `overdue:`, `silence:`, `gap:`, `followup:`, `pattern:`
- Slug regex hint: `^[a-z]+(:[a-z0-9-]+)?$`
- Explicit silence-on-doubt rule and 200-character draft target

### prompts/autonomous.md (Layer 2 — main-brain compose)

- Top-of-file placeholder block (WARNING 6 fix): `{self_md}` / `{self_state}` / `{journal_digest}` / `Today's date: {today_date}` — mirrors `prompts/smart_agent.md:1-9`
- First-person role: "I am Klaus, composing an autonomous outreach to Sir."
- D-17 (no second veto) verbatim: "I do not get to refuse — judgment happened at the triage layer."
- D-03/D-16 voice rules (JARVIS competence + C-3PO protocol-awareness)
- Follow-up fire variant section with structured-output spec:
  - Polish-and-send: `{"action": "send"}`
  - Defer: `{"action": "defer"}`
- D-14 force-fire rule in two phrasings: `defer_count >= 3` and `MUST send` — both grep-checked by the test
- D-20 tools-loop affordance: lists `recall`, `get_self_status`, `delegate_to_worker` for calendar/TickTick, `list_followups`, `schedule_followup`, self-inspection — and the MAX_TOOL_ITERATIONS = 8 bound

### tests/test_prompts.py (TestAutonomousPrompts)

11 assertions, all green in 0.01s:

| # | Test | Assertion |
|---|---|---|
| 1 | `test_autonomous_triage_file_exists` | path exists |
| 2 | `test_autonomous_triage_contains_json_schema` | all 4 JSON keys present |
| 3 | `test_autonomous_triage_contains_latitude_framing` | "no cadence cap" + "hours_since_contact" |
| 4 | `test_autonomous_triage_contains_topic_key_examples` | all 5 slug prefixes |
| 5 | `test_autonomous_triage_contains_informative_suppression` | "block" within 30 chars of "not" (D-06) |
| 6 | `test_autonomous_md_file_exists` | path exists |
| 7 | `test_autonomous_md_no_second_veto` | "do not get to refuse" OR "no second veto" (D-17) |
| 8 | `test_autonomous_md_followup_action_schema` | `"action": "send"` AND `"action": "defer"` (D-13) |
| 9 | `test_autonomous_md_force_fire` | `defer_count >= 3` AND `MUST send` (D-14) |
| 10 | **`test_autonomous_md_contains_self_md_placeholder`** | all 4 placeholders present — **WARNING 6 fix; REPLACES the old `no_self_md_duplication` test** |
| 11 | `test_autonomous_md_does_not_inline_smart_agent_identity` | distinctive smart_agent.md identity sentence is NOT inlined (defensive guard) |

## Task Commits

Each task was committed atomically:

1. **Task 1 — Layer 1 triage prompt** — `041478c` (feat)
2. **Task 2 — Layer 2 compose prompt + tests** — `f753111` (feat)

**Plan metadata commit:** (pending — added by `<final_commit>` step below)

## Placeholder token inventory (for Plan 06 cross-reference)

### Substituted by `core/autonomous.py:_build_triage_prompt` (Plan 06) into `prompts/autonomous_triage.md`:
- `{situation_snapshot}` — the calendar/silence/follow-up/heartbeat snapshot
- `{self_state_block}` — current_focus + mood from SelfStateStore (D-04)
- `{journal_digest}` — last ~3 journal entries from JournalStore (D-04, Phase 17 D-14)
- `{now_context}` — now / tick_index / tick_total / last_tick_at (D-08)
- `{outreach_log_today}` — topic_keys raised today (D-06 informative block)

### Substituted by `AgentOrchestrator.render_smart_system` (Plan 06 Task 0) into `prompts/autonomous.md`:
- `{self_md}` — full SELF.md text (capability manifest)
- `{self_state}` — current_focus + mood + recent_context block
- `{journal_digest}` — last ~3 journal entries
- `{today_date}` — ISO date string

### Authored by Layer 2 itself in the synthetic user message (NOT substituted by the render step):
- `{situation_snapshot_summary}` — passed via the synthetic user message
- `{tick_brain_draft}` — passed via the synthetic user message
- `{tick_brain_reason}` — passed via the synthetic user message

## WARNING 6 fix — explicit call-out

The previous round's test `test_autonomous_md_no_self_md_duplication` asserted
the literal smart_agent.md identity block was ABSENT from autonomous.md — but
BLOCKER 5 proved the injection wasn't actually wired, so the test gave false
confidence.

With Plan 06 Task 0 making `render_smart_system` an explicit public method, this
plan's test changes shape:

- **`test_autonomous_md_contains_self_md_placeholder` (NEW, this plan)** —
  asserts `{self_md}`, `{self_state}`, `{journal_digest}`, `{today_date}` are
  ALL present in autonomous.md (verifies external injection is expected).
- **`test_autonomous_md_does_not_inline_smart_agent_identity` (kept as guard)** —
  asserts the distinctive smart_agent.md identity sentence is NOT inlined.
- **(Plan 06's job, NOT this plan's)** — `test_layer2_smart_system_has_placeholders_resolved`
  in `tests/test_autonomous.py` will assert the smart_system string passed
  to `_run_smart_loop` contains NO unresolved `{self_md}` / `{self_state}` /
  `{journal_digest}` / `{today_date}`. Together these two tests form the
  WARNING 6 integration confidence chain.

## Note for Plan 06 executor

The placeholder-resolution integration test
(`test_layer2_smart_system_has_placeholders_resolved`) belongs in
`tests/test_autonomous.py`, not in `tests/test_prompts.py`. Plan 18-06's
behavior block already lists it — do not duplicate it here.

## No-regression check

`pytest tests/test_tools.py tests/test_firestore_db.py -x` — **34 tests pass**
(no regressions in the Plan 18-01 + 18-02 surface).

## Deviations from Plan

None — plan executed exactly as written. All key-phrase requirements, line-count
minimums, and the WARNING 6 placeholder contract were satisfied on first pass.

## Threat Flags

None — this plan introduces only markdown system-prompt files and a test
module; no new network endpoints, auth paths, file access patterns, or
schema changes.

## Self-Check: PASSED

- `prompts/autonomous_triage.md` — FOUND (95 lines)
- `prompts/autonomous.md` — FOUND (110 lines)
- `tests/test_prompts.py` — FOUND (167 lines, 11/11 tests green)
- Commit `041478c` (Task 1) — FOUND in git log
- Commit `f753111` (Task 2) — FOUND in git log
- No-regression check (`tests/test_tools.py` + `tests/test_firestore_db.py`) — 34/34 PASS
