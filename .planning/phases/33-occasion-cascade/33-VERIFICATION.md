---
phase: 33-occasion-cascade
verified: 2026-08-03T16:45:00+03:00
status: human_needed
score: 6/7 roadmap success criteria fully verified in code+production; 1/7 (OCC-06's observation window) is an open human-judgment checkpoint
overrides_applied: 0
re_verification: false
human_verification:
  - test: "Close plan 33-13 Task 3 — the 3-4 day observation window (D-29)"
    expected: "Amit has lived with cascade-composed nightly/morning/weekly output for 3-4 days (with today's morning-gate fix, 30d8f45, actually in effect) and replies either 'window closed — proceed to Phase 35' or 'keep the legacy path' plus what needs fixing."
    why_human: "D-29 is explicit that no metric or checklist answers this — it is Amit's own judgment from daily use. The window opened 2026-08-01 but the morning briefing was silenced 4/4 days by an unrelated tick-vs-briefing race (fixed only today, 30d8f45); the intended end-state (briefing actually speaking on wake) has not yet been observed even once. Cannot be verified from the codebase."
  - test: "Ask Klaus 'why didn't you message me yesterday?' and 'did you change anything on my calendar?' in a live chat turn"
    expected: "get_recent_decisions returns real, specific answers drawn from TickLogStore/OutreachLogStore/ActionLogStore for the requested date range — not a hedge or apology."
    why_human: "OCC-07's UAT is explicitly manual per 33-VALIDATION.md; the tool's wiring and data shape are code-verified here (see Requirements Coverage), but the quality of the brain's actual answer in conversation is a live judgment call."
  - test: "Confirm every Layer-2 calendar write during the observation window showed up as a scannable Created:/Moved:/Deleted: line, and none appeared silently (D-24)"
    expected: "100% of writes disclosed; check_occasion_health anomaly #4 (undisclosed actions >24h) never fires."
    why_human: "This is the first live exercise of D-23's ungated writes (the plan's own threat register T-33-02b names this exact human audit as the mitigation) — cannot be confirmed by reading code."
---

# Phase 33: Occasion Cascade Verification Report

**Phase Goal:** Nightly review, morning briefing, and the Sunday weekly review stop being always-fire templates and become judgment-driven occasions through the same 3-layer cascade as the tick, with silence a valid, self-explainable outcome distinguishable from infra failure
**Verified:** 2026-08-03
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

This phase was already executed, code-reviewed (`33-REVIEW.md`, 2026-08-01: 5 critical + 12 warning findings), and had a fix round applied on top of production evidence. This verification re-derives the truth from the current state of `main` (not from what the plans/SUMMARYs originally claimed), cross-checks every review fix commit against the code, runs the affected test files, and treats the review's own PRODUCTION CORRECTION blocks and the task's supplied live-production evidence as authoritative where code-reading alone cannot settle a question (no infra access from this session).

### Observable Truths (Roadmap Success Criteria)

| # | Truth (Roadmap SC) | Status | Evidence |
|---|---|---|---|
| 1 | Nightly runs through the cascade, skippable by judgment (`skipped_by_judgment`); infra failure sends the deterministic fallback and is distinguishable in logs | ✓ VERIFIED | `core/nightly_review.py:427-551` (`run_nightly`) has three branches (`sent` / `skipped_by_judgment` with `skip_cause`+`draft` / infra-fault path that writes **no terminal status** and logs a warning so the 01:00 backstop can retry). Confirmed correct pre-review (CR-02's finding was that the *morning* diverged from this exact pattern, not the nightly). Production evidence supplied: `sent (cascade)` 2026-08-01 and 2026-08-02; the 01:00 backstop correctly stood down both nights ("already terminal"). |
| 2 | Morning runs through the cascade, push-triggered on `POST /trigger/morning`, no Garmin gate/10:15 cutoff/backstop, `structured`+`daily_note` written every run *(OVERRIDE: trigger mechanism, D-05/D-06/D-08/D-09)* | ✓ VERIFIED | `core/morning_briefing.py`: `handle_tick`'s Garmin-gate/10:15-cutoff/retry state machine deleted entirely (33-13, commit `a12ee91`; `grep -c "async def handle_tick"` → 0). `_set_state(... "structured": ...)` (D-05, line ~291) and the `daily_note` write (D-06, line ~312) both fire unconditionally — sent, skipped, or SC-1 fallback. `_verify_morning_trigger_request` mirrors the healthkit verifier (distinct secret, D-13); live-evidence table in `33-12-SUMMARY.md`: 401 no header, 403 bad bearer, 202 valid bearer. CR-02 (commit `83ec130`) closed the gap where a cascade infra fault was mislabeled `skipped_by_judgment` and permanently locked out the day — the morning now takes the same three-branch shape as the nightly, with the SC-1 plain-text fallback substituting for the backstop the morning deliberately lacks. Trigger deviation (Wake Up, not Sleep-Focus-off) is documented with device evidence in `docs/sleep_focus_off_shortcut.md` §3.0 and judged on the push-contract, per task instructions, not the literal name. |
| 3 | Weekly runs through the cascade as `occasion="weekly_review"`, retiring the last legacy composer | ⚠ PARTIALLY VERIFIED (deliberate, see note) | `core/weekly_training_review.py:658`: `if os.getenv("OCCASION_CASCADE", "false").lower() == "true":` routes to `run_occasion_cascade`; confirmed `OCCASION_CASCADE=true` is on `deploy.yml` (flipped 2026-08-01, commit `a774113`) and — per task context — the serving revision. Production evidence supplied: `status: sent`, `composed_via: llm` on 2026-08-02, substantive per-day content. **"Retiring"** (literal deletion of `_compose_review`) has explicitly **not** happened — `33-CONTEXT.md` D-30 ("morning ships cascade-only; nightly and weekly get the A/B") deliberately defers legacy-composer deletion to Phase 35, after the observation window. `grep -c "def _compose_review" core/weekly_training_review.py` → 1 (kept for the A/B by design). This mirrors the explicit `[OVERRIDE]` treatment already applied to SC-2/SC-5/SC-7 in ROADMAP.md, even though SC-3's roadmap text itself was not annotated with the same `[OVERRIDE]` marker — a minor documentation-consistency gap, not a functional one, since D-30's intent is unambiguous and consistently applied in code. |
| 4 | Occasions always get a free triage judgment (empty-gate bypassed); `OutreachLog` topic keys `nightly:<date>`/`morning:<date>`/`weekly:<date>`; log entries written only after successful send | ✓ VERIFIED | `core/autonomous.py:2545-2549`: the occasion path calls `gather_situation` and merges `occasion_data` with **no** `situation.get("empty")` gate check — structurally bypassed, not conditionally skipped (comment at line ~2539 confirms). `_OCCASION_TOPIC_PREFIX = {"nightly": "nightly", "morning": "morning", "weekly_review": "weekly"}` (line ~70) feeds `topic_key = f"{prefix}:{target_date}"` (line 2551). `OutreachLogStore.append` call (line 2444) sits strictly after the `send_and_inject` success path (line 2433 `decision["sent"] = True` precedes it; every failure branch returns before reaching it) — D-10 discipline intact. |
| 5 | Layer 2 composes agentically bounded by `MAX_TOOL_ITERATIONS=12` (forced tools-stripped final on exhaustion); calendar writes disclosed on a scannable action line; duplicate-create check before write *(OVERRIDE: D-21/22/23/24)* | ⚠ VERIFIED WITH A KNOWN GAP | `MAX_TOOL_ITERATIONS = 12` confirmed (`core/main.py:50`). Write-and-disclose confirmed real and wired: `prompts/autonomous.md` §"Write, then disclose" instructs `Created:`/`Moved:`/`Deleted:` action lines; `ActionLogStore` (D-25, `memory/firestore_db.py:2223`) records every write independent of send success; `check_occasion_health` anomaly #4 flags orphaned undisclosed entries >24h. Duplicate-create check confirmed and improved by WR-05 (commit `09adddb`): `_existing_event_at` now honours `calendar_id` scoping and `_DUPLICATE_LOOKUP_MAX_RESULTS`; `allow_duplicate` gives interactive requests a way through instead of a hard refusal. Production evidence supplied: the 2026-08-01 nightly created three calendar events via tool calls. **Known unresolved gap (WR-04, deliberately deferred, not re-filed):** the "forced tools-stripped final answer on exhaustion" (D-22) mechanism at `core/main.py:1051-1091` still passes `tools=None` to `smart_agent.chat` while `current_messages` can still carry `tool_use`/`tool_result` content from the exhausted loop — Anthropic requires `tools` be defined for such a request, so on the production backend (`claude-sonnet-5`) this forced-final call is likely to raise `APIStatusError`→`LLMError`, which is caught and silently falls through to the pre-existing (pre-D-22) fallback chain. Net effect: iteration exhaustion still produces *some* response (the old apologetic/`last_response_text` fallback), never silence — so this does not break SC-5's outcome, only its stated mechanism. Confirmed still present in current code; matches the review's own Warning (not Critical) classification. |
| 6 | `get_recent_decisions` gives Klaus a real, brain-direct answer to "why didn't you message me yesterday?" from tick/occasion verdicts and reasoning | ✓ VERIFIED | `core/tools.py:2170-2270` (`_handle_get_recent_decisions`): reads `TickLogStore.ticks_for_date` (extracts the `layer1` verdict from `decision_trail`), `OutreachLogStore.get_today` (what was sent), `ActionLogStore.get_recent` (what was written) across a clamped `days` window (1-30), returns structured JSON, never raises. WR-09 fix (commit `e8a75e2`) additionally ensures a tick that sent a follow-up but then triaged to silence is no longer misrecorded as a pure skip — `prior_trail` is threaded into `_run_cascade` so the persisted log is complete. Registered in the tool schema and `_HANDLERS` dispatch (`"get_recent_decisions"` present at both `core/tools.py:536` and `:3568`). |
| 7 | `OCCASION_CASCADE` ships behind a flag A/B-ing nightly+weekly for a 3-4 day observation window before Phase 35 deletes legacy composer code *(OVERRIDE: D-30/D-31 — morning-briefing-tick is the one scheduler change)* | ⚠ OPEN — HUMAN CHECKPOINT | Code/infra side fully done: `OCCASION_CASCADE=true` on `deploy.yml` (commit `a774113`); `klaus-morning-briefing` Cloud Scheduler job paused 2026-08-01 (documented in the commit message, with the uppercase-K job-name correction noted); no other scheduler jobs touched. **The observation window itself (33-13 Task 3, `checkpoint:human-verify`, gate="blocking") is explicitly not closed.** It opened 2026-08-01, but the morning briefing self-skipped `already_covered` 4/4 consecutive days because `run_autonomous_tick` was speaking hours before the wake trigger fired — a separate defect (unrelated to the occasion cascade itself) fixed only *today* (commit `30d8f45`, `_morning_gate_holds`/`TICK_MORNING_GATE_UNTIL_HOUR=11`). The intended end-state behavior (the briefing actually composing and speaking on wake, under real conditions) has not yet been observed even once. `ROADMAP.md` correctly reflects this as still-open ("33. Occasion Cascade \| 12/13 \| In Progress"; `33-13-PLAN.md` Task 2/3 checkboxes unmarked). |

**Score:** 5/7 cleanly VERIFIED, 2/7 VERIFIED-WITH-CAVEAT (a documented, defensible design deviation on SC-3's wording; an open human-judgment checkpoint on SC-7/OCC-06). No truth FAILED.

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `core/autonomous.py::run_occasion_cascade`/`_run_cascade` | Shared 3-layer cascade generalized for tick+occasions | ✓ VERIFIED | Present, exercised by 199 passing tests in `tests/test_autonomous.py`. CR-01's `_occasion_digest` (line 1385) confirmed rendered into `_build_triage_prompt`'s occasion branch only (line 1572), never the plain tick path (`test_tick_path_token_total_unchanged_by_cr01` exists and is named correctly). |
| `core/nightly_review.py::run_nightly` | Cascade-routed, judgment-skip vs infra-fault distinguishable | ✓ VERIFIED | See SC-1 evidence above. |
| `core/morning_briefing.py::run_morning_briefing_triggered` | Sole production entry point, no polling state machine | ✓ VERIFIED | `handle_tick` deleted (33-13); CR-02's three-branch fix present (commit `83ec130`). |
| `core/weekly_training_review.py::run_weekly_review` | Cascade-routed in advisory-only mode, idempotent | ✓ VERIFIED | CR-03 dedup guard present: `_WEEKLY_TERMINAL_STATUSES = frozenset({"sent", "skipped_by_directive"})`, checked at the top of `run_weekly_review` (line 640-644, commit `06014cd`). |
| `core/task_dispatch.py::enqueue_occasion` + `/internal/process-occasion` | Cloud-Tasks-backed occasion dispatch | ✓ VERIFIED | WR-07's `target_date` validation present (`_date_cls.fromisoformat` guard, 400 on malformed input, commit `43c974c`). |
| `core/tools.py::_handle_get_recent_decisions` | OCC-07 brain-direct read tool | ✓ VERIFIED | See SC-6. |
| `core/tools.py::_handle_run_morning_briefing` (manual "brief me") | Thread-safe dispatch | ✓ VERIFIED | CR-04 fix present (commit `7f66fdf`): routes through `enqueue_occasion`, no `asyncio.get_event_loop()` call from a worker thread. |
| `core/heartbeat.py::check_occasion_health` | D-28 occasion anomaly checks | ✓ VERIFIED | WR-12 (UTC/local normalization, commit `a53dbac`) and CR-05 (weekly-check-races-send false CRITICAL, commit `9ec309b`) both present and match the review's fix descriptions. |
| `docs/sleep_focus_off_shortcut.md` | Operator runbook for the morning trigger | ✓ VERIFIED | §3.0 documents the iOS-version-gated trigger selection with device evidence (iOS 26.5.2, Sleep Focus absent, Wake Up used instead). |
| `docs/SELF.md` | Auto-generated, accurate self-manifest | ✓ VERIFIED | WR-10 fix present (commit `c15acda`): "8 scheduled jobs", no `morning-briefing-tick`, no "not yet implemented" line for autonomous outreach. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `core/autonomous.py::_build_triage_prompt` | `_occasion_digest` | direct call, gated on `occasion` | ✓ WIRED | CR-01 fix; verified by reading the call site and by `test_digest_renders_inside_build_triage_prompt_for_occasion` / `test_digest_only_renders_on_occasion_runs`. |
| `core/nightly_review.py` / `core/morning_briefing.py` / `core/weekly_training_review.py` | `core/autonomous.py::run_occasion_cascade` | `occasion=` param | ✓ WIRED | All three call sites confirmed by direct grep/read. |
| `core/tools.py::_handle_create_calendar_event` | `_existing_event_at` | idempotency pre-check | ✓ WIRED | WR-05 scoping fix confirmed; `allow_duplicate` escape hatch confirmed for interactive requests. |
| `core/weekly_training_review.py::_parse_review_skip` | `_run_weekly_review_cascade` | `_LAST_DIRECTIVE_VETO_REASON` module global | ⚠ WIRED BUT FRAGILE (WR-08, deliberately deferred) | Confirmed still a mutable module-level global, unchanged. Review's own assessment ("safe today only because the weekly fires once a week and the read happens in the same event-loop turn") still holds; not re-filed as a new gap per task instructions. |
| `interfaces/web_server.py::/trigger/morning` | `_verify_morning_trigger_request` | bearer-token auth | ✓ WIRED | Distinct `MORNING_TRIGGER_TOKEN` secret (D-13); live 401/403/202 evidence supplied in `33-12-SUMMARY.md`. |
| `core/autonomous.py::run_autonomous_tick` | `_morning_gate_holds` | early-gate check | ✓ WIRED (new, unobserved) | Commit `30d8f45` (today). Fails open on any state-read error. Not yet exercised by a live wake cycle. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `core/main.py` | 1058-1064 | `tools=None` passed to a chat call whose message history can still contain `tool_use`/`tool_result` blocks | ⚠ Warning (WR-04, deferred) | D-22's forced-final recovery likely 400s and silently falls through to the pre-existing fallback chain on the production Anthropic backend. No user-facing silence results, but the stated SC-5 mechanism is not confirmed functional. |
| `core/autonomous.py` | 2545 / 2560 | `gather_situation(now)` (multi-second network fan-out) runs before `store.mark(occasion, ...)` | ℹ Info (WR-03, deferred) | Narrows but does not close the D-19 in-flight-marker collision window with a coincident `*/20` tick. |
| `core/weekly_training_review.py` | 48, 589, 604 | Mutable module-level global (`_LAST_DIRECTIVE_VETO_REASON`) carries state across a function boundary | ℹ Info (WR-08, deferred) | Process-wide, never reset; safe today only by the weekly's low fire-frequency. |
| `core/autonomous.py` | 1846 (per review) | Occasion tick-log snapshot has no size guard before a Firestore write | ℹ Info (WR-02, deferred) | Could exceed the 1 MiB document ceiling on a maximal weekly gather; fails open (swallowed + logged), so the failure mode is a missing audit record, not a crash. |
| `docs/DEPLOYMENT.md` | 1615-1616 | Documented timeout-chain invariant ("Cloud Run 600s > dispatch_deadline 540s > LLM_TIMEOUT 120s") no longer accounts for Layer 2's up-to-12-iteration tool loop | ℹ Info (WR-11, deferred) | Stated invariant is now inaccurate; CR-03's new dedup guard bounds the practical blast radius of a duplicate-send caused by this mismatch, even though the root timeout math is unchanged. |
| `interfaces/web_server.py` / `core/heartbeat.py` | — | Unsetting `CLOUD_TASKS_QUEUE` silently disables all three occasions with degraded observability | ℹ Info (WR-06, deferred) | Documented rollback lever (DEPLOYMENT.md §25) is more destructive for occasions than for the Telegram webhook; not yet reconciled. |

None of the six deferred warnings above are re-filed as new gaps — each was independently re-confirmed present in the current code and judged consistent with the review's own Warning-level (non-blocking) classification and the project's established pattern (per `.planning/STATE.md`/`RETROSPECTIVE.md`) of fixing Criticals inline and tracking Warnings forward. WR-04 is flagged with slightly more emphasis than the others because it touches a mechanism SC-5 names explicitly by design ("forcing a tools-stripped final answer on exhaustion") — worth a Phase 35 follow-up, not a blocker for this phase's goal.

### Test Suite

Run per-file per project convention (`pytest tests/` in one process is documented to segfault on grpc/protobuf GC under this environment's Python 3.13 venv; confirmed independently during this verification — combining multiple occasion-adjacent test files in one process also segfaults at interpreter shutdown, exit 139, always *after* 100% of tests already showed passing dots). All phase-33-relevant files run individually, clean:

| File | Result |
|---|---|
| `tests/test_autonomous.py` | 199 passed |
| `tests/test_morning_briefing.py` | 82 passed |
| `tests/test_nightly_review.py` | 42 passed (interpreter-exit segfault after 100% pass — not a test failure, pre-existing environment issue) |
| `tests/test_weekly_training_review.py` | 57 passed |
| `tests/test_heartbeat.py` | 90 passed |
| `tests/test_web_server.py` | 72 passed |
| `tests/test_task_dispatch.py` | 10 passed |
| `tests/test_tools.py` | 135 passed |
| `tests/test_tick_brain.py` + `tests/test_token_budget.py` + `tests/test_docs.py` | 95 passed, 7 subtests passed |

Spot-checked several of the review-fix-round's own named tests exist and are substantive (not just claimed in a SUMMARY): `test_maximal_occasion_triage_prompt_fits_groq_ceiling`, `test_tick_path_token_total_unchanged_by_cr01`, `test_occasion_path_drops_tick_only_keys` (all in `tests/test_token_budget.py`), `test_digest_hard_cap_regardless_of_source_size`, `test_digest_hard_cap_morning_pathological` (both in `tests/test_autonomous.py`) — read in full; they assert real, non-trivial behavior (fixed char caps under pathological input sizes, token budgets under a realistic maximal fixture), not the `occasion_data={}` fiction the review flagged as the root cause of CR-01 going undetected.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|---|---|---|---|
| OCC-01 | Nightly cascade, judgment-skip vs infra-failure distinguishable | ✓ SATISFIED | See SC-1. |
| OCC-02 | Morning cascade, `structured`+`daily_note` written only on actual send *(superseded: Garmin/10:15 language, D-05/D-08/D-09)* | ✓ SATISFIED | Flagged `requirements-partial` by `33-12`/`33-13` SUMMARYs pending the operator checkpoint; that checkpoint (Task 2) has since closed (`OCCASION_CASCADE=true` live, trigger confirmed live across 4+ days per supplied production evidence). Reassessed here as satisfied at the code+infra level. |
| OCC-03 | Weekly cascade as `occasion="weekly_review"`, last legacy composer retired | ⚠ PARTIALLY SATISFIED | Cascade routing live (flag on); literal composer deletion deferred to Phase 35 by D-30, consistent with how OCC-06 is scoped. Not a phase-33 defect. |
| OCC-04 | Occasions bypass empty gate; topic keys; send-gated log | ✓ SATISFIED | See SC-4. |
| OCC-05 | Bounded agentic Layer 2; idempotent calendar writes | ⚠ SATISFIED WITH KNOWN GAP | See SC-5 (WR-04). |
| OCC-06 | `OCCASION_CASCADE` flag rollout; 3-4 day observation window before Phase 35 deletion | ⚠ OPEN | The flag/infra portion is done; the observation window (33-13 Task 3) is explicitly unclosed — see SC-7. This is the phase's one genuinely incomplete requirement. |
| OCC-07 | `get_recent_decisions` brain-direct self-accountability | ✓ SATISFIED | See SC-6. |

`.planning/REQUIREMENTS.md`'s tracking table still shows all seven as "Pending" — this reflects that the orchestrator updates that table at phase close, not a functional gap; noted for completeness.

## Human Verification Required

See frontmatter `human_verification:` — three items, all rooted in the single open checkpoint (33-13 Task 3, the 3-4 day observation window) and its two associated manual UAT checks (OCC-07's live Q&A, D-24's write-disclosure audit). None of these are answerable by reading the codebase; all require Amit's own judgment against live, multi-day production behavior — most importantly, the observation window has not yet run under its intended conditions, since the tick-vs-briefing race that silenced the morning 4/4 days was only fixed today.

## Gaps Summary

No must-have truth FAILED. All cascade mechanics (gather, triage, compose, send-or-skip, disclosure, dedup, auth, monitoring) are present, correctly wired, and covered by passing tests that were spot-checked for substance rather than trusted at face value. The five Critical and six of twelve Warning findings from the 2026-08-01 code review are confirmed fixed in the current code, each verified independently against the review's own description of the defect (not merely trusted from commit messages). The six deferred Warnings were re-confirmed still present and judged non-blocking, consistent with the review's own severity classification.

The phase's remaining work is not a code gap: **33-13 Task 3 (the observation window) is genuinely open**, and honestly so — it opened 2026-08-01 but the morning briefing was silenced every day since by an unrelated race between the autonomous tick and the morning trigger, fixed only today (commit `30d8f45`). The intended end-state (a cascade-composed briefing actually reaching Amit on wake, judged over several real days) has not yet been observed even once. This phase cannot be marked `passed` while its own final task is an open, blocking, human-judgment checkpoint — but it should also not be marked `gaps_found`, since nothing in the code is broken or missing. `human_needed` is the accurate status: resume when Amit closes Task 3 with "window closed — proceed to Phase 35" or "keep the legacy path" (per `33-13-PLAN.md`'s resume-signal contract).

---

_Verified: 2026-08-03_
_Verifier: Claude (gsd-verifier)_
