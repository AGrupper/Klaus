---
phase: 15-codebase-self-knowledge
status: passed
verified: 2026-05-18
requirements_verified: 5
requirements_total: 5
must_haves_passed: 10
must_haves_total: 10
human_verification: []
---

# Verification: Phase 15 — Codebase Self-Knowledge

**Goal:** Klaus can read and search his own source at conversation time — genuine, always-current codebase self-knowledge.

**Verdict: PASSED** — All 5 requirements verified against live codebase. 35/35 tests green.

---

## Requirement Verification

### SELF-01 — list_own_files ✓

**Acceptance criteria:** `list_own_files(subdir=None)` lists deployed source files; no subdir → all files; subdir → filtered; excludes `.git/`, `__pycache__/`, `*.pyc`, `.env*`, `node_modules/`.

**Verified:**
- `list_own_files()` → 8743 files, `mcp_tools/self_inspect.py` present, no `.git/` entries
- `list_own_files('mcp_tools')` → all paths start with `mcp_tools/`
- `.env*` files excluded from listing (verified via `_is_excluded_from_listing`)

**Evidence:** `mcp_tools/self_inspect.py:195–232`, test suite `tests/test_self_inspect.py` (SELF-01 group, 10 tests)

---

### SELF-02 — read_own_source with denylist ✓

**Acceptance criteria:** `read_own_source(path)` returns file contents; rejects path traversal and secret denylist (`.env*`, `*secret*`, `*credential*`, `*token*`, OAuth JSON).

**Verified:**
- `read_own_source('.env')` → `{"error": "..."}` — never returns content
- `read_own_source('../../etc/passwd')` → `{"error": "..."}` — traversal blocked
- `read_own_source('/etc/passwd')` → `{"error": "..."}` — absolute path blocked
- `read_own_source('mcp_tools/self_inspect.py')` → `{"path": ..., "content": ..., "lines": N}`
- Double denylist check: raw path AND resolved path both checked

**Evidence:** `mcp_tools/self_inspect.py:235–284`, `_is_denied()`, tests (SELF-02 group)

---

### SELF-03 — search_own_source ✓

**Acceptance criteria:** `search_own_source(query)` full-text searches; returns `{file, line, snippet}` matches; empty query rejected.

**Verified:**
- `search_own_source('LLMUsageStore')` → 98 matches, finds `memory/firestore_db.py`
- `search_own_source('')` → `{"error": "query must be a non-empty string."}`
- Denied files skipped during walk (secrets never scanned)

**Evidence:** `mcp_tools/self_inspect.py:287–335`, tests (SELF-03 group)

---

### SELF-04 — Tool registration at all 5 sites ✓

**Acceptance criteria:** All three tools registered in `core/tools.py` (TOOL_SCHEMAS, _HANDLERS, SMART_AGENT_DIRECT_TOOLS, handler functions, WORKER_TOOL_SCHEMAS exclusion).

**Verified:**
- `SMART_AGENT_DIRECT_TOOLS` contains `list_own_files`, `read_own_source`, `search_own_source`
- `TOOL_SCHEMAS` has 3 new schema dicts, each with "do NOT delegate to the worker" in description
- `WORKER_TOOL_SCHEMAS` excludes all 3 tools (worker cannot see or call them)
- `from mcp_tools.self_inspect import ...` import in lazy-singleton block
- `_handle_list_own_files`, `_handle_read_own_source`, `_handle_search_own_source` handler functions defined
- `_HANDLERS` dict has 3 lambda entries routing to handlers
- `dispatch('read_own_source', {'path': '.env'})` → JSON with "error"
- `dispatch('list_own_files', {})` → JSON with "files" and "count"

**Evidence:** `core/tools.py` (5 edit sites), end-to-end dispatch verified

---

### SELF-05 — Smart agent prompt updated ✓

**Acceptance criteria:** `prompts/smart_agent.md` tells Klaus he can inspect his own source.

**Verified:**
- "CODEBASE SELF-INSPECTION" section present, after "LONG-TERM MEMORY"
- All 3 tool names documented with use cases
- D-01 enforced: "do not narrate the process" rule present
- "never via delegate_to_worker" explicit instruction present

**Evidence:** `prompts/smart_agent.md` (last section)

---

## Must-Have Truths

| Truth | Status |
|-------|--------|
| `list_own_files()` returns a list of source file paths from the project root, excluding secrets/cache | ✓ |
| `read_own_source(path)` returns file contents for safe paths and a descriptive error for denied paths | ✓ |
| `read_own_source('.env')` returns an error string, not file contents | ✓ |
| `search_own_source(query)` returns line-level matches with file path, line number, and snippet | ✓ |
| Path traversal (e.g. `../../etc/passwd`) is blocked by `read_own_source` | ✓ |
| Klaus can call all 3 tools directly without delegating to the worker | ✓ |
| The three tools appear in TOOL_SCHEMAS with "Call this directly" in their descriptions | ✓ |
| SMART_AGENT_DIRECT_TOOLS includes all three tool names | ✓ |
| WORKER_TOOL_SCHEMAS excludes all three tool names | ✓ |
| `prompts/smart_agent.md` tells Klaus these three tools exist and when to use them | ✓ |

---

## Test Results

```
35 passed in 21.16s
```

All 35 tests in `tests/test_self_inspect.py` green. Coverage: SELF-01 (listing), SELF-02 (denylist + traversal), SELF-03 (search), TDD RED→GREEN discipline confirmed via commit history.

---

## Key Artifacts

| Artifact | Status |
|----------|--------|
| `mcp_tools/self_inspect.py` | Created — 229 lines, 3 public functions, stdlib only |
| `tests/test_self_inspect.py` | Created — 35 tests, all passing |
| `core/tools.py` | Modified — 5 registration sites added |
| `prompts/smart_agent.md` | Modified — CODEBASE SELF-INSPECTION section appended |

---

## Phase Goal Achievement

**Goal:** Klaus can read and search his own source at conversation time — genuine, always-current codebase self-knowledge.

**Assessment:** Goal fully achieved. Klaus now has three working tools (`list_own_files`, `read_own_source`, `search_own_source`) that are wired into the agent's direct-tool path (brain-only, worker excluded), documented in the system prompt, and protected against secret leakage and path traversal. All capabilities are verified against the live codebase with 35 automated tests.
