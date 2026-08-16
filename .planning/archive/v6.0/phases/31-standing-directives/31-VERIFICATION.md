---
phase: 31-standing-directives
verified: 2026-07-22T11:26:08Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/7
  gaps_closed:
    - "When a directive contradicts a baked-in persona routine, Klaus records the answer as a refined directive with a superseded_by link on the old one (SC-5 / DIR-05 / D-16)"
    - "A vetoed self-directive proposal is kept (status vetoed) and is never re-proposed (31-06 must_have / DIR-07 durable anti-lesson / D-13)"
  gaps_remaining: []
  regressions: []
---

# Phase 31: Standing Directives Verification Report

**Phase Goal:** Amit can state a lasting wish about Klaus's behavior once and have it honored everywhere, indefinitely or until it expires/is cancelled, with conflicts surfaced and Klaus able to learn new directives from how Amit reacts to his own outreach.
**Verified:** 2026-07-22T11:26:08Z
**Status:** passed
**Re-verification:** Yes — after gap closure (31-07, 31-08)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Amit states a lasting wish in chat → stored verbatim with origin + triggering-context quote + one-line ack (SC-1 / DIR-01) | ✓ VERIFIED (regression check) | Unchanged since prior pass; `set_standing_directive` tools.py:867; 100 test_tools.py tests pass |
| 2 | End-condition directives expire automatically; conditionless persist until cancel; "until when?" only when unsure (SC-2 / DIR-02) | ✓ VERIFIED (regression check) | Unchanged; `expire()` firestore_db.py:2031-2053; D-06 soft-ask intact |
| 3 | An active directive changes behavior everywhere — chat, tick triage Step-0, Layer-2, follow-up compose, interim crons, nightly (SC-3 / DIR-03) | ✓ VERIFIED (regression check) | Unchanged; all injection sites intact, no touch by 31-07/31-08 |
| 4 | Amit can list and cancel standing directives from chat (SC-4 / DIR-04) | ✓ VERIFIED (regression check) | `cancel_standing_directive` now origin-routes (tools.py:2272-2301) but remains chat-reachable and idempotent per prior semantics; `list_standing_directives` unchanged |
| 5 | Persona conflict flagged, asked once "which wins", answer recorded as refined directive **with a `superseded_by` link on the old one** (SC-5 / DIR-05 / D-16) | ✓ VERIFIED — GAP 1 CLOSED | `set_standing_directive` now accepts `supersedes` (schema tools.py:890-898, handler 2170-2235); handler calls `store.supersede(old_id=supersedes, new_directive_id=result["id"])` after `add()` (tools.py:2232-2234), which writes `status="superseded"` + `superseded_by=<new id>` (firestore_db.py:2002-2029) — a real production caller now exists (previously 0). `prompts/smart_agent.md:364` rewritten: brain must pass `supersedes=<old id>` and is explicitly told "Do NOT cancel-and-recreate for persona-conflict resolution." Backward-compat preserved: omitting `supersedes` never calls `supersede()`. Tests: `tests/test_tools.py` (writes-link, no-supersedes-no-call, nonexistent-id-does-not-raise) — 100 passed. |
| 6 | Nightly reflection reads full 24h window, pairs each outreach with a reaction, may propose self-directives with a one-line veto (SC-6 / DIR-06) | ✓ VERIFIED (regression check) | Unchanged since prior pass; `get_recent_window` reflection.py:178 intact |
| 7 | A vetoed self-directive is kept (status vetoed) and never re-proposed — D-13 durable anti-lesson backing DIR-07 (SC-6/DIR-07) | ✓ VERIFIED — GAP 2 CLOSED | `StandingDirectiveStore.veto(did)` added (firestore_db.py:2055-2082): get-then-update to `status="vetoed"`, never hard-deletes, cache-invalidates, mirrors `cancel()`/`expire()` shape. `StandingDirectiveStore.get(did)` added (2084-2105): never-raises single-doc read exposing `origin`. `_handle_cancel_standing_directive` (tools.py:2272-2301) now looks up `origin` via `store.get(id)` first and routes: `origin=="klaus_self"` → `store.veto(id)`; else → `store.cancel(id)`. The reflection guard itself (`core/reflection.py:514-521`, unmodified per plan) now has a real writer feeding it. The replacement test `test_reflection_vetoed_directive_is_not_re_proposed` (tests/test_reflection.py:650-761) drives the REAL path end-to-end: seed `add(origin="klaus_self")` → reject via `core.tools._handle_cancel_standing_directive` (production handler, not a hand-seeded status) → `run_reflection()` confirmed to skip re-proposing the matching text. This is a genuine improvement over the prior seeded-status test the last verification flagged as masking the gap. |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `memory/firestore_db.py` StandingDirectiveStore | add/list_active/list_all/cancel/supersede/veto/get/expire, read-cached, never hard-delete | ✓ VERIFIED | Full lifecycle 1841-2105; `supersede()` (2002-2029) now has a real caller in `core/tools.py`; `veto()` (2055-2082) and `get()` (2084-2105) newly added, both never-hard-delete / cache-invalidating (veto) or never-raising (get) |
| `core/tools.py` set/list/cancel + supersedes param + origin-aware cancel routing | brain-direct tools with supersede/veto reachability | ✓ VERIFIED | `_handle_set_standing_directive` (2170-2235) `supersedes` param wired to `store.supersede()`; `_handle_cancel_standing_directive` (2272-2301) origin-routes to `veto()`/`cancel()` via `store.get()` lookup |
| `prompts/smart_agent.md` D-16 persona-conflict rule | Instructs supersede, not cancel-and-recreate | ✓ VERIFIED | Line 364 rewritten: explicit `supersedes=<id>` instruction + explicit prohibition on cancel-and-recreate |
| `core/reflection.py` D-13 anti-lesson guard | `status=="vetoed"` filter reachable via real writer | ✓ VERIFIED | Guard code unchanged (514-521, correctly left alone per plan) — now fed real data via `veto()` |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| **persona conflict capture** | **superseded_by on old doc** | `set_standing_directive(supersedes=...)` → `store.supersede()` | ✓ WIRED | Was NOT_WIRED in prior verification; grep confirms `core/tools.py:2234` is now a real caller of `supersede()` (previously 0 production callers) |
| **reflection anti-lesson guard** | **vetoed directive set** | `_handle_cancel_standing_directive` origin-routes `klaus_self` → `store.veto()` → `status="vetoed"` | ✓ WIRED | Was NOT_WIRED in prior verification; grep confirms `memory/firestore_db.py:2077` is now a real writer of `"vetoed"` (previously only the read comparison + docstring existed) |
| StandingDirectiveStore writes | _READ_CACHE | `_cache_invalidate_prefix(("standing_directives",))` | ✓ WIRED | Present in `veto()` (2081) and `supersede()` (2028) same as existing writers |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| `supersede()` has a production caller | `grep -rn "\.supersede(" core/ memory/ interfaces/` | `core/tools.py:2234` (call site) + `2189` (docstring) + `memory/firestore_db.py:2026` (own error log) | ✓ PASS (was FAIL) |
| Any code writes `status="vetoed"` | `grep -rn '"vetoed"' core/ memory/'` | `core/reflection.py:520` (read) + `memory/firestore_db.py:2077` (write) + docstring refs | ✓ PASS (was FAIL) |
| `tests/test_firestore_db.py` (full file) | `.venv/bin/python -m pytest tests/test_firestore_db.py -q` | 69 passed | ✓ PASS |
| `tests/test_tools.py` (full file) | `.venv/bin/python -m pytest tests/test_tools.py -q` | 100 passed | ✓ PASS |
| `tests/test_reflection.py` (full file) | `.venv/bin/python -m pytest tests/test_reflection.py -q` | 17 passed | ✓ PASS |

