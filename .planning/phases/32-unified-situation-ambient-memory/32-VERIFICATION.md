---
status: passed
phase: 32-unified-situation-ambient-memory
verified: "2026-07-23"
requirements: [MEM-01, MEM-02, MEM-03, MEM-04, MEM-05, MEM-06, MEM-07]
method: code-inspection + per-file pytest (full-suite segfaults on Py3.13 — known env quirk)
note: gsd-verifier subagent stalled on the stream watchdog after confirming wiring; verification completed inline by the orchestrator with the same evidence (per-file test runs + direct invariant inspection).
---

# Phase 32 Verification — Unified Situation (Ambient Memory)

**Goal:** Klaus perceives his full situation on every reasoning path — relevant memories,
conversation continuity, and reconciled training reality — without ever letting ordinary chat
activity defeat the free-tier cost gate that is Klaus's entire cost model.

**Verdict: PASSED.** All 7 requirements implemented and wired; all 6 success criteria verified
against the codebase; every affected test file passes per-file.

## Success Criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Ambient Pinecone recall auto-injected, timeout-guarded, never blocks turn (MEM-01) | ✓ | `memory/pinecone_db.py::recall_ambient` (score floor `AMBIENT_MIN_SCORE=0.5`); `core/main.py::_ambient_recall` timeout-guarded (`AMBIENT_RECALL_TIMEOUT_SECONDS=2.5`), never-raising, injected into the volatile prompt half; `{things_you_remember}` in `prompts/smart_agent.md`. Tests: `test_pinecone_recall.py` (16), `test_main.py` (36). |
| 2 | 6h+ idle → continuity tail prepended, no amnesia (MEM-02) | ✓ | `core/main.py::_build_continuity_tail` via `get_recent_window` + synthetic boundary marker; whole-function try/except. Tests: `-k continuity_tail`. |
| 3 | `forget_memory` + reflection contradiction flag, nothing auto-decays (MEM-03) | ✓ | `mcp_tools/memory.py` forget + 3-site tool registration in `core/tools.py`; brain-judged contradiction detection in `core/reflection.py` + `prompts/reflection.md`. Tests: `test_tools.py -k forget_memory` (3), `test_reflection.py -k contradiction` (3). |
| 4 | Reconciled `training_reality` in triage AND Layer-2 compose; done/moved never re-asked (MEM-04) | ✓ | Pure `core/training_checkin.py::build_training_reality` (D-01/D-02 reconciler, `today_iso`-aware); gathered in `core/autonomous.py::_gather_training_reality`; rendered into triage + both compose paths. `import nightly_review` invariant holds. Tests: `test_training_checkin.py` (59). |
| 5 | Per-request token guard (≤8000) + context-only invariant (new gathers never flip empty→non-empty) (MEM-05) | ✓ | `tests/test_token_budget.py` (3, real o200k_harmony tokenizer, maximal fixture 7,730/8,000). **Load-bearing invariant:** `core/autonomous.py::_is_empty_signals` explicitly excludes `conversation_tail`, `training_reality`, `standing_directives`, `location` — each with cost-gate rationale. Tests: `test_autonomous.py -k "is_empty_signals or conversation_tail or training_reality"`. |
| 6 | Weather/travel use derived `current_location`; Groq daily ledger alerts near 200K TPD (MEM-06/07) | ✓ | `core/autonomous.py::derive_current_location` (calendar travel + directives); weather/routes repointed in `nightly_review.py`/`morning_briefing.py`. `memory/firestore_db.py::GroqTokenLedgerStore` + `core/tick_brain.py` at-cap gate + `core/heartbeat.py::check_groq_budget` (80% + fallback spike). Tests: `test_autonomous.py -k current_location` (22), `test_tick_brain.py -k ledger` (20), `test_heartbeat.py -k groq_budget` (14). |

## Requirement Traceability

| Req | Plans | Status |
|-----|-------|--------|
| MEM-01 | 32-02, 32-06 | ✓ |
| MEM-02 | 32-02, 32-06 | ✓ |
| MEM-03 | 32-03 | ✓ |
| MEM-04 | 32-04, 32-07 | ✓ |
| MEM-05 | 32-01, 32-07, 32-08 | ✓ |
| MEM-06 | 32-05 | ✓ |
| MEM-07 | 32-08 | ✓ |

All 7 requirement IDs from PLAN frontmatter are accounted for.

## Test Evidence (per-file, `.venv/bin/python -m pytest <file>`)

test_token_budget (3), test_llm_client (32), test_main_render_smart_system (47),
test_reflection (22), test_tools (107), test_training_checkin (59), test_nightly_review (26),
test_heartbeat (60), test_tick_brain (58), test_firestore_db (69), test_pinecone_recall (16),
test_main (36), test_autonomous (126), test_morning_briefing (52) — all green.

## Production cross-check (relevant to the MEM-06 incident, 2026-07-22)

Live logs confirmed the tick-brain fallback spike was Groq's genuine **200K tokens/day** free-tier
cap (`429 rate_limit_exceeded ... TPD Limit 200000`), with per-request size ~6,453 tokens — well
under the ≤8000 per-request guard (SC-5). The per-request guard is therefore correct and not
implicated; MEM-06's `GroqTokenLedgerStore` + `check_groq_budget` are precisely the visibility this
incident lacked in production (ledger not yet deployed at time of alert). Fallback-to-Gemini is
designed behavior (D-08), not a defect.

## Deferred / follow-on (non-blocking)

- **Live cache-read verification** (32-02): confirm non-zero `cache_read_input_tokens` on a second
  same-day chat turn post-deploy.
- **Consumption vs. free tier** (MEM-06 follow-on): 32-07 increased per-tick Groq tokens; daily
  200K exhaustion will arrive earlier. Post-deploy the ledger surfaces the true daily curve — decide
  then whether to trim triage size / tick cadence or accept metered fallback. (User decision pending.)
- **CI egress for tiktoken** (32-01): confirm `o200k_harmony` loads in the CI/build environment
  (documented for Phase 35).
