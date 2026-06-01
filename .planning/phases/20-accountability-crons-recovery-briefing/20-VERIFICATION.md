---
phase: 20-accountability-crons-recovery-briefing
verified: 2026-06-01T13:30:00Z
status: passed
score: 19/19 must-haves verified
gap_resolved: 2026-06-01T13:45:00Z
overrides_applied: 0
gaps:
  - truth: "recovery_concern flows into the evening proactive-alert tone shift (RECOVERY-03 / D-16)"
    status: failed
    reason: >
      compute_recovery_concern() is never called inside proactive_alerts.run_proactive_alerts.
      The alerts_context dict built at line 141 of core/proactive_alerts.py contains only
      target_date, weather_alerts, overload_alert, and travel_alerts — no recovery_concern key.
      prompts/proactive_alert.md was updated with the recovery_concern framing (the prompt is
      ready), but the data path is broken: the key never reaches the LLM prompt at runtime for
      the evening alert. Morning briefing works correctly (morning_briefing._gather_data sets
      data["recovery_concern"]). The evening half of D-16 is not wired.
    artifacts:
      - path: "core/proactive_alerts.py"
        issue: >
          run_proactive_alerts (lines ~91–152) builds alerts_context without computing or
          inserting recovery_concern. No import of compute_recovery_concern anywhere in
          this file. No garmin_data fetch in this function for that purpose.
    missing:
      - >
        Add recovery_concern computation to run_proactive_alerts: fetch garmin data for today
        (or reuse existing data if already fetched), call
        core.training_checkin.compute_recovery_concern(garmin_data, today_iso), and insert
        the result into alerts_context before _compose_alert when non-None.
        The call should be best-effort (try/except) consistent with other data sources.
      - >
        Add a test in tests/test_proactive_alerts.py verifying that when
        compute_recovery_concern returns a non-None dict, it appears in the alerts_context
        passed to _compose_alert.
---

# Phase 20: Accountability Crons & Recovery Briefing — Verification Report

