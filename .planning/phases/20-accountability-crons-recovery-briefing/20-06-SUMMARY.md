---
phase: 20-accountability-crons-recovery-briefing
plan: 06
subsystem: cron/training-review
tags: [weekly-review, brain-composed, heartbeat, cron-route, training-log]

# Dependency graph
requires:
  - plan: 20-01
    provides: "TrainingLogStore.get_range (Sun-Sat window reads)"
  - plan: 20-01
    provides: "MealStore.get_day_aggregate (7-day nutrition totals)"
provides:
  - "/cron/weekly-training-review OIDC route (REVIEW-01)"
  - "core/weekly_training_review.py: run_weekly_review + _gather_week_data + _compose_review"
  - "prompts/weekly_training_review.md: brain system prompt with {today_date}, scorecard format, D-24 sparse copy"
  - "heartbeat 170h staleness key for weekly-training-review (REVIEW-04)"
affects:
  - "Cloud Scheduler (operator must add sunday-10:00 job pointing at /cron/weekly-training-review)"
  - "core/heartbeat.py: check_cron_health will alert if weekly review goes stale > 170h"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sun-Sat week boundary via _prev_sunday(): isoweekday() % 7 offset + minus 7 for prior completed week"
    - "Best-effort Pattern-C gather: each source in try/except, failure sets key to None + logs WARNING"
    - "Brain-composed cron: SMART_AGENT_* LLMClient + prompt.read_text + meal_audit.md appended"
    - "Weekly staleness key > 100h: raised test upper bound to 200h to accommodate weekly crons"

key-files:
  created:
    - "prompts/weekly_training_review.md"
    - "core/weekly_training_review.py"
  modified:
    - "interfaces/web_server.py"
    - "core/heartbeat.py"
    - "tests/test_web_server.py"
    - "tests/test_heartbeat.py"
    - "tests/test_docs.py"

key-decisions:
  - "prompts/weekly_training_review.md produces plain-text output (not JSON) because the message is sent directly to Telegram, unlike reflection.md which produces a structured JSON"
  - "biometrics_this_week / biometrics_last_week fetched from Postgres daily_biometrics via query_health_database SQL — no dedicated Firestore store for historical biometrics"
  - "test_all_cron_jobs_have_staleness_entry upper bound raised from 100 to 200 to accommodate weekly jobs (Rule 1 fix — the bound was implicitly assuming only daily/sub-daily crons)"
  - "run_weekly_review is async; the route awaits it directly (no run_in_executor needed unlike reflection.py sync path)"

# Metrics
duration: ~8min
completed: 2026-06-01
---

# Phase 20 Plan 06: Weekly Training Review — Cron Route + Brain Module + Heartbeat Summary

**Sunday 10:00 brain-composed weekly training review: OIDC cron route, gather-and-compose module reading TrainingLogStore/Garmin/biometrics/MealStore/goals, prompt file with emoji scorecard + D-24 always-send, and 170h heartbeat staleness key**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-01T09:12:54Z
- **Completed:** 2026-06-01T09:21:02Z
- **Tasks:** 3
- **Files modified/created:** 7

## Accomplishments

- `prompts/weekly_training_review.md` created with `{today_date}` placeholder, emoji scorecard format (✅/❌/⚠️ per D-18), 2–4 paragraph narrative structure, one suggestion (D-20), nutrition integration via meal_audit.md (D-21), D-24 sparse-week "Quiet week" copy, error state copies from UI-SPEC, JARVIS voice rules
- `core/weekly_training_review.py` created with three public surfaces: `_gather_week_data` (tz-aware Sun–Sat window via `ZoneInfo("Asia/Jerusalem")`, best-effort Pattern-C blocks for TrainingLogStore/Garmin 14-day activities/Postgres biometrics/MealStore 7-day totals/UserProfileStore goals), `_compose_review` (SMART_AGENT_* brain + meal_audit.md appended, D-24 fallback), `run_weekly_review` (always sends with inject_into_conversation=True)
- `/cron/weekly-training-review` route added to `interfaces/web_server.py` after autonomous-tick: _verify_cron_request → _application guard → lazy import → _log_cron_run on both paths → re-raise (REVIEW-01)
- `_CRON_MAX_STALENESS_HOURS["weekly-training-review"] = 170` added to `core/heartbeat.py` (REVIEW-04)
- 5 new tests in `TestCronWeeklyTrainingReview` (200/401/500/ok-true/ok-false), new `test_weekly_training_review_staleness_threshold`, new `test_weekly_training_review_prompt_exists` — all green

