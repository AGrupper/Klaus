---
phase: 18-autonomous-engine
plan: 02
type: execute
wave: 1
depends_on: [01]
files_modified:
  - core/tools.py
  - prompts/smart_agent.md
  - tests/test_tools.py
autonomous: true
requirements: [AUTO-05]
requirements_addressed: [AUTO-05]

must_haves:
  truths:
    - "Klaus can call schedule_followup, list_followups, cancel_followup directly from chat"
    - "schedule_followup accepts ISO 8601 strings and natural-language strings (D-12)"
    - "schedule_followup handler catches ImportError from dateutil (WARNING 7 fix) — if Plan 01's requirements.txt update did not deploy, handler returns structured {'error': 'could_not_parse_when: ...'} instead of crashing the chat with a 500"
    - "list_followups returns only pending follow-ups, stripped of internal fields"
    - "cancel_followup is idempotent — returns {ok: True} even on already-cancelled IDs"
    - "Worker agent cannot invoke any of the 3 follow-up tools (excluded from WORKER_TOOL_SCHEMAS)"
    - "prompts/smart_agent.md tells Klaus he can manage his own check-backs with these 3 tools"
    - "SMART_AGENT_DIRECT_TOOLS additions follow the EXISTING insertion-order pattern (NOT alphabetical) — verified by reading core/tools.py:39-48 (NOTE 4 fix)"
  artifacts:
    - path: "core/tools.py"
      provides: "3 tools registered at all 5 sites = 15 edit points"
      contains: "schedule_followup"
    - path: "prompts/smart_agent.md"
      provides: "SELF-SCHEDULED FOLLOW-UPS section advertising the 3 tools"
      contains: "schedule_followup"
    - path: "tests/test_tools.py"
      provides: "TestFollowupTools class — ISO/NL parsing, ImportError handling, idempotency, registration"
      contains: "test_followup_tools"
  key_links:
    - from: "core/tools.py _handle_schedule_followup"
      to: "memory.firestore_db.FollowupStore.add"
      via: "store.add(due_at=iso, note=note, origin='klaus_self')"
      pattern: "FollowupStore.*add"
    - from: "core/tools.py _handle_schedule_followup"
      to: "dateutil.parser.parse fallback for natural-language when"
      via: "from dateutil import parser as _dt_parser; _dt_parser.parse(when)"
      pattern: "dateutil.*parser"
---

<objective>
Register three new brain-direct tools — `schedule_followup`, `list_followups`,
`cancel_followup` — at all five canonical sites in `core/tools.py` (15 edit
points total), wire their handlers to `FollowupStore` (from Plan 01), and
advertise them in `prompts/smart_agent.md` so Klaus knows he can manage his own
check-backs mid-conversation.

Purpose: AUTO-05 specifies `schedule_followup` as the named direct tool, but
the spirit of the requirement (Klaus manages his own check-backs) needs all
three — `list_followups` to inspect what's pending, `cancel_followup` to drop
one when the user changes their mind. D-15 captures this expansion; the
15-edit-point pattern is established by Phases 15 and 16. RESEARCH §Pitfall 1
flags this as the highest-mechanical-risk task — execute it as a single atomic
plan with end-of-task grep verification.

**WARNING 7 fix:** the handler currently catches `(ValueError, TypeError,
OverflowError)` around the dateutil.parser.parse call but NOT `ImportError`.
If Plan 01's requirements.txt update fails to deploy (image build skips it,
Cloud Run uses stale image), the import raises ModuleNotFoundError and the
chat surfaces a 500 instead of a structured error message. Catch ImportError
too so the failure stays structured.

**NOTE 4 fix:** the existing `SMART_AGENT_DIRECT_TOOLS` frozenset (lines 39-48)
is NOT alphabetical — it preserves insertion order from prior phases. Match
that pattern: append the 3 new tool names AT THE END of the frozenset rather
than inserting alphabetically (which would split tools across non-adjacent
lines and obscure git blame).

Output: 15 edits across `core/tools.py`, a one-section addition to
`prompts/smart_agent.md`, and a `TestFollowupTools` test class.
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
@docs/CODING_STANDARDS.md

<interfaces>
<!-- The 5-site direct-tool registration pattern from Phase 15/16 (verbatim contract). -->

