---
phase: 18-autonomous-engine
plan: 06
type: execute
wave: 2
depends_on: [01, 02, 03, 05]
files_modified:
  - core/main.py
  - core/autonomous.py
  - memory/firestore_conversation.py
  - tests/test_autonomous.py
  - tests/test_main_render_smart_system.py
autonomous: true
requirements: [AUTO-01, AUTO-02, AUTO-03]
requirements_addressed: [AUTO-01, AUTO-02, AUTO-03]

must_haves:
  truths:
    - "gather_situation(now) returns a snapshot dict aggregating 8 sources (calendar, ticktick_overdue, unread_email_count, due_followups, hours_since_contact, recent_journal_digest, self_state, today_outreach_log) with per-source try/except isolation (one failure does not mask others)"
    - "gather_situation produces a now_context block per D-08 (now_iso, now_local, tick_index, tick_total, last_tick_at)"
    - "gather_situation uses REAL APIs verified from source: GoogleCalendarManager.list_events(time_min_iso, time_max_iso) (NOT CalendarManager.list_events_for_date), ticktick_tool.get_today_tasks() (module function returning dict with 'overdue' key), GmailTool(auth_manager).list_unread(max_results) (NOT GmailManager.get_unread_count), and FirestoreConversationStore iteration for last user message timestamp"
    - "gather_situation flags empty=True when no overdue, no due follow-ups, AND no calendar gap/overload (NOT 'any calendar event') — fixes SC-3 quiet-situation cost control (Layer 0 gate, D-11)"
    - "run_autonomous_tick(bot, now) skips tick-brain entirely when situation.empty (cost control SC-3)"
    - "Due follow-ups (from FollowupStore.list_due) trigger a dedicated Layer-2 compose path, skipping tick-brain (D-13)"
    - "Layer 2 receives synthetic [{role: user, content: situation+draft}] via AgentOrchestrator.render_smart_system + _run_smart_loop — placeholders {self_md}, {self_state}, {journal_digest}, {today_date} are resolved BEFORE _run_smart_loop is called (Pitfall 2 + verified BLOCKER 5 fix)"
    - "Layer-2 smart_system has NO unresolved {self_md}, {self_state}, {journal_digest}, or {today_date} substrings (asserted by test)"
    - "On Layer-2 LLM total failure OR sentinel-return ('I'm afraid I encountered a connectivity issue'), falls back to tick_brain_result['draft'] and ships (D-19) — sentinel detection is mandatory because _run_smart_loop RETURNS the sentinel string instead of raising"
    - "AgentOrchestrator is module-level singleton — instantiated once, reused across all ticks within the same process (avoids re-reading SELF.md, re-bootstrapping SelfStateStore, re-constructing 3 LLMClients ~42 times/day)"
    - "OutreachLogStore.append called ONLY after send_and_inject succeeds (D-10)"
    - "send_and_inject called with inject_into_conversation=True (D-18)"
    - "When tick_brain returns empty/missing topic_key, handler synthesises one (Pitfall 4)"
    - "When follow-up Layer-2 returns {action: defer} AND defer_count >= 3, handler force-fires (D-14, Pitfall 6)"
    - "All LLM calls use purpose='tick_autonomous' (Layer 1) or 'autonomous_compose' / 'autonomous_compose_fallback' (Layer 2)"
    - "_load_prompt uses the same strategy as core/main.py:_load_prompt (relative path from project root via Path(relative_path).read_text)"
    - "tick_total is 43 (cron */20 7-21 = inclusive 43 ticks); tick_index clamped to >=1 with safe behavior for hour<7"
  artifacts:
    - path: "core/main.py"
      provides: "Public AgentOrchestrator.render_smart_system(template) method exposing the existing per-message render logic (Task 0 BLOCKER 5 prep)"
      contains: "def render_smart_system"
    - path: "core/autonomous.py"
      provides: "Orchestration module — gather_situation, run_autonomous_tick, _compose_layer2, _compose_followup, _build_triage_prompt, _synthesize_topic_key, _get_orchestrator (singleton), _SMART_LOOP_ERROR_SENTINELS"
      min_lines: 280
    - path: "tests/test_autonomous.py"
      provides: "All AUTO-01/02/03 + pitfall + decision-trail + BLOCKER-regression tests"
      contains: "test_run_autonomous_tick_decision_trail"
  key_links:
    - from: "core/autonomous.py:_compose_layer2"
      to: "core/main.py:AgentOrchestrator.render_smart_system + _run_smart_loop"
      via: "smart_system = orchestrator.render_smart_system(_load_prompt('autonomous.md')); orchestrator._run_smart_loop(messages, smart_system, worker_system)"
      pattern: "render_smart_system"
    - from: "core/autonomous.py:run_autonomous_tick"
      to: "core/tick_brain.py:TickBrain.think(prompt, system_override=...)"
      via: "tick_brain.think(triage_prompt, system_override=<autonomous_triage.md>)"
      pattern: "system_override"
    - from: "core/autonomous.py:run_autonomous_tick"
      to: "memory/firestore_db.py:OutreachLogStore.append"
      via: "post-send, only on success (D-10)"
      pattern: "OutreachLogStore.*append"
    - from: "core/autonomous.py"
      to: "core/scheduled_message.py:send_and_inject"
      via: "send_and_inject(bot, final_text, inject_into_conversation=True)"
      pattern: "inject_into_conversation=True"
---

<objective>
Build the orchestration module `core/autonomous.py` — the heart of the
autonomous engine. Implements `gather_situation()` (Layer 0), `run_autonomous_tick()`
(top-level 3-layer pipeline), `_compose_layer2()` (smart-agent synthetic chat
turn), `_compose_followup()` (D-13 dedicated path), `_build_triage_prompt()`
(prompt rendering), `_synthesize_topic_key()` (Pitfall 4 fallback), and a
module-level `AgentOrchestrator` singleton (BLOCKER 5 fix).

Includes a small Task 0 prep edit to `core/main.py` that exposes a public
`AgentOrchestrator.render_smart_system(template)` method — the existing
per-message render logic (currently inline in `handle_message`) lifted out
so `_compose_layer2` can call it. **Verified by reading the actual source:
the render step lives in `handle_message` (core/main.py:236-275), NOT in
`_run_smart_loop`. The previous round's plan trusted CONTEXT.md/RESEARCH.md's
incorrect claim that injection happens in `_run_smart_loop`.**

Purpose: AUTO-01 (3-layer design), AUTO-02 (gather_situation 8-source
isolation), and AUTO-03 (outreach_log on success only, repeat-suppression via
topic_key). This plan also enforces D-07, D-10, D-11, D-13, D-14, D-17, D-18,
D-19, D-20 — most of the locked decisions land here. Heavy test coverage
(per VALIDATION.md Wave 0 gap list) protects against Pitfalls 2, 3, 4, 6
and against the 5 BLOCKERs surfaced by the prior checker pass.

Output: A small edit to `core/main.py` (new public method) + a new
~280-320 LOC module + a new test file ~450 LOC covering empty-signal skip,
triage-no, triage-yes-compose-yes, triage-yes-compose-fail fallback,
sentinel-return fallback, follow-up fire, defer, force-fire-at-3,
history-pollution avoidance, outreach-log-on-success, topic_key fallback,
placeholder-resolution, singleton reuse, and calendar gap/overload detection.
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
@.planning/phases/18-autonomous-engine/18-01-SUMMARY.md
@.planning/phases/18-autonomous-engine/18-03-SUMMARY.md
@.planning/phases/18-autonomous-engine/18-05-SUMMARY.md
@docs/CODING_STANDARDS.md
@core/reflection.py
@core/proactive_alerts.py
@core/tick_brain.py
@core/main.py
@core/scheduled_message.py
@core/tools.py
@mcp_tools/calendar_tool.py
@mcp_tools/ticktick_tool.py
@mcp_tools/gmail_tool.py
@memory/firestore_conversation.py
@memory/firestore_db.py

<interfaces>
<!-- VERIFIED from source — these are the REAL APIs, not the names CONTEXT/RESEARCH used. -->

From mcp_tools/calendar_tool.py:27,71 (verified by reading source):
```python
class GoogleCalendarManager:
    def __init__(self, auth_manager: GoogleAuthManager) -> None: ...
    def list_events(self, time_min_iso: str, time_max_iso: str, max_results: int = 20) -> list[dict]:
        # Returns list of {id, summary, start, end, description, location}
        # "start"/"end" are ISO strings (dateTime preferred over date for all-day events)
```
NOTE: `CalendarManager` does NOT exist. `list_events_for_date` does NOT exist. Use `list_events(time_min_iso, time_max_iso)`.

From mcp_tools/ticktick_tool.py:159 (module-level function, NOT a class):
```python
def get_today_tasks() -> dict:
    # Returns:
    # {
    #   "today":    [{"title": str, "tags": list[str]}, ...],
    #   "overdue":  [{"title": str, "due": str, "tags": list[str]}, ...],
    #   "due_today": [],
    #   "staleness_warning": None | "Task data unavailable, sir."
    # }
```
NOTE: `TickTickManager` does NOT exist. Use `from mcp_tools.ticktick_tool import get_today_tasks; tasks = get_today_tasks() or {}; overdue = tasks.get("overdue", [])`.

