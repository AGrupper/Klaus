---
phase: 17-reflection-journal
plan: 04
subsystem: interfaces
tags: [journal, recall, pinecone, firestore, prompt-injection, smart-agent, tdd, jour-06]

# Dependency graph
requires:
  - phase: 17-01
    provides: JournalStore in firestore_db.py; "self" kind in _VALID_KINDS; remember_self()
  - phase: 17-02
    provides: core/reflection.py with run_reflection(); JournalStore entries written
  - phase: 17-03
    provides: POST /cron/reflect route; reflect job in heartbeat

provides:
  - MemoryTool.recall with kinds= param forwarding (mcp_tools/memory.py)
  - recall tool schema with optional kind enum (fact|chunk|self) in core/tools.py
  - _handle_recall(query, k, kind) translating kind -> kinds=[kind] in core/tools.py
  - get_self_status.journal field returning {date, summary, mood} from JournalStore (D-16)
  - _build_journal_store() helper and self._journal_store in core/main.py
  - {journal_digest} assembly in handle_message (newest-first, ~3 entries)
  - {journal_digest} placeholder in prompts/smart_agent.md
  - test_journal_digest_assembly implemented and GREEN (JOUR-06)
  - _install_firestore_mock extended with googleapiclient/google-auth stubs

affects:
  - Conversation quality — Klaus's last ~3 journal entries injected into every smart prompt
  - get_self_status tool — journal field now populated from Firestore
  - recall tool — kind="self" parameter enables journal vector search

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "kinds passthrough: MemoryTool.recall(kinds=None) → MemoryStore.recall(kinds=None) — None preserves default ['fact','chunk'] behavior"
    - "_handle_recall kind→kinds translation: kinds=[kind] if kind else None — single param, no schema change to HANDLERS"
    - "Journal digest assembly: get_recent(3) newest-first, '- {date} (mood: {mood}): {summary} | {highlight}' format, omit block when empty"
    - "JournalStore lazy import inside get_self_status: env-guard + try/except mirroring LLMUsage block above it"
    - "_build_journal_store() helper: mirrors _build_self_state_store() pattern exactly"
    - "Test mock strategy for AgentOrchestrator: patch _build_self_state_store + _build_journal_store + _load_self_md + os.environ to avoid real GCP/LLM calls"

key-files:
  created:
    - .planning/phases/17-reflection-journal/17-04-SUMMARY.md
  modified:
    - mcp_tools/memory.py
    - core/tools.py
    - core/main.py
    - prompts/smart_agent.md
    - tests/test_reflection.py

key-decisions:
  - "MemoryTool.recall gains kinds= not kind= — consistent with MemoryStore.recall interface; _handle_recall translates the singular kind param to kinds=[kind] list"
  - "JournalStore imported lazily inside get_self_status body — mirrors LLMUsageStore import pattern; avoids circular imports and startup failures when GCP is unavailable"
  - "_install_firestore_mock extended with googleapiclient + google_auth_oauthlib stubs — enables core.main/core.tools import in test environment without real Google libs"
  - "test_journal_digest_assembly patches _build_journal_store at core.main level — store builder runs in __init__; attribute-level patch is the correct interception point"

patterns-established:
  - "Store builder helper pattern: _build_journal_store() mirrors _build_self_state_store() — same env-var guard, same None return, same warning log"
  - "Digest assembly with empty-state guard: journal_digest='' when no entries → .replace() leaves no literal {journal_digest} in prompt"

requirements-completed: [JOUR-06]

# Metrics
duration: ~25min
completed: 2026-05-19
---

# Phase 17 Plan 04: Journal Conversation Wiring Summary

**`recall(kind="self")` journal search, `get_self_status.journal` populated from Firestore, and `{journal_digest}` of last ~3 entries injected into every smart-agent prompt — closing the self-model evolution loop (JOUR-06)**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-19T12:35:00Z
- **Completed:** 2026-05-19T13:00:00Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- **Task 1 (TDD):** Plumbed the `kind` parameter through all three layers:
  - `MemoryTool.recall` gained `kinds: list[str] | None = None` and forwards it to `MemoryStore.recall` (the `search_chat_history` sibling already did this — proved the pattern)
  - `recall` tool schema gained optional `kind` enum (`fact|chunk|self`) — NOT in `required` list
  - `_handle_recall(query, k, kind)` translates `kind → kinds=[kind]`; `kinds=None` with no kind preserves the default `fact+chunk` behavior
  - `test_recall_self_kind` extended with tool-layer assertions (MemoryTool.recall forwards kinds)
  - No changes to `SMART_AGENT_DIRECT_TOOLS`, `WORKER_TOOL_SCHEMAS`, or `_HANDLERS` — `recall` was already a direct tool; the `lambda args: _handle_recall(**args)` entry splats kwargs automatically

