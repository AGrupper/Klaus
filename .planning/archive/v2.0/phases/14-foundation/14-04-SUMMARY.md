---
plan: 14-04
phase: 14-foundation
status: complete
subsystem: core
tags: [tick-brain, groq, llm, judgment, fallback, tdd]
dependency_graph:
  requires: ["14-03"]
  provides: ["TickBrain class", "TICK_BRAIN_* env vars"]
  affects: ["core/heartbeat.py", "Phase 18 autonomous engine"]
tech_stack:
  added: ["Groq OpenAI-compatible API (free tier)", "Qwen3-32B model"]
  patterns: ["Primary/fallback LLMClient chain", "JSON judgment response with safe mode", "TDD RED/GREEN"]
key_files:
  created:
    - core/tick_brain.py
    - tests/test_tick_brain.py
  modified:
    - .env.example
decisions:
  - "TickBrain imports LLMClient and LLMError inside the module (top-level) rather than lazily inside methods — cleaner and import errors surface immediately"
  - "Fallback client construction never raises — if SMART_AGENT_* vars are absent, _fallback_client is None and think() returns safe mode on primary failure"
  - "purpose='tick_fallback' (not 'tick') used for fallback calls to distinguish metering entries"
metrics:
  duration_seconds: 166
  completed_date: "2026-05-18"
  tasks_completed: 2
  files_created: 2
  files_modified: 1
  tests_added: 17
---

# Phase 14 Plan 04: Tick-Brain Judgment Layer Summary

## One-liner

Groq/Qwen3-32B free-tier judgment client with Gemini fallback and JSON safe-mode parse via TDD.

## What Was Built

`core/tick_brain.py` — a new module providing the `TickBrain` class, Klaus's lightweight judgment
layer for the heartbeat tick and (in Phase 18) the autonomous engine.

Key behaviors:

1. **Config-driven from env vars** — `TICK_BRAIN_BACKEND` (default: `openai`), `TICK_BRAIN_MODEL`
   (default: `qwen3-32b`), `TICK_BRAIN_API_KEY` (required), `TICK_BRAIN_BASE_URL` (default:
   `https://api.groq.com/openai/v1`). `ValueError` on missing API key.

2. **Primary + fallback chain** — primary uses `LLMClient(backend="openai", base_url=groq_url)`.
   On `LLMError`, retries with `LLMClient` built from `SMART_AGENT_*` vars (Gemini brain).
   Both failing → `{should_act: False, reason: "llm_error"}`.

3. **JSON safe-mode parse** — `_parse_response()` strips markdown fences, validates JSON, checks
   for `"should_act"` key. Any parse failure → `{should_act: False, reason: "parse_failure"}`.
   Never raises.

4. **purpose passthrough** — `purpose="tick"` for primary calls, `purpose="tick_fallback"` for
   fallback calls, enabling cost metering to distinguish the two paths.

5. **INFRA-02 documented** — `.env.example` Phase 14 block includes exact `gcloud secrets create`
   command for storing `TICK_BRAIN_API_KEY` in GCP Secret Manager.

## Key Files

- `core/tick_brain.py` — new file, 186 lines, exports `TickBrain`
- `tests/test_tick_brain.py` — new file, 256 lines, 17 tests (TDD)
- `.env.example` — 10 lines appended (Phase 14 Tick-Brain block)

## Commits

- `2632fd5` test(14-04): add failing tests for TickBrain judgment layer (RED)
- `f6fdb4c` feat(14-04): implement TickBrain Groq judgment layer with Gemini fallback (GREEN)
- `0a4a3af` chore(14-04): add TICK_BRAIN_* env vars to .env.example

## TDD Gate Compliance

RED gate: `2632fd5` — 17 failing tests committed before implementation.
GREEN gate: `f6fdb4c` — all 17 tests pass with implementation.
REFACTOR: no refactor needed; implementation matched spec exactly.

## Verification

All plan checks passed:

1. `TickBrain._parse_response('{"should_act": false, "reason": "ok"}')` → `{'should_act': False, 'reason': 'ok'}` ✓
2. `TickBrain._parse_response('not json')['reason'] == 'parse_failure'` → exits 0 ✓
3. `grep -c "TICK_BRAIN_BASE_URL" .env.example` → 1 ✓
4. `ast.parse(open('core/tick_brain.py').read())` → exits 0 ✓

All 9 acceptance criteria for Task 1 passed. All 6 acceptance criteria for Task 2 passed.

## Deviations from Plan

None — plan executed exactly as written. The implementation matches the spec in `<action>` verbatim.

## Known Stubs

None — `TickBrain` is fully functional (reads real env vars, calls real LLMClient). Integration
with `core/heartbeat.py` is deferred to a later plan (heartbeat currently does not call TickBrain).

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model:

| Flag | File | Description |
|------|------|-------------|
| (none) | — | All surfaces covered by T-14-09, T-14-10, T-14-11 in plan threat model |

## Self-Check: PASSED

Files exist:
- `core/tick_brain.py` — confirmed created
- `tests/test_tick_brain.py` — confirmed created
- `.env.example` — TICK_BRAIN_* entries confirmed at lines 148-154

Commits exist:
- `2632fd5` — confirmed in git log
- `f6fdb4c` — confirmed in git log
- `0a4a3af` — confirmed in git log