**Phase Goal:** Training accountability loop — TrainingLogStore, evidence-first check-in folded into 21:30 cron, weekly training review (Sunday 10:00), recovery-aware morning briefing and evening alert, Cloud Scheduler bootstrap.
**Verified:** 2026-06-01T13:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TrainingLogStore writes sessions to `training_log/{date}_{slot}` with all required fields | VERIFIED | `memory/firestore_db.py` lines 699–856: `log_session` writes `date, slot, type, planned, completed, skipped_reason, rpe, feel, notes, source, garmin_activity_id` with `merge=True` idempotency and RPE normalisation (Pitfall 7) |
| 2 | `get_recent(days)` and `get_by_date(date)` return entries; never raise | VERIFIED | `memory/firestore_db.py` lines 779–827; both return `[]` on error. `get_range` also present. |
| 3 | `log_training` tool registered brain-direct; accepts free-form fields | VERIFIED | `core/tools.py` line 56 (`SMART_AGENT_DIRECT_TOOLS`), line 756 schema, line 1396 handler, line 1463 dispatch |
| 4 | `get_training_history` registered worker-delegated | VERIFIED | Not in `SMART_AGENT_DIRECT_TOOLS`; not excluded from `WORKER_TOOL_SCHEMAS`; handler at line 1413; dispatch at line 1464 |
| 5 | Training check-in folds into 21:30 proactive-alerts cron (no separate endpoint) | VERIFIED | `core/proactive_alerts.py` lines 98–108: `run_training_checkin(bot, today)` called before `_already_sent` gate |
| 6 | Silent Garmin sync writes RPE-present activities to TrainingLogStore (no Telegram) | VERIFIED | `core/training_checkin.py` lines 447–481: `_silent_garmin_sync` iterates activities, writes only when `perceived_exertion` is not None, source="garmin" |
| 7 | Check-in sends keyboard prompts only for unlogged past-start workouts; fully silent when all covered | VERIFIED | `core/training_checkin.py` lines 507–657: D-07 time-gate, covered-check, `prompts_to_send` list, early return if empty (CHECKIN-05) |
| 8 | RPE inline keyboard is two rows of 5 (1–5 / 6–10); callback_query dispatch wired in router | VERIFIED | `_rpe_keyboard` at line 304, `_watchoff_keyboard` at 317, `_skipreason_keyboard` at 329; `interfaces/_router.py` lines 72–79 dispatches callback_query before message guard; lines 171–178 routes rpe/watchoff/skipreason prefixes |
| 9 | Notes follow-up open until reply (`/skip`); reply-to detection wired in router | VERIFIED | `attach_note` at line 849, `handle_skip_note` at line 893; router `_check_pending_note_reply` at line 180 matches `message_id` from PendingPromptStore |
| 10 | PendingPromptStore manages multi-step session state with 20h soft TTL | VERIFIED | `memory/firestore_db.py` lines 874–1038: `set/get/delete/get_open_note_session`; TTL enforced on `get` (stale-replay rejected) |
| 11 | `send_and_inject` accepts `reply_markup` for inline keyboards | VERIFIED | `core/scheduled_message.py` line 31: `reply_markup=None` kwarg; line 53: passed to `bot.send_message` |
| 12 | `/cron/weekly-training-review` endpoint exists with OIDC auth | VERIFIED | `interfaces/web_server.py` lines 438–470: `@app.post("/cron/weekly-training-review")`, calls `_verify_cron_request`, lazy-imports `core.weekly_training_review`, calls `_log_cron_run` on both paths |
| 13 | Weekly review gathers training_log, Garmin activities, biometrics, MealStore 7-day totals, athletic_goals | VERIFIED | `core/weekly_training_review.py` lines 42–192: 5 data sources, each best-effort wrapped, D-23 Sun–Sat window, D-22 14-day Garmin for trend comparison |
| 14 | `prompts/weekly_training_review.md` exists with scorecard + narrative + one suggestion format | VERIFIED | File exists; contains ✅/❌/⚠️ scorecard, 2–4 paragraph narrative, one suggestion, D-24 empty-week handling, D-18 no monospace tables, D-13 no invented numeric targets |
| 15 | Weekly review always sends (D-24); brain-composed via SMART_AGENT_* | VERIFIED | `core/weekly_training_review.py` line 281: `send_and_inject(bot, message, inject_into_conversation=True)`; `_compose_review` uses `SMART_AGENT_BACKEND/MODEL/API_KEY` (lines 238–241); fallback string always non-empty |
| 16 | `recovery_concern` computed in `morning_briefing._gather_data` and wired to morning briefing prompt | VERIFIED | `core/morning_briefing.py` lines 236–246: imports `compute_recovery_concern`, calls with `garmin_data`, conditionally sets `data["recovery_concern"]`; `prompts/morning_briefing.md` lines 116–147 read the key and shift tone |
| 17 | RECOVERY_THRESHOLDS defined at module level with v0 heuristics and docstring | VERIFIED | `core/training_checkin.py` lines 65–75: dict with 7 keys (`acwr_mild=1.5`, `acwr_strong=1.8`, `sleep_low=70`, `consecutive_low_sleep_nights=2`, `intensity_keywords_high/moderate`, `hrv_flag_values`) |
| 18 | `scripts/bootstrap_shifu_crons.sh` creates ONLY `klaus-weekly-training-review` at `0 10 * * 0` Asia/Jerusalem | VERIFIED | Script lines 1–33: one job, schedule matches, OIDC SA param, re-runnable describe-or-create |
| 19 | `recovery_concern` flows into the evening proactive-alert tone shift (RECOVERY-03 / D-16) | FAILED | `prompts/proactive_alert.md` was extended with recovery_concern framing, but `core/proactive_alerts.run_proactive_alerts` never computes `recovery_concern` or inserts it into `alerts_context`. The key is absent from the LLM prompt data at runtime for the evening alert path. |

