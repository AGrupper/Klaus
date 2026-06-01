---
phase: 20-accountability-crons-recovery-briefing
plan: 05
subsystem: cron/recovery-awareness
tags: [recovery, training, acwr, hrv, sleep, morning-briefing, proactive-alert, tdd]

# Dependency graph
requires:
  - plan: 20-04
    provides: "core/training_checkin.py (import target for compute_recovery_concern)"
  - plan: 20-01
    provides: "daily_biometrics Postgres table (sleep_score column for _recent_sleep_scores)"
provides:
  - "core/training_checkin.py: RECOVERY_THRESHOLDS + compute_recovery_concern + _recent_sleep_scores + _classify_intensity"
  - "core/morning_briefing.py: recovery_concern best-effort computation in _gather_data"
  - "prompts/morning_briefing.md: recovery_concern tone-shift section (D-16)"
  - "prompts/proactive_alert.md: recovery_concern framing with 🔴 strong prefix (D-16)"
affects:
  - "core/morning_briefing.py: _gather_data now sets data['recovery_concern'] when triggered"
  - "prompts/morning_briefing.md: brain now reads recovery_concern and shifts tone"
  - "prompts/proactive_alert.md: evening alert now includes recovery note when triggered"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level import of compute_acwr_from_db from garmin_tool (for test patchability at core.training_checkin.compute_acwr_from_db)"
    - "intensity=none sentinel for rest days (empty events list → no concern, not 'unknown → moderate')"
    - "Best-effort Pattern-C block in _gather_data: lazy import + try/except + silent omit on no-concern"
    - "Postgres sleep read via psycopg2 lazy import in _recent_sleep_scores (mirrors compute_acwr_from_db never-raises)"

key-files:
  created:
    - "tests/test_recovery_concern.py"
  modified:
    - "core/training_checkin.py"
    - "core/morning_briefing.py"
    - "prompts/morning_briefing.md"
    - "prompts/proactive_alert.md"

key-decisions:
  - "intensity='none' for empty events list (rest day → no concern), not 'moderate'; avoids ACWR-triggered false positives on rest days"
  - "Module-level import of compute_acwr_from_db (not lazy inside function) enables test patching at core.training_checkin.compute_acwr_from_db"
  - "RECOVERY_THRESHOLDS moved to module level (not inside compute_recovery_concern) so callers and tests can inspect the thresholds dict directly"
  - "prompts/proactive_alert.md: 🔴 prefix only in the alert (not in morning_briefing prose) per UI-SPEC line 238"

# Metrics
duration: ~5 min
completed: 2026-06-01
---

# Phase 20 Plan 05: Recovery Concern — RECOVERY_THRESHOLDS + compute_recovery_concern + Prompt Tone-Shift Summary

**RECOVERY_THRESHOLDS v0 heuristic dict + compute_recovery_concern (D-12 mild/strong severity, D-14 keyword intensity, D-15 consecutive-sleep via Postgres, D-13 no-fabrication) wired into morning_briefing._gather_data and both prompts shifted to metric-anchored suggesting tone**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-01T11:05:10Z
- **Completed:** 2026-06-01T11:10:38Z
- **Tasks:** 3
- **Files modified/created:** 5

## Accomplishments

- `RECOVERY_THRESHOLDS` v0 heuristic dict added to `core/training_checkin.py` (RECOVERY-02): 7 keys — `acwr_mild` (1.5), `acwr_strong` (1.8), `sleep_low` (70), `consecutive_low_sleep_nights` (2), `intensity_keywords_high`, `intensity_keywords_moderate`, `hrv_flag_values` — with v0 docstring noting to tune after ~2 weeks
- `_recent_sleep_scores(today_iso, n)` added: lazy psycopg2 import, reads `daily_biometrics` table (Open Q3 — no second Garmin call), never-raises, mirrors compute_acwr_from_db sentinel pattern
- `_classify_intensity(events)` added: D-14 keyword classification; empty events list returns `"none"` (rest day, no concern triggered); unknown title → `"moderate"`
- `compute_recovery_concern(garmin_data, today_iso)` added (RECOVERY-01): D-12 severity logic (strong/mild/None), D-15 consecutive sleep via Postgres, D-13 no prescriptive numeric targets in returned dict; module-level import of `compute_acwr_from_db` for test patchability
- `core/morning_briefing.py` `_gather_data`: best-effort Pattern-C block added after Garmin+Postgres writeback, before TickTick tasks; sets `data["recovery_concern"]` only when truthy (NUTR-07 silent-omit pattern); no else branch / no "all clear" placeholder (D-13)
- `prompts/morning_briefing.md`: Recovery Concern section added — metric-anchored, suggesting tone, mild/strong differentiation, D-13 no-invented-numbers guardrail, absent → no framing
- `prompts/proactive_alert.md`: matching Recovery Concern section with equal weight (D-16), 🔴 prefix for strong severity (UI-SPEC line 238), same D-13 guardrail, absent → no framing

