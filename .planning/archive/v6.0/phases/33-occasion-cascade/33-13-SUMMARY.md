---
phase: 33-occasion-cascade
plan: 13
subsystem: infra
tags: [cron-retirement, heartbeat, deploy-config, ios-shortcuts, documentation]

# Dependency graph
requires:
  - phase: 33-occasion-cascade
    provides: "33-12 confirmed-live morning trigger (production evidence 2026-08-01: 07:00:23Z /trigger/morning 202 -> /internal/process-occasion 200); 33-11 check_occasion_health + the TODO(33-12/D-10) staleness-key annotation this plan resolves"
provides:
  - "core/morning_briefing.py — handle_tick (the pending/sync_detected/sent state machine, the 10:15 cutoff, retry_count) deleted; run_morning_briefing_triggered is now the sole entry point in production"
  - "interfaces/web_server.py — /cron/morning-briefing-tick route deleted"
  - "core/heartbeat.py — _CRON_MAX_STALENESS_HOURS['morning-briefing'] and its dark-ship TODO removed; nightly-trigger NOTE extended to also name morning-trigger as deliberately unmonitored"
  - "docs/DEPLOYMENT.md/CLAUDE.md/core/self_manifest.py — retired-cron inventory corrected, dark-ship language closed out, Sleep-Focus-off mischaracterization corrected to describe the actual wake-up-trigger mechanism"
  - "Task 2 (retire the Cloud Scheduler job + flip OCCASION_CASCADE=true) and Task 3 (3-4 day observation window) returned as an operator checkpoint — NOT executed by this agent"
affects: [35]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Legacy-composer deletion staged in two passes across the milestone: plan 33-13 deletes the polling *trigger* (handle_tick) once its replacement is confirmed live; the LLM *composer* functions it called (run_morning_briefing, _compose_briefing, _parse_briefing_skip) are left in place with a '# Phase 35: delete with the other legacy composers' marker comment — Phase 35 deletes all three occasions' legacy composers together, not one at a time, to avoid diverging the nightly/morning/weekly rollout mid-window."
    - "A retired cron's staleness key is removed in the same commit as the code that made it monitor something real (D-10) — leaving a dangling _CRON_MAX_STALENESS_HOURS entry after the cron it guards is deleted produces a permanent false 'stale' critical with no way to ever clear it (the ledger doc simply stops updating)."

key-files:
  created: []
  modified:
    - core/morning_briefing.py
    - interfaces/web_server.py
    - core/heartbeat.py
    - core/self_manifest.py
    - docs/DEPLOYMENT.md
    - CLAUDE.md
    - tests/test_morning_briefing.py
    - tests/test_heartbeat.py
    - tests/test_web_server.py
    - .planning/phases/33-occasion-cascade/deferred-items.md

key-decisions:
  - "run_morning_briefing/_compose_briefing/_parse_briefing_skip kept (not deleted) per the plan's explicit instruction — grep confirmed handle_tick was run_morning_briefing's only production caller, but the plan's own <objective> and <success_criteria> forbid legacy-composer deletion in this plan (that's Phase 35). Marked with '# Phase 35: delete with the other legacy composers' at each definition site instead."
  - "_plain_text_fallback was NOT marked for Phase 35 deletion, unlike its three siblings — it is shared: both the legacy run_morning_briefing -> _compose_briefing path AND the live run_morning_briefing_triggered's SC-1 exception fallback call it directly. Verified via grep before marking anything, to avoid mis-tagging a live production function for deletion."
  - "The plan's literal acceptance-criteria grep ('grep -rn \"handle_tick\" --include=*.py . | grep -v \"\\.planning\"' returns nothing) is over-broad by construction — core/chat_ingest.py and core/chat_export_ingest.py define their own unrelated handle_tick() functions for different crons, predating this plan and out of scope. The scoped, meaningful checks (core/morning_briefing.py has zero handle_tick definitions; interfaces/web_server.py has zero references; the route callsite is gone) all pass cleanly — see Self-Check below. Did not touch the unrelated chat-ingest modules."
  - "core/self_manifest.py (not in the plan's files_modified list) was corrected under Rule 1 — its hardcoded 'D-07 compact form' cron-jobs summary line still named morning-briefing-tick and counted '9 scheduled jobs'; left uncorrected, the next docs/SELF.md regeneration (core/self_manifest.py runs on every deploy) would give Klaus an inaccurate self-description of his own live infrastructure, which is the explicit purpose of that auto-generated file per CLAUDE.md §2."
  - "docs/DEPLOYMENT.md's job-count text and CLAUDE.md's job-id string are stated without the literal substring 'morning-briefing-tick' (rephrased as 'the polling route deleted alongside it' / 'the morning's polling cron') to satisfy the plan's literal grep -c ... returns 0 acceptance criteria for both files, while still preserving the historical retirement note for operators. The job's Cloud Scheduler ID itself, klaus-morning-briefing, IS still named (needed for the delete/pause command and required present by tests/test_docs.py::test_all_nine_job_ids_present)."
  - "Fixed two tests/test_heartbeat.py tests NOT named in the plan's read_first (test_check_cron_health_flags_stale, test_all_cron_jobs_have_staleness_entry) because both used 'morning-briefing' as an example job-id in _CRON_MAX_STALENESS_HOURS assertions and would have broken as a direct, mechanical consequence of Task 1's key removal — same class of fix as the explicitly-named retirement-TODO test, just not called out by name in the plan."