**Score:** 18/19 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `memory/firestore_db.py` — TrainingLogStore | log_session + get_recent + get_by_date + get_range | VERIFIED | Lines 699–856, all methods present, idempotent, never-raise reads |
| `memory/firestore_db.py` — PendingPromptStore | multi-step session state, TTL, get_open_note_session | VERIFIED | Lines 874–1038 |
| `core/training_checkin.py` | run_training_checkin + 4 callbacks + compute_recovery_concern + RECOVERY_THRESHOLDS | VERIFIED | 935 lines; all required functions present and substantive |
| `core/proactive_alerts.py` | fold-in of run_training_checkin before _already_sent gate | VERIFIED | Lines 98–108 |
| `interfaces/_router.py` | callback_query dispatch + reply-to detection | VERIFIED | Lines 72–229 |
| `core/scheduled_message.py` | reply_markup support | VERIFIED | Lines 31, 53 |
| `mcp_tools/calendar_tool.py` | list_training_events + get_calendar_id_by_name | VERIFIED | Lines 151–264 |
| `core/weekly_training_review.py` | _gather_week_data + _compose_review + run_weekly_review | VERIFIED | 282 lines, all three functions present and substantive |
| `interfaces/web_server.py` | /cron/weekly-training-review with OIDC | VERIFIED | Lines 438–470 |
| `prompts/weekly_training_review.md` | scorecard + narrative + suggestion | VERIFIED | 72 lines |
| `prompts/morning_briefing.md` | recovery_concern tone-shift section | VERIFIED | Lines 116–156 |
| `prompts/proactive_alert.md` | recovery_concern framing | VERIFIED (prompt exists) | Lines 13–36 — prompt ready but data never reaches it at runtime |
| `scripts/bootstrap_shifu_crons.sh` | creates only weekly-training-review, re-runnable | VERIFIED | 34 lines |
| `docs/DEPLOYMENT.md` | §24 Phase Shifu + §19 inventory updated | VERIFIED | §19 table row 8, §24 full documentation |
| `core/heartbeat.py` | 170h staleness key for weekly-training-review | VERIFIED | Line 116 |
| `docs/SELF.md` | regenerated with new tools and cron | VERIFIED | Lines 64–65 (tools), line 78 (cron job) |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `core/proactive_alerts.run_proactive_alerts` | `core/training_checkin.run_training_checkin` | import + await at line 103 | WIRED | Runs before _already_sent gate (D-09 Pitfall 5) |
| `interfaces/_router.handle_update` | `core/training_checkin.handle_rpe_callback` | callback_query dispatch line 172 | WIRED | rpe: prefix → handle_rpe_callback |
| `interfaces/_router._check_pending_note_reply` | `memory/firestore_db.PendingPromptStore.get_open_note_session` | import + call line 200 | WIRED | match on message_id |
| `core/morning_briefing._gather_data` | `core/training_checkin.compute_recovery_concern` | import line 237, call line 238 | WIRED | sets data["recovery_concern"] when truthy |
| `core/proactive_alerts.run_proactive_alerts` | `core/training_checkin.compute_recovery_concern` | — | NOT WIRED | recovery_concern never computed or inserted into alerts_context (RECOVERY-03 gap) |
| `core/weekly_training_review._compose_review` | `core/llm_client.LLMClient` | import line 237, chat call line 246 | WIRED | uses SMART_AGENT_BACKEND/MODEL/API_KEY (D-17) |
| `interfaces/web_server.cron_weekly_training_review` | `core/weekly_training_review.run_weekly_review` | lazy import line 462, await line 465 | WIRED | OIDC auth via _verify_cron_request |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `run_training_checkin` | `events` (Training calendar) | `GoogleCalendarManager.list_training_events` (API) | Yes — resolves calendar by name, filters buffer blocks | FLOWING |
| `run_training_checkin` | `garmin_activities` | `fetch_garmin_activities(1)` | Yes — Garmin API | FLOWING |
| `compute_recovery_concern` | `ratio` (ACWR) | `compute_acwr_from_db()` — Postgres query | Yes — reads activities table | FLOWING |
| `morning_briefing._gather_data` | `recovery_concern` | `compute_recovery_concern(garmin_data, today_iso)` | Yes — real ACWR/HRV/sleep inputs | FLOWING |
| `proactive_alerts._compose_alert` | `recovery_concern` | not computed, not in alerts_context | No — key absent from prompt data | DISCONNECTED |
| `weekly_training_review._gather_week_data` | `training_log` | `TrainingLogStore.get_range` | Yes — Firestore reads | FLOWING |
| `weekly_training_review._gather_week_data` | `nutrition_7day` | `MealStore.get_day_aggregate` (7 days) | Yes — Firestore reads | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Result | Status |
|----------|--------|--------|
| tests/test_training_log_store.py (13 tests) | 13 passed in 0.01s | PASS |
| tests/test_recovery_concern.py (21 tests) | 21 passed in 0.04s | PASS |
| tests/test_training_checkin.py (28 tests) | 28 passed in 0.05s | PASS |
| tests/test_pending_prompt_store.py | 29 passed in 0.02s (combined with test_tool_registration_phase20.py) | PASS |
| tests/test_tool_registration_phase20.py | included above | PASS |
| Full suite segfault | Pre-existing grpc/protobuf GC crash on Python 3.13; confirmed at base commit 91e218e, unrelated to Phase 20 | EXCLUDED |

