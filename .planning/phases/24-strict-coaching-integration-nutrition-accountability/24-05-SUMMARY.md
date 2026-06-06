---
phase: 24-strict-coaching-integration-nutrition-accountability
plan: "05"
subsystem: morning-briefing + weekly-review + prompts
tags: [coaching, dedup, tdd, prompts, morning-briefing, weekly-review, COACH-05, PROG-01, PROG-03, PROG-04]
dependency_graph:
  requires:
    - CoachingTopicStore (24-01 — has_topic/add_topic/topics_today)
    - derive_session_quality + TrainingLogStore.log_session quality param (24-01)
  provides:
    - cross-cron dedup gate in morning_briefing (coaching_topics_today + post-send write)
    - prior-day recap gather in morning_briefing (coaching_topics_yesterday / D-08)
    - cross-cron dedup gate in weekly_review (coaching_topics_today + post-send write)
    - {coaching_guide} injection in weekly_review._compose_review
    - D-18 integrated block prompt instruction (morning_briefing.md)
    - D-08 prior-day recap prompt instruction (morning_briefing.md)
    - D-02 dedup gate prompt instruction (morning_briefing.md)
    - per-facet within-block status prompt instruction (weekly_training_review.md)
    - session quality trend prompt instruction (weekly_training_review.md)
    - Phase 25 fence (no dated projection) in weekly_training_review.md
  affects:
    - core/morning_briefing.py
    - core/weekly_training_review.py
    - prompts/morning_briefing.md
    - prompts/weekly_training_review.md
tech_stack:
  added: []
  patterns:
    - Best-effort gather block with silent-omit (fail-open to [])
    - Write-after-send discipline mirroring OutreachLogStore.append (Phase 18 D-10)
    - {coaching_guide} injection via _get_orchestrator()._coaching_guide_content
    - TDD RED/GREEN per task (4 commits total)
key_files:
  created: []
  modified:
    - core/morning_briefing.py
    - core/weekly_training_review.py
    - prompts/morning_briefing.md
    - prompts/weekly_training_review.md
    - tests/test_morning_briefing.py
    - tests/test_weekly_training_review.py
decisions:
  - coaching_topics_today and coaching_topics_yesterday gathered in _gather_data (morning_briefing)
    using CoachingTopicStore.topics_today(today_iso) and topics_today(yesterday_iso)
  - post-send topic write in both crons uses coaching_topics_included key from gathered data
    (write-after-send: T-24-17 mitigation)
  - weekly_training_review._gather_week_data section 7 gathers coaching_topics_today only;
    quality already present on training_log entries — no new gather code needed (Finding 10)
  - _compose_review coaching_guide injection: mirrors morning_briefing._compose_briefing exactly
  - prompts use embedded dedup instructions (coaching_topics_today / coaching_topics_yesterday)
    so the brain can self-apply the gate without code-level filtering
  - Phase 25 fence in weekly_training_review.md uses "ABSOLUTELY FORBIDDEN" framing to be
    unambiguous for the LLM
metrics:
  duration: "~11 minutes"
  completed: "2026-06-06"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 6
  files_created: 0
  tests_added: 16
  tests_passing: 53
---

# Phase 24 Plan 05: Morning Briefing + Weekly Review Coaching Integration Summary

## One-liner

Cross-cron dedup gate (COACH-05) and coaching guide injection wired into morning briefing and Sunday weekly review: gather today+yesterday topic keys, write only after send, D-18 integrated block + D-08 prior-day recap in morning briefing prompt, per-facet within-block status + session quality trend + Phase 25 fence in weekly review prompt.

## What Was Built

### Task 1: Morning briefing — dedup + prior-day recap gather + post-send write + D-18 prompt

**`core/morning_briefing.py` `_gather_data` — new section (Phase 24 COACH-05):**
- Added a best-effort try/except block after the Block gather (before `return data`)
- Constructs `CoachingTopicStore` via env vars (`GCP_PROJECT_ID` + `FIRESTORE_DATABASE`)
- Computes `yesterday_iso = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()`
- Sets `data["coaching_topics_today"] = _cts.topics_today(today_iso)`
- Sets `data["coaching_topics_yesterday"] = _cts.topics_today(yesterday_iso)`
- Both fail-open to `[]` on any exception (T-24-18 mitigated — cron never crashes on topic fetch)