From core/tools.py (read each site fully before editing):

Site 1 — `SMART_AGENT_DIRECT_TOOLS` frozenset (lines 39-48). **VERIFIED current order is insertion-based, NOT alphabetical** (NOTE 4):
```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    "remember",
    "recall",
    "run_morning_briefing",
    "search_chat_history",
    "list_own_files",
    "read_own_source",
    "search_own_source",
    "get_self_status",
})
```

Site 2 — `TOOL_SCHEMAS` list (analog at lines 651-666 for `get_self_status`, a no-param tool):
```python
{
    "name": "get_self_status",
    "description": "Return Klaus's current operational status: ...",
    "input_schema": {"type": "object", "properties": {}, "required": []},
},
```

Site 3 — `WORKER_TOOL_SCHEMAS` exclusion (lines 701-713):
```python
WORKER_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["name"] not in {
        "delegate_to_worker", "remember", "recall", "search_chat_history",
        "list_own_files", "read_own_source", "search_own_source", "get_self_status",
    }
]
```

Site 4 — `_handle_<name>()` functions (lines 1119+, near get_self_status handler).

Site 5 — `_HANDLERS` dispatch dict (lines 1197-1226):
```python
_HANDLERS: dict[str, object] = {
    "remember": lambda args: _handle_remember(**args),
    "recall":   lambda args: _handle_recall(**args),
    ...
}
```

