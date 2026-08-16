---
phase: 33-occasion-cascade
plan: 11
subsystem: heartbeat
tags: [heartbeat, observability, occasion, cascade, D-28, monitoring, firestore]

# Dependency graph
requires:
  - phase: 33-occasion-cascade
    provides: "33-06 nightly_reviews/{date} state-doc contract (status/composed_via/skip_cause); 33-07 morning_briefings/{date} state-doc contract (same shape, SC-1 plain_text_fallback reachable); 33-08 weekly_reviews/{date} state-doc contract (status sent|skipped_by_directive, never skipped_by_judgment); 33-01 memory.firestore_db.ActionLogStore.undisclosed"
provides:
  - "core/heartbeat.py::check_occasion_health(now=None) -> list[Signal] — the four D-28 anomaly classes, wired into _collect_signals so it runs every hourly tick"
  - "core/heartbeat.py::_read_occasion_state / _occasion_skip_streak / _most_recent_sunday / _parse_occasion_timestamp — module-local helpers, no new store class per 33-PATTERNS.md"
affects: [35]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Read the occasion's own state doc directly (mirrors nightly_review.py/morning_briefing.py/weekly_training_review.py's own _get_state pattern) instead of the generic heartbeat_runs cron ledger — the load-bearing design constraint from 33-RESEARCH § Pitfall 8: _log_cron_run's ok boolean cannot see a degraded-but-shipped send."
    - "Presence/absence of a field (composed_via) as the health signal, not its value — a skipped_by_judgment doc with no composed_via key is healthy by construction; only composed_via in {plain_text_fallback, draft_fallback} on a doc that otherwise looks fine is unhealthy."
    - "Date-free fingerprint for a streak/backlog condition (occasion:{name}:skip_streak, occasion:actions_undisclosed) so the existing _register_incidents/_resolve_absent machinery auto-resolves it the moment the underlying condition clears, with zero new code."

key-files:
  created: []
  modified:
    - core/heartbeat.py
    - tests/test_heartbeat.py

key-decisions:
  - "Anomaly #1 (errored occasion) keys off composed_via values only ({plain_text_fallback, draft_fallback}), not a separate explicit fault marker — audited all three occasion modules (nightly_review.py, morning_briefing.py, weekly_training_review.py) and core/autonomous.py's _run_cascade and confirmed no state doc ever persists an explicit 'send failure' or 'Layer-1/2 exception' field; decision['trail'].append('send_failed') is in-memory only and never reaches Firestore. composed_via is the only persisted signal that distinguishes a degraded send from a clean one, so the checker reads exactly that."
  - "morning_briefing.py's actual behavior (confirmed by reading 33-07's shipped code) writes status='skipped_by_judgment' for BOTH a genuine Layer-1 judgment skip AND an infra failure with no explicit skip verdict (33-07's own documented design decision) — meaning skip_cause can legitimately be empty on a 'skip'. Anomaly #1 does not attempt to second-guess this via skip_cause; per the plan's own acceptance criteria, a skipped_by_judgment doc with no composed_via key is healthy regardless of skip_cause content. Distinguishing an empty-cause judgment skip from an infra failure that also produced no send is out of this plan's scope (SC-1's structural guarantee is about composed_via, not skip_cause completeness)."
  - "Anomaly #1's 2-day lookback picks the single most recent existing doc (today, else yesterday) rather than evaluating both — 'the most recent state doc within the last 2 days' read as singular per the plan's literal wording, and the fingerprint's {date} component confirms one signal per occasion per check, not one per stale day."
  - "Anomaly #3's directive-veto and absent-doc cases share one fingerprint format (occasion:weekly_review:not_fired:{date}) — the plan's <interfaces> block documents exactly one fingerprint pattern for this anomaly, and the two cases are mutually exclusive per date (a Sunday is either absent, vetoed, or sent), so no dedup collision is possible."
  - "check_occasion_health(now=None) takes an optional now parameter (mirrors run_tick's own now=None shape) purely for test determinism — production call sites (added to _collect_signals) call it with no argument, defaulting to datetime.now(_TZ), identical to every other checker's real-clock behavior."