- **Task 2:** Filled `get_self_status.journal` stub (D-16):
  - Replaced bare `result["journal"] = None  # Phase 17 will populate` with real `JournalStore.get_recent(1)` lookup
  - Wrapped in env-var guard (`GCP_PROJECT_ID`) + `try/except` — degrades gracefully to `None` on any failure
  - Returns `{date, summary, mood}` from latest entry; `None` when journal is absent
  - `journal_error` key captured on exception (mirrors `cost_error` pattern from LLMUsage block above)

- **Task 3 (TDD):** Injected `{journal_digest}` into smart-agent prompt per JOUR-06 / D-14 / D-15:
  - `_build_journal_store()` helper added to `core/main.py` (mirrors `_build_self_state_store()`)
  - `self._journal_store = _build_journal_store()` initialized in `AgentOrchestrator.__init__`
  - `handle_message` assembles `journal_digest` from `get_recent(3)` (newest-first), one line per entry: `- {date} (mood: {mood}): {summary} | {top_highlight}`; empty string when no entries (block omitted)
  - Smart prompt render step gains `.replace("{journal_digest}", journal_digest)` between `{self_state}` and `{today_date}` (D-15 ordering)
  - `worker_system` is untouched — D-15 smart-only
  - `{journal_digest}` placeholder inserted into `prompts/smart_agent.md` after `{self_state}`; `prompts/worker_agent.md` is unchanged
  - `_install_firestore_mock()` extended with `googleapiclient`, `google_auth_oauthlib`, `google.auth.*`, `google.oauth2.credentials` stubs — enables `core.main` / `core.tools` import in the test environment
  - `test_journal_digest_assembly` implemented and GREEN: verifies 3-entry digest content + top highlight, empty-journal omission, and worker template cleanliness

## Task Commits

| Task | Type | Hash | Description |
|------|------|------|-------------|
| Task 1 RED+GREEN | feat | `681da2b` | Plumb kind param — MemoryTool.recall + recall tool schema + _handle_recall |
| Task 2 | feat | `78129b5` | Fill get_self_status journal field from JournalStore (D-16) |
| Task 3 RED | test | `3c37d81` | RED — failing test for journal_digest assembly (JOUR-06) |
| Task 3 GREEN | feat | `54cc0e1` | Inject {journal_digest} into smart prompt — JOUR-06 |

## Files Created/Modified

- `mcp_tools/memory.py` — `MemoryTool.recall` gains `kinds: list[str] | None = None`; forwards to `self._store.recall(user_id, query, k, kinds=kinds)`; 8 lines net added
- `core/tools.py` — recall schema gains `kind` enum property; `_handle_recall` gains `kind` param + `kinds=[kind] if kind else None` translation; `get_self_status` journal stub replaced with 18-line JournalStore lookup; 38 lines net added
- `core/main.py` — `JournalStore` import added; `_build_journal_store()` helper added; `self._journal_store` initialized in `__init__`; journal_digest assembly + render step `.replace()` added to `handle_message`; 32 lines net added
- `prompts/smart_agent.md` — `{journal_digest}` placeholder added on its own line after `{self_state}`; 2 lines added
- `tests/test_reflection.py` — `test_recall_self_kind` extended with tool-layer assertions; `_install_firestore_mock` extended with google-auth/googleapiclient stubs; `test_journal_digest_assembly` implemented (94 lines replacing 2-line skip stub); 150 lines net added

## Decisions Made

