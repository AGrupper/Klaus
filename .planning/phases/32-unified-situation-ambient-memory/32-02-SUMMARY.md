---
phase: 32-unified-situation-ambient-memory
plan: 02
subsystem: llm-infra
tags: [anthropic, prompt-caching, cache_control, llm_client, render_smart_system, cost]

# Dependency graph
requires:
  - phase: 30.5-brain-upgrade-sonnet-5
    provides: Anthropic backend with a single-block cache_control system param, cache-token metering (cache_read_tokens/cache_write_tokens) in LLMClient.chat + LLMUsageStore
provides:
  - "LLMClient.chat system param accepts str | tuple[str, str]; Anthropic backend emits two real content blocks (cache_control on stable only) for a tuple, degrading to the existing single block when volatile is empty"
  - "AgentOrchestrator.render_smart_system returns (stable, volatile) split at the existing CURRENT TIME heading in prompts/smart_agent.md — no template edit"
  - "handle_message appends chat-only meal_audit guidance to the volatile half only, preserving the cached stable prefix"
  - "core/autonomous.py's two compose sites pass the tuple through render_smart_system -> _run_smart_loop -> chat() unchanged"
affects: [32-06 (adds ambient/tail placeholders to the volatile section), 30.5-brain-upgrade-sonnet-5 (cache-token metering now gets real cache reads on same-day chat turns)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "System prompt cache split: render once, then split the fully-rendered string at a literal seam marker in the template — no template restructuring needed for the split itself"
    - "str | tuple[str, str] system param across all three LLM backends, each degrading a tuple appropriately (Anthropic: two cache blocks; Gemini/OpenAI-compat: joined string)"

key-files:
  created: []
  modified:
    - core/llm_client.py
    - core/main.py
    - core/autonomous.py
    - tests/test_llm_client.py
    - tests/test_main_render_smart_system.py
    - tests/test_main.py
    - tests/test_reflection.py

key-decisions:
  - "Anthropic tuple system with an empty volatile half degrades to a single cached block instead of sending an empty text content block (avoids a likely Anthropic 400) — applies to autonomous.md/worker_agent.md, which lack the CURRENT TIME seam"
  - "The split marker is the literal 'CURRENT TIME\\nCurrent time:' text already in prompts/smart_agent.md (no template edit) — templates without it (autonomous.md, worker_agent.md, synthetic test templates) fall back to (full_content, '')"
  - "{today_date} stays in the stable half by design (once/day change, acceptable on the 1h cache TTL) — only {current_time} (per-minute) is volatile"
  - "meal_audit chat-only guidance is appended to the volatile half, not the stable half, so the cached persona prefix is never touched by chat-path-only content"
  - "core/autonomous.py's two compose sites needed zero logic changes — render_smart_system's tuple return already flows through them unmodified since neither site unpacks or string-concatenates the result"

requirements-completed: [MEM-01, MEM-02]

# Metrics
duration: 25min
completed: 2026-07-22
---

# Phase 32 Plan 02: Prompt-Cache Architecture Fix Summary

**Anthropic system prompt now emits a real two-block cache split (stable cached + volatile uncached) instead of one ever-rewriting block, fixing the structural cache-write/zero-read bug RESEARCH identified at `core/llm_client.py:238-244`.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-22T20:00:00Z (approx, worktree setup)
- **Completed:** 2026-07-22T20:18:56Z
- **Tasks:** 2/2 completed
- **Files modified:** 7 (2 source + 1 doc-comment-only source + 4 test files)

## Accomplishments

- `LLMClient.chat`'s `system` param now accepts `str | tuple[str, str]` across all three backends (Anthropic, Gemini, OpenAI-compat), with full backward compatibility for plain-string callers (worker, tick-brain, cost-tripwire — all unchanged).
- The Anthropic backend builds a genuine second system content block for a `(stable, volatile)` tuple — `cache_control` ephemeral 1h lands on the stable block only, so a same-day chat turn is now a real cache READ instead of a full cache WRITE every time (the RESEARCH-identified bug: per-minute `{current_time}` previously sat inside the one cached block, so Anthropic's cumulative block-hash never matched turn to turn).
- `render_smart_system` returns `(stable, volatile)`, splitting the fully-rendered string at the **existing** `CURRENT TIME` heading in `prompts/smart_agent.md` (~line 378) — no template edit required. `{today_date}` (once/day) stays in stable by design; `{current_time}` (per-minute) is volatile.
- All three callers (`handle_message`, `_compose_layer2`, `_compose_followup_layer2`) pass the tuple through to `chat()` correctly — the two autonomous.py compose sites needed no code changes at all, since they never unpack or string-concatenate the render result.
- The chat-path `meal_audit` guidance now appends to the volatile half only, leaving the cached persona prefix untouched.

## Task Commits

Each task followed RED → GREEN (TDD):

1. **Task 1: LLMClient.chat system param str | tuple[str, str]**
   - `99624b6` test(32-02): add failing tests for str|tuple system param (RED)
   - `03966c3` feat(32-02): LLMClient.chat system param accepts str | tuple[str, str] (GREEN)
2. **Task 2: render_smart_system returns (stable, volatile); update 3 call sites**
   - `e15a224` test(32-02): add failing tests for render_smart_system tuple split (RED)
   - `a6fef17` feat(32-02): render_smart_system returns (stable, volatile) tuple (GREEN)

_No REFACTOR commits were needed — both implementations were clean on first pass._

## Files Created/Modified

- `core/llm_client.py` — `chat()` type hints widened to `str | tuple[str, str]` on `LLMClient`, `_BaseBackend`, and all three backend `chat()` methods; `_AnthropicBackend.chat` builds a two-block list for a tuple (cache_control on stable only, degrading to one block when volatile is empty); `_GeminiBackend.chat` and `_OpenAIBackend.chat`/`_convert_messages` join a tuple with `"\n\n"`.
- `core/main.py` — new module-level `_VOLATILE_SEAM_MARKER` constant + `_split_stable_volatile()` helper; `render_smart_system` now renders as before then returns the split tuple; `handle_message` unpacks the tuple, appends `meal_audit` to the volatile half only, rebuilds the tuple, and passes it to `_run_smart_loop`; `_run_smart_loop`/`_run_worker_loop` type hints widened.
- `core/autonomous.py` — clarifying comments only at the two `render_smart_system` call sites in `_compose_layer2`/`_compose_followup_layer2` documenting the new tuple return and confirming no logic change was needed.
- `tests/test_llm_client.py` — 5 new tests covering the tuple contract on all three backends (Anthropic two-block/degrade, Gemini join, OpenAI join at both the `chat()` and `_convert_messages()` levels).
- `tests/test_main_render_smart_system.py` — new `TestPlan3202StableVolatileSplit` class (6 tests: tuple shape, seam-absent fallback, real-template split, byte-identical-stable-across-renders, tuple pass-through in `handle_message`, meal_audit-targets-volatile, autonomous.py source guard); every pre-existing test adapted via a new `_rendered(orch, template)` helper that concatenates the tuple back to one string for content-only assertions.
- `tests/test_main.py` — `_make_orchestrator_for_handle_message`'s `render_smart_system` stub updated to return a tuple.
- `tests/test_reflection.py` — `test_journal_digest_assembly` joins the captured `smart_system` tuple before running its content assertions.

## Decisions Made

- Empty-volatile degrade for the Anthropic backend (single block, no second empty text block) — a defensive addition beyond the plan's literal "always two blocks" wording, justified by Anthropic likely rejecting an empty `text` content block; the primary two-block behavior is still fully exercised and asserted with a non-empty volatile input.
- `core/autonomous.py`'s two compose functions required zero logic changes — confirmed by tracing that `smart_system`/`worker_system` are only ever assigned from `render_smart_system(...)` and passed straight through to `_run_smart_loop(...)`, never unpacked or string-concatenated. Added source-level comments only, plus a regression test (`test_autonomous_compose_sites_never_string_concat_smart_system`) guarding against a future accidental string-concat there.
- `worker_system` in `_compose_layer2`/`_compose_followup_layer2` is also built via `render_smart_system(worker_system_template)` (pre-existing pattern, unrelated to this plan) — since `worker_agent.md` has no CURRENT TIME seam, this now resolves to `(full_content, "")`, and the OpenAI-compat worker backend joins it back into one string transparently. No behavior change for the worker path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1/3 — mechanical test adaptation forced by the return-type change] `tests/test_main.py` and `tests/test_reflection.py` needed tuple-aware updates**
- **Found during:** Task 2 verification (full related-suite run)
- **Issue:** Neither file is listed in the plan's per-task `<files>` scope, but both directly exercise `render_smart_system`'s real output (one via a lambda stub returning the old plain-string shape, one via a live `AgentOrchestrator()` + `handle_message()` call capturing the real tuple) and broke once the return type changed.
- **Fix:** `tests/test_main.py`'s `render_smart_system` stub now returns `("rendered-system", "")`; `tests/test_reflection.py`'s `test_journal_digest_assembly` joins the captured tuple (`"".join(...)`) before its content assertions, since `{journal_digest}` lands in the stable half.
- **Files modified:** `tests/test_main.py`, `tests/test_reflection.py`
- **Verification:** `pytest tests/test_main.py tests/test_reflection.py -q` — both green (in this run: 19 + 17 tests).
- **Committed in:** `a6fef17` (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (mechanical test adaptation, not called out per-task but authorized by the plan's top-level `files_modified` frontmatter and the phase invariant that the backend suite stays green).
**Impact on plan:** No scope creep — same tuple contract, same assertions, just unpacked/joined correctly.

## Issues Encountered

- `tests/test_hub_chat.py` segfaults (exit 139) when run standalone or as part of a multi-file pytest invocation, **independent of any change in this plan** (confirmed via `git diff --stat HEAD -- tests/test_hub_chat.py` showing zero diff — the file was never touched). This matches the pre-existing, documented environment issue in `CLAUDE.md`/`STATE.md`: "full `pytest tests/` segfaults in one process (grpc/protobuf GC, Python 3.13 + 3.14) — verify per-file." Not a regression from this plan; out of scope to fix here.
- The worktree's base commit was stale on session start (HEAD was at `ee27203`, a phase-31 hardening fix, not the phase-32 planning tip `e706176`); corrected via the mandated `git reset --hard` to the expected base per the `<worktree_branch_check>` protocol before any work began.

## Self-Check: PASSED

- `core/llm_client.py` — FOUND (modified, present)
- `core/main.py` — FOUND (modified, present)
- `core/autonomous.py` — FOUND (modified, present)
- `tests/test_llm_client.py` — FOUND (modified, present)
- `tests/test_main_render_smart_system.py` — FOUND (modified, present)
- `tests/test_main.py` — FOUND (modified, present)
- `tests/test_reflection.py` — FOUND (modified, present)
- Commit `99624b6` — FOUND in `git log --oneline`
- Commit `03966c3` — FOUND in `git log --oneline`
- Commit `e15a224` — FOUND in `git log --oneline`
- Commit `a6fef17` — FOUND in `git log --oneline`
- `pytest tests/test_llm_client.py -x` — 32 passed
- `pytest tests/test_main_render_smart_system.py -x` — 47 passed
- `grep -n "tuple" core/main.py | grep -i render` — confirms `render_smart_system(self, template: str) -> tuple[str, str]:` and `_split_stable_volatile(rendered: str) -> tuple[str, str]:`

## Next Phase Readiness

- The cache-split structural prerequisite is in place: Plan 06 can now add the MEM-01 "Things you remember" block and MEM-02 continuity tail to the volatile section of `prompts/smart_agent.md` (after the CURRENT TIME heading) without touching the cached stable prefix.
- **Manual validation still open (VALIDATION Manual-Only per the plan's `<verification>` block):** on a live deploy, confirm two back-to-back chat turns show non-zero `cache_read_input_tokens` on the second turn's stable block. Not verifiable from this local/worktree execution — flag for the operator at next deploy.

---
*Phase: 32-unified-situation-ambient-memory*
*Plan: 02*
*Completed: 2026-07-22*