From mcp_tools/gmail_tool.py:20,28,143 (verified by reading source):
```python
class GmailTool:
    def __init__(self, auth_manager: GoogleAuthManager) -> None: ...
    def list_unread(self, max_results: int = 10) -> list[dict]:
        # Returns list of {id, from, subject, snippet, received}
```
NOTE: `GmailManager` does NOT exist. `get_unread_count()` does NOT exist. To get count, call `len(gm.list_unread(max_results=50))`.

From core/tools.py:757-784 (the canonical auth/tool singleton pattern):
```python
def _get_auth_manager() -> GoogleAuthManager:
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = build_auth_manager_from_env()
    return _auth_manager

def _get_gmail_tool() -> GmailTool:
    global _gmail_tool
    if _gmail_tool is None:
        _gmail_tool = GmailTool(auth_manager=_get_auth_manager())
    return _gmail_tool

def _get_calendar_tool() -> GoogleCalendarManager:
    global _calendar_tool
    if _calendar_tool is None:
        _calendar_tool = GoogleCalendarManager(auth_manager=_get_auth_manager())
    return _calendar_tool
```
**REUSE THESE** in `core/autonomous.py` (`from core.tools import _get_calendar_tool, _get_gmail_tool`) rather than reconstructing the auth chain.

From memory/firestore_conversation.py (verified — only get/append/clear exist):
```python
class FirestoreConversationStore:
    def get(self, user_id: int) -> list[dict]:
        # Returns [{"role": "user"|"assistant", "content": str}, ...] or [] if empty/expired
    def append(self, user_id: int, role: str, content: str) -> None: ...
    def clear(self, user_id: int) -> None: ...
```
NOTE: `get_last_user_timestamp()` does NOT exist. **This plan adds it** as a small clean addition to `FirestoreConversationStore` (preferred path). Alternative: iterate `store.get(user_id)` to find last user-role message — but the store's `messages` array does not carry per-message timestamps, so we read the doc-level `updated_at` field instead. **The cleanest implementation:** add `get_last_user_timestamp(user_id) -> datetime | None` that reads the doc and returns `updated_at` if the most-recent message is `role=="user"`, else iterates backward to find one (no per-message timestamp exists, so the doc `updated_at` is the closest signal). See Step C of Task 1.

From core/main.py:236-275 (`handle_message` per-message render — THE INJECTION SITE, verified):
```python
# This render lives in handle_message, NOT in _run_smart_loop.
# CONTEXT/RESEARCH claimed it was in _run_smart_loop — VERIFIED WRONG.
smart_system = (
    self._smart_prompt_template
    .replace("{self_md}", self._self_md_content)
    .replace("{self_state}", self_state_snippet)
    .replace("{journal_digest}", journal_digest)
    .replace("{today_date}", today_label)
)
```
Plan 06 must replicate this render step before calling `_run_smart_loop`. Task 0 adds a public method `AgentOrchestrator.render_smart_system(template)` to encapsulate it.

From core/main.py:295-345 (`_run_smart_loop` total-failure path — VERIFIED returns sentinel, does NOT raise):
```python
# On total LLM exhaustion, _run_smart_loop RETURNS this string instead of raising:
return (
    "I'm afraid I encountered a connectivity issue, Sir. "
    "Please try again in a moment."
)
```
Plan 06's Layer-2 fallback MUST detect this sentinel (substring match) and treat it as failure (BLOCKER 3).

From core/main.py:163-167 (`AgentOrchestrator` docstring — VERIFIED singleton contract):
```
Instantiate once at startup and share across all user sessions. The
LLMClient instances are stateless after construction; conversation state
is managed by ConversationManager.
```
Plan 06 implements a module-level singleton `_get_orchestrator()` for the cron path (BLOCKER 5(a)).

From core/main.py:43:
```python
MAX_TOOL_ITERATIONS = 8  # bounds Layer 2 tool iterations
```

From core/main.py:504-516 (existing `_load_prompt` pattern — STANDARDISE on this):
```python
def _load_prompt(relative_path: str) -> str:
    """Load a prompt file relative to the project root.
    Raises FileNotFoundError if the prompt file does not exist."""
    path = Path(relative_path)
    if not path.exists():
        raise FileNotFoundError(...)
    return path.read_text(encoding="utf-8").strip()
```
`core/autonomous.py` MUST use this same shape (relative path, Path(relative_path).read_text). Re-import from core.main: `from core.main import _load_prompt as _load_main_prompt` OR replicate the same shape locally. Reference: `core/main.py` calls `_load_prompt("prompts/smart_agent.md")` — same project-root-relative pattern in `core/reflection.py` and `core/proactive_alerts.py`.

From core/tick_brain.py (Plan 05 extended signature):
```python
TickBrain.think(prompt: str, tools=None, system_override: str | None = None) -> dict
# Returns {should_act, reason, draft?, topic_key?} or safe-mode {should_act: False, reason: 'parse_failure' | 'llm_error'}
```
**VERIFIED safe-mode reason strings:** `"parse_failure"` (tick_brain.py:174,178) and `"llm_error"` (tick_brain.py:139,150,153). `"fallback_failed"` is NOT emitted — do not test for it.

From memory/firestore_db.py (Plan 01 stores):
```python
FollowupStore.list_due(now_iso: str) -> list[dict]            # status='pending' AND due_at <= now_iso
FollowupStore.mark_done(fid: str) -> None
FollowupStore.defer(fid: str, new_due_at: str) -> None         # increments defer_count
OutreachLogStore.append(date_str: str, entry: dict) -> None    # ArrayUnion atomic
OutreachLogStore.topics_today(date_str: str) -> list[str]
```

From memory/firestore_db.py (existing — read for shape):
```python
SelfStateStore.get() -> dict          # {} on error, never raises
JournalStore.get(date_str: str) -> dict | None
JournalStore.get_recent(n: int) -> list[dict]
```