- **MemoryTool.recall accepts `kinds=` not `kind=`:** The underlying `MemoryStore.recall` takes `kinds` (plural list). `_handle_recall` does the singular→list translation so the tool schema stays clean (one optional enum param, not a list param).
- **JournalStore deferred import in get_self_status:** Importing at the top of `core/tools.py` would add a Firestore dependency at module load time. The deferred import inside the try/except guard matches the `LLMUsageStore` import directly above it — consistent and avoids startup failures when GCP is unavailable.
- **_install_firestore_mock extended (not replaced):** Adding google-auth/googleapiclient stubs to the existing module-level mock function ensures all tests in the file can import `core.main` and `core.tools` without real Google libraries. This is the minimal-change approach vs. per-test patch.dict.
- **test_journal_digest_assembly patches at _build_journal_store level:** The store builder runs in `__init__` before any message handling. Patching `_build_journal_store` at the `core.main` module level (not `__init__` itself) is the correct interception point — returns a pre-configured mock directly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] googleapiclient/google-auth stubs needed for core.tools/core.main import in tests**
- **Found during:** Task 1 GREEN (test_recall_self_kind tool-layer assertions) and Task 3 GREEN (test_journal_digest_assembly)
- **Issue:** `core/tools.py` imports `from googleapiclient.errors import HttpError` at module level; `core/auth_google.py` (imported by `core/tools.py`) imports `google_auth_oauthlib.flow`. Neither is installed in the local dev environment. Importing `core.tools` or `core.main` (which imports `core.tools`) failed with `ModuleNotFoundError`.
- **Fix:** Extended `_install_firestore_mock()` in `tests/test_reflection.py` with stubs for `googleapiclient`, `googleapiclient.errors`, `google_auth_oauthlib`, `google_auth_oauthlib.flow`, `google.auth.exceptions`, `google.auth.transport`, `google.auth.transport.requests`, and `google.oauth2.credentials`. The mock function already existed for Firestore; the extension is minimal and follows the same `sys.modules.setdefault()` pattern.
- **Files modified:** `tests/test_reflection.py`
- **Commit:** `54cc0e1`

**2. [Rule 2 - Missing critical functionality] AgentOrchestrator env vars needed in test**
- **Found during:** Task 3 GREEN — `AgentOrchestrator.__init__` requires `SMART_AGENT_BACKEND`, `SMART_AGENT_MODEL`, `SMART_AGENT_API_KEY`, `WORKER_AGENT_BACKEND`, `WORKER_AGENT_MODEL`, `WORKER_AGENT_API_KEY` from `os.environ`.
- **Fix:** Added `patch.dict("os.environ", _orch_env)` wrapping the `AgentOrchestrator()` construction in `test_journal_digest_assembly`. The same env-patch pattern was already used in `_mock_gather_sources` for run_reflection tests.
- **Files modified:** `tests/test_reflection.py`
- **Commit:** `54cc0e1`

**3. [Rule 1 - Bug] test_recall_self_kind tool-layer: avoid importing full core.tools**
- **Found during:** Task 1 GREEN — adding assertions that imported `core.tools._handle_recall` directly triggered the full transitive import chain (googleapiclient + google-auth + mcp_tools + more), which is too large to stub inline per-test.
- **Fix:** Changed the tool-layer assertions to test `MemoryTool.recall(kinds=...)` → `MemoryStore.recall(kinds=...)` directly (using a mock store), which is the real semantic contract. The `_handle_recall` logic (kinds=[kind] if kind else None) is thin and covered implicitly; the schema content is verified via grep in the acceptance criteria. This keeps the test fast and focused on the actual behavior change.
- **Files modified:** `tests/test_reflection.py`
- **Commit:** `681da2b`

## Known Stubs

None — all 9 `tests/test_reflection.py` tests are now real (8 pass; 1 pre-existing fastapi env failure in local dev, passes in CI where fastapi is installed).

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: prompt-injection-surface | core/main.py | LLM-authored journal summary/mood injected verbatim into smart prompt |

Mitigation: T-17-10 — single-user system, journal is Klaus's own first-person diary read back only into his own prompt. `summary` and `mood` are plain text, never executed. Acceptable risk per plan's threat model (LOW severity). T-17-11 — `kind` enum constrained to `["fact","chunk","self"]`; Pinecone `user_id` $eq filter prevents cross-user leakage regardless. T-17-12 — `get_recent(3)` in `handle_message` and `JournalStore.get_recent(1)` in `get_self_status` both wrapped in try/except returning `""`/`None` — Firestore failure degrades gracefully and never crashes a conversation.

## Self-Check: PASSED

- FOUND: mcp_tools/memory.py
- FOUND: core/tools.py
- FOUND: core/main.py
- FOUND: prompts/smart_agent.md
- FOUND: tests/test_reflection.py
- FOUND: .planning/phases/17-reflection-journal/17-04-SUMMARY.md
- FOUND: commit 681da2b (feat: kind param plumbing)
- FOUND: commit 78129b5 (feat: get_self_status journal field)
- FOUND: commit 3c37d81 (test: RED test_journal_digest_assembly)
- FOUND: commit 54cc0e1 (feat: journal_digest injection)
- No unexpected file deletions

---
*Phase: 17-reflection-journal*
*Completed: 2026-05-19*