From memory/firestore_db.py (Plan 01 output — FollowupStore signatures):
- `FollowupStore.add(due_at: str, note: str, origin: str = "user_chat") -> {"id": str, "due_at": str}`
- `FollowupStore.list_pending() -> list[dict]`
- `FollowupStore.cancel(fid: str) -> bool`
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Wire 3 follow-up tools at all 5 registration sites + smart_agent.md advertisement + tests (WARNING 7 + NOTE 4 fixes inline)</name>
  <files>core/tools.py, prompts/smart_agent.md, tests/test_tools.py</files>
  <read_first>
    - core/tools.py (read fully — confirm exact line numbers for SMART_AGENT_DIRECT_TOOLS, TOOL_SCHEMAS end, WORKER_TOOL_SCHEMAS exclusion, _handle_get_self_status, _HANDLERS dict — RESEARCH cites lines 39, 651-666, 701-713, 1119, 1197 but line numbers may have drifted. **NOTE 4 verify**: confirm SMART_AGENT_DIRECT_TOOLS at lines 39-48 follows insertion order, NOT alphabetical)
    - prompts/smart_agent.md (read fully — observe LONG-TERM MEMORY and SELF-INSPECTION sections at lines 54-94 from PATTERNS.md; use the same style)
    - memory/firestore_db.py (review FollowupStore signatures from Plan 01)
    - tests/test_tools.py (if exists — observe existing patterns; if missing, follow tests/test_self_inspect.py shape)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "core/tools.py — 15 edit points" — full breakdown of all 5 sites with current line numbers and exact additions)
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-12, D-15)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (Pitfall 1 — 15-edit-point miss; section "core/tools.py — 15-edit-point pattern" lines 177-205)
  </read_first>
  <behavior>
    - Test 1: `_handle_schedule_followup(when="2026-05-21T15:00:00+00:00", note="check on maya")` returns JSON-string `{"id": <str>, "due_at": "2026-05-21T15:00:00+00:00"}`; FollowupStore.add is called with `origin="klaus_self"`.
    - Test 2: `_handle_schedule_followup(when="tomorrow 3pm", note="x")` parses NL via dateutil; returns ISO-8601 UTC due_at; FollowupStore.add is called.
    - Test 3: `_handle_schedule_followup(when="not a date", note="x")` returns JSON-string `{"error": "could_not_parse_when: ..."}` and does NOT call FollowupStore.add.
    - Test 4: `_handle_schedule_followup` with naive datetime (no tzinfo, e.g., "2026-05-21 15:00") assigns UTC and stores ISO-8601 with `+00:00`.
    - Test 5: `_handle_list_followups()` returns JSON-string of a list; each entry strips internal fields (returns only `id`, `due_at`, `note`, `defer_count` — NOT `created_at`, `status`, `origin`).
    - Test 6: `_handle_list_followups()` returns `"[]"` (empty-list JSON) when FollowupStore.list_pending returns `[]`.
    - Test 7: `_handle_cancel_followup(id="abc")` returns JSON-string `{"ok": True}` when FollowupStore.cancel returns True; returns `{"ok": True}` again on second call (idempotent — never returns `{"ok": False}` for already-cancelled).
    - Test 8: `_handle_cancel_followup(id="nonexistent")` (FollowupStore.cancel returns False) returns JSON-string `{"ok": False}`.
    - Test 9: All three tools are members of `SMART_AGENT_DIRECT_TOOLS`.
    - Test 10: All three tools are EXCLUDED from `WORKER_TOOL_SCHEMAS` (assert none of the worker schema names match the 3 names).
    - Test 11: All three tools appear in `_HANDLERS` dispatch dict.
    - Test 12: All three tools have a JSON schema in `TOOL_SCHEMAS` with correct `required` arrays (`["when", "note"]` for schedule, `[]` for list, `["id"]` for cancel).
    - Test 13 (NEW — WARNING 7 fix): `_handle_schedule_followup(when="tomorrow", note="x")` with `dateutil` monkeypatched so `from dateutil import parser` raises `ImportError("No module named 'dateutil'")`. Assert handler returns a JSON-string `{"error": "could_not_parse_when: ..."}` AND does NOT raise. Implement with `monkeypatch.setitem(sys.modules, "dateutil", None)` or by patching `dateutil.parser.parse` to raise ImportError when imported (test the actual exception path).
  </behavior>
  <action>
    Execute all 15 edits + smart_agent.md addition + tests as ONE atomic task. The 5 sites in `core/tools.py`:

    **Site 1 — `SMART_AGENT_DIRECT_TOOLS` frozenset (NOTE 4 — append at the end, NOT alphabetical):**
    Find the closing `})` of the frozenset (currently after `"get_self_status",`). Insert the three new entries BEFORE the closing brace, matching the existing insertion-order convention:
    ```python
    SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
        "remember",
        "recall",
        "run_morning_briefing",
        "search_chat_history",
        "list_own_files",
        "read_own_source",
        "search_own_source",
        "get_self_status",
        # Phase 18 — self-scheduled follow-ups (D-15)
        "schedule_followup",
        "list_followups",
        "cancel_followup",
    })
    ```

    **Site 2 — `TOOL_SCHEMAS` list (append after the `get_self_status` schema; find via `grep -n '"name": "get_self_status"' core/tools.py`):**
    ```python
    {
        "name": "schedule_followup",
        "description": (
            "Schedule a self-managed check-back. You will be reminded at the chosen "
            "time and may polish, send, or defer at that point. `when` accepts ISO 8601 "
            "('2026-05-21T15:00:00+00:00') or natural language ('tomorrow 3pm', 'next monday 10am'). "
            "Call this directly — do NOT delegate to the worker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "when": {"type": "string", "description": "ISO 8601 or natural-language datetime"},
                "note": {"type": "string", "description": "Reminder text — what is this check-back about"},
            },
            "required": ["when", "note"],
        },
    },
    {
        "name": "list_followups",
        "description": (
            "List your pending self-scheduled check-backs. Returns id, due_at, note, defer_count "
            "for each. Cancelled and done follow-ups are excluded. Call directly — no worker delegation."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "cancel_followup",
        "description": (
            "Cancel a previously scheduled follow-up by id. Idempotent — calling on an already-"
            "cancelled or already-done follow-up is safe. Returns {ok: bool}. Call directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Follow-up id from list_followups"}},
            "required": ["id"],
        },
    },
    ```

    **Site 3 — `WORKER_TOOL_SCHEMAS` exclusion (find via `grep -n "WORKER_TOOL_SCHEMAS" core/tools.py`):**
    Add the three names to the exclusion set.

    **Site 4 — `_handle_<name>()` functions (append after `_handle_get_self_status`).**
    **WARNING 7 fix in this handler — catch ImportError too:**

    ```python
    def _handle_schedule_followup(when: str, note: str) -> str:
        """Schedule a follow-up. ISO 8601 preferred; falls back to dateutil for NL. D-12.

        WARNING 7 fix — ImportError caught explicitly. If Plan 01's requirements.txt
        update did not deploy (Cloud Run on stale image, dev env without sync), the
        `from dateutil import parser` statement raises ModuleNotFoundError. Without
        catching it here the chat surfaces a 500. With the catch, the user gets a
        structured 'could_not_parse_when' error and Klaus's next turn can re-frame.
        """
        from datetime import datetime, timezone
        try:
            due_dt = datetime.fromisoformat(when)
        except (ValueError, TypeError):
            try:
                from dateutil import parser as _dt_parser
                due_dt = _dt_parser.parse(when)
            except (ImportError, ValueError, TypeError, OverflowError) as exc:
                return json.dumps({"error": f"could_not_parse_when: {exc}"})
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
        due_iso = due_dt.astimezone(timezone.utc).isoformat()
        from memory.firestore_db import FollowupStore
        store = FollowupStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        result = store.add(due_at=due_iso, note=note, origin="klaus_self")
        return json.dumps(result)

    def _handle_list_followups() -> str:
        """Return pending follow-ups (status='pending'), stripped of internal fields."""
        from memory.firestore_db import FollowupStore
        store = FollowupStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        pending = store.list_pending()
        stripped = [
            {
                "id": p.get("id", ""),
                "due_at": p.get("due_at", ""),
                "note": p.get("note", ""),
                "defer_count": int(p.get("defer_count", 0)),
            }
            for p in pending
        ]
        return json.dumps(stripped)

    def _handle_cancel_followup(id: str) -> str:
        """Cancel a follow-up. Idempotent — already-cancelled returns {ok: True}.

        Returns {ok: False} only when the id does not exist.
        """
        from memory.firestore_db import FollowupStore
        store = FollowupStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        ok = store.cancel(id)
        return json.dumps({"ok": bool(ok)})
    ```

    **Site 5 — `_HANDLERS` dispatch dict (find via `grep -n "_HANDLERS" core/tools.py`):**
    ```python
    "schedule_followup": lambda args: _handle_schedule_followup(**args),
    "list_followups":    lambda args: _handle_list_followups(),
    "cancel_followup":   lambda args: _handle_cancel_followup(**args),
    ```

    **Site 6 (prompt) — `prompts/smart_agent.md`:**
    Append a new section after the existing SELF-INSPECTION block:
    ```
    SELF-SCHEDULED FOLLOW-UPS
    You can manage your own check-backs with three brain-direct tools (never via delegate_to_worker):

    schedule_followup — set a reminder for yourself:
    - When Sir asks you to follow up later, OR when you decide a check-back is warranted, call schedule_followup(when, note).
    - `when` accepts ISO 8601 ("2026-05-21T15:00:00+00:00") or natural language ("tomorrow 3pm", "next monday 10am").
    - At the chosen time, an autonomous tick will give you a chance to polish-and-send, or defer if the moment isn't right.

    list_followups — inspect what's pending:
    - Returns id, due_at, note, defer_count for each pending follow-up.

    cancel_followup — drop a follow-up:
    - Idempotent. Use when Sir says "forget that reminder" or when you determine it's no longer relevant.

    You may also reach out proactively when judgment warrants it; your proactive messages appear in this conversation as a previous assistant turn.
    ```

    **Tests — `tests/test_tools.py`:**
    Implement all 13 tests from the behavior block in a `TestFollowupTools` class. Mock `FollowupStore`. Style reference: `tests/test_self_inspect.py`.

    For WARNING 7 test (Test 13), here is the canonical shape:
    ```python
    def test_schedule_followup_handles_dateutil_import_error(self, monkeypatch):
        """WARNING 7 — ImportError on dateutil must not surface as a 500."""
        import sys
        # Force the dateutil import inside the handler to fail.
        original_dateutil = sys.modules.pop("dateutil", None)
        original_parser = sys.modules.pop("dateutil.parser", None)
        monkeypatch.setitem(sys.modules, "dateutil", None)  # raises ImportError on `from dateutil import parser`
        try:
            from core.tools import _handle_schedule_followup
            result = _handle_schedule_followup(when="tomorrow 3pm", note="x")
            assert "could_not_parse_when" in result, f"expected structured error, got {result!r}"
        finally:
            if original_dateutil is not None:
                sys.modules["dateutil"] = original_dateutil
            if original_parser is not None:
                sys.modules["dateutil.parser"] = original_parser
    ```

    **End-of-task verification (MANDATORY):**
    ```bash
    grep -c "schedule_followup" core/tools.py   # expect >= 5
    grep -c "list_followups"    core/tools.py   # expect >= 5
    grep -c "cancel_followup"   core/tools.py   # expect >= 5
    grep -cE "schedule_followup|list_followups|cancel_followup" core/tools.py   # expect >= 15
    grep -c "ImportError" core/tools.py         # expect >= 1 (handler catches it — WARNING 7)
    ```
  </action>
  <verify>
    <automated>test "$(grep -cE 'schedule_followup|list_followups|cancel_followup' core/tools.py)" -ge 15 && grep -c "schedule_followup" prompts/smart_agent.md && grep -c "ImportError" core/tools.py && pytest tests/test_tools.py::TestFollowupTools -x</automated>
  </verify>
  <done>
    - `grep -cE "schedule_followup|list_followups|cancel_followup" core/tools.py` returns at least 15
    - `grep -c "schedule_followup" core/tools.py` returns at least 5
    - `grep -c "list_followups" core/tools.py` returns at least 5
    - `grep -c "cancel_followup" core/tools.py` returns at least 5
    - `grep -c "ImportError" core/tools.py` returns at least 1 (WARNING 7 — `_handle_schedule_followup` catches it)
    - `grep -c "schedule_followup" prompts/smart_agent.md` returns at least 1
    - `grep -n "SELF-SCHEDULED FOLLOW-UPS" prompts/smart_agent.md` returns 1 hit
    - All 13 tests in `TestFollowupTools` pass with `pytest tests/test_tools.py::TestFollowupTools -x` (includes `test_schedule_followup_handles_dateutil_import_error`)
    - `python -c "from core.tools import _HANDLERS; assert 'schedule_followup' in _HANDLERS and 'list_followups' in _HANDLERS and 'cancel_followup' in _HANDLERS; print('OK')"` prints OK
    - NOTE 4 verified: the 3 new entries appear AT THE END of the SMART_AGENT_DIRECT_TOOLS frozenset, not interspersed alphabetically (visual inspection of the diff)
  </done>