**`core/morning_briefing.py` `run_morning_briefing` — post-send write (Phase 24 COACH-05):**
- After `send_and_inject` succeeds, writes any `today_data.get("coaching_topics_included") or []`
  topics via `CoachingTopicStore.add_topic(today_iso, topic)` in a best-effort wrapped loop
- Write-after-send discipline: T-24-17 mitigated — no orphan topic keys on send failure
- Non-fatal: a write failure logs at WARNING and continues (dedup just won't fire for that topic)

**`prompts/morning_briefing.md` — three new sections added:**
- **D-18: Integrated Training + Recovery + Fueling Block** — instructs the brain to weave named
  session + recovery state + fueling reminder into ONE integrated block (not three labeled lines);
  explains the "weave" pattern with a list of the three elements; replaces separate Recovery Concern
  note when all three are present
- **D-08: Prior-Day Unresolved Miss (Prior-Day Recap)** — instructs the brain to use
  `coaching_topics_yesterday` to surface one low-priority contextual line for unresolved prior-day
  misses; rules: at most one line, never repeat as if new, omit if not relevant
- **D-02: Cross-Cron Dedup Gate** — instructs the brain not to repeat topics in
  `coaching_topics_today` unless materially worsened (one escalation only)

**Tests added to `tests/test_morning_briefing.py` (8 tests):**
- `test_gather_data_includes_coaching_topics_today_and_yesterday` — mocks CoachingTopicStore with two side_effect returns; asserts both keys present and correct
- `test_gather_data_coaching_topics_fail_open` — CoachingTopicStore constructor raises; asserts both keys set to []
- `test_gather_data_coaching_topics_today_empty_when_no_topics` — topics_today returns []; asserts both keys []
- `test_run_morning_briefing_writes_topics_after_send` — asserts add_topic called 2x after successful send
- `test_run_morning_briefing_no_topic_write_when_send_fails` — send raises; asserts add_topic never called
- `test_morning_briefing_prompt_integrated_block_instruction` — asserts "weave" or "integrated" in prompt
- `test_morning_briefing_prompt_prior_day_recap_instruction` — asserts "prior" or "yesterday" in prompt
- `test_morning_briefing_prompt_dedup_instruction` — asserts "coaching_topics_today" or "do not repeat" in prompt

### Task 2: Weekly review — per-facet + quality trend + dedup + {coaching_guide}; prompt framing

**`core/weekly_training_review.py` `_gather_week_data` — new section 7 (Phase 24 COACH-05):**
- Added best-effort try/except block at the end of `_gather_week_data`
- Constructs `CoachingTopicStore` and sets `data["coaching_topics_today"]`
- Fail-open to [] on error (T-24-18 mitigated)
- NOTE: quality NOT gathered here — already present on training_log entries from Plan 01 (Finding 10)

**`core/weekly_training_review.py` `_compose_review` — {coaching_guide} injection:**
- Added `_get_orchestrator()._coaching_guide_content` fetch before prompt read (fail-open to "")
- Prompt substitution: `.replace("{coaching_guide}", coaching_guide_content).replace("{today_date}", today_iso)`
- Mirrors `morning_briefing._compose_briefing` (lines 317–328) exactly

**`core/weekly_training_review.py` `run_weekly_review` — post-send write:**
- After `send_and_inject` succeeds, writes `week_data.get("coaching_topics_included") or []`
  topics via `CoachingTopicStore.add_topic(today_iso, topic)` in a best-effort wrapped loop
- Write-after-send discipline: T-24-17 mitigated

**`prompts/weekly_training_review.md` — rewritten with Phase 24 additions:**
- Added `{coaching_guide}` placeholder (now injected by `_compose_review`)
- Updated training_log description to include the `quality` field description
- Added `coaching_topics_today` to the data field list with D-12 dedup gate note
- **PHASE 25 FENCE (ABSOLUTELY FORBIDDEN)**: explicit prohibition on dated projection, "on track for",
  "weeks behind" — placed immediately after the training block framing paragraph
- **Per-Facet Within-Block Status (PROG-01 / D-17)**: new section instructing strength top-set trend,
  threshold volume vs target, ACWR — all block-relative ("Week N of 16"), no projection
- **Session Quality Trend (PROG-04 / D-17)**: new section instructing quality count distribution
  (strong/neutral/grind) from `training_log[].quality`, null-safe, integrated into narrative
- **D-12 dedup gate section**: skip `structural-critique:*` topics in `coaching_topics_today`

**Tests added to `tests/test_weekly_training_review.py` (8 tests):**
- `test_gather_week_includes_coaching_topics_today` — mocks CoachingTopicStore; asserts key present
- `test_gather_week_coaching_topics_fail_open` — CoachingTopicStore raises; asserts key = []
- `test_compose_review_injects_coaching_guide` — captures LLM system prompt; asserts guide content present
- `test_run_weekly_review_writes_topics_after_send` — asserts add_topic called after send
- `test_run_weekly_review_no_topic_write_when_send_fails` — send raises; asserts no add_topic
- `test_weekly_review_prompt_has_per_facet_instruction` — asserts "facet" or "ACWR" in prompt
- `test_weekly_review_prompt_has_quality_trend_instruction` — asserts "quality" / "strong" / "grind" in prompt
- `test_weekly_review_prompt_forbids_dated_projection` — asserts "weeks behind" / "on track for" only inside prohibition clause

## Test Summary

| Test file | Tests before | Tests added | Total | All pass |
|-----------|-------------|-------------|-------|----------|
| tests/test_morning_briefing.py | 27 | 8 | 35 | Yes (+ 3 skipped) |
| tests/test_weekly_training_review.py | 10 | 8 | 18 | Yes |

**Total passing in this plan's scope: 53 (+ 3 skipped by design)**

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 4a19d00 | test | RED tests for morning briefing COACH-05 dedup + D-18 integrated block |
| cee4ad9 | feat | morning briefing COACH-05 dedup + D-18 integrated block + D-08 prior-day recap |
| 9b11ace | test | RED tests for weekly review COACH-05 dedup + coaching_guide + PROG-01/04 |
| 2d09d67 | feat | weekly review COACH-05 dedup + coaching_guide + PROG-01/04 per-facet + quality |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test env vars missing in weekly review test**
- **Found during:** Task 2 GREEN phase
- **Issue:** `test_compose_review_injects_coaching_guide` and the post-send write tests raised `KeyError` for `SMART_AGENT_BACKEND` and `GCP_PROJECT_ID` because the weekly review test fixture didn't set env vars needed by the production code path
- **Fix:** Added `monkeypatch.setenv(...)` calls in the affected test functions to supply the required env vars
- **Files modified:** `tests/test_weekly_training_review.py`
- **Commit:** 2d09d67 (folded into GREEN commit)

## Known Stubs

None. All changes are fully wired:
- `CoachingTopicStore.topics_today()` reads real Firestore (mocked in tests)
- `CoachingTopicStore.add_topic()` writes real Firestore after send
- `{coaching_guide}` injection reads real `_coaching_guide_content` from the orchestrator singleton
- Prompt instructions reference real data fields that are present in the gathered JSON

## Threat Surface Scan

No new network endpoints introduced. All changes are within existing cron compose paths.

| Threat ID | Status |
|-----------|--------|
| T-24-17 | Mitigated — add_topic only after send_and_inject succeeds in both crons; tests verify no write on failure |
| T-24-18 | Mitigated — all new CoachingTopicStore reads and coaching_guide fetches are best-effort wrapped |
| T-24-19 | Mitigated — Phase 25 fence added to weekly_training_review.md as "ABSOLUTELY FORBIDDEN" |
| T-24-20 | N/A — no quality/biometric data logged; topic keys only |
| T-24-21 | Mitigated — D-08 prior-day recap instruction ensures an unresolved yesterday topic surfaces as one low-priority line |

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| core/morning_briefing.py | FOUND |
| core/weekly_training_review.py | FOUND |
| prompts/morning_briefing.md | FOUND |
| prompts/weekly_training_review.md | FOUND |
| tests/test_morning_briefing.py | FOUND |
| tests/test_weekly_training_review.py | FOUND |
| Commit 4a19d00 (RED morning briefing tests) | FOUND |
| Commit cee4ad9 (feat morning briefing) | FOUND |
| Commit 9b11ace (RED weekly review tests) | FOUND |
| Commit 2d09d67 (feat weekly review) | FOUND |
| pytest tests/test_morning_briefing.py tests/test_weekly_training_review.py | 53 passed, 3 skipped |
| grep coaching_topics_today core/morning_briefing.py | FOUND |
| grep coaching_guide core/weekly_training_review.py | FOUND |
| grep -ni 'weeks behind\|on track for' prompts/weekly_training_review.md | Only in prohibition clause |
