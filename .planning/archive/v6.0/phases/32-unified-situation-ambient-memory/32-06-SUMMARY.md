---
phase: 32-unified-situation-ambient-memory
plan: 06
subsystem: memory-chat
tags: [pinecone, ambient-recall, conversation-continuity, timeout-guard, prompt-caching]

# Dependency graph
requires:
  - phase: 32-unified-situation-ambient-memory
    plan: 02
    provides: "render_smart_system returns (stable, volatile); LLMClient.chat system param accepts str | tuple[str, str]; volatile half is the cache-safe injection point"
provides:
  - "MemoryStore.recall_ambient(user_id, query, k, min_score) — blended-score-floored auto-inject path, sharing _rank_candidates() with the unthresholded recall() tool"
  - "AgentOrchestrator._ambient_recall — timeout-guarded (2.5s), never-raising 'Things you remember' block injected into the volatile half of every chat turn"
  - "{things_you_remember} placeholder in prompts/smart_agent.md, post-CURRENT-TIME (volatile, cache-safe)"
  - "AgentOrchestrator._build_continuity_tail — best-effort idle-fresh session tail rehydrate (hours=6) + one synthetic role:user time-gap boundary marker"
affects: [32-03 (forget_memory correction path shares the pinecone_db module), 33 (occasion cascade will reuse the volatile-half injection pattern for its own context blocks)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared ranking helper (_rank_candidates) feeding two callers with different post-filter policy — unthresholded recall() vs floored recall_ambient() — instead of a boolean/None param that would silently change tool-facing behavior"
    - "Timeout-guarded background recall via a persistent (non-context-managed) ThreadPoolExecutor + future.result(timeout=...) — deliberately never `with executor:` to avoid shutdown(wait=True) blocking on a hung worker"
    - "Pre-turn snapshot (conversation_manager.get() before append()) used as the idle-fresh trigger, avoiding any Firestore-backend-specific 'was this a new session' API"

key-files:
  created: []
  modified:
    - memory/pinecone_db.py
    - core/main.py
    - prompts/smart_agent.md
    - tests/memory/test_pinecone_recall.py
    - tests/test_main.py

key-decisions:
  - "recall_ambient() is a separate method, not a min_score param on recall() — keeps the deliberate recall tool call unthresholded (D-03) with zero risk of an accidental default-arg regression later coupling the two paths"
  - "AMBIENT_MIN_SCORE=0.5 module constant marked [ASSUMED]/tunable; recall_ambient logs the raw (score, was_injected) pair at debug for every candidate so the floor can be re-tuned from real production score distributions"
  - "Ambient recall executor is NOT used as a context manager — `with executor:` calls shutdown(wait=True) on exit, which would block handle_message on a hung worker thread indefinitely, defeating the whole point of the timeout guard"
  - "Continuity-tail idle-fresh detection reads conversation_manager.get(user_id) BEFORE persisting the new turn (pre_turn_messages) rather than probing FirestoreConversationStore internals — works identically across any ConversationStore backend"
  - "_build_continuity_tail wraps its ENTIRE body (not just the get_recent_window call) in one broad try/except — verified necessary because a generic MagicMock() collaborator (used throughout the existing test suite) auto-creates get_recent_window as a truthy, callable, non-list-returning attribute; only a whole-function guard degrades safely against that shape"
  - "Boundary marker uses role:\"user\" (never a bespoke system-flavored aside) — Anthropic's messages array only supports user/assistant roles, mirroring core/autonomous.py::_compose_layer2's existing synthetic-turn pattern"

requirements-completed: [MEM-01, MEM-02]

# Metrics
duration: 55min
completed: 2026-07-22
---

# Phase 32 Plan 06: Ambient Auto-Recall + Conversation Continuity Summary

**Every chat turn now best-effort injects a score-thresholded "Things you remember" block (timeout-guarded, never blocking) into the volatile prompt half, and a 6h+ idle-fresh session rehydrates its recent tail with a synthetic time-gap marker instead of greeting Amit as an amnesiac.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 3/3 completed
- **Files modified:** 5 (2 source, 1 prompt template, 2 test files)

## Accomplishments

- `MemoryStore.recall_ambient(user_id, query, k=5, min_score=AMBIENT_MIN_SCORE)` filters candidates by their BLENDED (post-recency-decay) score before slicing to `k`, sharing a new `_rank_candidates()` helper with the existing `recall()` — which stays fully unthresholded (D-03: a deliberate recall tool call must still surface a marginal match). `AMBIENT_MIN_SCORE=0.5` is a module constant, tagged `[ASSUMED]`/tunable, with every candidate's `(score, was_injected)` logged at debug for future re-tuning from real production data.
- `AgentOrchestrator._ambient_recall(user_message, user_id)` runs `recall_ambient` on the LIVE user message before every smart-loop turn via a shared, non-context-managed `ThreadPoolExecutor` with a hard `AMBIENT_RECALL_TIMEOUT_SECONDS=2.5` budget. ANY exception (embed/network error, missing `PINECONE_API_KEY`, malformed store) OR a timeout yields an empty block and never raises into `handle_message` — proven by a forced-hang test that asserts the turn returns in well under the timeout despite a live 0.3s-sleeping worker.
- `{things_you_remember}` was added to `prompts/smart_agent.md` immediately after the existing `CURRENT TIME` heading — the Plan 02 cache seam — so the block always lands in the volatile half and never touches the cached stable prefix (T-32-13 mitigation, verified against the real template file, not just a test fixture).
- `AgentOrchestrator._build_continuity_tail` detects an idle-fresh session by reading `conversation_manager.get(user_id)` BEFORE persisting the new turn; an empty pre-turn read triggers `get_recent_window(hours=CONTINUITY_TAIL_HOURS=6)` and prepends the stored tail plus exactly one synthetic `role:"user"` boundary marker (`"[~Nh elapsed since the messages above — a new conversation begins here.]"`) to the LOCAL message list passed to `_run_smart_loop` — never re-persisted, since it's already stored. Active (non-idle) sessions never call `get_recent_window` at all.
- The whole tail-building helper is wrapped in one broad `try`/`except` (not just the store call) — this was load-bearing, not decorative: a bare `MagicMock()` conversation manager (used throughout the pre-existing test suite) auto-creates `get_recent_window` as a truthy, callable attribute whose return value is *also* a `MagicMock` — only a whole-function guard, combined with `if not tail:` short-circuiting on the mock's default empty-iterable behavior, keeps every unrelated pre-existing `handle_message` test passing unmodified.

## Task Commits

1. **Task 1: Score-thresholded ambient recall path in pinecone_db**
   - `d87ed70` feat(32-06): score-thresholded ambient recall path in pinecone_db
2. **Task 2: Ambient "Things you remember" block in handle_message (timeout-guarded, never blocks)**
   - `6b31910` feat(32-06): ambient Things-you-remember block in handle_message (MEM-01)
3. **Task 3: Continuity tail + time-gap boundary marker for idle-fresh sessions**
   - `cd067ce` feat(32-06): continuity tail + time-gap boundary marker for idle-fresh sessions (MEM-02)

Each task's tests were written and run to green before being folded into that task's single commit; Tasks 2 and 3 were implemented together during exploration (both touch `handle_message`) and then deliberately split apart and re-applied task-by-task so each commit is independently atomic and independently test-green (verified by running the full `tests/test_main.py` suite after each split).

## Files Created/Modified

- `memory/pinecone_db.py` — new `AMBIENT_MIN_SCORE` module constant; new `recall_ambient()` method; `recall()` refactored onto a shared `_rank_candidates()` helper (over-fetch + recency-blend, unsliced) with no behavior change; ambient path logs raw `(score, was_injected)` pairs at debug.
- `core/main.py` — `import concurrent.futures`; new constants `AMBIENT_RECALL_TIMEOUT_SECONDS`, `AMBIENT_RECALL_K`, `CONTINUITY_TAIL_HOURS`, and the shared `_AMBIENT_RECALL_EXECUTOR`; new module functions `_ambient_recall_worker`, `_format_things_you_remember`, `_ambient_recall`, `_build_continuity_tail`, `_format_elapsed_hours`; `handle_message` now (a) substitutes the ambient block into the volatile half right after `render_smart_system`, before the `meal_audit` append, and (b) captures `pre_turn_messages` before persisting the new turn and prepends a continuity tail + marker when that pre-turn read was empty.
- `prompts/smart_agent.md` — added `{things_you_remember}` on its own line immediately after the `CURRENT TIME` section (post cache-seam, volatile half).
- `tests/memory/test_pinecone_recall.py` — new `TestRecallAmbientScoreThreshold` class (7 tests: below-floor exclusion, at/above-floor inclusion, exact-boundary inclusivity, mixed-batch filtering, unthresholded `recall()` regression, user_id scoping, custom `min_score` param).
- `tests/test_main.py` — new `TestAmbientRecall` class (5 tests: non-empty injection into volatile, forced-raise → empty block no exception, forced-hang → bounded latency, stable-half never touched, empty-result → empty placeholder) and new `TestContinuityTail` class (4 tests: idle-fresh prepends tail + one marker with correct elapsed-hours wording, active session gets no tail and never calls `get_recent_window`, a raising `get_recent_window` degrades safely, a conversation manager entirely missing `get_recent_window` degrades safely).

## Decisions Made

- `recall_ambient()` kept as a fully separate method rather than a `min_score` parameter on `recall()` — a shared signature risks a future caller accidentally passing a floor into the deliberate-recall tool path and silently changing D-03 behavior.
- The ambient-recall executor is a persistent module-level `ThreadPoolExecutor`, never opened with `with executor:` — that pattern calls `shutdown(wait=True)` on exit, which blocks the *calling* thread until every submitted worker finishes, including a hung one. Using `.submit()` + `future.result(timeout=...)` directly gives a true bounded wait; the (rare) hung worker finishes in the background and its result is simply discarded.
- Idle-fresh detection deliberately reads `conversation_manager.get(user_id)` (protocol-level, backend-agnostic) rather than any Firestore-specific "session_start_index" internals — works the same whether the backend is `FirestoreConversationStore` or (in local dev) `InMemoryConversationStore`, which naturally has no `get_recent_window` and therefore naturally never triggers a tail (verified by an explicit test using `MagicMock(spec=["get", "append", "clear"])`).
- Plan's per-task `<files>` referenced `tests/test_pinecone_db.py`, which does not exist in this codebase — the real home of `MemoryStore` unit tests is `tests/memory/test_pinecone_recall.py`, and that's where the new score-threshold tests were added (documented as a deviation below).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — blocking: nonexistent test file path in plan] `tests/test_pinecone_db.py` does not exist**
- **Found during:** Task 1, before writing any test code.
- **Issue:** The plan's frontmatter `files_modified` and Task 1's `<files>`/`<verify>` reference `tests/test_pinecone_db.py`, but `MemoryStore` tests actually live under `tests/memory/` (`test_pinecone_recall.py`, `test_pinecone_upsert.py`, `test_pinecone_embed.py`) — confirmed via `find`/`ls`.
- **Fix:** Added the new `TestRecallAmbientScoreThreshold` class to `tests/memory/test_pinecone_recall.py` (the file that already owns `MemoryStore.recall`/`_blend_recency` tests). Every new test method name carries the literal `score_threshold` substring so the plan's specified `pytest ... -k score_threshold -x` verification command still selects exactly this class regardless of file location.
- **Files modified:** `tests/memory/test_pinecone_recall.py` (in place of the nonexistent `tests/test_pinecone_db.py`).
- **Verification:** `pytest tests/memory/test_pinecone_recall.py -k score_threshold -x` → 7 passed.
- **Committed in:** `d87ed70` (Task 1).