</task>

</tasks>

<verification>
After task completes:
1. 15-edit-point grep proves no site was missed: `grep -cE "schedule_followup|list_followups|cancel_followup" core/tools.py` >= 15
2. `pytest tests/test_tools.py -x` passes (including WARNING 7 regression test)
3. `python -c "from core.tools import SMART_AGENT_DIRECT_TOOLS, WORKER_TOOL_SCHEMAS; assert {'schedule_followup','list_followups','cancel_followup'} <= SMART_AGENT_DIRECT_TOOLS; assert {s['name'] for s in WORKER_TOOL_SCHEMAS}.isdisjoint({'schedule_followup','list_followups','cancel_followup'}); print('OK')"` prints OK
4. `prompts/smart_agent.md` has SELF-SCHEDULED FOLLOW-UPS section
5. `grep -c "ImportError" core/tools.py` >= 1 (WARNING 7)
</verification>

<success_criteria>
- All 3 tools registered at all 5 sites (15 grep hits in `core/tools.py`).
- Worker agent cannot invoke any of the 3 (exclusion test passes).
- ISO 8601 and natural-language `when` both parse correctly (D-12).
- WARNING 7: ImportError on dateutil produces structured error, not 500.
- NOTE 4: New entries appended at the end of SMART_AGENT_DIRECT_TOOLS (matches existing insertion-order pattern).
- `cancel_followup` is idempotent (D-15 spirit).
- `prompts/smart_agent.md` advertises the new tools and the "may reach out proactively" sentence (RESEARCH Open Question 3 recommendation).
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-02-SUMMARY.md` with:
- Final hit counts for each grep (proves all 15 edits)
- Confirmation: ImportError catch is in `_handle_schedule_followup` (WARNING 7) — show the exact line
- Confirmation: SMART_AGENT_DIRECT_TOOLS entries appended at the end (NOTE 4)
- Test class additions in `tests/test_tools.py` (including `test_schedule_followup_handles_dateutil_import_error`)
- prompts/smart_agent.md addition (line range)
</output>
