---
phase: 15-codebase-self-knowledge
reviewed: 2026-05-18T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - mcp_tools/self_inspect.py
  - tests/test_self_inspect.py
  - core/tools.py
  - prompts/smart_agent.md
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-05-18
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the three new source files (`mcp_tools/self_inspect.py`, `tests/test_self_inspect.py`, `core/tools.py`) and the updated `prompts/smart_agent.md` for Phase 15. The self-inspection implementation is well-structured, applies path-traversal guards correctly at two points (pre-resolve and post-resolve), and the test suite provides solid acceptance coverage for all three SELF-0x criteria.

Three warnings were found: a deprecated asyncio API in `core/tools.py` that raises `RuntimeError` in Python 3.14 when called outside an async context, a divergence between the "Get Ready" block timing stated in the system prompt (T-60 min) and what the calendar tool actually creates (45 min before start), and a `list_own_files` information leak that exposes the names of credential-adjacent files (e.g. `config/token.json`, `config/ticktick_tokens.json`) even though reading them is blocked. Three info items cover minor style and defence-in-depth improvements.

---

## Warnings

### WR-01: `asyncio.get_event_loop()` raises `RuntimeError` in Python 3.14

**File:** `core/tools.py:1022`
**Issue:** `asyncio.get_event_loop()` was deprecated in Python 3.10 and in Python 3.12+ raises `RuntimeError: There is no current event loop` when called from a thread with no running loop. The project runs Python 3.14 (confirmed from environment). In the normal Cloud Run path, `_handle_run_morning_briefing` is called from an async handler where a loop already exists, so this silently works — but if the function is ever called from a worker thread, a test harness, or a sync entry point, the outer `except Exception` swallows the `RuntimeError` and the briefing silently never fires.

**Fix:**
```python
# Replace:
loop = asyncio.get_event_loop()
loop.create_task(run_morning_briefing(_application.bot, today_iso, dedup=False))

# With:
loop = asyncio.get_running_loop()   # raises RuntimeError if no loop — makes the failure loud
loop.create_task(run_morning_briefing(_application.bot, today_iso, dedup=False))
```
`get_running_loop()` is the correct API for scheduling a task from within an already-running async context. If this handler might legitimately be called from a sync context in the future, add an explicit guard before the call.

---

### WR-02: "Get Ready" block timing diverges between system prompt and calendar implementation

**File:** `prompts/smart_agent.md:23-24` vs `mcp_tools/calendar_tool.py:344`
**Issue:** The system prompt instructs Klaus: _"T-60 min: 'Get Ready' block — create as a SEPARATE calendar event."_ However, the actual `create_calendar_event` tool description (lines 80-81 in `core/tools.py`) and the calendar tool implementation both create a **45-minute** "Get Ready" block. The brain model reads the system prompt and forms a belief about a 60-minute prep block; the actual block created is 45 minutes. This discrepancy could cause Klaus to misreport event timings to the user, or to flag false scheduling conflicts when consulting its own prompt.

**Fix:** Align the system prompt with the implementation. Since `calendar_tool.py` documents the 45-minute value with an explicit rationale (line 341-342: "user's personal pre-workout routine takes ~45 min per docs/USER.md"), the prompt is wrong:
```markdown
# In prompts/smart_agent.md, change:
  T-60 min: "Get Ready" block — create as a SEPARATE calendar event.

# To:
  T-45 min: "Get Ready" block — create as a SEPARATE calendar event
            (45-minute pre-workout prep, per your personal routine).
```

---

### WR-03: `list_own_files` exposes credential-adjacent filenames that denylist is intended to protect

**File:** `mcp_tools/self_inspect.py:72-82` and `mcp_tools/self_inspect.py:114-126`
**Issue:** `list_own_files` uses `_is_excluded_from_listing` (which checks only `*.pyc`, `.env`, `.env.*`, `*.env`) rather than the broader `_DENYLIST_PATTERNS` (`*token*`, `*oauth*`, `*.json`, etc.). As a result, files like `config/token.json` and `config/ticktick_tokens.json` appear by name in the listing even though `read_own_source` correctly blocks reading them. An adversary who can prompt Klaus to call `list_own_files` learns that `config/ticktick_tokens.json` exists at that path, which aids targeted attacks even without file contents.

The listing currently outputs:
```
config/token.json
config/ticktick_tokens.json
```

**Fix:** Apply `_is_denied` as a secondary filter inside `list_own_files`, after `_is_excluded_from_listing`:
```python
# In list_own_files, change the inner loop body from:
        if _is_excluded_from_listing(rel):
            continue
        files.append(rel)

# To:
        if _is_excluded_from_listing(rel):
            continue
        if _is_denied(rel):          # also hide denylist filenames from the index
            continue
        files.append(rel)
```
This makes the listing consistent with the read and search policies.

---

## Info

### IN-01: `_handle_notion_query_database` shadows the built-in `filter`

**File:** `core/tools.py:1047`
**Issue:** The parameter is named `filter`, which shadows Python's built-in `filter()` function within that function's scope. This is not a bug here because the built-in is not used inside the function, but it is a naming anti-pattern that CODING_STANDARDS.md flags ("Be highly descriptive").

**Fix:**
```python
def _handle_notion_query_database(
    database_id: str,
    notion_filter: dict | None = None,   # renamed
    sorts: list | None = None,
    page_size: int = 100,
) -> str:
    result = _notion_query_database(
        database_id=database_id, filter=notion_filter, sorts=sorts, page_size=page_size
    )
    return json.dumps(result)
```
The public tool schema uses the name `"filter"` (correct for Notion API alignment), so the rename is only in the Python handler.

---

### IN-02: Stray double blank line between `_get_calendar_tool` and `_get_memory_store`

**File:** `core/tools.py:758-761`
**Issue:** Three consecutive blank lines appear between `_get_calendar_tool` and `_get_memory_store`. PEP 8 and the project's readability standard both call for exactly two blank lines between top-level definitions.

**Fix:** Remove the extra blank line so lines 758-761 read:
```python
    return _calendar_tool


def _get_memory_store() -> MemoryStore:
```

---

### IN-03: `test_llm_usage_store_found` asserts on infrastructure that may not exist in CI

**File:** `tests/test_self_inspect.py:252-257`
**Issue:** The test `test_llm_usage_store_found` searches live source files for `LLMUsageStore` in `memory/firestore_db.py` and fails with `AssertionError` if the symbol is absent. This couples the self-inspection test suite to a specific symbol in a different module. If `LLMUsageStore` is renamed or moved during a future refactor, this test breaks without any change to `self_inspect.py`. The SELF-0x acceptance criteria being validated here is that `search_own_source` returns results at all — not that a specific class exists.

**Fix:** Refactor to test a symbol guaranteed to exist in `self_inspect.py` itself (or add a comment explaining that this test is an integration smoke test for the firestore module):
```python
def test_known_symbol_in_self_inspect(self):
    """search_own_source finds a symbol defined in the module under test."""
    mod = _import_module()
    result = mod.search_own_source("_DENYLIST_PATTERNS")
    assert result["total"] >= 1, \
        f"_DENYLIST_PATTERNS not found in source; total={result['total']}"
```

---

_Reviewed: 2026-05-18_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