## Task Commits

1. **Task 1 RED: failing tests** — `3decaba` (test)
2. **Task 1 GREEN: RECOVERY_THRESHOLDS + compute_recovery_concern** — `ac99f03` (feat)
3. **Task 2: wire recovery_concern into morning_briefing._gather_data** — `fd5f8d6` (feat)
4. **Task 3: extend both prompts** — `1eeda21` (feat)

## Files Created/Modified

- `tests/test_recovery_concern.py` — 21 tests covering thresholds shape, None on no-trigger, mild/strong crossings, D-15 consecutive sleep, D-13 no-prescriptive-keys
- `core/training_checkin.py` — RECOVERY_THRESHOLDS, _recent_sleep_scores, _classify_intensity, compute_recovery_concern; module-level compute_acwr_from_db import
- `core/morning_briefing.py` — recovery_concern best-effort block in _gather_data
- `prompts/morning_briefing.md` — Recovery Concern section (D-16 equal weight, D-13 guardrail)
- `prompts/proactive_alert.md` — Recovery Concern section (D-16 equal weight, 🔴 strong prefix, D-13 guardrail)

## Decisions Made

- `intensity="none"` for empty events list (rest day → no concern), not "moderate"; prevents ACWR-triggered false positives on days with no planned training
- Module-level import of `compute_acwr_from_db` enables `patch("core.training_checkin.compute_acwr_from_db")` in tests without having to use `create=True`
- 🔴 emoji prefix only in `proactive_alert.md` (not in `morning_briefing.md` prose) per UI-SPEC line 238 specification

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Empty events list classified as "moderate" caused false-positive mild concern on rest days**
- **Found during:** Task 1 (GREEN — test_none_when_no_events failed after initial implementation)
- **Issue:** _classify_intensity returned "moderate" for empty events list (D-14 "unknown → moderate"). This triggered mild concern whenever ACWR >= 1.5, even on rest days with no Training events.
- **Fix:** Changed empty-events return value to "none" (a new sentinel distinct from "moderate") and added `if intensity == "none": return None` early exit in compute_recovery_concern. D-14 "unknown → moderate" still applies to *events with unrecognized titles*, not to an *empty events list*.
- **Files modified:** `core/training_checkin.py`
- **Commit:** `ac99f03`

## Known Stubs

None — compute_recovery_concern makes real Garmin/Postgres calls in production; tests patch at module boundary. Prompts produce real LLM-composed tone shifts.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-20-12 mitigated | prompts/morning_briefing.md | D-13 guardrail: "Never invent a specific weight, HR zone, HR cap, pace target, or rep count" |
| T-20-12 mitigated | prompts/proactive_alert.md | Same D-13 guardrail: "Never invent a specific weight, HR zone, or pace" |

## TDD Gate Compliance

- RED commit: `3decaba` — `test(20-05): add failing recovery_concern tests`
- GREEN commit: `ac99f03` — `feat(20-05): RECOVERY_THRESHOLDS + compute_recovery_concern`
- REFACTOR: not needed (clean implementation on first pass)

## Self-Check: PASSED

Files verified:
- `tests/test_recovery_concern.py` — FOUND (21 tests, all green)
- `core/training_checkin.py` — FOUND (RECOVERY_THRESHOLDS at line 65, compute_recovery_concern at line 136, _recent_sleep_scores at line 78, daily_biometrics query)
- `core/morning_briefing.py` — FOUND (compute_recovery_concern import + call, data["recovery_concern"] conditional set)
- `prompts/morning_briefing.md` — FOUND (recovery_concern section, Never invent guardrail, absent → no framing)
- `prompts/proactive_alert.md` — FOUND (recovery_concern section, 🔴 strong prefix, absent → no framing)

Commits verified:
- `3decaba` — test(20-05): add failing recovery_concern tests
- `ac99f03` — feat(20-05): RECOVERY_THRESHOLDS + compute_recovery_concern
- `fd5f8d6` — feat(20-05): wire recovery_concern into morning_briefing._gather_data
- `1eeda21` — feat(20-05): extend morning_briefing + proactive_alert prompts with recovery_concern

---
*Phase: 20-accountability-crons-recovery-briefing*
*Completed: 2026-06-01*