Each test file run in isolation per-file per environment convention (grpc/protobuf test-isolation artifact in this repo when run in one process).

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| DIR-01 | 31-03 | ✓ SATISFIED | Unchanged — verbatim capture, origin, context_quote |
| DIR-02 | 31-01, 31-06 | ✓ SATISFIED | Unchanged — hybrid expiry |
| DIR-03 | 31-03, 31-04, 31-05, 31-06 | ✓ SATISFIED | Unchanged — all injection sites |
| DIR-04 | 31-03 | ✓ SATISFIED | Unchanged (routing added inside cancel handler doesn't change external contract) |
| DIR-05 | 31-01, 31-03, 31-07 | ✓ SATISFIED | `supersedes` param + real `supersede()` caller + prompt rule rewrite — gap 1 closed |
| DIR-06 | 31-02, 31-06 | ✓ SATISFIED | Unchanged |
| DIR-07 | 31-06, 31-08 | ✓ SATISFIED | `veto()`/`get()` + origin-routed cancel handler + real writer feeding the reflection guard + end-to-end test — gap 2 closed |

All 7 requirement IDs now SATISFIED. No orphaned requirements (REQUIREMENTS.md maps exactly DIR-01..07 to Phase 31).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| — | — | No debt markers (TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER) found in `core/tools.py`, `memory/firestore_db.py`, `core/reflection.py`, `prompts/smart_agent.md` | — | None |

Both previously flagged 🛑 Blockers (dead guard / orphaned supersede()) are resolved. Remaining prior ⚠️ Warnings (tz-naive edge case in `firestore_conversation.py`, skip-parser JSON-fence truncation, prompt-only provenance guard) are unrelated to the two gaps and out of scope for this re-verification pass — carried forward as pre-existing warnings, not new findings, and not part of the two gaps this pass targeted.

### Human Verification Required

None new. The two behavioral items from the prior verification (capture ack voice, persona-conflict "which wins" flow) remain LLM-voice items outside code-verifiable scope, but the machinery each depends on (supersede link, veto routing) is now fully wired — these do not block `passed` status since they were already noted as non-blocking human-verify items in the prior report and the machinery gaps behind them are closed.

### Gaps Summary

None. Both previously open BLOCKERs are closed:

**Gap 1 (DIR-05 / SC-5 — superseded_by) — CLOSED.** `set_standing_directive` gained a `supersedes` parameter; when passed, the handler calls the previously-orphaned `StandingDirectiveStore.supersede()` after `add()`, producing a real `status="superseded"` + `superseded_by=<new id>` write. The prompt rule (D-16) now explicitly instructs the brain to use `supersedes=` and explicitly forbids cancel-and-recreate. Backward compatibility confirmed by a dedicated test (omitting `supersedes` never calls `supersede()`).

**Gap 2 (DIR-07 / D-13 — vetoed anti-lesson) — CLOSED.** `StandingDirectiveStore.veto()` and `get()` were added; `_handle_cancel_standing_directive` now looks up the directive's `origin` before writing and routes `klaus_self` directives to `veto()` (durable `status="vetoed"`, never hard-deleted) while `user_chat` directives still go through the unchanged `cancel()` path. The reflection guard (`core/reflection.py:514-521`) was left untouched per the plan — it is now fed real data. The regression risk the prior verification specifically called out (a green test seeding an unreachable status) was eliminated: the replacement test drives the actual `_handle_cancel_standing_directive` → `veto()` → `run_reflection()` path end-to-end through a real-semantics in-memory fake shared across two independently-constructed store instances, matching production reality.

No regressions found in the other 5 requirements (DIR-01, 02, 03, 04, 06) — none of their supporting code was touched by 31-07/31-08, and their test suites remain green.

**Verdict: Phase 31 (Standing Directives) is fully closed.** All 7 truths verified, all 7 requirements (DIR-01..DIR-07) satisfied, no blockers remaining, no regressions detected. Ready to proceed.

---

_Verified: 2026-07-22T11:26:08Z_
_Verifier: Claude (gsd-verifier)_