## Task Commits

1. **Task 1: prompt + module + docs test** — `1165123` (feat)
2. **Task 2: cron route + web_server tests** — `35e4005` (feat)
3. **Task 3: heartbeat staleness key + heartbeat tests** — `04e5890` (feat)

## Files Created/Modified

- `prompts/weekly_training_review.md` — brain system prompt (REVIEW-03)
- `core/weekly_training_review.py` — gather + compose + run_weekly_review entry point (REVIEW-02)
- `interfaces/web_server.py` — /cron/weekly-training-review OIDC route (REVIEW-01)
- `core/heartbeat.py` — weekly-training-review: 170h staleness entry (REVIEW-04)
- `tests/test_web_server.py` — TestCronWeeklyTrainingReview class (5 tests)
- `tests/test_heartbeat.py` — test_weekly_training_review_staleness_threshold + bound fix
- `tests/test_docs.py` — test_weekly_training_review_prompt_exists

## Decisions Made

- Plain-text output from the weekly review prompt (not JSON) — the message goes directly to Telegram, unlike reflection.md which produces a structured JSON for Firestore storage
- Biometrics historical range fetched from Postgres daily_biometrics via `query_health_database` SQL covering both this-week and last-week in a single query, then split in Python
- `test_all_cron_jobs_have_staleness_entry` upper bound raised 100→200 so weekly crons (170h) do not trip the sanity check

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_all_cron_jobs_have_staleness_entry bound too tight for weekly crons**
- **Found during:** Task 3
- **Issue:** Existing test asserted `0 < hours <= 100` for ALL staleness entries. Adding weekly-training-review at 170h caused this sanity test to fail.
- **Fix:** Raised upper bound to 200 in the assertion and updated the docstring to explain the change (weekly crons with up to 8d slack need the wider range).
- **Files modified:** `tests/test_heartbeat.py`
- **Commit:** `04e5890`

## Known Stubs

None — no placeholder data or hardcoded empty values. `run_weekly_review` makes real Firestore and Garmin calls in production; the test layer patches at the module boundary. The prompt produces a genuine brain-composed narrative.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-20-13 mitigated | interfaces/web_server.py | _verify_cron_request runs first on /cron/weekly-training-review |
| T-20-14 mitigated | interfaces/web_server.py, core/heartbeat.py | _log_cron_run ok=True/False + 170h staleness key |
| T-20-15 mitigated | prompts/weekly_training_review.md | Prompt enforces D-13/D-20 no-invented-targets guardrail |

## Self-Check: PASSED

Files verified:
- `prompts/weekly_training_review.md` — FOUND (contains {today_date}, ✅/❌/⚠️, "Quiet week")
- `core/weekly_training_review.py` — FOUND (run_weekly_review, _gather_week_data, _compose_review, ZoneInfo("Asia/Jerusalem"), SMART_AGENT_BACKEND, meal_audit, inject_into_conversation=True)
- `interfaces/web_server.py` — FOUND (/cron/weekly-training-review at line 438)
- `core/heartbeat.py` — FOUND ("weekly-training-review": 170 at line 116)
- `tests/test_web_server.py` — FOUND (TestCronWeeklyTrainingReview, 5 tests green)
- `tests/test_heartbeat.py` — FOUND (test_weekly_training_review_staleness_threshold green)
- `tests/test_docs.py` — FOUND (test_weekly_training_review_prompt_exists green)

Commits verified:
- `1165123` — feat(20-06): add weekly_training_review module + prompt + docs test
- `35e4005` — feat(20-06): add /cron/weekly-training-review route + web_server tests
- `04e5890` — feat(20-06): add heartbeat 170h staleness key for weekly-training-review

---
*Phase: 20-accountability-crons-recovery-briefing*
*Completed: 2026-06-01*