requirements-completed: [OCC-06]

# Metrics
duration: ~35min
completed: 2026-07-30
---

# Phase 33 Plan 11: Heartbeat Occasion-Health Anomaly Checks Summary

**`check_occasion_health()` reads each occasion's own state doc directly (never the generic `heartbeat_runs` cron ledger) to surface all four D-28 anomaly classes — a degraded-but-shipped send, a judgment-skip streak, a Sunday the weekly never fired, and an orphaned undisclosed calendar/task write — while a legitimate `skipped_by_judgment` with no `composed_via` stays completely silent, closing the SC-1 gap where `_log_cron_run`'s `ok=True` would otherwise mask a real degradation.**

## Performance

- **Duration:** ~35 min (worktree base-correction to final commit)
- **Started:** 2026-07-30 (session start)
- **Completed:** 2026-07-30
- **Tasks:** 2/2
- **Files modified:** 2 (`core/heartbeat.py`, `tests/test_heartbeat.py`)

## Accomplishments

- **`check_occasion_health(now=None) -> list[Signal]` (Task 1+2 combined function, built incrementally across two commits).** Placed immediately after `_check_push_health` per the plan's structural precedent, and wired into `_collect_signals`'s checker tuple so it runs every hourly tick (not weekly-only), alongside `check_cron_health`/`check_tokens`/`check_degradation`/`check_deployment`/`_check_push_health`.
- **Anomaly #1 — errored occasion (D-28 #1, SC-1, T-33-35).** For each of `nightly`/`morning`/`weekly_review`, reads the most recent state doc within a 2-day lookback via the new `_read_occasion_state(collection, date_str)` helper (direct `_make_firestore_client(...).collection(...).document(...).get()` access — no new store class, per 33-PATTERNS.md's explicit guidance that these date-keyed docs stay store-class-free). `composed_via in {"plain_text_fallback", "draft_fallback"}` raises `SEVERITY_CRITICAL` with the date, occasion name, and trigger in the detail. Verified both non-firing cases explicitly: `status="sent"` + `composed_via="llm"` is silent, and `status="skipped_by_judgment"` with no `composed_via` key at all is silent — the exact SC-1 guarantee the plan calls out as load-bearing ("a false positive here would make the checker useless within a week").
- **Anomaly #2 — skip streak (D-28 #2, T-33-36).** New `_occasion_skip_streak(collection, today, window_days)` walks back up to 10 calendar dates for `nightly`/`morning` only (never `weekly_review`, which cannot self-skip by D-03), counting a consecutive `status=="skipped_by_judgment"` run ending at the most recent date with *any* state doc. A missing doc mid-run is treated as "unknown" — skipped without breaking or counting the streak, since D-09 explicitly removed the morning's backstop and a gap day is expected. Threshold `_OCCASION_SKIP_STREAK_THRESHOLD = 3` (Claude's Discretion per D-28 #2) emits `SEVERITY_WARNING` with `fingerprint=f"occasion:{name}:skip_streak"` (no date component — auto-resolves via the existing `_resolve_absent` machinery once Klaus speaks again) and a `detail` listing the `skip_cause` values seen in the run.
- **Anomaly #3 — weekly not firing (D-28 #3, T-33-27, T-33-38).** New `_most_recent_sunday(today)` helper (`isoweekday() % 7` back-calculation). On any day after the most recent Sunday, or on that Sunday itself at/after 10:00 (the weekly cron's fire time — verified with a dedicated before/after-10:00 test pair), reads `weekly_reviews/{sunday_iso}`: an absent doc raises `SEVERITY_CRITICAL`; `status=="skipped_by_directive"` raises `SEVERITY_WARNING` naming the veto reason; `status=="sent"` is silent. Explicitly complementary to (not a replacement for) the pre-existing `_CRON_MAX_STALENESS_HOURS["weekly-training-review"]` staleness check — that one catches "the cron never fired at all", this one catches "the cron fired and nothing happened."
- **Anomaly #4 — undisclosed actions pending (D-28 #4, T-33-37).** Calls `ActionLogStore(...).undisclosed(days=7)`; when non-empty and the oldest entry (by its `at` ISO timestamp, parsed via the new `_parse_occasion_timestamp` — mirrors `_parse_push_timestamp`'s defensive shape) is more than 24h old, emits one date-free `SEVERITY_WARNING` Signal (`fingerprint="occasion:actions_undisclosed"`) listing up to 5 entries as `{action} {detail} ({at})`. A fresh (<24h) or empty backlog is silent.
- **Dangling `morning-briefing` staleness key annotated, not removed (RESEARCH Assumption A3, T-33-38).** `_CRON_MAX_STALENESS_HOURS["morning-briefing"]` keeps its `26` value and gains a `# TODO(33-12/D-10): remove once morning-briefing-tick cron is retired` comment on the same line — the cron is still running during the D-31 dark-ship window and removing the entry early would blind real monitoring. A dedicated test asserts the comment's presence so the retirement can't be forgotten. Confirmed `"morning-trigger"` was never added to the staleness map (a second, separate regression-guard test) — like `nightly-trigger`, the push trigger is user-driven and may legitimately not fire on a given day (D-09); anomaly #1 already covers a morning that ran and went wrong.

