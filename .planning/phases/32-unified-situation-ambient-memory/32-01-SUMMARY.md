---
phase: 32-unified-situation-ambient-memory
plan: 01
subsystem: testing
tags: [tiktoken, groq, gpt-oss-120b, token-budget, autonomous-tick, o200k_harmony]

# Dependency graph
requires: []
provides:
  - "tiktoken==0.13.0 pinned in requirements.txt (o200k_harmony tokenizer)"
  - "tests/test_token_budget.py — MEM-05 deterministic Groq per-request token-budget guard"
  - "_build_maximal_fixture_situation() fixture builder — reusable by Plan 07 to re-verify once conversation_tail/training_reality are wired into _build_triage_prompt"
affects: [32-07-training-reality-render, 32-08]

# Tech tracking
tech-stack:
  added: [tiktoken==0.13.0]
  patterns:
    - "Real-tokenizer budget guard (not char-count heuristic) for a fixed third-party API admission ceiling"

key-files:
  created: [tests/test_token_budget.py]
  modified: [requirements.txt]

key-decisions:
  - "Fixture sizes calibrated to a 'busy real day', not the raw API technical caps (_gather_calendar's max_results=50, etc.) — using the technical ceilings produced an unreachable 13,975-token scenario that would fail the guard for a situation no real tick ever renders (PITFALLS.md Pitfall 11 confirms current triage input is ~3.2-3.7K tokens, not ~10K+)."
  - "o200k_harmony loads successfully in this environment (no cl100k_base fallback needed) — first use downloads a ~3.6MB merge-ranks file from openaipublic.blob.core.windows.net and caches it locally; this dev/executor environment has network egress. Documented as a residual CI-environment risk below."
  - "TICK_BRAIN_MAX_TOKENS effective value is read via the same os.getenv(\"TICK_BRAIN_MAX_TOKENS\", str(_DEFAULT_MAX_TOKENS)) resolution TickBrain.__init__ uses, imported from core.tick_brain._DEFAULT_MAX_TOKENS rather than hardcoding 2048."

requirements-completed: [MEM-05]

# Metrics
duration: 25min
completed: 2026-07-22
---

# Phase 32 Plan 01: Groq Token-Budget Guard (MEM-05) Summary

**Pinned `tiktoken==0.13.0` and added a deterministic, network-free guard test that counts the real `o200k_harmony`-tokenized maximal triage prompt + completion budget against Groq's verified 8,000-token per-request ceiling for `openai/gpt-oss-120b` — passes at baseline with 191 tokens of headroom.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-22T20:00Z (approx, worktree base reset + context read)
- **Completed:** 2026-07-22T20:09:32Z
- **Tasks:** 3 (Task 1 checkpoint pre-approved by orchestrator; Tasks 2-3 executed)
- **Files modified:** 2 (`requirements.txt`, `tests/test_token_budget.py`)

## Accomplishments

- `tiktoken==0.13.0` added to `requirements.txt` under a new `# --- Groq token-budget measurement (Phase 32) ---` comment block; installed into the project's Python 3.13 venv (`.venv`, never 3.14 per the CLAUDE.md invariant).
- Verified `tiktoken.get_encoding("o200k_harmony")` — the actual gpt-oss-120b tokenizer OpenAI open-sourced — loads and encodes successfully in this environment. No `cl100k_base` fallback was needed.
- `tests/test_token_budget.py` created with three tests: the MEM-05 budget-guard assertion, plus two fixture self-checks (conversation-tail cap, training-reality date-window coverage).
- The guard passes at baseline: **system=2864, user=2897, completion=2048 → total=7809, headroom=191 tokens** under Groq's 8,000-token ceiling.
- The fixture builder (`_build_maximal_fixture_situation`) already populates the two Phase-32 keys Plan 07 will wire into `_build_triage_prompt` (`conversation_tail` at its 15-message/240-char MEM-04 cap, `training_reality` across the 5-date today-3d..tomorrow reconciliation window) even though the current `_build_triage_prompt` doesn't read them yet — so the guard tightens automatically, with no fixture rebuild, the moment Plan 07 wires the render.

## Task Commits

Each task was committed atomically:

1. **Task 1: Verify tiktoken package legitimacy before install** — checkpoint, pre-approved by the orchestrator (no commit; gate only)
2. **Task 2: Add tiktoken to requirements.txt and confirm o200k_harmony loads offline** - `f2dc334` (chore)
3. **Task 3: Write tests/test_token_budget.py** - `52e2e29` (test)

_Note: TDD-style test-then-implementation split isn't applicable here — Task 3 is a standalone guard test with no corresponding production code change in this plan._

## Files Created/Modified