---

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| LOG-01 | TrainingLogStore.log_session with all fields, idempotent | VERIFIED | firestore_db.py lines 730–777 |
| LOG-02 | get_recent(days) + get_by_date(date) never raise | VERIFIED | firestore_db.py lines 779–856 |
| LOG-03 | log_training brain-direct tool | VERIFIED | tools.py SMART_AGENT_DIRECT_TOOLS + handler |
| LOG-04 | get_training_history worker-delegated | VERIFIED | Not in SMART_AGENT_DIRECT_TOOLS, in WORKER_TOOL_SCHEMAS |
| CHECKIN-01 | No separate endpoint; logic folds into proactive_alerts | VERIFIED | proactive_alerts.py lines 98–108 |
| CHECKIN-02 | Silent Garmin sync first | VERIFIED | training_checkin.py _silent_garmin_sync |
| CHECKIN-03 | Prompt only for unlogged past-start workouts; branch logic | VERIFIED | training_checkin.py run_training_checkin |
| CHECKIN-04 | RPE inline keyboard 1–10; notes follow-up | VERIFIED | _rpe_keyboard + attach_note |
| CHECKIN-05 | Fully silent when all covered | VERIFIED | early return when prompts_to_send is empty |
| CHECKIN-06 | 0 21 schedule moot; runs at 21:30 in proactive-alerts | VERIFIED | reconciled per D-09 |
| REVIEW-01 | /cron/weekly-training-review with OIDC auth | VERIFIED | web_server.py lines 438–470 |
| REVIEW-02 | Gathers training_log + activities + biometrics + MealStore 7-day + athletic_goals | VERIFIED | weekly_training_review._gather_week_data 5 sources |
| REVIEW-03 | prompts/weekly_training_review.md: scorecard + narrative + suggestion | VERIFIED | File verified, all required sections present |
| REVIEW-04 | 0 10 * * 0 Asia/Jerusalem | VERIFIED | bootstrap_shifu_crons.sh schedule="0 10 * * 0" |
| RECOVERY-01 | morning_briefing._gather_data computes recovery_concern | VERIFIED | morning_briefing.py lines 236–246 |
| RECOVERY-02 | RECOVERY_THRESHOLDS module-level dict | VERIFIED | training_checkin.py lines 65–75 |
| RECOVERY-03 | Both prompts read recovery_concern and shift tone | PARTIAL — FAILED for evening alert | Prompt extended; morning briefing data path wired; evening alert data path missing |
| CRON-01 | bootstrap_shifu_crons.sh creates only weekly-training-review | VERIFIED | Script creates one job; no training-checkin job |
| CRON-02 | DEPLOYMENT.md Phase Shifu section + inventory table | VERIFIED | §19 row 8, §24 section |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| No debt markers (TBD/FIXME/XXX) found in Phase 20 files | — | — | — | — |

