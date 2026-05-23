---
phase: 18-autonomous-engine
plan: 05
type: execute
wave: 2
depends_on: [03]
files_modified:
  - core/tick_brain.py
  - tests/test_tick_brain.py
autonomous: true
requirements: [AUTO-01, AUTO-07]
requirements_addressed: [AUTO-01, AUTO-07]

must_haves:
  truths:
    - "TickBrain.think() accepts an optional system_override kwarg defaulting to None"
    - "When system_override is None, _TICK_SYSTEM_PROMPT is used (heartbeat backward-compat preserved)"
    - "When system_override is set, that string replaces _TICK_SYSTEM_PROMPT for both primary and fallback LLM calls"
    - "Purpose string layering preserves Phase 14 INFRA-02 fallback-rate visibility (WARNING 1 fix): primary_purpose = 'tick_autonomous' if override else 'tick'; fallback_purpose = primary_purpose + '_fallback' (so heartbeat fallback remains 'tick_fallback' and autonomous fallback becomes 'tick_autonomous_fallback')"
    - "_parse_response passes through topic_key when present in the LLM JSON; safe-mode return unchanged (no topic_key key)"
  artifacts:
    - path: "core/tick_brain.py"
      provides: "Extended think() signature + extended _parse_response output + layered purpose strings"
      contains: "system_override"
    - path: "tests/test_tick_brain.py"
      provides: "Tests for system_override + topic_key passthrough + layered purpose strings"
      contains: "test_topic_key_passthrough"
  key_links:
    - from: "core/tick_brain.py think() with system_override"
      to: "core/autonomous.py:_build_triage_prompt + Layer 1 call (Plan 06)"
      via: "TickBrain.think(prompt, system_override=<rendered autonomous_triage.md>)"
      pattern: "system_override"
    - from: "core/tick_brain.py _parse_response topic_key"
      to: "core/autonomous.py topic_key fallback (Plan 06)"
      via: "result['topic_key'] = str(data['topic_key'])"
      pattern: "topic_key"
---

<objective>
Extend `core/tick_brain.py` with two surgical changes that unlock the autonomous
tick path:

1. Add a `system_override: str | None = None` kwarg to `TickBrain.think()` so
   `core/autonomous.py` (Plan 06) can pass `prompts/autonomous_triage.md` (Plan 03)
   without mutating the heartbeat caller (`core/heartbeat.py:707`). When the
   override is active, also flip `purpose` from `"tick"` to `"tick_autonomous"`
   for cost-metering granularity (D-04).
2. Extend `_parse_response` to pass through the new fourth JSON field
   `topic_key` per D-07 — alongside `should_act`, `reason`, `draft`. Safe-mode
   return (on parse failure) remains unchanged; missing/empty `topic_key` is
   handled downstream in `core/autonomous.py` (handler-synthesised fallback,
   Pitfall 4).

**WARNING 1 fix:** the existing code uses `purpose="tick_fallback"` (hardcoded
on the fallback path) so Phase 14 INFRA-02 can measure tick-brain fallback
rate independently. A naive "replace both with `active_purpose`" would lose
that distinction when system_override is None. Use **layered purpose strings**
instead: `primary_purpose = "tick_autonomous" if system_override else "tick";
fallback_purpose = primary_purpose + "_fallback"`. That gives us 4 buckets
visible in LLMUsageStore: `tick`, `tick_fallback`, `tick_autonomous`,
`tick_autonomous_fallback`.

Purpose: AUTO-01 (3-layer pipeline) needs Layer 1 to accept the new triage
prompt. AUTO-07 (autonomous prompts) needs the JSON schema extension landed in
the parser so `topic_key` propagates to `outreach_log` (AUTO-03). RESEARCH
recommended approach (a) — add the kwarg; Phase 17 D-08 set the precedent for
"extend an existing function with a new optional param."

Output: 2 edits in `core/tick_brain.py` + extended `tests/test_tick_brain.py`.
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
@.planning/phases/18-autonomous-engine/18-03-SUMMARY.md
@core/tick_brain.py

<interfaces>
<!-- Existing tick_brain.py interface — the contract to extend. -->

From core/tick_brain.py:101-156 (current `think()` signature + flow):