- `requirements.txt` - Added `tiktoken==0.13.0` under a new `# --- Groq token-budget measurement (Phase 32) ---` block, sibling to the existing SDK section.
- `tests/test_token_budget.py` - New MEM-05 guard test: `_count_tokens` (real `o200k_harmony` tokenizer), `_build_maximal_fixture_situation` (every `gather_situation` key + the two future Phase-32 keys), and three test functions.

## Decisions Made

1. **Fixture calibration — realistic busy day, not API technical caps.** The first draft used the raw `_gather_calendar`/`_gather_unread_email_count` `max_results=50` API ceilings for list sizes, producing a 13,975-token total that failed the guard. Per `PITFALLS.md` Pitfall 11 (verified current triage input ≈3.2-3.7K tokens), that scenario is unreachable in production and would make the guard fail for a situation no real tick ever renders. Rescaled to a genuinely busy-but-real day (12 calendar events, 6 overdue tasks, 3 due follow-ups, 4 standing directives, 2 recent meals, 5 pending habits, 2 training-log rows) — still deliberately larger than a typical day so the guard has teeth, but reachable.
2. **`o200k_harmony` chosen over `cl100k_base`.** It loaded successfully in this environment (network egress present; first use downloads and caches a ~3.6MB merge-ranks file from `openaipublic.blob.core.windows.net`). No fallback was needed per the plan's acceptance criteria.
3. **`TICK_BRAIN_MAX_TOKENS` effective value imported, not hardcoded.** `core/tick_brain.py` has no module-level `TICK_BRAIN_MAX_TOKENS` constant — only `_DEFAULT_MAX_TOKENS = 2048` plus an instance-level `os.getenv("TICK_BRAIN_MAX_TOKENS", ...)` resolution inside `TickBrain.__init__`. The test mirrors that same resolution at module level (`os.getenv("TICK_BRAIN_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS))`) so the guard reflects the actual deployed budget, honoring an env override if one is ever set.

## Deviations from Plan

None — plan executed exactly as written. Task 1's checkpoint was pre-approved by the orchestrator per the spawning context (Amit already confirmed `tiktoken==0.13.0` on PyPI is the genuine `github.com/openai/tiktoken` package before this executor ran).

## Issues Encountered

**Fixture sized at the raw API technical caps failed the guard on first pass** (13,975 tokens vs the 8,000 ceiling). Resolved by rescaling list sizes to a realistic busy-day worst case per `PITFALLS.md` Pitfall 11's verified baseline (~3.2-3.7K token triage input) — see Decision 1 above. Not logged as a Rule 1/2/3 deviation since this was iterative tuning of the test being written in this same task, not a bug in separately-shipped code.

## Known Risk (documented per Task 2's acceptance criteria, not a stub)

`tiktoken.get_encoding("o200k_harmony")` required a first-run network download (~3.6MB from `openaipublic.blob.core.windows.net`) in this dev/executor environment, which has egress and succeeded, then cached the file locally (subsequent loads: ~0.1s). **This has not been verified in the actual CI/Cloud Run deploy environment.** If that environment lacks egress to `openaipublic.blob.core.windows.net` on a cold container/CI runner, `tiktoken.get_encoding("o200k_harmony")` will raise on first use there and this guard test will fail its own import step (not the assertion — the encoding load itself). Per the plan's documented fallback: if this surfaces in CI, switch `_count_tokens`'s encoding to `cl100k_base` (already bundled, same library, a documented safe over-estimate) — no other test logic changes. Flagging for Plan 07 / Phase 35 hardening to confirm CI egress before relying on this long-term, or to vendor/cache the merge-ranks file in-repo.

## User Setup Required

None - no external service configuration required. `tiktoken` is a pure Python-library dependency; no new secrets, env vars, or cloud resources.

## Next Phase Readiness

- The guard is baseline-green with **191 tokens of headroom** — genuinely tight. Plan 07 (which wires `conversation_tail`/`training_reality` into `_build_triage_prompt`'s render) must re-run this test immediately after wiring and should expect it to need active prompt-shrinking work (per `PITFALLS.md` Pitfall 11's recommendation to shrink `prompts/autonomous_triage.md`, currently ~2864 tokens / ~11KB, toward half its current size) to stay under the 8,000-token ceiling once those slots render real content.
- `_build_maximal_fixture_situation(now)` in `tests/test_token_budget.py` is directly reusable by Plan 07 — it already carries `conversation_tail` and `training_reality` at their documented caps; Plan 07 only needs to wire `_build_triage_prompt` to read those two keys, not touch the fixture.
- No blockers for Plan 02+.

---
*Phase: 32-unified-situation-ambient-memory*
*Completed: 2026-07-22*
