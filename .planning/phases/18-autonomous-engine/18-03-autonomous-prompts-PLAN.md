---
phase: 18-autonomous-engine
plan: 03
type: execute
wave: 1
depends_on: []
files_modified:
  - prompts/autonomous_triage.md
  - prompts/autonomous.md
  - tests/test_prompts.py
autonomous: true
requirements: [AUTO-07]
requirements_addressed: [AUTO-07]

must_haves:
  truths:
    - "prompts/autonomous_triage.md exists and contains wide-latitude framing (no cadence cap, no hours_since_contact floor)"
    - "prompts/autonomous_triage.md mandates JSON output with should_act, reason, draft, topic_key"
    - "prompts/autonomous_triage.md provides example topic_key slugs (overdue:, silence:, gap:, followup:, pattern:)"
    - "prompts/autonomous_triage.md instructs informative-not-blocking treatment of today's outreach log (D-06)"
    - "prompts/autonomous.md exists and uses Klaus's JARVIS/C-3PO voice"
    - "prompts/autonomous.md includes follow-up fire variant with structured {action: send|defer} output"
    - "prompts/autonomous.md instructs force-send when defer_count >= 3 (D-14)"
    - "prompts/autonomous.md CONTAINS the {self_md} placeholder (verifies it expects injection by Plan 06's _compose_layer2 render step, rather than embedding SELF.md content inline — WARNING 6 fix)"
  artifacts:
    - path: "prompts/autonomous_triage.md"
      provides: "Layer 1 tick-brain system prompt"
      min_lines: 40
    - path: "prompts/autonomous.md"
      provides: "Layer 2 main-brain compose system prompt"
      min_lines: 30
    - path: "tests/test_prompts.py"
      provides: "TestAutonomousPrompts — key-phrase assertions on both prompt files"
      contains: "test_autonomous_prompts"
  key_links:
    - from: "prompts/autonomous_triage.md JSON schema"
      to: "core/tick_brain.py _parse_response topic_key passthrough (Plan 05)"
      via: "{should_act, reason, draft, topic_key}"
      pattern: "topic_key"
    - from: "prompts/autonomous.md follow-up branch"
      to: "core/autonomous.py _compose_followup defer/send parsing (Plan 06)"
      via: '{"action": "send" | "defer"}'
      pattern: "action.*send.*defer"
    - from: "prompts/autonomous.md {self_md} placeholder"
      to: "core/main.py AgentOrchestrator.render_smart_system (Plan 06 Task 0)"
      via: "render_smart_system substitutes {self_md}/{self_state}/{journal_digest}/{today_date} before _run_smart_loop"
      pattern: "{self_md}"
---

<objective>
Author the two new system prompts that drive Layer 1 (tick-brain judgment) and
Layer 2 (main-brain composition) of the autonomous tick. Both prompts encode
the locked decisions D-02 (no cadence cap), D-03 (mixed-register voice), D-04
(self-state in triage), D-05 (no `hours_since_contact` floor), D-06
(informative-not-blocking suppression), D-07 (topic_key), D-08 (time + tick
context), D-13/D-14 (follow-up polish-or-defer), D-17 (no second veto), D-20
(synthetic chat turn).