From core/proactive_alerts.py + core/scheduled_message.py:22 (send signature):
```python
async def send_and_inject(bot, text: str, *, inject_into_conversation: bool = False) -> None
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 0 (Wave 1 prep): Add public AgentOrchestrator.render_smart_system(template) method to core/main.py (BLOCKER 5b prep)</name>
  <files>core/main.py, tests/test_main_render_smart_system.py</files>
  <read_first>
    - core/main.py lines 236-275 (the existing inline render block inside `handle_message` — this is the source we extract from)
    - core/main.py lines 200-218 (`AgentOrchestrator.__init__` — confirms `_self_md_content`, `_self_state_store`, `_journal_store` are instance attrs we can reuse)
    - tests/test_main.py if it exists, or tests/test_reflection.py for mocking style
  </read_first>
  <behavior>
    - Test 1: `AgentOrchestrator.render_smart_system(template)` substitutes `{self_md}` with `_self_md_content`.
    - Test 2: When `_self_state_store` is None, the `{self_state}` placeholder is replaced with `""` (empty string), NOT left as a literal placeholder.
    - Test 3: When `_journal_store` is None, the `{journal_digest}` placeholder is replaced with `""`.
    - Test 4: `{today_date}` is replaced with the result of `_today_israel()`.
    - Test 5: After calling `render_smart_system`, the returned string contains NO literal `{self_md}`, `{self_state}`, `{journal_digest}`, or `{today_date}` substrings.
    - Test 6: `handle_message` still works end-to-end (regression test — mock LLM client, ensure no behavior change).
  </behavior>
  <action>
    Step A — Extract the existing render block (currently inline in `handle_message`, core/main.py:236-275) into a new public method on `AgentOrchestrator`. Place the new method directly above or below `handle_message`. Signature:

    ```python
    def render_smart_system(self, template: str) -> str:
        """Render a smart_system template by substituting all standard placeholders.

        Resolves: `{self_md}`, `{self_state}`, `{journal_digest}`, `{today_date}`.
        Empty stores (None) substitute empty strings (NOT literal placeholders).

        Used by:
          - handle_message (per-message chat path)
          - core/autonomous.py:_compose_layer2 (per-tick autonomous path) — Plan 18-06

        Stable content (self_md) is placed before dynamic content for Gemini prompt caching.
        """
        today_label = _today_israel()

        # Build self_state snippet — omit blank fields per D-05.
        self_state_snippet = ""
        if self._self_state_store is not None:
            state = self._self_state_store.get()
            non_empty = {k: v for k, v in state.items()
                         if k not in ("updated_at", "bootstrapped_at") and v}
            if non_empty:
                lines = ["**Self-state:**"]
                for key, value in non_empty.items():
                    lines.append(f"- {key}: {value}")
                self_state_snippet = "\n".join(lines)

        # Build journal_digest — last ~3 entries, newest-first.
        journal_digest = ""
        if self._journal_store is not None:
            entries = self._journal_store.get_recent(3)
            if entries:
                lines = ["**Recent journal:**"]
                for e in entries:
                    line = f"- {e.get('date','')} (mood: {e.get('mood','')}): {e.get('summary','')}"
                    highlights = e.get("highlights") or []
                    if highlights:
                        line += f" | {highlights[0]}"
                    lines.append(line)
                journal_digest = "\n".join(lines)

        return (
            template
            .replace("{self_md}", self._self_md_content)
            .replace("{self_state}", self_state_snippet)
            .replace("{journal_digest}", journal_digest)
            .replace("{today_date}", today_label)
        )
    ```

    Step B — Refactor `handle_message` to call the new method instead of inlining the render. Replace lines ~239-275 (the entire today_label / self_state_snippet / journal_digest / smart_system block) with a single call:

    ```python
    smart_system = self.render_smart_system(self._smart_prompt_template)
    worker_system = self._worker_prompt_template.replace("{today_date}", _today_israel())
    ```

    **Behavior must be IDENTICAL** — this is a pure refactor. If your edit changes any observable behavior of `handle_message`, you've done it wrong.

    Step C — Create `tests/test_main_render_smart_system.py` with the 6 tests above. Use `unittest.mock.MagicMock` to stub `_self_state_store`, `_journal_store`, and the LLM clients. Pattern reference: `tests/test_reflection.py`.

    Step D — Run full test suite to confirm no regressions: `pytest tests/ -x`.
  </action>
  <verify>
    <automated>grep -n "def render_smart_system" core/main.py && pytest tests/test_main_render_smart_system.py -x && pytest tests/ -x</automated>
  </verify>
  <done>
    - `grep -c "def render_smart_system" core/main.py` == 1
    - `grep -c "self.render_smart_system" core/main.py` >= 1 (handle_message uses it)
    - All 6 new tests pass
    - Full test suite still passes (no regressions)
    - `handle_message` line count after refactor is smaller than before (proves render block was extracted)
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 1: Write Wave 0 test scaffold (tests/test_autonomous.py) + implement Layer-0 helpers (gather_situation, _build_triage_prompt, _synthesize_topic_key, _now_context, _is_empty_signals + helpers) + add FirestoreConversationStore.get_last_user_timestamp</name>
  <files>core/autonomous.py, tests/test_autonomous.py, memory/firestore_conversation.py</files>
  <read_first>
    - core/reflection.py (full read — `_gather_day` is the structural analog; `run_reflection` shows how a cron-driven orchestrator is built; `_minimal_fallback_entry` analog for D-19)
    - core/proactive_alerts.py (full read — `run_proactive_alerts` is the secondary analog for cron→detect→compose→send shape; `_already_sent`/`_mark_processed` pattern)
    - core/tick_brain.py (Plan 05 output — confirm new `system_override` kwarg present, `_parse_response` topic_key; **VERIFIED safe-mode reasons are "parse_failure" and "llm_error" only**)
    - core/main.py lines 295-345 (`_run_smart_loop` total-failure RETURNS sentinel string starting with "I'm afraid I encountered a connectivity" — DOES NOT raise; this is BLOCKER 3 evidence)
    - core/main.py lines 504-516 (`_load_prompt` strategy — relative path from project root; WARNING 2 fix)
    - core/scheduled_message.py (`send_and_inject` full signature)
    - core/tools.py lines 748-784 (auth/gmail/calendar singleton pattern — REUSE `_get_gmail_tool`, `_get_calendar_tool` from here)
    - memory/firestore_db.py (Plan 01 — FollowupStore + OutreachLogStore + JournalStore + SelfStateStore)
    - memory/firestore_conversation.py (full read — confirms only `get`/`append`/`clear` exist; we ADD `get_last_user_timestamp` here)
    - prompts/autonomous_triage.md (Plan 03 output — confirm placeholder tokens that `_build_triage_prompt` must substitute)
    - mcp_tools/calendar_tool.py (VERIFY class name `GoogleCalendarManager`, method `list_events(time_min_iso, time_max_iso)`)
    - mcp_tools/ticktick_tool.py (VERIFY module function `get_today_tasks()` returns dict with `"overdue"` key)
    - mcp_tools/gmail_tool.py (VERIFY class name `GmailTool`, method `list_unread(max_results)`)
    - tests/test_reflection.py (full read — mocking patterns for cron-orchestrator tests)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "core/autonomous.py" — Mechanical Hot-Spots; "Per-source error isolation" shared pattern)
    - .planning/phases/18-autonomous-engine/18-VALIDATION.md (per-task table rows 18-06-01 to 18-06-08)
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-02..D-22)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "core/autonomous.py (NEW)" lines 92-125)
  </read_first>
  <behavior>
    Wave 0 test scaffold — create `tests/test_autonomous.py`:
    - test_pre_flight_imports_resolve (Task 1 GREEN — guards against BLOCKER 1)
    - test_gather_situation_isolation (Task 1 GREEN)
    - test_gather_situation_now_context_block (Task 1 GREEN)
    - test_gather_situation_empty_signal_detection (Task 1 GREEN)
    - test_synthesize_topic_key_for_each_trigger_type (Task 1 GREEN)
    - test_build_triage_prompt_substitutes_all_placeholders (Task 1 GREEN)
    - test_quiet_situation_skips_tick_brain (Task 1 GREEN — BLOCKER 2 fix)
    - test_calendar_overload_triggers_non_empty (Task 1 GREEN — BLOCKER 2 fix)
    - test_calendar_overlap_triggers_non_empty (Task 1 GREEN — BLOCKER 2 fix)
    - test_calendar_with_single_non_conflicting_event_is_quiet (Task 1 GREEN — BLOCKER 2 fix)
    - test_now_context_tick_index_at_7_00_is_1 (Task 1 GREEN — WARNING 3 fix)
    - test_now_context_tick_index_at_21_00_is_43 (Task 1 GREEN — WARNING 3 fix)
    - test_now_context_tick_index_clamps_for_early_hours (Task 1 GREEN — WARNING 3 fix)
    - test_hours_since_contact_no_record_renders_as_unknown_in_prompt (Task 1 GREEN — WARNING 4 fix)
    - test_load_prompt_resolves_paths_correctly (Task 1 GREEN — WARNING 2 fix)
    - test_firestore_conversation_get_last_user_timestamp_returns_none_when_empty (Task 1 GREEN — new method test)
    - The remaining tests for `run_autonomous_tick` are filled in Task 2 — leave them as `@pytest.mark.skip(reason="Task 2 GREEN")` stubs HERE so the test file builds out cleanly.

    Per-test specifics:
    - `test_pre_flight_imports_resolve` (BLOCKER 1 guard): ensure `from mcp_tools.calendar_tool import GoogleCalendarManager`, `from mcp_tools.ticktick_tool import get_today_tasks`, `from mcp_tools.gmail_tool import GmailTool`, `from memory.firestore_conversation import FirestoreConversationStore` all succeed without raising. The test is one-liner imports inside the test body.
    - `test_gather_situation_isolation`: mock all 8 sources; make one (e.g., calendar via `core.tools._get_calendar_tool`) raise `RuntimeError("kaboom")`; assert returned dict has all 8 keys; assert no exception propagates.
    - `test_gather_situation_now_context_block`: assert returned dict has `now_context` with keys `now_iso`, `now_local`, `tick_index`, `tick_total`, `last_tick_at`; assert `tick_total == 43` (WARNING 3).
    - `test_gather_situation_empty_signal_detection`: mock all sources to return empty; assert returned dict has `empty == True`.
    - `test_quiet_situation_skips_tick_brain` (BLOCKER 2): mock calendar with one non-conflicting event (standup 10:00-10:30 only); mock ticktick_overdue=[]; due_followups=[]; assert situation `empty == True` (since calendar event has no overlap/overload).
    - `test_calendar_overload_triggers_non_empty` (BLOCKER 2): 3 events in next 2 hours; assert `_calendar_has_gap_or_overload(events, now_ctx) == True` and `_is_empty_signals(situation) == False`.
    - `test_calendar_overlap_triggers_non_empty` (BLOCKER 2): two events with overlapping time ranges; assert `_calendar_has_gap_or_overload(events, now_ctx) == True`.
    - `test_calendar_with_single_non_conflicting_event_is_quiet` (BLOCKER 2): exactly one event today, no overlap, no overload; assert `_calendar_has_gap_or_overload(events, now_ctx) == False`.
    - `test_now_context_tick_index_at_7_00_is_1`: pass `now = datetime(2026,5,21,7,0,0)`; assert `tick_index == 1`.
    - `test_now_context_tick_index_at_21_00_is_43`: pass `now = datetime(2026,5,21,21,0,0)`; assert `tick_index == 43`.
    - `test_now_context_tick_index_clamps_for_early_hours`: pass `now = datetime(2026,5,21,3,0,0)`; assert no exception AND `tick_index >= 1` (clamped to 1, not negative).
    - `test_hours_since_contact_no_record_renders_as_unknown_in_prompt` (WARNING 4): pass `hours_since_contact = None`; assert built triage prompt contains the literal string `"unknown"` for the contact line; assert it does NOT contain `999`.
    - `test_load_prompt_resolves_paths_correctly` (WARNING 2): call `_load_prompt("prompts/autonomous_triage.md")` from project root; assert file content returned (not error); confirm the strategy matches `core/main.py:_load_prompt` (relative path).
    - `test_firestore_conversation_get_last_user_timestamp_returns_none_when_empty`: instantiate FirestoreConversationStore (or mock its `get`), assert `get_last_user_timestamp(user_id)` returns `None` when conversation is empty.
    - `test_synthesize_topic_key_for_each_trigger_type`: call `_synthesize_topic_key("overdue", situation_dict)` and assert returns string matching `^overdue:`; same for `silence`, `gap`, `followup`, `quiet`. Empty-key inputs never return empty string.
    - `test_build_triage_prompt_substitutes_all_placeholders`: feed a complete situation dict; assert returned string has NO unresolved `{situation_snapshot}`, `{self_state_block}`, `{journal_digest}`, `{now_context}`, `{outreach_log_today}` placeholders and contains representative substrings from each input block.
  </behavior>
  <action>
    Step A — Create `tests/test_autonomous.py` skeleton. Use the test patterns from `tests/test_reflection.py`. Include `@pytest.mark.skip(reason="Task 2 GREEN")` stubs for the run_autonomous_tick tests so the file structure is complete from Task 1.

    Step B — Extend `memory/firestore_conversation.py` with a new method `get_last_user_timestamp` (BLOCKER 1 fix). Add this method to the `FirestoreConversationStore` class:

    ```python
    def get_last_user_timestamp(self, user_id: int) -> datetime | None:
        """Return the timestamp of the most recent user-role message for user_id.

        Per-message timestamps are not stored; the closest signal we have is the
        document-level `updated_at` field, written on every append. We return
        `updated_at` when the most-recent message in the array is role=='user',
        else None (no user message stored in this session window).

        Returns None on empty/expired conversation OR on Firestore error.
        Never raises.

        Added in Phase 18 for autonomous tick's hours_since_contact signal.
        """
        doc_ref = self._col.document(str(user_id))
        try:
            snapshot = doc_ref.get()
        except GoogleAPICallError:
            logger.warning(
                "FirestoreConversationStore.get_last_user_timestamp failed for user_id=%d",
                user_id,
            )
            return None
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        updated_at = data.get("updated_at")
        messages = data.get("messages") or []
        if not messages:
            return None
        # Find the most recent user-role message. We have no per-message timestamps,
        # so updated_at is the best signal — return it iff a user message exists.
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return updated_at if isinstance(updated_at, datetime) else None
        return None
    ```

    Add a small unit test in `tests/test_firestore_conversation.py` (or wherever existing tests for this class live) — but the primary contract test is the test in `tests/test_autonomous.py` from Task 1's behavior block.

    Step C — Create `core/autonomous.py` with the Layer-0 / utility functions ONLY (Task 2 adds `run_autonomous_tick` + `_compose_layer2` + `_compose_followup`).

    File skeleton:
    ```python
    """Autonomous tick orchestrator — Klaus's judgment-driven proactive outreach.

    Called by Cloud Scheduler via Cloud Run:
      POST /cron/autonomous-tick  (*/20 7-21 * * *, Asia/Jerusalem)

    3-layer design (D-20):
      Layer 0 — gather_situation(): free aggregation from 8 sources, per-source isolation.
      Layer 1 — TickBrain.think() with system_override=autonomous_triage.md; returns
                {should_act, reason, draft, topic_key}.
      Layer 2 — _run_smart_loop with synthetic [{role: user, content: ...}] messages
                and prompts/autonomous.md as smart_system; full tool-loop bounded by
                MAX_TOOL_ITERATIONS.

    Repeat-suppression (D-06/D-09): per-day outreach_log/{date} doc; informative
    to triage prompt, not blocking.

    Phase 18 — AUTO-01, AUTO-02, AUTO-03.
    """
    from __future__ import annotations

    import json
    import logging
    import os
    from datetime import date, datetime, timedelta, timezone
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from telegram import Bot

    logger = logging.getLogger(__name__)

    _TZ = ZoneInfo("Asia/Jerusalem")

    # Cron */20 7-21 = ticks at 7:00, 7:20, 7:40, 8:00, ..., 21:00 = 43 ticks/day inclusive.
    # (21 - 7) hours * 3 ticks/hour = 42 intervals, but the 21:00 tick fires too, making 43.
    _TICK_TOTAL_PER_DAY = 43

    _DEFER_FORCE_FIRE_THRESHOLD = 3  # D-14: defer_count >= 3 force-fires next due tick

    # BLOCKER 3 guard — _run_smart_loop RETURNS this sentinel string on total LLM exhaustion
    # (core/main.py:337-345). Layer-2 callers MUST detect it and treat as failure (D-19 fallback).
    _SMART_LOOP_ERROR_SENTINELS = (
        "I'm afraid I encountered a connectivity",
    )


    def _load_prompt(relative_path: str) -> str:
        """Load a prompt file by project-root-relative path.

        Mirrors core/main.py:_load_prompt strategy (WARNING 2 fix — single
        path strategy across the codebase). Cloud Run sets CWD to /workspace
        which is the project root; local dev runs from the project root too.

        Raises:
            FileNotFoundError: If the prompt file does not exist.
        """
        path = Path(relative_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Prompt file not found: {path.resolve()}. "
                "Ensure you are running from the project root."
            )
        return path.read_text(encoding="utf-8").strip()


    def _now_context(now: datetime) -> dict:
        """Build the now_context block per D-08.

        Tick window 07:00..21:00, every 20 minutes inclusive = 43 ticks (WARNING 3 fix).
        tick_index is 1-indexed for display ("tick 22 of 43").
        For hours <7 (manual test invocations), clamps to tick_index=1.
        """
        local = now.astimezone(_TZ)
        # WARNING 3: guard against negative minutes (hour < 7 from manual test runs).
        minutes_into_window = max(0, (local.hour - 7) * 60 + local.minute)
        tick_index = max(1, (minutes_into_window // 20) + 1)
        # Cap at the total — late ticks past 21:00 (manual test) shouldn't display "tick 50 of 43".
        tick_index = min(tick_index, _TICK_TOTAL_PER_DAY)
        last_tick_local = local - timedelta(minutes=20)
        return {
            "now_iso": now.isoformat(),
            "now_local": local.strftime("%H:%M %Z"),
            "tick_index": tick_index,
            "tick_total": _TICK_TOTAL_PER_DAY,
            "last_tick_at": last_tick_local.strftime("%H:%M"),
        }


    def _calendar_has_gap_or_overload(events: list[dict], now_ctx: dict) -> bool:
        """BLOCKER 2 fix — narrow calendar-signal detection.

        Returns True only if at least one of:
          - Two events overlap (start_a < end_b AND start_b < end_a), OR
          - More than 2 events fall in the next 2 hours from now.

        A single non-conflicting event ("Standup 10:00-10:30") is NOT a signal —
        normal workdays have events all day; treating "any event" as signal
        defeats SC-3 cost control.

        (Gap detection — a 90+ min gap between events during productive window —
        is intentionally deferred to a future iteration; we mark it as Claude's
        discretion if added later.)
        """
        if not events:
            return False

        # Parse start/end pairs into tz-aware datetimes for comparison.
        parsed: list[tuple[datetime, datetime]] = []
        for e in events:
            s_raw = e.get("start") or ""
            e_raw = e.get("end") or ""
            try:
                s = datetime.fromisoformat(s_raw.replace("Z", "+00:00")) if s_raw else None
                en = datetime.fromisoformat(e_raw.replace("Z", "+00:00")) if e_raw else None
            except (ValueError, TypeError):
                continue
            if s and en:
                parsed.append((s, en))

        # (1) Pairwise overlap detection.
        for i, (a_s, a_e) in enumerate(parsed):
            for (b_s, b_e) in parsed[i + 1:]:
                if a_s < b_e and b_s < a_e:
                    return True

        # (2) >2 events in the next 2 hours.
        try:
            now_local = datetime.fromisoformat(now_ctx.get("now_iso", "").replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False
        horizon = now_local + timedelta(hours=2)
        upcoming_count = sum(
            1 for (s, _e) in parsed if now_local <= s <= horizon
        )
        if upcoming_count > 2:
            return True

        return False


    def _is_empty_signals(situation: dict) -> bool:
        """D-11 Layer-0 gate. Return True if nothing salient is present.

        BLOCKER 2 fix: calendar signal is "GAP / OVERLOAD" per D-01/D-11 —
        NOT "any calendar event exists". A normal workday with a standup
        and a workout block must be treated as quiet unless those events
        overlap, overload the next 2h, or there's an actionable overdue/followup.
        """
        if situation.get("ticktick_overdue"):
            return False
        if situation.get("due_followups"):
            return False
        if _calendar_has_gap_or_overload(
            situation.get("calendar") or [],
            situation.get("now_context") or {},
        ):
            return False
        return True


    def gather_situation(now: datetime) -> dict:
        """Layer 0 — aggregate situation snapshot from 8 sources with per-source isolation.

        Each source lives in its own try/except. Failures are logged and the source falls
        back to a sentinel (empty list / 0 / empty string / None). One failure does NOT
        mask others — critical for the D-11 empty-signals detection.

        Uses REAL APIs verified from source (BLOCKER 1 fix):
          - GoogleCalendarManager.list_events(time_min_iso, time_max_iso)
          - ticktick_tool.get_today_tasks() (returns dict with 'overdue' key)
          - GmailTool(auth_manager).list_unread(max_results)
          - FirestoreConversationStore.get_last_user_timestamp(user_id)
        """
        gathered: dict = {
            "calendar": [],
            "ticktick_overdue": [],
            "unread_email_count": 0,
            "due_followups": [],
            "hours_since_contact": None,   # WARNING 4: None means "unknown/never contacted"
            "recent_journal_digest": "",
            "self_state": {},
            "today_outreach_log": [],
            "now_context": _now_context(now),
        }

        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")

        # (a) Calendar — today's events. Use the shared singleton from core.tools to avoid
        # re-bootstrapping GoogleAuthManager and OAuth tokens on every tick (BLOCKER 5 spirit).
        try:
            from core.tools import _get_calendar_tool
            cal = _get_calendar_tool()
            local = now.astimezone(_TZ)
            day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            gathered["calendar"] = cal.list_events(
                day_start.isoformat(),
                day_end.isoformat(),
                max_results=50,
            ) or []
        except Exception:
            logger.warning("autonomous: calendar gather failed", exc_info=True)

        # (b) TickTick overdue (BLOCKER 1 fix — module function, not a class).
        try:
            from mcp_tools import ticktick_tool
            tasks = ticktick_tool.get_today_tasks() or {}
            gathered["ticktick_overdue"] = tasks.get("overdue", []) or []
        except Exception:
            logger.warning("autonomous: ticktick gather failed", exc_info=True)

        # (c) Unread email count (BLOCKER 1 fix — GmailTool, not GmailManager;
        # uses list_unread length, not non-existent get_unread_count).
        try:
            from core.tools import _get_gmail_tool
            gm = _get_gmail_tool()
            gathered["unread_email_count"] = len(gm.list_unread(max_results=50))
        except Exception:
            logger.warning("autonomous: gmail gather failed", exc_info=True)

        # (d) Due follow-ups
        try:
            from memory.firestore_db import FollowupStore
            fs = FollowupStore(project_id=project_id, database=database)
            gathered["due_followups"] = fs.list_due(now.astimezone(timezone.utc).isoformat())
        except Exception:
            logger.warning("autonomous: followup gather failed", exc_info=True)

        # (e) Hours since last user contact (BLOCKER 1 fix — get_last_user_timestamp is a new
        # method added to FirestoreConversationStore in this plan; WARNING 4 fix — None on
        # never-contacted instead of 999.0 which would render as "Sir vanished" every tick).
        try:
            from memory.firestore_conversation import FirestoreConversationStore
            from core.tools import _telegram_user_id  # if available; else read from env
            user_id = int(os.environ.get("TELEGRAM_USER_ID", "0"))
            store = FirestoreConversationStore(project_id=project_id, database=database)
            last_ts = store.get_last_user_timestamp(user_id)
            if last_ts:
                delta = now.astimezone(timezone.utc) - last_ts.astimezone(timezone.utc)
                gathered["hours_since_contact"] = round(delta.total_seconds() / 3600.0, 2)
            else:
                gathered["hours_since_contact"] = None  # WARNING 4: None == "unknown"
        except Exception:
            logger.warning("autonomous: hours_since_contact gather failed", exc_info=True)

        # (f) Recent journal digest (last 3 entries)
        try:
            from memory.firestore_db import JournalStore
            js = JournalStore(project_id=project_id, database=database)
            digest_parts = []
            for days_back in range(0, 3):
                d = (now.astimezone(_TZ).date() - timedelta(days=days_back)).isoformat()
                entry = js.get(d)
                if entry:
                    digest_parts.append(f"[{d}] {entry.get('summary', '')}")
            gathered["recent_journal_digest"] = "\n".join(digest_parts)
        except Exception:
            logger.warning("autonomous: journal digest gather failed", exc_info=True)

        # (g) Self-state (current_focus, mood)
        try:
            from memory.firestore_db import SelfStateStore
            ss = SelfStateStore(project_id=project_id, database=database)
            gathered["self_state"] = ss.get() or {}
        except Exception:
            logger.warning("autonomous: self_state gather failed", exc_info=True)

        # (h) Today's outreach log topics
        try:
            from memory.firestore_db import OutreachLogStore
            ols = OutreachLogStore(project_id=project_id, database=database)
            today_iso = now.astimezone(_TZ).date().isoformat()
            gathered["today_outreach_log"] = ols.topics_today(today_iso)
        except Exception:
            logger.warning("autonomous: outreach_log gather failed", exc_info=True)

        # D-11 Layer-0 gate (BLOCKER 2 — narrow calendar detection).
        gathered["empty"] = _is_empty_signals(gathered)
        if gathered["empty"]:
            gathered["raw_signals"] = {
                "ticktick_overdue_count": len(gathered.get("ticktick_overdue") or []),
                "due_followups_count": len(gathered.get("due_followups") or []),
                "calendar_count": len(gathered.get("calendar") or []),
                "hours_since_contact": gathered.get("hours_since_contact"),
            }
        return gathered


    def _synthesize_topic_key(trigger_hint: str, situation: dict) -> str:
        """Pitfall 4 fallback — synthesize a topic_key when tick-brain returns empty.

        Examples:
          _synthesize_topic_key("overdue", sit) -> "overdue:auto-<first-task-slug>"
          _synthesize_topic_key("silence", sit) -> "silence:tick-<N>"
          _synthesize_topic_key("gap",     sit) -> "gap:tick-<N>"
          _synthesize_topic_key("followup", sit) -> "followup:<id>"
          _synthesize_topic_key("quiet",   sit) -> "quiet:tick-<N>"
        Never returns empty string.
        """
        tick_idx = situation.get("now_context", {}).get("tick_index", 0)
        trigger = (trigger_hint or "general").lower().strip()
        if trigger == "overdue":
            overdue = situation.get("ticktick_overdue") or []
            if overdue:
                title = str(overdue[0].get("title") or overdue[0].get("id") or "0")
                slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:30].strip("-") or "0"
                return f"overdue:auto-{slug}"
            return f"overdue:auto-tick-{tick_idx}"
        if trigger == "followup":
            fus = situation.get("due_followups") or []
            if fus:
                return f"followup:{fus[0].get('id', 'unknown')}"
            return f"followup:tick-{tick_idx}"
        return f"{trigger}:tick-{tick_idx}"


    def _build_triage_prompt(situation: dict, triage_system: str) -> str:
        """Build the user-message content for the triage call.

        triage_system is reserved for future use; the actual triage system prompt
        is passed to TickBrain.think via system_override. WARNING 4 fix: when
        hours_since_contact is None, renders as "unknown" rather than "999.0"
        which the LLM would interpret as "Sir vanished".
        """
        snap = {
            "calendar": situation.get("calendar", []),
            "ticktick_overdue": situation.get("ticktick_overdue", []),
            "unread_email_count": situation.get("unread_email_count", 0),
            "due_followups": situation.get("due_followups", []),
        }
        hsc = situation.get("hours_since_contact")
        snap["hours_since_contact"] = "unknown" if hsc is None else hsc
        snap_json = json.dumps(snap, indent=2, ensure_ascii=False)

        self_state = situation.get("self_state") or {}
        self_state_block = (
            f"current_focus: {self_state.get('current_focus', '')}\n"
            f"mood: {self_state.get('mood', '')}"
        )

        journal = situation.get("recent_journal_digest") or "(no recent journal entries)"
        nc = situation.get("now_context") or {}
        now_context_block = (
            f"now: {nc.get('now_local', '')}\n"
            f"tick {nc.get('tick_index', 0)} of {nc.get('tick_total', _TICK_TOTAL_PER_DAY)}\n"
            f"last tick at: {nc.get('last_tick_at', '')}"
        )
        outreach_today = situation.get("today_outreach_log") or []
        outreach_block = ", ".join(outreach_today) if outreach_today else "(none yet)"

        return (
            f"Situation snapshot:\n{snap_json}\n\n"
            f"My self-state:\n{self_state_block}\n\n"
            f"My recent journal:\n{journal}\n\n"
            f"Time context:\n{now_context_block}\n\n"
            f"Topics I have already raised today:\n{outreach_block}\n"
        )
    ```

    Step D — Verify Task 1 tests pass with this much of the module:
    `pytest tests/test_autonomous.py -x -k "not skip"`

    All active tests should pass. Skipped stubs remain for Task 2.
  </action>
  <verify>
    <automated>test -f core/autonomous.py && grep -n "def gather_situation" core/autonomous.py && grep -n "def _synthesize_topic_key" core/autonomous.py && grep -n "def _build_triage_prompt" core/autonomous.py && grep -n "def _calendar_has_gap_or_overload" core/autonomous.py && grep -n "_SMART_LOOP_ERROR_SENTINELS" core/autonomous.py && grep -n "_TICK_TOTAL_PER_DAY = 43" core/autonomous.py && grep -n "def get_last_user_timestamp" memory/firestore_conversation.py && pytest tests/test_autonomous.py -x -k "not skip"</automated>
  </verify>
  <done>
    - `core/autonomous.py` exists with `gather_situation`, `_now_context`, `_is_empty_signals`, `_calendar_has_gap_or_overload`, `_synthesize_topic_key`, `_build_triage_prompt`, `_load_prompt`, `_SMART_LOOP_ERROR_SENTINELS`, `_TICK_TOTAL_PER_DAY = 43` defined
    - `memory/firestore_conversation.py` has new method `get_last_user_timestamp`
    - `tests/test_autonomous.py` exists with all Task-1 tests + skipped stubs for Task 2
    - All active Task-1 tests pass (including the BLOCKER-regression tests)
    - `python -c "import core.autonomous as a; print(a.gather_situation.__doc__[:50])"` works
    - Pre-flight import test passes (BLOCKER 1 guard)
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement run_autonomous_tick + _compose_layer2 (with render_smart_system + sentinel detection) + _compose_followup + module singleton + remaining tests</name>
  <files>core/autonomous.py, tests/test_autonomous.py</files>
  <read_first>
    - core/autonomous.py (your Task 1 output)
    - core/main.py (your Task 0 output — confirm `render_smart_system` method exists)
    - tests/test_autonomous.py (your Task 1 stubs — un-skip them in this task)
    - core/main.py lines 295-345 (`_run_smart_loop` — VERIFIED returns sentinel string on total LLM failure, does NOT raise — BLOCKER 3 evidence)
    - core/proactive_alerts.py lines 91-140 (cron-driven orchestrator end-to-end: compose → send → mark)
    - core/scheduled_message.py (send_and_inject signature — inject_into_conversation=True kwarg)
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-10, D-11, D-13, D-14, D-17, D-18, D-19, D-20)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (Pitfalls 2, 3, 4, 6)
    - .planning/phases/18-autonomous-engine/18-VALIDATION.md (test cases 18-06-02 to 18-06-08)
  </read_first>
  <behavior>
    Un-skip and implement the following tests in `tests/test_autonomous.py`:

    - `test_run_autonomous_tick_decision_trail`: 4 sub-cases (parametrize or 4 separate tests):
      - Empty-signal skip: `gather_situation` returns `empty=True`; assert `tick_brain.think` NOT called, `send_and_inject` NOT called, return dict has `skipped: 'empty'`.
      - Triage-no: tick_brain returns `{should_act: False}`; assert `_run_smart_loop` NOT called, `send_and_inject` NOT called.
      - Triage-yes → compose-yes: tick_brain returns `{should_act: True, draft: "...", topic_key: "x:y"}`; `_run_smart_loop` returns "final text"; assert `send_and_inject(bot, "final text", inject_into_conversation=True)` called; `OutreachLogStore.append` called with `{topic_key: "x:y", ..., final: "final text"}`.
      - Triage-yes → compose-fail-fallback: tick_brain returns `{should_act: True, draft: "raw draft", topic_key: "x:y"}`; `_run_smart_loop` raises `Exception`; assert `send_and_inject(bot, "raw draft", inject_into_conversation=True)` called; `OutreachLogStore.append` called with `{topic_key: "x:y", ..., final: "raw draft"}`.

    - `test_layer2_returns_smart_loop_error_sentinel_falls_back_to_draft` (BLOCKER 3 fix): mock `AgentOrchestrator._run_smart_loop` to RETURN (not raise) the literal sentinel `"I'm afraid I encountered a connectivity issue, Sir. Please try again in a moment."`; assert `send_and_inject` is called with the tick-brain `draft`, NOT the sentinel; assert outreach_log `final == draft`.

    - `test_layer2_smart_system_has_placeholders_resolved` (BLOCKER 5b fix): capture the `smart_system` argument passed to `_run_smart_loop`; assert it does NOT contain literal `{self_md}`, `{self_state}`, `{journal_digest}`, or `{today_date}` substrings.

    - `test_orchestrator_is_module_singleton` (BLOCKER 5a fix): call `_get_orchestrator()` twice; assert the SAME object is returned (`is` identity, not just equal); assert `AgentOrchestrator.__init__` is called exactly once across the two calls.

    - `test_outreach_log_on_success_only` (D-10 / Pitfall 3): mock `send_and_inject` to raise; assert `OutreachLogStore.append` is NOT called.

    - `test_synthetic_message_does_not_pollute_history` (Pitfall 2): mock `AgentOrchestrator.handle_message` AND `conversation_manager.append`; run a tick that escalates; assert `handle_message` NOT called AND `conversation_manager.append("user", ANY)` NOT called.

    - `test_defer_force_fire_at_three` (D-14 / Pitfall 6): set up a due follow-up with `defer_count=3`; mock Layer-2 to return JSON `{"action": "defer"}`; assert that despite the LLM saying defer, `send_and_inject` IS called (force-fire override); `FollowupStore.mark_done` is called.

    - `test_topic_key_fallback` (D-07 / Pitfall 4): tick_brain returns `{should_act: True, draft: "...", reason: "..."}` (NO topic_key); assert `OutreachLogStore.append` is called with a non-empty `topic_key` synthesised by `_synthesize_topic_key`.

    - `test_followup_fire_skips_tick_brain` (D-13): gather returns 1 due followup AND empty otherwise; assert `tick_brain.think` is NOT called for the follow-up path.

    - `test_layer2_followup_send_action_marks_done`: Layer-2 returns `{"action": "send"}`; assert `FollowupStore.mark_done(fid)` called; `send_and_inject` called.

    - `test_layer2_followup_defer_below_three_does_not_send`: Layer-2 returns `{"action": "defer"}` with defer_count=1; assert `send_and_inject` NOT called; `FollowupStore.defer(fid, new_due_at)` called with `new_due_at` = original due + 1 hour.

    - `test_malformed_json_block_stripped_from_polished_text` (WARNING 5 fix): pass Layer-2 output containing `"some text ```json {malformed bad json``` "` — `_parse_followup_action` returns `("send", "some text")` (with the malformed JSON block stripped, not leaking to the user).

    - `test_lllm_purpose_strings`: assert tick_brain called with system_override; assert (via mock spy) purpose strings used downstream match `"tick_autonomous"` (Layer 1).
  </behavior>
  <action>
    Step A — Append to `core/autonomous.py`. Note the key changes vs the previous round (BLOCKERs 3, 5a, 5b, WARNING 5):

    ```python
    # BLOCKER 5a fix — module-level singleton, instantiated once per process.
    _orchestrator_singleton = None  # type: ignore[var-annotated]


    def _get_orchestrator():
        """Return the process-wide AgentOrchestrator singleton.

        AgentOrchestrator.__init__ reads SELF.md from disk, bootstraps
        SelfStateStore, and constructs 3 LLMClients — ~42 times/day is wasteful.
        Singleton lives for the Cloud Run instance lifetime (which is typically
        many ticks before scale-to-zero).
        """
        global _orchestrator_singleton
        if _orchestrator_singleton is None:
            from core.main import AgentOrchestrator
            _orchestrator_singleton = AgentOrchestrator()
        return _orchestrator_singleton


    async def run_autonomous_tick(bot, now: datetime | None = None) -> dict:
        """Top-level autonomous tick orchestrator.

        3-layer pipeline per D-20:
          1. gather_situation (Layer 0) — fast, no LLM
          2. If empty signals → return early (D-11 gate; cost control)
          3. Due follow-ups (D-13) → dedicated Layer-2 compose loop (no tick-brain)
          4. Triage (Layer 1) — TickBrain.think with autonomous_triage system_override
          5. If should_act=False → log + return
          6. Compose (Layer 2) — synthetic [{role:user, content}] via _run_smart_loop with
             autonomous.md as smart_system; on total failure (raise OR sentinel return),
             fall back to tick-brain draft (D-19, BLOCKER 3)
          7. Send via send_and_inject(..., inject_into_conversation=True) (D-18)
          8. ONLY on send success: append to outreach_log (D-10)

        Returns a decision-trail dict for tick_logs / debugging.
        """
        import asyncio as _asyncio
        if now is None:
            now = datetime.now(_TZ)

        situation = gather_situation(now)
        decision = {"skipped": False, "sent": False, "trail": []}

        # Layer 0 gate (D-11 / SC-3)
        if situation.get("empty"):
            decision["skipped"] = "empty"
            decision["trail"].append("layer0_empty_signals")
            await _write_tick_log(now, situation, decision)
            return decision

        # Due follow-ups path (D-13) — dedicated Layer 2, no tick-brain
        due_followups = situation.get("due_followups") or []
        if due_followups:
            for fu in due_followups:
                fu_decision = await _compose_followup(bot, fu, situation, now)
                decision["trail"].append({"followup": fu.get("id"), "outcome": fu_decision})
            # Continue: a followup firing doesn't preclude an overdue alert via triage.

        # Layer 1 — triage
        try:
            from core.tick_brain import TickBrain
            tb = TickBrain()
            triage_system = _load_prompt("prompts/autonomous_triage.md")
            triage_user_msg = _build_triage_prompt(situation, triage_system)
            verdict = tb.think(triage_user_msg, system_override=triage_system)
        except Exception:
            logger.error("autonomous: Layer 1 (triage) failed entirely", exc_info=True)
            decision["trail"].append("layer1_exception")
            await _write_tick_log(now, situation, decision)
            return decision

        decision["trail"].append({"layer1": verdict})

        if not verdict.get("should_act"):
            decision["trail"].append("layer1_no_act")
            await _write_tick_log(now, situation, decision)
            return decision

        # Layer 2 — compose. Pitfall 2: build messages FRESHLY, do NOT call handle_message.
        draft = verdict.get("draft", "")
        triage_reason = verdict.get("reason", "")
        topic_key = verdict.get("topic_key") or ""
        if not topic_key:
            # Pitfall 4 — synthesise from trigger hint
            trigger_hint = _infer_trigger_type(situation)
            topic_key = _synthesize_topic_key(trigger_hint, situation)
            decision["trail"].append({"topic_key_synthesised": topic_key})

        # BLOCKER 3 — _run_smart_loop returns sentinel on total LLM failure.
        # MUST detect both exception AND sentinel-return as failure.
        try:
            final_text = await _asyncio.get_running_loop().run_in_executor(
                None, _compose_layer2, situation, draft, triage_reason,
            )
            if not final_text or any(s in final_text for s in _SMART_LOOP_ERROR_SENTINELS):
                raise RuntimeError(
                    f"Layer 2 returned empty or sentinel error text: {final_text!r:.120s}"
                )
        except Exception as exc:
            logger.warning(
                "autonomous: Layer 2 failed; falling back to draft (D-19): %s", exc,
            )
            final_text = draft

        if not final_text:
            decision["trail"].append("layer2_and_draft_both_empty")
            await _write_tick_log(now, situation, decision)
            return decision

        # Send (D-18: inject_into_conversation=True)
        from core.scheduled_message import send_and_inject
        try:
            await send_and_inject(bot, final_text, inject_into_conversation=True)
        except Exception:
            logger.error(
                "autonomous: send_and_inject failed; outreach_log NOT updated (D-10)",
                exc_info=True,
            )
            decision["trail"].append("send_failed")
            await _write_tick_log(now, situation, decision)
            return decision

        decision["sent"] = True

        # D-10 — write to outreach_log ONLY after send succeeded
        try:
            from memory.firestore_db import OutreachLogStore
            ols = OutreachLogStore(
                project_id=os.environ.get("GCP_PROJECT_ID", ""),
                database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
            )
            today_iso = now.astimezone(_TZ).date().isoformat()
            ols.append(today_iso, {
                "topic_key": topic_key,
                "time": now.astimezone(_TZ).strftime("%H:%M"),
                "draft": draft,
                "final": final_text,
                "tick_index": situation.get("now_context", {}).get("tick_index", 0),
            })
        except Exception:
            logger.warning(
                "autonomous: outreach_log append failed (send already succeeded)",
                exc_info=True,
            )

        decision["trail"].append({"shipped": topic_key})
        await _write_tick_log(now, situation, decision)
        return decision


    def _compose_layer2(situation: dict, draft: str, triage_reason: str) -> str:
        """Layer 2 — synthetic chat turn via _run_smart_loop.

        BLOCKER 5a fix — uses module singleton, not per-call AgentOrchestrator().
        BLOCKER 5b fix — explicitly renders smart_system placeholders before
        calling _run_smart_loop. Replaces {self_md}, {self_state}, {journal_digest},
        {today_date}. The injection happens in handle_message (verified at
        core/main.py:236-275), NOT in _run_smart_loop — so autonomous tick MUST
        replicate it here.

        Pitfall 2: builds messages list freshly. Does NOT call handle_message
        (which would append to conversation history, polluting it with the
        synthetic message).
        """
        orchestrator = _get_orchestrator()

        # BLOCKER 5b — replicate handle_message's render step.
        smart_system_template = _load_prompt("prompts/autonomous.md")
        smart_system = orchestrator.render_smart_system(smart_system_template)
        worker_system_template = _load_prompt("prompts/worker_agent.md")
        # worker_system just needs {today_date}; reuse the same render to be safe.
        worker_system = orchestrator.render_smart_system(worker_system_template)

        snap_summary = json.dumps({
            "calendar": situation.get("calendar", []),
            "ticktick_overdue": situation.get("ticktick_overdue", []),
            "unread_email_count": situation.get("unread_email_count", 0),
            "due_followups": situation.get("due_followups", []),
            "hours_since_contact": situation.get("hours_since_contact"),
        }, indent=2, ensure_ascii=False)

        synthetic_content = (
            f"Situation snapshot:\n{snap_summary}\n\n"
            f"Triage layer's draft:\n{draft}\n\n"
            f"Triage reasoning:\n{triage_reason}\n"
        )
        messages = [{"role": "user", "content": synthetic_content}]
        return orchestrator._run_smart_loop(messages, smart_system, worker_system)


    async def _compose_followup(bot, followup: dict, situation: dict, now: datetime) -> str:
        """D-13 — dedicated Layer-2 path for a due follow-up.

        - Layer 2 returns structured JSON: {"action": "send"} or {"action": "defer"}.
        - D-14 force-fire: if defer_count >= _DEFER_FORCE_FIRE_THRESHOLD, override defer to send.
        - On send: send_and_inject(..., inject=True) + FollowupStore.mark_done.
        - On defer: FollowupStore.defer (due_at += 1h, defer_count++).
        Returns "sent" | "deferred" | "force_fired" | "failed".

        BLOCKER 3 — sentinel detection mirrored from run_autonomous_tick.
        """
        import asyncio as _asyncio
        defer_count = int(followup.get("defer_count", 0))
        fid = followup.get("id") or ""

        try:
            text = await _asyncio.get_running_loop().run_in_executor(
                None, _compose_followup_layer2, followup, situation,
            )
            # BLOCKER 3 — sentinel detection
            if text and any(s in text for s in _SMART_LOOP_ERROR_SENTINELS):
                logger.warning(
                    "autonomous: followup Layer 2 returned sentinel; treating as failure",
                )
                text = ""
        except Exception:
            logger.warning("autonomous: followup Layer 2 failed", exc_info=True)
            text = ""

        action, polished = _parse_followup_action(text)

        # D-14 force-fire
        if action == "defer" and defer_count >= _DEFER_FORCE_FIRE_THRESHOLD:
            logger.info(
                "autonomous: follow-up %s force-fired (defer_count=%d >= %d)",
                fid, defer_count, _DEFER_FORCE_FIRE_THRESHOLD,
            )
            action = "send"
            force_fired = True
        else:
            force_fired = False

        if action == "send":
            from core.scheduled_message import send_and_inject
            from memory.firestore_db import FollowupStore, OutreachLogStore
            try:
                final_text = polished or followup.get("note", "")
                await send_and_inject(bot, final_text, inject_into_conversation=True)
            except Exception:
                logger.error("autonomous: followup send_and_inject failed", exc_info=True)
                return "failed"
            try:
                fs = FollowupStore(
                    project_id=os.environ.get("GCP_PROJECT_ID", ""),
                    database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
                )
                fs.mark_done(fid)
            except Exception:
                logger.warning("autonomous: mark_done failed", exc_info=True)
            try:
                ols = OutreachLogStore(
                    project_id=os.environ.get("GCP_PROJECT_ID", ""),
                    database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
                )
                today_iso = now.astimezone(_TZ).date().isoformat()
                ols.append(today_iso, {
                    "topic_key": f"followup:{fid}",
                    "time": now.astimezone(_TZ).strftime("%H:%M"),
                    "draft": followup.get("note", ""),
                    "final": final_text,
                    "tick_index": situation.get("now_context", {}).get("tick_index", 0),
                })
            except Exception:
                logger.warning(
                    "autonomous: outreach_log append (followup) failed", exc_info=True,
                )
            return "force_fired" if force_fired else "sent"

        # action == "defer"
        # NOTE 2 fix — defer pushes original due_at + 1h, not now + 1h.
        # Otherwise a followup deferred at 14:05 (originally due 14:00) shifts to 15:05,
        # drifting the followup cadence further from the user's intended cadence on each defer.
        from memory.firestore_db import FollowupStore
        try:
            original_due = datetime.fromisoformat(followup.get("due_at"))
            new_due = (original_due + timedelta(hours=1)).isoformat()
            fs = FollowupStore(
                project_id=os.environ.get("GCP_PROJECT_ID", ""),
                database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
            )
            fs.defer(fid, new_due)
        except Exception:
            logger.error("autonomous: followup defer failed", exc_info=True)
            return "failed"
        return "deferred"


    def _compose_followup_layer2(followup: dict, situation: dict) -> str:
        """Sync helper called from executor — synthetic chat turn for a follow-up.

        Uses module singleton (BLOCKER 5a) and renders smart_system (BLOCKER 5b)
        the same way _compose_layer2 does.

        Layer 2 must end its response with a fenced JSON block: {"action": "send"|"defer"}.
        """
        orchestrator = _get_orchestrator()
        smart_system_template = _load_prompt("prompts/autonomous.md")
        smart_system = orchestrator.render_smart_system(smart_system_template)
        worker_system_template = _load_prompt("prompts/worker_agent.md")
        worker_system = orchestrator.render_smart_system(worker_system_template)

        snap = json.dumps({
            "calendar": situation.get("calendar", []),
            "ticktick_overdue": situation.get("ticktick_overdue", []),
        }, indent=2, ensure_ascii=False)
        synthetic = (
            f"Due follow-up:\n"
            f"id: {followup.get('id', '')}\n"
            f"due_at: {followup.get('due_at', '')}\n"
            f"note: {followup.get('note', '')}\n"
            f"defer_count: {followup.get('defer_count', 0)}\n\n"
            f"Current situation:\n{snap}\n"
        )
        messages = [{"role": "user", "content": synthetic}]
        return orchestrator._run_smart_loop(messages, smart_system, worker_system)


    def _parse_followup_action(text: str) -> tuple[str, str]:
        """Parse the trailing JSON action from a Layer-2 follow-up response.

        Looks for a fenced ```json {"action": "send"|"defer"} ``` block. Returns
        (action, polished_text). polished_text is the message body BEFORE the JSON block.

        WARNING 5 fix:
          - No JSON block found    -> ("send", text.strip())  [original behavior]
          - JSON block parse fails -> ("send", text_BEFORE_the_block.strip())
            so the malformed JSON internals don't leak to the user.

        Default to "send" rather than eternally deferring (D-17 spirit + Pitfall 6).
        """
        import re as _re
        if not text:
            return ("send", "")
        m = _re.search(r"```json\s*(\{.*?\})\s*```", text, _re.DOTALL)
        if not m:
            return ("send", text.strip())
        try:
            obj = json.loads(m.group(1))
            action = str(obj.get("action", "send")).lower()
            if action not in ("send", "defer"):
                action = "send"
        except (json.JSONDecodeError, ValueError):
            # WARNING 5 — strip the malformed JSON from the polished text.
            action = "send"
        polished = text[:m.start()].strip()
        return (action, polished)


    def _infer_trigger_type(situation: dict) -> str:
        """Return a coarse trigger-type label from the situation. Used for topic_key synthesis."""
        if situation.get("ticktick_overdue"):
            return "overdue"
        if situation.get("due_followups"):
            return "followup"
        hsc = situation.get("hours_since_contact")
        if hsc is not None and hsc >= 8:
            return "silence"
        if _calendar_has_gap_or_overload(
            situation.get("calendar") or [],
            situation.get("now_context") or {},
        ):
            return "gap"
        return "quiet"


    async def _write_tick_log(now: datetime, situation: dict, decision: dict) -> None:
        """D-21 / Claude's discretion — write the tick snapshot for retroactive labeling.

        Best-effort. Never raises.
        """
        try:
            # NOTE 1 fix — use TickLogStore (added by Plan 01) instead of reaching into the
            # private firestore helper. Keeps the memory-layer pattern consistent: every
            # persistent collection has a named store. TickLogStore.write is best-effort
            # and never raises per Plan 01.
            from memory.firestore_db import TickLogStore
            project_id = os.environ.get("GCP_PROJECT_ID", "")
            database = os.environ.get("FIRESTORE_DATABASE", "(default)")
            today_iso = now.astimezone(_TZ).date().isoformat()
            tick_time = now.astimezone(_TZ).strftime("%H:%M")
            snapshot = {k: v for k, v in situation.items() if k != "empty"}
            TickLogStore(project_id=project_id, database=database).write(
                today_iso, tick_time, snapshot, decision,
            )
        except Exception:
            logger.warning("autonomous: tick_log write failed (non-fatal)", exc_info=True)
    ```

    Step B — Implement all listed tests in `tests/test_autonomous.py`. Use heavy mocking:
    - Reset the module singleton between tests: `core.autonomous._orchestrator_singleton = None` in a pytest fixture.
    - Patch `gather_situation`, `TickBrain`, `AgentOrchestrator._run_smart_loop`, `send_and_inject`, `FollowupStore`, `OutreachLogStore`.
    - Use `pytest.mark.asyncio` (or `asyncio.run` wrappers). Read `tests/test_reflection.py` for the async-test style.

    For `test_layer2_smart_system_has_placeholders_resolved`: capture the actual `smart_system` argument passed to the mock `_run_smart_loop` via `mock.call_args.args[1]` (the second positional arg) and assert no literal placeholders survive.

    For `test_orchestrator_is_module_singleton`: patch `core.main.AgentOrchestrator` to count instantiations; clear `_orchestrator_singleton` to None first; call `_get_orchestrator()` twice; assert instantiation count == 1 and `obj1 is obj2`.

    For `test_layer2_returns_smart_loop_error_sentinel_falls_back_to_draft`: patch `_compose_layer2` (or the synchronous `_run_smart_loop` it calls) to RETURN the sentinel string. Assert `send_and_inject` got the draft, not the sentinel.

    Step C — Run full file: `pytest tests/test_autonomous.py -x -v`. Every test must pass.

    **CRITICAL — anti-shallow-execution checks at end of task:**
    - `grep -c "inject_into_conversation=True" core/autonomous.py` >= 2 (used in run_autonomous_tick + _compose_followup)
    - `grep -c "system_override" core/autonomous.py` >= 1 (passed to tick_brain.think)
    - `grep -c "_DEFER_FORCE_FIRE_THRESHOLD" core/autonomous.py` >= 2 (definition + use)
    - `grep -c "handle_message" core/autonomous.py` == 0 (Pitfall 2 — must NOT route through handle_message)
    - `grep -c "OutreachLogStore" core/autonomous.py` >= 2 (run_autonomous_tick + _compose_followup, both AFTER send)
    - `grep -c "_get_orchestrator" core/autonomous.py` >= 3 (definition + at least 2 call sites)
    - `grep -c "render_smart_system" core/autonomous.py` >= 2 (at least 2 call sites)
    - `grep -c "_SMART_LOOP_ERROR_SENTINELS" core/autonomous.py` >= 2 (definition + sentinel check)
  </action>
  <verify>
    <automated>grep -c "inject_into_conversation=True" core/autonomous.py && test "$(grep -c "handle_message" core/autonomous.py)" -eq 0 && grep -c "_DEFER_FORCE_FIRE_THRESHOLD" core/autonomous.py && grep -c "_get_orchestrator" core/autonomous.py && grep -c "render_smart_system" core/autonomous.py && grep -c "_SMART_LOOP_ERROR_SENTINELS" core/autonomous.py && pytest tests/test_autonomous.py -x -v</automated>
  </verify>
  <done>
    - `core/autonomous.py` has functions: `gather_situation`, `run_autonomous_tick` (async), `_compose_layer2` (sync), `_compose_followup` (async), `_compose_followup_layer2` (sync), `_parse_followup_action`, `_infer_trigger_type`, `_synthesize_topic_key`, `_build_triage_prompt`, `_now_context`, `_is_empty_signals`, `_calendar_has_gap_or_overload`, `_get_orchestrator`, `_load_prompt`, `_write_tick_log`
    - `wc -l core/autonomous.py` >= 280
    - All Task 1 + Task 2 tests pass (16+ tests including BLOCKER regressions)
    - `grep -c "inject_into_conversation=True" core/autonomous.py` >= 2
    - `grep -c "handle_message" core/autonomous.py` == 0 (Pitfall 2 verified)
    - `grep -c "_DEFER_FORCE_FIRE_THRESHOLD" core/autonomous.py` >= 2
    - `grep -c "_get_orchestrator" core/autonomous.py` >= 3 (BLOCKER 5a)
    - `grep -c "render_smart_system" core/autonomous.py` >= 2 (BLOCKER 5b)
    - `grep -c "_SMART_LOOP_ERROR_SENTINELS" core/autonomous.py` >= 2 (BLOCKER 3)
    - `grep -c "OutreachLogStore" core/autonomous.py` >= 2
    - `python -c "import core.autonomous; print('import OK')"` succeeds
  </done>
</task>

</tasks>

<verification>
1. `pytest tests/test_autonomous.py -x -v` — all tests pass (Task 1 + Task 2 BLOCKER regressions)
2. `pytest tests/ -x` — full test suite still green (no regressions from Task 0 refactor)
3. Grep audit:
   - `grep -c "handle_message" core/autonomous.py` returns 0 (Pitfall 2)
   - `grep -c "inject_into_conversation=True" core/autonomous.py` returns ≥2 (D-18)
   - `grep -c "system_override" core/autonomous.py` returns ≥1 (uses Plan 05 extension)
   - `grep -c "_DEFER_FORCE_FIRE_THRESHOLD" core/autonomous.py` returns ≥2 (D-14)
   - `grep -c "_get_orchestrator" core/autonomous.py` returns ≥3 (BLOCKER 5a)
   - `grep -c "render_smart_system" core/autonomous.py` returns ≥2 (BLOCKER 5b)
   - `grep -c "_SMART_LOOP_ERROR_SENTINELS" core/autonomous.py` returns ≥2 (BLOCKER 3)
   - `grep -c "_calendar_has_gap_or_overload" core/autonomous.py` returns ≥2 (BLOCKER 2)
   - `grep -c "_TICK_TOTAL_PER_DAY = 43" core/autonomous.py` returns 1 (WARNING 3)
4. Decision-trail test confirms 4-way scenario coverage (empty / no-act / send / fallback-draft)
5. `grep -c "def render_smart_system" core/main.py` == 1 (Task 0 prep edit landed)
6. `grep -c "def get_last_user_timestamp" memory/firestore_conversation.py` == 1 (new method)
</verification>

<success_criteria>
- 8-source `gather_situation` with per-source isolation using REAL APIs (BLOCKER 1).
- `_is_empty_signals` uses narrow calendar detection — single non-conflicting event = quiet (BLOCKER 2).
- Layer-2 sentinel detection prevents shipping connectivity-error string to user (BLOCKER 3).
- `_get_orchestrator` module singleton (BLOCKER 5a).
- `render_smart_system` resolves placeholders before `_run_smart_loop` (BLOCKER 5b).
- Pitfall 2 protected by test (no `handle_message` route, no conversation-history pollution).
- Pitfall 3 protected by test (outreach_log on send-success only, D-10).
- Pitfall 4 protected by test (topic_key fallback synthesis).
- Pitfall 6 protected by test + handler (defer force-fire at >=3, D-14).
- D-19 fallback-to-draft when Layer 2 fails OR returns sentinel.
- D-18 send_and_inject with inject=True.
- D-13 follow-up path skips tick-brain.
- WARNING 2: _load_prompt uses core/main.py's relative-path strategy.
- WARNING 3: tick_total = 43 (43 ticks 7:00..21:00 inclusive); clamped for early-morning manual runs.
- WARNING 4: hours_since_contact None on never-contacted, renders as "unknown" in prompt.
- WARNING 5: malformed JSON block stripped from polished follow-up text.
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-06-SUMMARY.md` with:
- Final LOC for `core/autonomous.py` (>=280)
- New public method `AgentOrchestrator.render_smart_system` line count in `core/main.py`
- New method `FirestoreConversationStore.get_last_user_timestamp` line count
- List of all tests in `tests/test_autonomous.py` and their pass status
- Grep audit results (8 numerical checks above)
- Note any deviations from RESEARCH (e.g., `FirestoreConversationStore.get_last_user_timestamp` implementation choice — confirm whether you returned `updated_at` field or iterated messages)
- BLOCKER regression test names (call out the 5 BLOCKER fix verifications explicitly)
</output>