```python
def think(self, prompt: str, tools: list[dict] | None = None) -> dict:
    """Run a judgment pass over the given prompt."""
    messages = [{"role": "user", "content": prompt}]

    response = None
    try:
        response = self._client.chat(
            messages,
            system=_TICK_SYSTEM_PROMPT,
            tools=tools,
            purpose="tick",
        )
    except LLMError as exc:
        # ... falls through to _fallback_client
    ...
    response = self._fallback_client.chat(
        messages,
        system=_TICK_SYSTEM_PROMPT,
        tools=tools,
        purpose="tick_fallback",   # <-- VERIFIED at tick_brain.py:146 — must remain visible (WARNING 1)
    )
```

From core/tick_brain.py:158-186 (current `_parse_response`):

```python
@staticmethod
def _parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("tick-brain: JSON parse failure; safe mode. Raw: %.200s", text)
        return {"should_act": False, "reason": "parse_failure"}

    if not isinstance(data, dict) or "should_act" not in data:
        return {"should_act": False, "reason": "parse_failure"}

    result = {
        "should_act": bool(data.get("should_act", False)),
        "reason":     str(data.get("reason", "")),
    }
    if "draft" in data and data["draft"]:
        result["draft"] = str(data["draft"])
    return result
```

From core/heartbeat.py:707 (existing caller — must remain backward-compat):
```python
verdict = tick_brain.think(reasoning_prompt)
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Extend TickBrain.think() with system_override (layered purpose strings) + _parse_response with topic_key + tests</name>
  <files>core/tick_brain.py, tests/test_tick_brain.py</files>
  <read_first>
    - core/tick_brain.py (read fully — confirm current line numbers for `_TICK_SYSTEM_PROMPT` definition, `think()` signature, fallback branch using `_fallback_client`, `_parse_response`. **VERIFY** line 146 currently emits `purpose="tick_fallback"` — this string must remain visible in LLMUsageStore for heartbeat callers; WARNING 1)
    - core/heartbeat.py around line 707 (confirm the existing caller's exact invocation — must remain working with no kwarg-change pressure)
    - tests/test_tick_brain.py (read fully — observe existing test fixtures and mocking style for `_client.chat`)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "core/tick_brain.py (MODIFIED)" — lines 177-236)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "core/tick_brain.py — topic_key schema extension")
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-07 — topic_key)
  </read_first>
  <behavior>
    - Test 1: `think(prompt)` with no system_override calls `self._client.chat` with `system=_TICK_SYSTEM_PROMPT` AND `purpose="tick"` (heartbeat backward-compat).
    - Test 2: `think(prompt, system_override="custom system")` calls `self._client.chat` with `system="custom system"` AND `purpose="tick_autonomous"`.
    - Test 3: When primary `_client.chat` raises `LLMError` AND system_override is None, the fallback `_fallback_client.chat` is called with `purpose="tick_fallback"` (WARNING 1 fix — heartbeat fallback rate visibility preserved).
    - Test 4: When primary raises and `system_override` is set, fallback purpose is `"tick_autonomous_fallback"` (autonomous fallback visible separately).
    - Test 5: Fallback receives the SAME `system` value as primary (active_system carries through).
    - Test 6 (NEW — WARNING 1 explicit): `test_fallback_purpose_preserves_tick_fallback_when_no_override` — set up primary to raise; call `think("p")` with NO system_override; assert fallback chat call kwargs contain `purpose="tick_fallback"` (NOT "tick" or any other string).
    - Test 7: `_parse_response('{"should_act": true, "reason": "x", "draft": "y", "topic_key": "overdue:maya"}')` returns dict with `topic_key == "overdue:maya"`.
    - Test 8: `_parse_response('{"should_act": true, "reason": "x"}')` (no topic_key) returns dict WITHOUT a `topic_key` key.
    - Test 9: `_parse_response('{"should_act": true, "reason": "x", "topic_key": ""}')` (empty string) returns dict WITHOUT a `topic_key` key.
    - Test 10: `_parse_response('not json')` safe-mode return unchanged: `{"should_act": False, "reason": "parse_failure"}` with NO `topic_key`.
    - Test 11: `_parse_response('{"should_act": true, "topic_key": 123}')` (non-string topic_key) coerces to `"123"` via `str()` (defensive parsing).
  </behavior>
  <action>
    Step A — `core/tick_brain.py` edit 1: `TickBrain.think()` signature change with **layered** purpose strings (WARNING 1 fix).

    Modify the signature and the two `.chat()` call sites:

    Before:
    ```python
    def think(self, prompt: str, tools: list[dict] | None = None) -> dict:
        messages = [{"role": "user", "content": prompt}]

        response = None
        try:
            response = self._client.chat(
                messages,
                system=_TICK_SYSTEM_PROMPT,
                tools=tools,
                purpose="tick",
            )
        except LLMError as exc:
            ...
        # fallback:
        response = self._fallback_client.chat(
            messages,
            system=_TICK_SYSTEM_PROMPT,
            tools=tools,
            purpose="tick_fallback",
        )
    ```

    After:
    ```python
    def think(
        self,
        prompt: str,
        tools: list[dict] | None = None,
        system_override: str | None = None,
    ) -> dict:
        """Run a judgment pass over the given prompt.

        Args:
            prompt: User-content prompt (the situation snapshot, formatted).
            tools: Optional tool list (currently unused for autonomous path).
            system_override: When set, replaces _TICK_SYSTEM_PROMPT for this call
                (e.g., autonomous tick passes prompts/autonomous_triage.md).
                Also flips purpose from 'tick' to 'tick_autonomous' for cost
                metering granularity (D-04 / Phase 18).

        Purpose-string layering (WARNING 1 — preserves Phase 14 INFRA-02 visibility):
            override=None  -> primary 'tick',            fallback 'tick_fallback'
            override=...   -> primary 'tick_autonomous', fallback 'tick_autonomous_fallback'

        Returns:
            dict with at least {should_act, reason}; optionally draft, topic_key.
            On parse failure, returns safe mode {should_act: False, reason: 'parse_failure'}.
        """
        messages = [{"role": "user", "content": prompt}]
        active_system = system_override if system_override is not None else _TICK_SYSTEM_PROMPT
        # WARNING 1 fix — layered purpose strings keep tick_fallback visible.
        primary_purpose = "tick_autonomous" if system_override is not None else "tick"
        fallback_purpose = primary_purpose + "_fallback"

        response = None
        try:
            response = self._client.chat(
                messages,
                system=active_system,
                tools=tools,
                purpose=primary_purpose,
            )
        except LLMError as exc:
            # ... existing fallback branch — confirm it uses active_system + fallback_purpose
    ```

    **CRITICAL:** In the existing fallback branch (where `self._fallback_client.chat(...)` is called), replace:
    - `system=_TICK_SYSTEM_PROMPT` → `system=active_system`
    - `purpose="tick_fallback"` → `purpose=fallback_purpose`

    After the edit, `grep -n "_TICK_SYSTEM_PROMPT" core/tick_brain.py` should only show the definition (~line 30) and the `if system_override is not None else _TICK_SYSTEM_PROMPT` ternary. `grep -n '"tick_fallback"' core/tick_brain.py` should return 0 (the literal is replaced by the layered variable).

    Step B — `core/tick_brain.py` edit 2: `_parse_response` topic_key passthrough.

    Find `_parse_response` (around line 158). Find the existing block:
    ```python
    if "draft" in data and data["draft"]:
        result["draft"] = str(data["draft"])
    return result
    ```

    Replace with:
    ```python
    if "draft" in data and data["draft"]:
        result["draft"] = str(data["draft"])
    # D-07 — pass through topic_key for autonomous tick repeat-suppression.
    # Falsy values (empty string, None) treated as missing; downstream synthesises a fallback.
    if "topic_key" in data and data["topic_key"]:
        result["topic_key"] = str(data["topic_key"])
    return result
    ```

    Step C — `tests/test_tick_brain.py` extension: append a new test class `TestSystemOverrideAndTopicKey` covering all 11 tests in the behavior block. Use existing mock patterns (`MagicMock` on `_client.chat` and `_fallback_client.chat`). Assert via `mock.call_args.kwargs` that the right `system=` and `purpose=` kwargs were passed.

    Example shape:
    ```python
    def test_fallback_purpose_preserves_tick_fallback_when_no_override(self):
        tb = TickBrain(...)
        tb._client = MagicMock()
        tb._client.chat.side_effect = LLMError("boom")
        tb._fallback_client = MagicMock()
        tb._fallback_client.chat.return_value = {"text": '{"should_act": false, "reason": "ok"}'}
        tb.think("p")  # no system_override
        kwargs = tb._fallback_client.chat.call_args.kwargs
        assert kwargs["purpose"] == "tick_fallback", (
            f"WARNING 1 regression: fallback purpose changed to {kwargs['purpose']!r}"
        )

    def test_fallback_purpose_is_autonomous_when_override_set(self):
        tb = TickBrain(...)
        tb._client = MagicMock()
        tb._client.chat.side_effect = LLMError("boom")
        tb._fallback_client = MagicMock()
        tb._fallback_client.chat.return_value = {"text": '{"should_act": false, "reason": "ok"}'}
        tb.think("p", system_override="custom")
        kwargs = tb._fallback_client.chat.call_args.kwargs
        assert kwargs["purpose"] == "tick_autonomous_fallback"
    ```

    Verify with `pytest tests/test_tick_brain.py -x`.
  </action>
  <verify>
    <automated>grep -nE "system_override" core/tick_brain.py && grep -c "active_system" core/tick_brain.py && grep -c "fallback_purpose" core/tick_brain.py && test "$(grep -c '\"tick_fallback\"' core/tick_brain.py)" -eq 0 && pytest tests/test_tick_brain.py -x</automated>
  </verify>
  <done>
    - `grep -c "system_override" core/tick_brain.py` >= 2 (signature + use in active_system)
    - `grep -c "active_system" core/tick_brain.py` >= 2 (primary call + fallback call)
    - `grep -c "primary_purpose" core/tick_brain.py` >= 2 (definition + use)
    - `grep -c "fallback_purpose" core/tick_brain.py` >= 2 (definition + use)
    - `grep -c "tick_autonomous" core/tick_brain.py` >= 1 (primary_purpose branch)
    - `grep -c '"tick_fallback"' core/tick_brain.py` == 0 (the literal is replaced — WARNING 1)
    - `grep -c "_TICK_SYSTEM_PROMPT" core/tick_brain.py` == 2 (definition + ternary)
    - `grep -c "topic_key" core/tick_brain.py` >= 2 (comment + body)
    - All 11 tests in `TestSystemOverrideAndTopicKey` pass (includes `test_fallback_purpose_preserves_tick_fallback_when_no_override`)
    - Existing tests in `tests/test_tick_brain.py` still pass — full file run: `pytest tests/test_tick_brain.py -x` passes
    - `python -c "from core.tick_brain import TickBrain; import inspect; sig = inspect.signature(TickBrain.think); assert 'system_override' in sig.parameters; assert sig.parameters['system_override'].default is None; print('OK')"` prints OK
  </done>
</task>

</tasks>

<verification>
1. `pytest tests/test_tick_brain.py -x` — full test file green (new + existing tests)
2. Heartbeat backward-compat smoke: `python -c "from core.tick_brain import TickBrain; import inspect; assert len([p for p in inspect.signature(TickBrain.think).parameters if p != 'self']) == 3; print('OK')"` confirms 3 params (prompt, tools, system_override) with sensible defaults
3. Manual diff inspection: `_TICK_SYSTEM_PROMPT` referenced only at definition + the `active_system` ternary; `"tick_fallback"` literal does not appear anywhere (replaced by `fallback_purpose` variable).
</verification>

<success_criteria>
- `TickBrain.think()` accepts `system_override` kwarg with sensible default (None preserves heartbeat behavior).
- Both primary and fallback `.chat()` calls receive `active_system` AND `primary_purpose`/`fallback_purpose` respectively (WARNING 1 layering).
- LLMUsageStore observes 4 distinct buckets across the codebase: `tick`, `tick_fallback`, `tick_autonomous`, `tick_autonomous_fallback`.
- `_parse_response` passes through `topic_key` when present and truthy; ignores empty/missing.
- Safe-mode return unchanged on parse failure.
- All new tests + all existing tests pass.
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-05-SUMMARY.md` listing:
- Lines modified in `core/tick_brain.py` (think signature + primary call + fallback call + _parse_response)
- Test additions (call out `test_fallback_purpose_preserves_tick_fallback_when_no_override` explicitly — WARNING 1 regression guard)
- Confirmation that heartbeat caller is unchanged (backward-compat verified) and `purpose="tick_fallback"` is still emitted when no override is set
</output>