No `TBD`, `FIXME`, or `XXX` markers in any Phase 20 modified files. No stub returns or placeholder implementations detected.

---

### Human Verification Required

None identified by automated verification. The callback_query flow (RPE taps, watch-off branch, skip-reason, notes reply-to) requires a live Telegram session to end-to-end verify, but the code paths are fully wired and covered by unit tests. The weekly review brain composition quality requires human judgment but is not a correctness gate.

---

### Gaps Summary

**One gap blocking complete goal achievement:**

**RECOVERY-03 / D-16 — Evening alert missing recovery_concern data path**

The requirement states both `prompts/morning_briefing.md` AND `prompts/proactive_alert.md` should read `recovery_concern` and shift tone. The decision D-16 explicitly says "Surfaced in BOTH morning briefing and evening proactive-alert, equally."

- Morning briefing: WIRED. `morning_briefing._gather_data` calls `compute_recovery_concern` and sets `data["recovery_concern"]` when triggered.
- Evening proactive alert: NOT WIRED. `proactive_alerts.run_proactive_alerts` builds `alerts_context` with only `target_date`, `weather_alerts`, `overload_alert`, `travel_alerts`. `compute_recovery_concern` is never called. `recovery_concern` never appears in the dict passed to `_compose_alert`. The prompt is correctly extended but the data path is absent.

**Fix required:**
In `core/proactive_alerts.run_proactive_alerts`, after the training check-in block and before building `alerts_context`, add a best-effort call to `compute_recovery_concern`. Today's Garmin data should be fetched (or reused from the training check-in path), and the result inserted into `alerts_context` when non-None. This mirrors exactly how it is done in `morning_briefing._gather_data`.

A test should be added to `tests/test_proactive_alerts.py` verifying the data flows through.

**All other 18 requirements are satisfied.** The phase delivered a complete training accountability loop with working stores, evidence-first check-in, inline keyboard infrastructure, weekly review cron, and the morning briefing half of recovery awareness. Only the evening alert half of RECOVERY-03 is missing.

---

_Verified: 2026-06-01T13:30:00Z_
_Verifier: Claude (gsd-verifier)_

---

## Gap Resolution (2026-06-01T13:45:00Z)

The single gap (**RECOVERY-03 / D-16** — recovery_concern not wired into the evening
proactive-alert) was closed inline during execute-phase, commit `67bd7dc`:

- `core/proactive_alerts.run_proactive_alerts` now computes `compute_recovery_concern`
  best-effort (fetching `fetch_garmin_today` for HRV/sleep parity with the morning path)
  and injects the result into `alerts_context` before `_compose_alert`. The key is omitted
  when `None` (D-13 no-fabrication).
- Scope: data wiring only, matching the locked decision D-16 ("full recovery framing in
  each path") and the verifier's prescribed remediation. The alert **send-trigger gate was
  intentionally not changed** — a recovery concern rides along with an alert that is already
  firing; it does not by itself trigger a standalone evening send. (If standalone
  overreach-triggered evening sends are desired, that is a separate notification-frequency
  decision for a future phase.)
- Tests: `tests/test_proactive_alerts.py` gains 2 cases —
  `test_recovery_concern_injected_into_alert_context` and
  `test_no_recovery_concern_key_when_none`. File passes 6/6.

**Final status: PASSED — 19/19 must-haves verified.**