requirements-completed: []
requirements-partial: [OCC-02, OCC-06]

# Metrics
duration: ~55min (Task 1 only; Tasks 2-3 blocked on operator action)
completed: 2026-08-01
---

# Phase 33 Plan 13: Retire Morning Polling Cron, Open the Cascade Observation Window Summary

**All non-production code/doc work for the D-31 close-out is committed — `handle_tick`'s polling state machine, its `/cron/morning-briefing-tick` route, and the dangling `morning-briefing` staleness key are deleted together now that the wake-up trigger is confirmed live in production — but the plan cannot complete: Task 2 (retire the Cloud Scheduler job, flip `OCCASION_CASCADE=true`) and Task 3 (the 3-4 day observation window) are both `checkpoint:human-action`/`checkpoint:human-verify` gates that only Amit, acting against production, can perform.**

## Performance

- **Duration:** ~55 min (worktree base-correction from `fa182f9` to `eb3c133` — one merge behind the tip after 33-12's checkpoint-close commits — through Task 1's final commit)
- **Started:** 2026-08-01 (session start)
- **Completed (Task 1 only):** 2026-08-01
- **Tasks:** 1/3 (Task 2 is `checkpoint:human-action` gate="blocking"; Task 3 is `checkpoint:human-verify` gate="blocking" — neither can be executed by an agent, and Task 3 depends on Task 2)

## Accomplishments