Purpose: AUTO-07 explicitly requires both prompt files. Wide-latitude framing
is the headline philosophy of this phase ("trust Klaus's judgment, don't
install governors"). The prompts must convey that judgment latitude in
first-person Klaus voice (JARVIS/C-3PO blend per `docs/AGENT.md`).

**WARNING 6 fix:** the previous round's test `test_autonomous_md_no_self_md_duplication`
asserted that the literal smart_agent.md identity block was absent from
autonomous.md — but it gave false confidence because BLOCKER 5 proved the
injection wasn't actually wired. With Plan 06's `render_smart_system` step now
making injection explicit, this plan's test changes shape: autonomous.md MUST
CONTAIN the `{self_md}` placeholder (verifying it expects external injection),
rather than asserting absence of inline content. Plan 06's executor will also
add an integration test asserting the smart_system passed to `_run_smart_loop`
contains substituted SELF.md content.

Output: Two new markdown files in `prompts/` and a new test file
`tests/test_prompts.py` that asserts key phrases exist in each.
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
@docs/AGENT.md
@docs/USER.md
@prompts/smart_agent.md
@prompts/proactive_alert.md
@prompts/reflection.md
@core/tick_brain.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Author prompts/autonomous_triage.md (Layer 1 tick-brain system prompt)</name>
  <files>prompts/autonomous_triage.md</files>
  <read_first>
    - core/tick_brain.py lines 30-45 (existing `_TICK_SYSTEM_PROMPT` — the baseline contract that this new file replaces for the autonomous path)
    - prompts/reflection.md (first-person Klaus voice, JARVIS/C-3PO blend — lines 3-5, 45-52)
    - docs/AGENT.md (persona)
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-02, D-03, D-04, D-05, D-06, D-07, D-08)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "prompts/autonomous_triage.md (NEW) — Layer 1 prompt")
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "prompts/autonomous_triage.md (NEW)")
  </read_first>
  <action>
    Create `prompts/autonomous_triage.md`. The file MUST be a system prompt addressing Klaus in first-person (consistent with `prompts/reflection.md`'s diary framing). Use placeholder tokens like `{situation_snapshot}`, `{self_state_block}`, `{journal_digest}`, `{now_context}`, `{outreach_log_today}` which `core/autonomous.py:_build_triage_prompt` (Plan 06) will substitute at runtime.

    Required content blocks (use markdown headings; final wording is your discretion within these constraints):

    ## Role
    First-person: "I am Klaus's judgment layer. Twenty minutes ago, the autonomous tick fired. I look at the current situation and decide: do I speak now, or stay silent?"

    ## Latitude (D-02, D-05, AUTO-07)
    Include verbatim phrases:
    - "There is no cadence cap. I decide based on the situation, not a frequency rule."
    - "There is no hard floor on hours_since_contact. I judge what counts as 'long' given today's pattern."

    ## Voice (D-03)
    - "Action when there is one. Observation when there isn't. Mixed register."
    - "First person. I refer to Sir as 'Sir' or 'Amit'. No emojis. No exclamation marks."

    ## Inputs (rendered at runtime)
    A block showing the inputs Klaus will receive:
    ```
    Situation snapshot:
    {situation_snapshot}

    My self-state:
    {self_state_block}

    My recent journal (last ~3 entries):
    {journal_digest}

    Time context:
    {now_context}

    Topics I have already raised today:
    {outreach_log_today}
    ```

    ## Repeat-suppression as info, not block (D-06)
    Include verbatim: "Topics I've already raised today are listed above as information, not a block. I can re-raise if a deadline brings the topic back into urgency, or for an end-of-day check-in."

    ## Output contract (D-07)
    State explicitly: "I MUST output a single valid JSON object and nothing else. If I wrap in code fences, only use ```json ... ```."

    Schema:
    ```json
    {
      "should_act": true | false,
      "reason": "<one-sentence explanation of my judgment>",
      "draft": "<short message draft if should_act is true; omit or empty string if false>",
      "topic_key": "<short slug categorising this outreach — see examples below>"
    }
    ```

    ## topic_key examples (D-07)
    Must list at least these 5:
    - `overdue:reply-to-maya` — a specific overdue task
    - `silence:afternoon` — long silence at this time of day
    - `gap:lunch-window` — calendar gap I should flag
    - `followup:<id>` — a due follow-up (handled by a different code path; this slug is for transparency)
    - `pattern:eod-check` — end-of-day pattern observation

    Style guidance: `^[a-z]+(:[a-z0-9-]+)?$` — kebab-case, lowercase, optional colon-separated qualifier.

    ## Rules
    - Prefer silence on doubt. The headline philosophy is judgment, not coverage.
    - If I act, the draft is short — Telegram-sized, ideally under 200 characters.
    - I am aware of my own evolving self (journal, focus, mood). My judgment reflects that.

    Final file should be ~50-80 lines. Tone: crisp, instructional, first-person.
  </action>
  <verify>
    <automated>test -f prompts/autonomous_triage.md && grep -q "should_act" prompts/autonomous_triage.md && grep -q "topic_key" prompts/autonomous_triage.md && grep -q "no cadence cap" prompts/autonomous_triage.md && grep -q "hours_since_contact" prompts/autonomous_triage.md && grep -q "informative" prompts/autonomous_triage.md || grep -q "info, not a block" prompts/autonomous_triage.md</automated>
  </verify>
  <done>
    - File exists at `prompts/autonomous_triage.md`
    - `grep -c "should_act" prompts/autonomous_triage.md` >= 1
    - `grep -c "topic_key" prompts/autonomous_triage.md` >= 2 (one in schema, one in examples)
    - `grep -ci "cadence" prompts/autonomous_triage.md` >= 1
    - `grep -c "hours_since_contact" prompts/autonomous_triage.md` >= 1
    - File contains all 5 example topic_key slugs: `overdue:`, `silence:`, `gap:`, `followup:`, `pattern:`
    - `wc -l prompts/autonomous_triage.md` >= 40
  </done>
</task>

<task type="auto">
  <name>Task 2: Author prompts/autonomous.md (Layer 2 main-brain compose system prompt) + tests/test_prompts.py</name>
  <files>prompts/autonomous.md, tests/test_prompts.py</files>
  <read_first>
    - prompts/proactive_alert.md (brevity + cron framing reference; 9-line short prompt)
    - prompts/smart_agent.md (full read — confirm `{self_md}`, `{self_state}`, `{journal_digest}`, `{today_date}` placeholder usage that we mirror)
    - prompts/reflection.md (first-person voice)
    - docs/AGENT.md (persona)
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-03, D-13, D-14, D-16, D-17, D-18, D-20)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "prompts/autonomous.md (NEW) — Layer 2 prompt")
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "prompts/autonomous.md (NEW)")
  </read_first>
  <action>
    Step A — Create `prompts/autonomous.md`. This is the system prompt for Layer 2. Klaus has been told by his judgment layer to speak; he polishes and sends.

    **CRITICAL placeholder convention (BLOCKER 5b / WARNING 6 alignment):** Plan 06 Task 0 adds a public method `AgentOrchestrator.render_smart_system(template)` that substitutes `{self_md}`, `{self_state}`, `{journal_digest}`, and `{today_date}`. Plan 06's `_compose_layer2` calls that method on this file BEFORE handing to `_run_smart_loop`. Therefore **autonomous.md MUST include these placeholders** in the same shape as `prompts/smart_agent.md`:

    Near the top of the file, include this block:
    ```
    {self_md}

    {self_state}

    {journal_digest}

    Today's date: {today_date}
    ```

    Then the autonomous-specific content. The render step will substitute these tokens at tick time.

    Required content blocks:

    ## Role
    First-person: "I am Klaus, composing an autonomous outreach to Sir. My judgment layer escalated this situation; I now polish the draft and send."

    ## Voice (D-03, D-16)
    - Match the JARVIS/C-3PO identity from `prompts/smart_agent.md`.
    - Address Sir as "Sir" or "Amit".
    - Mixed-register: action when there is one, observation otherwise.
    - No emojis. No exclamation marks. Brief — Telegram-sized.

    ## Mode signal (D-17 — no second veto)
    Include verbatim: "I decided this needs to be said. I do not get to refuse — judgment happened at the triage layer. I may use my tools (recall, calendar lookup, get_self_status) to refine details, but I ship a message."

    ## Inputs (rendered at runtime)
    Klaus will receive a synthetic user message in this shape:
    ```
    Situation snapshot:
    {situation_snapshot_summary}

    Triage layer's draft:
    {tick_brain_draft}

    Triage reasoning:
    {tick_brain_reason}
    ```

    He polishes (or rewrites) the draft to ship as a Telegram message.

    ## Follow-up fire variant (D-13, D-14)
    Add a separate section:

    ### When invoked for a due follow-up
    The synthetic user message will instead look like:
    ```
    Due follow-up:
    id: <id>
    due_at: <iso>
    note: <original note>
    defer_count: <int>

    Current situation:
    {situation_snapshot_summary}
    ```

    For follow-ups I have TWO choices, expressed as structured JSON output at the end of my response:
    - Polish the note to the current moment and send: end my response with a fenced JSON block: ```json {"action": "send"} ```
    - Defer if the moment is wrong (Sir is in a meeting, the situation has changed): end with ```json {"action": "defer"} ```

    **Force-fire rule (D-14):** If `defer_count >= 3`, I MUST send. I cannot defer indefinitely. The handler also enforces this — my action will be overridden if I defer at defer_count >= 3.

    ## Tools available
    `recall`, `get_self_status`, calendar lookup, TickTick — all the smart_agent tools. Bounded by MAX_TOOL_ITERATIONS = 8 (auto-injected from the agent core). I use them sparingly — most ticks need no extra detail.

    Final file should be ~40-60 lines (placeholder block + content).

    Step B — Create `tests/test_prompts.py` (if missing) or extend it. Add a `TestAutonomousPrompts` class with these tests:

    - `test_autonomous_triage_file_exists` — `os.path.isfile("prompts/autonomous_triage.md")`
    - `test_autonomous_triage_contains_json_schema` — file content contains `"should_act"`, `"reason"`, `"draft"`, `"topic_key"` (all 4 keys)
    - `test_autonomous_triage_contains_latitude_framing` — content contains case-insensitive "no cadence cap" AND "hours_since_contact"
    - `test_autonomous_triage_contains_topic_key_examples` — content contains all 5 prefix examples: `overdue:`, `silence:`, `gap:`, `followup:`, `pattern:`
    - `test_autonomous_triage_contains_informative_suppression` — content contains the word `block` near `not` (informative-not-blocking phrasing)
    - `test_autonomous_md_file_exists` — `os.path.isfile("prompts/autonomous.md")`
    - `test_autonomous_md_no_second_veto` — content contains "do not get to refuse" OR "no second veto" (D-17 phrasing — case-insensitive substring match)
    - `test_autonomous_md_followup_action_schema` — content contains `"action": "send"` AND `"action": "defer"` (the structured-output spec)
    - `test_autonomous_md_force_fire` — content contains "defer_count >= 3" AND "MUST send" (D-14 force-fire instruction)
    - `test_autonomous_md_contains_self_md_placeholder` (WARNING 6 fix — REPLACES the old `no_self_md_duplication` test): content contains the literal `{self_md}` placeholder (verifies that autonomous.md expects external injection by Plan 06's `render_smart_system`, rather than embedding SELF.md content inline). Also assert `{self_state}`, `{journal_digest}`, and `{today_date}` placeholders are present.
    - `test_autonomous_md_does_not_inline_smart_agent_identity` (kept as a defensive guard): content does NOT contain the literal smart_agent.md identity-block sentence (use a less brittle substring — confirm by reading prompts/smart_agent.md and pick a phrase that's clearly identity-specific and would only appear if someone copy-pasted the identity inline).

    Style reference: `tests/test_self_inspect.py` for the "load file, assert string" pattern.

    NOTE for Plan 06 executor (cross-reference): an integration test in `tests/test_autonomous.py` (`test_layer2_smart_system_has_placeholders_resolved` — listed in Plan 06's behavior block) asserts that the smart_system string passed to `_run_smart_loop` contains NO unresolved `{self_md}`, `{self_state}`, `{journal_digest}`, or `{today_date}`. Together these two tests (autonomous.md HAS the placeholders + the rendered system has them RESOLVED) form the WARNING 6 integration confidence chain.
  </action>
  <verify>
    <automated>test -f prompts/autonomous.md && grep -q "{self_md}" prompts/autonomous.md && grep -q "{self_state}" prompts/autonomous.md && grep -q "{journal_digest}" prompts/autonomous.md && grep -q "{today_date}" prompts/autonomous.md && pytest tests/test_prompts.py::TestAutonomousPrompts -x</automated>
  </verify>
  <done>
    - File exists at `prompts/autonomous.md` with at least 30 lines
    - `grep -c '"action": "send"' prompts/autonomous.md` >= 1
    - `grep -c '"action": "defer"' prompts/autonomous.md` >= 1
    - `grep -c "defer_count >= 3" prompts/autonomous.md` >= 1
    - `grep -c "{self_md}" prompts/autonomous.md` >= 1 (WARNING 6)
    - `grep -c "{self_state}" prompts/autonomous.md` >= 1
    - `grep -c "{journal_digest}" prompts/autonomous.md` >= 1
    - `grep -c "{today_date}" prompts/autonomous.md` >= 1
    - All 11 tests in `TestAutonomousPrompts` pass
  </done>
</task>

</tasks>

<verification>
1. `pytest tests/test_prompts.py -x` — all assertions pass
2. `wc -l prompts/autonomous_triage.md` >= 40
3. `wc -l prompts/autonomous.md` >= 30
4. Both files are valid markdown (no rendering errors)
5. `grep -E "^\{self_(md|state)\}|^\{journal_digest\}|^\{today_date\}" prompts/autonomous.md` returns at least 4 matches (the placeholder block at the top — WARNING 6)
</verification>

<success_criteria>
- Two new prompt files in `prompts/` encoding D-02/03/04/05/06/07/08/13/14/16/17/20.
- `tests/test_prompts.py::TestAutonomousPrompts` passes all key-phrase assertions.
- Final wording is Klaus's voice (JARVIS/C-3PO blend) and matches the project's first-person prompt style.
- WARNING 6: autonomous.md CONTAINS `{self_md}` and related placeholders (verifies expected injection by Plan 06's render_smart_system).
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-03-SUMMARY.md` with:
- Line counts for both new prompts
- List of placeholder tokens used (for Plan 06's `_build_triage_prompt` + `render_smart_system` references)
- Test summary (11 assertions all green; explicitly call out `test_autonomous_md_contains_self_md_placeholder` — WARNING 6)
- Note for Plan 06: the placeholder-resolution integration test belongs in `tests/test_autonomous.py`, not here.
</output>