**2. [Rule 3 — blocking: MagicMock auto-attribute defeats a naive `getattr(..., None)` guard] `_build_continuity_tail` needed a whole-function try/except, not just a guarded store call**
- **Found during:** Task 3, running the pre-existing `tests/test_main.py` suite after the first implementation pass.
- **Issue:** `_make_orchestrator_for_handle_message` (the shared test helper used by ~30 pre-existing tests) stubs `orch.conversation_manager = MagicMock()`. A bare `MagicMock()` auto-creates `get_recent_window` as a truthy, callable attribute on first access, so a naive `getattr(conversation_manager, "get_recent_window", None)` never falls back to `None` for these tests — the code would then call the mock, receive another `MagicMock` back as "tail", and proceed into indexing/formatting logic never designed to handle a non-list.
- **Fix:** Wrapped the entire `_build_continuity_tail` body (not just the `get_recent_window(...)` call) in one `try`/`except Exception`, and confirmed empirically (via a standalone Python probe) that a bare `MagicMock`'s default `__iter__` returns `iter([])`, so `clean_tail` ends up `[]` and the caller's `if tail:` guard correctly no-ops — no exception is ever raised, and the ~30 unrelated pre-existing `handle_message` tests remain green unmodified.
- **Files modified:** `core/main.py` (`_build_continuity_tail`).
- **Verification:** Full `tests/test_main.py` suite (36 tests) green after the fix; explicit regression test `test_continuity_tail_missing_get_recent_window_is_a_safe_noop` added using a `spec`-restricted mock to also cover the real "attribute genuinely absent" case.
- **Committed in:** `cd067ce` (Task 3).