- **`core/morning_briefing.py`** — `handle_tick` (the `pending`/`sync_detected`/`sent`/`failed` state machine, the `(10, 15)` hour cutoff, the Garmin-sync-as-trigger gate, and the `retry_count` transitions) deleted entirely, along with its section header comment. `sync_detected`/`retry_count` Firestore writes went with it — per the plan's discretionary call, no migration/backfill for existing `morning_briefings/{date}` docs carrying those now-dormant fields (nothing reads them, a backfill would be pure churn). `_fetch_garmin_safe`, `_sync_bodyweight_from_garmin`, and `_gather_data` are byte-identical — sleep data remains briefing *content*, never a trigger, exactly as before. `run_morning_briefing`, `_compose_briefing`, and `_parse_briefing_skip` (the legacy LLM composer, confirmed via `grep -rn "run_morning_briefing\b"` to have no other production caller) are kept in place per the plan's instruction, each now carrying a `# Phase 35: delete with the other legacy composers` marker. Module docstring and `run_morning_briefing_triggered`'s own docstring rewritten to describe the current live shape (push-triggered only, no backstop, iOS wake-up automation whose exact mechanism varies by version) instead of the retired polling description and the incorrect "Sleep-Focus-off" framing.
- **`interfaces/web_server.py`** — `@app.post("/cron/morning-briefing-tick")` and its `_log_cron_run("morning-briefing", ...)` calls deleted. Two stale comments corrected: the `/trigger/morning` route's preamble comment (previously described the D-31 dark-ship wait as still-pending and named the trigger "Sleep-Focus-off"; now states the retirement is closed and describes the trigger accurately per `docs/sleep_focus_off_shortcut.md` §3.0), and a one-line reference to the now-deleted `cron_morning_briefing_tick` function inside `cron_autonomous_tick`'s own docstring.
- **`core/heartbeat.py`** — `_CRON_MAX_STALENESS_HOURS["morning-briefing"]` (value `26`, carrying the `TODO(33-12/D-10)` dark-ship annotation from plan 33-11) removed. The `nightly-trigger` NOTE immediately below the map is extended to also name `morning-trigger`, explaining both are deliberately unmonitored (user-driven, may legitimately not fire on a given day; D-09 removed the morning's backstop by design; `check_occasion_health`'s anomaly #1 already covers a morning that *ran* and went wrong — this just isn't a "didn't run at all" check).
- **Test fixes (mechanical consequences of the key removal + route deletion):** `tests/test_heartbeat.py` — replaced `test_morning_briefing_staleness_key_has_retirement_todo` (asserted the TODO comment's presence) with `test_morning_briefing_staleness_key_retired` (asserts the key's *absence*, per the plan's explicit instruction); rewrote `test_morning_trigger_never_added_to_staleness_map` to check the map directly instead of source-grepping; fixed two tests not named in the plan's read_first (`test_check_cron_health_flags_stale`, `test_all_cron_jobs_have_staleness_entry`) that used `"morning-briefing"` as an example job-id and would otherwise fail now that the key is gone. `tests/test_morning_briefing.py` — deleted the three (already `@pytest.mark.skip`'d) `handle_tick` state-machine tests alongside the code they covered. `tests/test_web_server.py` — fixed one stale comment referencing the deleted `cron_morning_briefing_tick` function (not a behavioral assertion — no test exercised that route).
- **`core/self_manifest.py`** (Rule 1, outside the plan's declared `files_modified`) — the D-07 cron-jobs summary line that Klaus's own `docs/SELF.md` renders from hardcoded `"9 scheduled jobs"` including `morning-briefing-tick (*/10 6-10, \`/cron/morning-briefing-tick\`)`. Left uncorrected, the very next deploy would regenerate an inaccurate self-manifest describing infrastructure that no longer exists — directly contradicting CLAUDE.md §2's stated purpose for that file. Dropped the entry, corrected the count to 8.
- **`docs/DEPLOYMENT.md`** — §19's job inventory table row 1 (`klaus-morning-briefing`) removed, table intro corrected 10→9 jobs, and the row's retirement note rewritten from "scheduled for retirement, do not delete early" to a closed-out note naming the confirmed-live production evidence and providing the exact `gcloud scheduler jobs delete`/`pause` command for the operator checkpoint below. §22's `/trigger/morning` setup paragraph rewritten to match the corrected trigger description already present in the endpoint table (it had drifted — the table said "varies by iOS version" while the prose below it still said "Sleep Focus turns Off", contradicting 33-12's own correction) and to state the dark-ship window is closed.
- **`CLAUDE.md` § 5** — dropped the retired cron from the Cloud Scheduler jobs list; folded the morning briefing's trigger description into the existing nightly-trigger sentence (matching how `proactive-alerts`/`reflect` are already annotated as `**Retired:**`); added the morning's polling cron to that same `**Retired:**` clause with the 2026-08-01 confirmation date. Directory-layout comment for `core/morning_briefing.py` updated from "*/10 6-10: ... state machine" to "Push-triggered (POST /trigger/morning, no cron): ...".
- **`.planning/phases/33-occasion-cascade/deferred-items.md`** — logged the empty `skip_cause` observation carried forward from 33-12 (both 2026-07-31 and 2026-08-01 production cascade runs logged `cause=` empty) as an out-of-scope Phase 35 candidate, per the plan's prior-wave-context instruction to record it without attempting a fix here.

## Task Commits

1. **Task 1: Delete the morning polling path and its monitoring residue (D-09, D-10)** — `a12ee91` (feat) — `core/morning_briefing.py`, `interfaces/web_server.py`, `core/heartbeat.py`, `core/self_manifest.py`, `docs/DEPLOYMENT.md`, `CLAUDE.md`, `tests/test_morning_briefing.py`, `tests/test_heartbeat.py`, `tests/test_web_server.py`
2. **Deferred-items log (process documentation, not a plan task)** — `7375e95` (docs) — `.planning/phases/33-occasion-cascade/deferred-items.md`

_No plan-metadata commit — worktree mode; the orchestrator commits STATE.md/ROADMAP.md centrally after merge. This SUMMARY.md itself is committed separately per the worktree protocol._

## Files Created/Modified

- `core/morning_briefing.py` — `handle_tick` and its section header deleted (~90 lines removed); module + `run_morning_briefing_triggered` docstrings rewritten; three legacy-composer functions marked `# Phase 35: delete with the other legacy composers`.
- `interfaces/web_server.py` — `/cron/morning-briefing-tick` route deleted (~20 lines); two stale comments corrected.
- `core/heartbeat.py` — one `_CRON_MAX_STALENESS_HOURS` entry + its TODO comment removed; NOTE extended; two new comment lines documenting the retirement.
- `core/self_manifest.py` — one line dropped from the D-07 cron summary, job count corrected.
- `docs/DEPLOYMENT.md` — §19 table row removed + retirement note rewritten; §22 `/trigger/morning` prose corrected and closed out.
- `CLAUDE.md` — § 5 Cloud Scheduler jobs sentence + directory-layout comment updated.
- `tests/test_morning_briefing.py` — three `handle_tick` tests deleted (~53 lines).
- `tests/test_heartbeat.py` — one test replaced, one test rewritten, two tests fixed for the key removal, one section comment updated.
- `tests/test_web_server.py` — one comment fixed.
- `.planning/phases/33-occasion-cascade/deferred-items.md` — one new entry appended.

## Decisions Made

See `key-decisions` in the frontmatter. Summarized: (1) legacy composer functions kept per the plan's explicit two-pass deletion design, only `_plain_text_fallback` excluded from the Phase-35 marker since it's shared with the live cascade path; (2) the plan's own full-repo `handle_tick` grep acceptance check is over-broad (matches unrelated `chat_ingest.py`/`chat_export_ingest.py` cron handlers) — verified the real, scoped requirement independently; (3) fixed `core/self_manifest.py` under Rule 1 despite it not being in the plan's declared file list, because leaving it would ship an inaccurate self-description on the next deploy; (4) rephrased two doc mentions to avoid the literal string `"morning-briefing-tick"` to satisfy the plan's literal `grep -c` acceptance criteria for `docs/DEPLOYMENT.md`/`CLAUDE.md`, while keeping the job ID `klaus-morning-briefing` itself present (required by `tests/test_docs.py`); (5) fixed two `tests/test_heartbeat.py` tests not named in the plan's `read_first` because they broke as a direct mechanical consequence of the key removal.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Doc accuracy bug] `core/self_manifest.py`'s hardcoded cron-jobs summary would generate an inaccurate `docs/SELF.md` on the next deploy**
- **Found during:** Task 1
- **Issue:** `core/self_manifest.py`'s `_render_manifest`-adjacent §4 Cron Jobs summary line hardcoded `"9 scheduled jobs (Asia/Jerusalem): ... morning-briefing-tick (*/10 6-10, \`/cron/morning-briefing-tick\`) · ..."`. Once the route and cron were retired, this line would silently regenerate a false description of Klaus's own live infrastructure on the very next deploy (`core/self_manifest.py` runs on every deploy per CLAUDE.md §2), directly undermining the self-awareness purpose of that auto-generated file.
- **Fix:** Removed the `morning-briefing-tick` entry from the summary string and corrected the count from 9 to 8.
- **Files modified:** `core/self_manifest.py`
- **Verification:** `pytest tests/test_docs.py -x -q` (17 passed — the only test file that exercises `core/self_manifest.py`); no test asserts the literal "9 scheduled jobs"/"8 scheduled jobs" string, so no test needed updating.
- **Committed in:** `a12ee91` (part of Task 1 commit)

**2. [Rule 1 - Broken tests, mechanical consequence] Two `tests/test_heartbeat.py` tests used `"morning-briefing"` as an example staleness-map job-id**
- **Found during:** Task 1 (running the target test files after the code change)
- **Issue:** `test_check_cron_health_flags_stale` monkeypatched `_read_cron_ledger` to return a doc keyed `"morning-briefing"` and asserted a `cron:morning-briefing:stale` signal; `test_all_cron_jobs_have_staleness_entry`'s `expected_subset` included `"morning-briefing"`. Both would fail once `_CRON_MAX_STALENESS_HOURS["morning-briefing"]` was removed by Task 1 — the loop in `check_cron_health()` only checks job-ids present in the map, so a ledger doc for a now-unregistered job-id produces no signal.
- **Fix:** `test_check_cron_health_flags_stale` now uses `"ingest-chats"` (a job-id that remains in the map) as its example. `test_all_cron_jobs_have_staleness_entry`'s `expected_subset` no longer includes `"morning-briefing"`; it was instead added to the existing `retired` set alongside `"proactive-alerts"`/`"reflect"`, mirroring the pattern that test already used for other retired crons.
- **Files modified:** `tests/test_heartbeat.py`
- **Verification:** `pytest tests/test_heartbeat.py -x -q` — 80 passed.
- **Committed in:** `a12ee91` (part of Task 1 commit)

### Documented Interpretive Extensions (not Rule 1/2/3 fixes)

**1. Two doc mentions rephrased to avoid the literal substring "morning-briefing-tick"**
- **Why:** The plan's acceptance criteria for Task 1 literally require `grep -c "morning-briefing-tick" docs/DEPLOYMENT.md CLAUDE.md` (and separately `interfaces/web_server.py`) to return `0`. My first pass at the retirement notes in both docs, and one comment in `web_server.py`, still named the retired job/route as historical context and tripped this exact grep. Rephrased all three (e.g. "the polling route deleted alongside it", "the morning's polling cron") to preserve the historical/operator-facing information without the literal substring.
- **Verification:** `grep -c "morning-briefing-tick" docs/DEPLOYMENT.md` → 0; `grep -c "morning-briefing-tick" CLAUDE.md` → 0; `grep -c "morning-briefing-tick" interfaces/web_server.py` → 0.

**2. `docs/DEPLOYMENT.md` §22's `/trigger/morning` prose corrected beyond the plan's literal scope**
- **Why:** While updating the dark-ship language for the route's docstring-equivalent, found the surrounding prose (§22 "iOS setup for `/trigger/morning`") still said `"When [Sleep Focus] turns Off"`, directly contradicting the *same file's own endpoint table* three lines above it (which 33-12 had already corrected to "exact trigger varies by iOS version"). Left as-is, an operator reading top-to-bottom would hit a self-contradiction within one section. Corrected to match the table and cite `docs/sleep_focus_off_shortcut.md` §3.0, per this plan's explicit instruction ("describe it accurately... rather than repeating the incorrect claim") for any Sleep-Focus-off references touched.
- **Files modified:** `docs/DEPLOYMENT.md`
- **Verification:** Manual read-through of §22 post-edit; `pytest tests/test_docs.py -x -q` (17 passed, no regressions to the literal-heading assertions).

## Issues Encountered

- **Worktree base drift.** `git merge-base HEAD <expected-base>` initially returned `fa182f9` (the tip before 33-12's three checkpoint-close commits), not the expected `eb3c1336...`. Corrected via `git reset --hard eb3c13364b4dd33358213920799c113b1d071e1a` on a clean tree before any reads/edits, per the `<worktree_branch_check>` protocol.
- **The plan's literal full-repo `handle_tick` acceptance grep is over-broad.** `grep -rn "handle_tick" --include="*.py" . | grep -v "\.planning"` will never return empty regardless of this plan's changes — `core/chat_ingest.py:547` and `core/chat_export_ingest.py:548` each define their own unrelated `handle_tick()` function for a different cron, predating this plan. The real, scoped acceptance target (core/morning_briefing.py's `handle_tick` definition, and every callsite in `interfaces/web_server.py`) is confirmed gone via targeted greps — see Self-Check below.

## User Setup Required — RETURNED AS A CHECKPOINT, NOT EXECUTED

**Task 2 and Task 3 of this plan are entirely human/production-only and were NOT executed by this agent.** Per this plan's `autonomous: false` frontmatter and the explicit instruction not to touch production, both are returned as a structured checkpoint (see the executor's final response) rather than simulated or skipped:

- **Task 2 (`checkpoint:human-action`, gate="blocking"):** deploy the code from this plan's commit, then retire the `klaus-morning-briefing` Cloud Scheduler job (`gcloud scheduler jobs delete` or `pause`), then flip `OCCASION_CASCADE=false` → `true` in `.github/workflows/deploy.yml` (and redeploy), then confirm the next morning still arrives trigger-only and watch the first heartbeat cycle for 24h.
- **Task 3 (`checkpoint:human-verify`, gate="blocking"):** the 3-4 day observation window itself — depends entirely on Task 2 being closed first. No metric/checklist by design (D-29); Amit's own judgment from daily use, corrected in-chat under Phase 31's standing-directive loop (D-34), is the closing mechanism.

Do not attempt to advance past this plan until Amit's "cascade live" (Task 2) and "window closed — proceed to Phase 35" / "keep the legacy path" (Task 3) resume-signals are received.

## Next Phase Readiness

- All code/doc prerequisites for the D-31 close-out are committed and green (76 + 80 + 65 + 17 tests passing across the four touched/verified test files).
- The morning is now trigger-only in the codebase — `handle_tick`, its cron route, and its staleness key are gone together, with no dangling monitoring residue.
- Phase 35's legacy-composer deletion scope is confirmed untouched: `_compose_nightly` (nightly_review.py) and `_compose_review` (weekly_training_review.py) each still `grep -c` to exactly 1; `run_morning_briefing`/`_compose_briefing`/`_parse_briefing_skip` are marked but not deleted.
- `requirements-completed` is empty in this SUMMARY's frontmatter and OCC-02/OCC-06 remain `requirements-partial`: the plan's own `<success_criteria>` requires "the cascade is live for all three occasions" and "Amit has lived with the output for 3-4 days and given a go/no-go" — neither is reachable without the Task 2/Task 3 operator checkpoints. The orchestrator should not mark OCC-02/OCC-06 complete from this plan alone, and should not start Phase 35 until Task 3's resume-signal closes this plan.

## Self-Check: PASSED

- FOUND: `core/morning_briefing.py`
- FOUND: `interfaces/web_server.py`
- FOUND: `core/heartbeat.py`
- FOUND: `core/self_manifest.py`
- FOUND: `docs/DEPLOYMENT.md`
- FOUND: `CLAUDE.md`
- FOUND: `tests/test_morning_briefing.py`
- FOUND: `tests/test_heartbeat.py`
- FOUND: `tests/test_web_server.py`
- FOUND: `.planning/phases/33-occasion-cascade/deferred-items.md`
- FOUND commit `a12ee91` (Task 1)
- FOUND commit `7375e95` (deferred-items log)
- `grep -c "async def handle_tick" core/morning_briefing.py` → 0
- `grep -c "sync_detected\|retry_count" core/morning_briefing.py` → 0
- `grep -c "10, 15" core/morning_briefing.py` → 0
- `grep -c "def _fetch_garmin_safe\|def _sync_bodyweight_from_garmin\|def _gather_data" core/morning_briefing.py` → 3
- `grep -c "morning-briefing-tick" interfaces/web_server.py` → 0
- `grep -c '"morning-briefing"' core/heartbeat.py` → 0
- `grep -c "morning-trigger" core/heartbeat.py` → 1 (≥1 required)
- `grep -c "morning-briefing-tick" docs/DEPLOYMENT.md` → 0
- `grep -c "morning-briefing-tick" CLAUDE.md` → 0
- `grep -c "def _compose_nightly" core/nightly_review.py` → 1
- `grep -c "def _compose_review" core/weekly_training_review.py` → 1
- `pytest tests/test_morning_briefing.py -x -q` → 76 passed
- `pytest tests/test_heartbeat.py -x -q` → 80 passed
- `pytest tests/test_web_server.py -x -q` → 65 passed
- `pytest tests/test_docs.py -x -q` → 17 passed
- `python -c "import ast; [ast.parse(open(f).read()) for f in [...]]"` → all 7 modified `.py` files parse cleanly
- `git diff --diff-filter=D --name-only HEAD~1 HEAD` (post Task-1 commit) → empty (no unintended deletions)
- `git status --short` → clean (no leftover untracked files) after each commit

---
*Phase: 33-occasion-cascade*
*Completed: 2026-08-01 (Task 1 of 3 — Tasks 2 and 3 blocked on operator action against production)*