## Task Commits

1. **Task 1 — `core/heartbeat.py` + `tests/test_heartbeat.py`** — `85e5a56` (feat) — `check_occasion_health` skeleton, `_read_occasion_state`, `_occasion_skip_streak`, Anomalies #1 + #2, `_collect_signals` wiring, 10 tests
2. **Task 2 — `core/heartbeat.py` + `tests/test_heartbeat.py`** — `68839e3` (feat) — `_most_recent_sunday`, `_parse_occasion_timestamp`, Anomalies #3 + #4, `morning-briefing` staleness-key TODO annotation, 13 tests

_No plan-metadata commit — worktree mode; the orchestrator commits STATE.md/ROADMAP.md centrally after merge. This SUMMARY.md itself is committed separately per the worktree protocol._

## Files Created/Modified

- `core/heartbeat.py` — `date` added to the top-level `datetime` import; new module-level constants (`_OCCASION_STATE_COLLECTIONS`, `_OCCASION_SKIP_STREAK_THRESHOLD`, `_OCCASION_SKIP_STREAK_WINDOW_DAYS`, `_OCCASION_ERRORED_LOOKBACK_DAYS`, `_OCCASION_UNDISCLOSED_STALE_HOURS`, `_OCCASION_ERRORED_COMPOSED_VIA`); new helpers `_read_occasion_state`, `_occasion_skip_streak`, `_most_recent_sunday`, `_parse_occasion_timestamp`; new `check_occasion_health(now=None)`; `_collect_signals`'s checker tuple gains `check_occasion_health`; `_CRON_MAX_STALENESS_HOURS["morning-briefing"]` gains the `TODO(33-12/D-10)` comment.
- `tests/test_heartbeat.py` — two new sections (`Phase 33 Plan 11 ... Task 1` and `Task 2`), 23 new tests total: errored-occasion (plain-text/draft fallback critical, healthy-send silent, healthy-judgment-skip silent), skip-streak (3-consecutive warns, 2-consecutive silent, missing-doc-mid-run doesn't reset, weekly_review structurally excluded), all-Signal-fields-nonempty, `_collect_signals` registration, weekly-not-firing (absent/sent/directive-vetoed/before-Sunday-cron/after-Sunday-cron), undisclosed-actions (stale/fresh/empty), and the two retirement-annotation regression guards.

## Decisions Made

See `key-decisions` in the frontmatter — summarized: (1) Anomaly #1 reads `composed_via` only, since no occasion module or `core.autonomous._run_cascade` ever persists an explicit fault marker to a state doc (`decision["trail"].append("send_failed")` is in-memory only); (2) morning's own shipped behavior (33-07) writes `skipped_by_judgment` for both genuine skips and infra failures with no verdict, and this plan does not attempt to distinguish them via `skip_cause` — only `composed_via`'s presence/absence is load-bearing per the plan's own acceptance criteria; (3) the 2-day lookback for Anomaly #1 picks a single most-recent doc, not both days independently; (4) Anomaly #3's absent-doc and directive-veto cases intentionally share one fingerprint format, matching the plan's `<interfaces>` block which documents exactly one pattern; (5) `check_occasion_health` takes an optional `now` parameter purely for test determinism, mirroring `run_tick`'s existing shape.

## Deviations from Plan

None requiring a Rule 1/2/3 fix. No bugs found in the codebase this plan reads from (nightly_review.py/morning_briefing.py/weekly_training_review.py/ActionLogStore all matched their documented shapes exactly, cross-checked against 33-06/33-07/33-08's own SUMMARY.md files). No missing critical functionality beyond what's covered under Decisions Made above. No blocking issues.

## Issues Encountered

None. No auth gates, no checkpoints. The one area requiring care was confirming (by reading the actual shipped `core/nightly_review.py`, `core/morning_briefing.py`, and `core/weekly_training_review.py` bodies rather than trusting only the plan text) exactly which fields each occasion's state doc does and does not persist on an infra-failure path — nightly writes nothing terminal on infra failure (stays retriable), morning writes `skipped_by_judgment` with an empty `skip_cause`, and weekly writes nothing at all (by design, so an absent doc is the D-28 #3 signal). This shaped Anomaly #1's scope (composed_via-only) and confirmed Anomaly #3's absent-doc detection is correct for the weekly's actual failure mode.

## User Setup Required

None — pure application code + tests, no new env vars, no infra changes, no new Cloud Scheduler jobs. `check_occasion_health` runs automatically on the next hourly heartbeat tick once this plan merges; no deploy-config changes needed since it reads collections that plans 33-06/07/08 already write to in production once `OCCASION_CASCADE` is flipped on.

## Next Phase Readiness

- All four D-28 anomaly classes are live and wired into the existing hourly heartbeat, `_register_incidents`/`_resolve_absent` incident-dedup machinery, and Telegram alert composition — no further plumbing needed for the rollout to be watchable.
- The `morning-briefing` staleness-key TODO is a hard dependency for plan 33-12: when that plan retires `morning-briefing-tick`, it must also delete the `_CRON_MAX_STALENESS_HOURS["morning-briefing"]` entry (and this plan's `test_morning_briefing_staleness_key_has_retirement_todo` test, or repoint it) — otherwise a permanent false "stale" critical will fire once the cron truly stops.
- No blockers or concerns for downstream plans. `core/tools.py` and `core/task_dispatch.py`/`interfaces/web_server.py` (sibling plans 33-09/33-10) were not touched.

## Self-Check: PASSED

- FOUND: `core/heartbeat.py`
- FOUND: `tests/test_heartbeat.py`
- FOUND: `.planning/phases/33-occasion-cascade/33-11-SUMMARY.md`
- FOUND commit `85e5a56` (Task 1)
- FOUND commit `68839e3` (Task 2)
- `grep -c "def check_occasion_health" core/heartbeat.py` → 1 (exact match required)
- `grep -c "check_occasion_health" core/heartbeat.py` → 2 (def + `_collect_signals` wiring, ≥2 required)
- `grep -c "_OCCASION_SKIP_STREAK_THRESHOLD = 3" core/heartbeat.py` → 1
- `grep -n "TODO(33-12" core/heartbeat.py` → hit on the `morning-briefing` staleness line
- `pytest tests/test_heartbeat.py -k "anomaly or occasion_health or skip_streak" -x -q` → 10 passed
- `pytest tests/test_heartbeat.py -k "not_fired or undisclosed or staleness" -x -q` → 13 passed
- `pytest tests/test_heartbeat.py -x -q` → 80 passed
- `pytest tests/test_nightly_review.py tests/test_morning_briefing.py tests/test_weekly_training_review.py -q` → all passed (no regressions in the modules this plan reads state docs from)

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-30*