---

**Total deviations:** 2 auto-fixed (Rule 3 — a nonexistent referenced test file, and a test-infrastructure edge case that required broader defensive coding than the plan's illustrative snippet showed). No scope creep — both fixes stayed within the plan's stated behavior contracts.

## Issues Encountered

- The worktree's base commit needed correcting via the mandated `git reset --hard` to `2092e9096ee87c5ed1715cecd618c156f9ec9946` (the Phase 32 wave-1 tracking commit) before any work began — HEAD was on a stale merge-base at session start, same class of issue documented in the 32-02 SUMMARY.
- `.venv` at the worktree path did not exist; the repo's real Python 3.13.12 virtualenv at `/Users/amitgrupper/Desktop/Klaus/.venv` was used directly (read-only interpreter invocation, not a git operation) for all `pytest` runs — the system `python3` defaults to 3.14, which is documented as unsafe (grpc/protobuf GC segfault risk).
- `tests/test_hub_chat.py`, documented in the 32-02 SUMMARY as segfaulting standalone, passed cleanly (29/29) when run alone during this plan's full-suite verification — likely environment/ordering-dependent, not a regression introduced here (this plan never touches hub chat code).

## Full-suite Verification

- `pytest tests/ -q --ignore=tests/test_hub_chat.py` → **2085 passed, 3 skipped** (60.8s).
- `pytest tests/test_hub_chat.py -q` (run separately) → **29 passed**.
- Combined: **2114 passed, 3 skipped**, comfortably above the documented ≥1775 baseline.
- `pytest tests/memory/test_pinecone_recall.py -k score_threshold -x` → 7 passed.
- `pytest tests/test_main.py -k ambient_recall -x` → 5 passed.
- `pytest tests/test_main.py -k continuity_tail -x` → 4 passed.
- `grep -n "{things_you_remember}" prompts/smart_agent.md` → line 385, confirmed after the `CURRENT TIME` heading (line 378) — in the volatile half per `_split_stable_volatile`'s seam marker (verified directly via a `_split_stable_volatile(open('prompts/smart_agent.md').read())` sanity script: placeholder present in `volatile`, absent from `stable`).

## Self-Check: PASSED

- `memory/pinecone_db.py` — FOUND (modified, present)
- `core/main.py` — FOUND (modified, present)
- `prompts/smart_agent.md` — FOUND (modified, present)
- `tests/memory/test_pinecone_recall.py` — FOUND (modified, present)
- `tests/test_main.py` — FOUND (modified, present)
- Commit `d87ed70` — FOUND in `git log --oneline --all`
- Commit `6b31910` — FOUND in `git log --oneline --all`
- Commit `cd067ce` — FOUND in `git log --oneline --all`
- `pytest tests/memory/test_pinecone_recall.py -k score_threshold -x` — 7 passed
- `pytest tests/test_main.py -k ambient_recall -x` — 5 passed
- `pytest tests/test_main.py -k continuity_tail -x` — 4 passed
- `pytest tests/ -q --ignore=tests/test_hub_chat.py` — 2085 passed, 3 skipped
- `grep -n "{things_you_remember}" prompts/smart_agent.md` — line 385, confirmed post-CURRENT-TIME (volatile half)

## Next Phase Readiness

- Both MEM-01 (ambient auto-recall) and MEM-02 (continuity tail) structural pieces are live in `handle_message` and safe by construction (timeout-guarded, best-effort, never-raising). The remaining MEM-0x work in this phase (`training_reality` reconciliation, `forget_memory`, Groq daily token ledger, location awareness) is scoped to other plans in the wave.
- **Manual validation still open (not verifiable from this local/worktree execution):** on a live deploy with real Pinecone data, confirm (a) the ambient block actually surfaces relevant memories for a real user turn and the score floor feels right in practice (the debug log of raw `(score, was_injected)` pairs is designed to make this observable), and (b) a real 6h+ idle Telegram/Hub return shows the tail + boundary marker in the brain's effective context rather than a cold start. Flag for the operator at next deploy.

---
*Phase: 32-unified-situation-ambient-memory*
*Plan: 06*
*Completed: 2026-07-22*
