---
phase: 24-strict-coaching-integration-nutrition-accountability
verified: 2026-06-06T14:45:00Z
status: resolved
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  date: 2026-06-06T15:05:00Z
  by: orchestrator-inline-fix
  commit: e08d6aa
  summary: "COACH-05 dedup write-back gap closed. Conservative-writer producers added (user decision): morning_briefing._gather_data sets coaching_topics_included = carried prior-day misses (same 21:30 namespace, closes the real cross-cron overlap); weekly_training_review._derive_structural_topics deterministically emits structural-critique:* keys from session quality, wired into _gather_week_data. Production-path tests added (prior tests only asserted write-after-send on a mock-injected key). Full suite 1023 passed, 3 skipped."
gaps:
  - truth: "The same coaching topic (e.g., protein miss, skipped session) does not appear in both the morning briefing and the evening check-in on the same day"
    status: resolved
    reason: "The 21:30 cron correctly reads + writes its topics to CoachingTopicStore. Morning briefing and weekly review read existing topics (so they won't repeat yesterday's 21:30 topics), but they NEVER write the topics they surface. The coaching_topics_included key that the post-send write loop reads from today_data/week_data is never populated by _gather_data or _gather_week_data in production code — only injected in tests via mocks. This means morning-briefing-surfaced topics (e.g., 'skipped-session:threshold-run') are never written to the store, so the 21:30 cron that fires later the same day has no way to know those topics were already raised."
    artifacts:
      - path: "core/morning_briefing.py"
        issue: "_gather_data never sets coaching_topics_included; post-send write reads it (line 148) but it is always [] in production"
      - path: "core/weekly_training_review.py"
        issue: "_gather_week_data never sets coaching_topics_included; post-send write reads it (line 351) but it is always [] in production"
    missing:
      - "In morning_briefing._gather_data or _compose_briefing, determine which topics are being raised and populate data['coaching_topics_included'] with those topic keys before run_morning_briefing reads it for the post-send write"
      - "Same pattern for weekly_training_review: populate week_data['coaching_topics_included'] before the post-send write loop"
      - "Alternative: mirror the proactive_alerts pattern — use a local _new_topics list derived before compose (from _collect_detected_topics equivalent), and write those directly after send, bypassing the coaching_topics_included key entirely"
human_verification:
  - test: "Trigger a skipped session and observe the 21:30 cron output"
    expected: "Names the specific session type, states the volume deficit in concrete units (km or sets), gives a directional blueprint-anchored consequence, no softening language, no dated projection"
    why_human: "LLM prompt output — register and specificity are judgment-based; unit tests only assert structural prompt markers exist"
  - test: "Trigger a low-HRV vs. heavy-session conflict and observe the 21:30 cron output"
    expected: "Cites the exact HRV number and baseline percentage, gives exactly ONE ranked recommendation, ends with 'your call, Sir', never presents a menu of options"
    why_human: "LLM compose output — the 'exactly one rec' constraint and 'never a menu' constraint require live observation"
  - test: "Observe morning briefing output on a training day with a recovery concern and at least one fueling reminder"
    expected: "Today's session name + recovery state + fueling reminder appear as a single integrated paragraph, not three labeled lines"
    why_human: "D-18 'weave' instruction is a compositional LLM behavior — unit test only asserts prompt contains 'weave' or 'integrated'"
  - test: "Observe Sunday weekly review output with block data and at least one logged session with quality"
    expected: "Includes per-facet within-block status (strength top-set, threshold volume, ACWR), session quality distribution, no 'on track for October' or 'N weeks behind' framing"
    why_human: "Per-facet reporting and projection prohibition are LLM behaviors; unit tests only assert prompt structure"
---

# Phase 24: Strict Coaching Integration + Nutrition Accountability — Verification Report

**Phase Goal:** Expert, specific coaching is folded into every existing coaching touchpoint (morning briefing, 21:30 training check-in + evening alert, Sunday weekly review, and chat); coaching is proactive and reactive; a cross-cron dedup gate ensures the same topic fires at most once per day across all crons; nutrition macro adherence and fueling-slot accountability and supplement timing are part of the 21:30 check-in; session quality rating is captured at log time
**Verified:** 2026-06-06T14:45:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A skipped session triggers pushback naming the session, volume deficit in concrete units, and consequence for goal timeline — no softening | VERIFIED | `prompts/proactive_alert.md` lines 84–99: COACH-03 section enforces named session, concrete units, directional consequence, "No softening, no hedging" (line 92). Reactive counterpart in `prompts/smart_agent.md` lines 172–188. |
| 2 | A recovery-vs-plan conflict produces biometric fact + plan conflict + exactly ONE ranked recommendation + "your call, Sir" | VERIFIED | `prompts/proactive_alert.md` lines 102–116: COACH-04 section enforces literal number citation, exactly ONE ranked rec, "your call, Sir", "Never present a menu". Reactive in `smart_agent.md` lines 184–188. |
| 3 | The same coaching topic does not appear in both morning briefing and 21:30 check-in on the same day | PARTIAL — BLOCKER | `CoachingTopicStore` gate is correctly wired in `proactive_alerts.py` (read + write). Morning briefing and weekly review read topics but NEVER write them: `coaching_topics_included` is never set in `_gather_data()` or `_gather_week_data()` — only in test mocks. Post-send write path in both crons is dead code in production. |
| 4 | The 21:30 check-in flags structural fueling-slot misses using MealStore timestamps mapped to blueprint slots | VERIFIED | `_detect_slot_misses` (line 337 in `proactive_alerts.py`) correctly evaluates slots #2/#5/#6 only when anchors are resolved; Pitfall 2 guard (`am_anchor is not None`) prevents rest-day false positives. Supplement riders in `SLOT_SUPPLEMENTS` dict and wired into `prompts/proactive_alert.md` lines 129–131. `_gather_nutrition_data` wired into `run_proactive_alerts` at line 797. 62 tests pass (excluding 2 pre-existing Python 3.14 failures). |
| 5 | The morning briefing frames today's named session, recovery state, and fueling reminder as one integrated block | VERIFIED | `prompts/morning_briefing.md` lines 174–188: D-18 section instructs "weave the following into ONE integrated block — NOT three separate labeled sections". Morning briefing gathers `coaching_topics_today` and `coaching_topics_yesterday`. Coaching guide injected via `_compose_briefing`. 8 Phase 24 tests green on Python 3.13. |
| 6 | The Sunday weekly review reports per-facet progress (strength top-set trend, threshold volume vs target, ACWR) with block-relative framing and session quality trends | VERIFIED | `prompts/weekly_training_review.md` lines 43–79: Per-Facet Within-Block Status section and Session Quality Trend section present. Phase 25 fence ("ABSOLUTELY FORBIDDEN") at line 37 prevents dated projections. `_compose_review` injects `{coaching_guide}`. 18 weekly review tests pass on Python 3.13. |

**Score: 5/6 truths verified**

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `memory/firestore_db.py` | `CoachingTopicStore` class with per-day dedup gate | VERIFIED | `class CoachingTopicStore` at line 1413; `_COLLECTION = "coaching_topics"` (lowercase); `has_topic` fail-open, `add_topic` ArrayUnion string-list, `topics_today` fail-open. |
| `core/training_checkin.py` | `derive_session_quality` pure function wired into both log paths | VERIFIED | `def derive_session_quality` at line 443; `feel is not None` guard (Pitfall 4); wired in `_silent_garmin_sync` (line 548) and `handle_rpe_callback` (line 783). |
| `core/proactive_alerts.py` | `MACRO_THRESHOLDS`, `SLOT_SUPPLEMENTS`, `_macro_gap_check`, `_resolve_anchor_times`, `_map_meals_to_slots`, `_detect_slot_misses`, `_gather_nutrition_data`, `_collect_detected_topics` | VERIFIED | All 8 symbols present: lines 61, 82, 116, 176, 256, 337, 503, 616. Dedup gate wiring at lines 804–843. |
| `core/morning_briefing.py` | `coaching_topics_today` + `coaching_topics_yesterday` gather + post-send write | PARTIAL | Gather is VERIFIED (lines 323–336). Post-send write is HOLLOW — reads `coaching_topics_included` (line 148) which is never populated in production. |
| `core/weekly_training_review.py` | `coaching_topics_today` gather + `{coaching_guide}` injection + post-send write | PARTIAL | Gather verified (lines 225–240). `{coaching_guide}` injection verified (line 267–274). Post-send write is HOLLOW — reads `coaching_topics_included` (line 351) which is never populated. |
| `prompts/proactive_alert.md` | COACH-03/04 strict pushback, NUTR-01/02/03 nutrition, COACH-05 dedup sections | VERIFIED | Four sections present: lines 84–116 (COACH-03/04), 119–137 (NUTR-01/02/03), 141–151 (COACH-05). |
| `prompts/morning_briefing.md` | D-18 integrated block + D-08 prior-day recap + D-02 dedup gate instructions | VERIFIED | Lines 174–221: all three instruction sections present. |
| `prompts/weekly_training_review.md` | Per-facet within-block status + session quality trend + Phase 25 fence | VERIFIED | Lines 37–79: all three sections present, ABSOLUTELY FORBIDDEN framing enforced. |
| `prompts/smart_agent.md` | Reactive COACH-03/04 format + COACH-05 reactive-never-suppressed rule | VERIFIED | Lines 172–198: strict pushback format and reactive dedup rule present. |
| `core/main.py` | `MAX_TOOL_ITERATIONS = 12` + `last_response_text` double-send fix | VERIFIED | Line 47: `MAX_TOOL_ITERATIONS = 12`; `last_response_text` tracker at lines 549, 591, 685, 689, 691. |
| `core/tools.py` | `_handle_read_coaching_guide` WR-02 fuzzy hardening with candidate count | VERIFIED | Lines 1536/1542/1543: `len(word) < 4` skip guard + `candidate_anchors = anchor_re.findall(content)` + `len(candidate_anchors) != 1` unambiguous-only gate. |
| `tests/test_coaching_topic_store.py` | 12 COACH-05 gate unit tests | VERIFIED | File exists; 12 tests pass. |
| `memory/firestore_db.py` `TrainingLogStore.log_session` | `quality: str | None = None` parameter + payload write | VERIFIED | Line 808: parameter present; line 842: `"quality": quality` in payload dict. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `core/training_checkin.py::_silent_garmin_sync` | `TrainingLogStore.log_session(quality=...)` | `derive_session_quality(rpe, feel)` | WIRED | `grep -n 'derive_session_quality' core/training_checkin.py` returns 3+ hits including def + 2 call sites. `feel is not None` guard confirmed. |
| `CoachingTopicStore.add_topic` | `firestore coaching_topics/{date}.topics` | `ArrayUnion([topic_key])` plain string | WIRED | `firestore.ArrayUnion([topic_key])` at line 1492. `_COLLECTION = "coaching_topics"` at line 1432. String-only (no dict). |
| `_detect_slot_misses` | MealStore meal timestamps + AM/PM anchors | slot window membership check | WIRED | Pure function accepts already-fetched meals as args; `am_anchor is not None` guard at line 380; `_gather_nutrition_data` passes `meals` from `MealStore.get_day()`. |
| `_macro_gap_check` | `MACRO_THRESHOLDS` | protein/carb threshold comparison | WIRED | `MACRO_THRESHOLDS["protein"]["floor_g"]` at line 139; `MACRO_THRESHOLDS["carbs"]` at line 154. |
| `run_proactive_alerts` | `CoachingTopicStore.add_topic` | `_new_topics` list after `send_and_inject` | WIRED | Lines 835–843: write only after send succeeds; `_cts = None` guard if gate fails. |
| `morning_briefing.run_morning_briefing` | `CoachingTopicStore.add_topic` | `coaching_topics_included` from `today_data` | NOT_WIRED | `coaching_topics_included` never set in `_gather_data()`. Key always missing from `today_data` in production — `_topics_included = today_data.get("coaching_topics_included") or []` always resolves to `[]`. |
| `weekly_training_review.run_weekly_review` | `CoachingTopicStore.add_topic` | `coaching_topics_included` from `week_data` | NOT_WIRED | Same structural gap as morning briefing — `coaching_topics_included` never set in `_gather_week_data()`. |
| `weekly_training_review._compose_review` | `_get_orchestrator()._coaching_guide_content` | `{coaching_guide}` injection | WIRED | Lines 267–274: `_get_orchestrator()._coaching_guide_content` fetched; `.replace("{coaching_guide}", ...)` applied. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `core/proactive_alerts.py` nutrition block | `alerts_context["nutrition"]` | `_gather_nutrition_data` → `MealStore.get_day()` + `UserProfileStore` + pure helpers | Yes — live Firestore reads with best-effort fallback | FLOWING |
| `core/proactive_alerts.py` dedup gate | `coaching_topics_new`, `coaching_topics_already_raised` | `CoachingTopicStore.topics_today()` + `_collect_detected_topics()` | Yes — live Firestore read | FLOWING |
| `core/morning_briefing.py` topic gather | `coaching_topics_today`, `coaching_topics_yesterday` | `CoachingTopicStore.topics_today()` | Yes — live Firestore reads | FLOWING |
| `core/morning_briefing.py` post-send write | topics written to store | `today_data["coaching_topics_included"]` | No — key never populated in production | DISCONNECTED |
| `core/weekly_training_review.py` post-send write | topics written to store | `week_data["coaching_topics_included"]` | No — key never populated in production | DISCONNECTED |
| `core/training_checkin.py::_silent_garmin_sync` | `quality` field | `derive_session_quality(rpe=perceived_exertion, feel=_feel)` → `log_session(quality=...)` | Yes — Garmin fields + RPE signal | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `CoachingTopicStore` exists and has correct collection name | `grep -n 'class CoachingTopicStore\|_COLLECTION' memory/firestore_db.py` | Line 1413 + `"coaching_topics"` | PASS |
| `derive_session_quality` uses `is not None` guard for feel | `grep -n 'feel is not None' core/training_checkin.py` | Line 470 confirmed | PASS |
| `MAX_TOOL_ITERATIONS` raised to 12 | `grep -n 'MAX_TOOL_ITERATIONS = 12' core/main.py` | Line 47 confirmed | PASS |
| WR-02 fuzzy hardening: candidate count guard | `grep -n 'candidate_anchors\|len(candidate_anchors)' core/tools.py` | Lines 1542–1543 confirmed | PASS |
| `coaching_topics_included` populated in production code | `grep -rn "coaching_topics_included" core/` | Only 2 read sites, zero write sites | FAIL |
| Full test suite passes on Python 3.13 venv | `.venv/bin/python -m pytest -q --tb=no` | 1019 passed, 3 skipped | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| COACH-03 | 24-04 | Strict skip/off-plan pushback with named session + deficit + consequence | SATISFIED | `prompts/proactive_alert.md` COACH-03 section; `prompts/smart_agent.md` reactive format. Prompt structural assertions in 10 test cases. |
| COACH-04 | 24-04 | Recovery-vs-plan: biometric fact + ONE ranked rec + "your call, Sir" | SATISFIED | `prompts/proactive_alert.md` COACH-04 section enforces single-rec and "your call, Sir". |
| COACH-05 | 24-01, 24-04, 24-05 | Cross-cron dedup gate fires each topic at most once per day | PARTIAL | Gate implemented in `CoachingTopicStore`. 21:30 cron correctly reads+writes. Morning briefing and weekly review READ only — their topics are never written to the store. Topic raised in morning briefing CAN be re-raised by 21:30 cron same day. |
| NUTR-01 | 24-02, 24-04 | Macro adherence flagging on meaningful-gap threshold only | SATISFIED | `_macro_gap_check` with `MACRO_THRESHOLDS` (protein floor 120g, carb day-type floors). No micro-optimization per D-09. Prompt section enforces structural-only critique. |
| NUTR-02 | 24-02, 24-04 | Fueling-slot structural-miss detection from MealStore timestamps | SATISFIED | `_detect_slot_misses` with anchor-based windows, Pitfall 2 guard. `_gather_nutrition_data` wired into 21:30 cron. |
| NUTR-03 | 24-02, 24-04 | Supplement-timing gaps inferred via carrier fueling slot | SATISFIED | `SLOT_SUPPLEMENTS` dict present; prompt riders wired (D3+K2/Omega-3 on slot #2, Creatine on #5, Mg/Zn/Cu standalone on #6). |
| PROG-01 | 24-05 | Sunday weekly review reports per-facet within-block status (strength, threshold, ACWR) | SATISFIED | `prompts/weekly_training_review.md` Per-Facet Within-Block Status section (lines 43–63); block-relative framing enforced. |
| PROG-03 | 24-05 | Morning briefing frames session + recovery + fueling as one integrated block | SATISFIED | `prompts/morning_briefing.md` D-18 instruction at lines 174–188; one-paragraph weave required. |
| PROG-04 | 24-01, 24-05 | Session quality (strong/neutral/grind) captured at log time from existing signals | SATISFIED | `derive_session_quality` pure function; wired in both Garmin-sync and Telegram-tap log paths; `log_session` persists via merge=True; quality trend instruction in weekly review prompt. |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `core/morning_briefing.py` | 148 | `today_data.get("coaching_topics_included") or []` — key never set in production | BLOCKER | Post-send dedup write for morning briefing is dead code; morning briefing topics are never registered in CoachingTopicStore, so the 21:30 cron on the same day may repeat them |
| `core/weekly_training_review.py` | 351 | `week_data.get("coaching_topics_included") or []` — key never set in production | BLOCKER | Same structural gap — weekly review topics never written to store |

No TBD/FIXME/XXX debt markers found in any Phase 24 modified file.

---

### Human Verification Required

#### 1. Strict Skip Pushback Tone

**Test:** Send a skipped session scenario to the 21:30 cron (or reproduce via a coaching chat query about a skipped threshold run). Observe the output.
**Expected:** Output names the specific session type (e.g., "threshold run"), states the volume deficit in concrete measured units (e.g., "~12km off your Week-3 aerobic target"), gives a directional consequence tied to the block goal (e.g., "Oct half-marathon pace slips"), no softening qualifiers, no dated "N weeks behind" projection.
**Why human:** LLM compose output — register, specificity, and tone are judgment-based; unit tests only assert structural prompt markers exist.

#### 2. Recovery Single-Ranked-Rec Format

**Test:** Trigger an HRV-below-baseline vs. top-set bench conflict in the 21:30 check-in path.
**Expected:** Cites the literal HRV value and percentage of baseline; gives exactly ONE ranked recommendation (not a menu); ends with "your call, Sir"; does not dictate.
**Why human:** "Exactly one rec" and "never a menu" are LLM output quality checks; unit tests only assert the prompt contains the instruction.

#### 3. Integrated Morning Briefing Block

**Test:** On a training day with a recovery concern and a relevant fueling reminder, observe the morning briefing output.
**Expected:** Today's named session + recovery state + fueling reminder appear in a single integrated paragraph, not as three separate labeled lines or bullet points.
**Why human:** D-18 "weave" instruction is a compositional LLM behavior; the unit test only asserts the prompt contains "weave" or "integrated" as text.

#### 4. Sunday Weekly Review Per-Facet + Quality Trend

**Test:** Observe Sunday weekly review output during Block 1 with at least one logged session carrying a quality label.
**Expected:** Includes per-facet within-block status (strength top-set named, threshold volume vs target, ACWR stated); session quality distribution shown (e.g., "3 strong, 2 neutral, 1 grind"); no "on track for October" or "N weeks behind" projection language.
**Why human:** Per-facet reporting completeness and projection prohibition are LLM output checks; unit tests only assert prompt structure.

---

### Gaps Summary

**One BLOCKER gap found — COACH-05 dedup write path is dead code in morning briefing and weekly review.**

The dedup gate implementation has a structural wiring defect in `core/morning_briefing.py` and `core/weekly_training_review.py`. Both files' post-send write loops look for `coaching_topics_included` in the gathered data dict, but neither `_gather_data()` nor `_gather_week_data()` ever populates that key. As a result:

- Morning briefing's topics are never written to `CoachingTopicStore`
- Weekly review's topics are never written to `CoachingTopicStore`
- The 21:30 cron, which fires later on the same day as morning briefing, has no record of what morning briefing raised and may repeat the same topic (e.g., a skipped session flagged in morning briefing may appear again in the evening alert)

The 21:30 proactive alerts cron (`core/proactive_alerts.py`) has a correct implementation: it uses a local `_new_topics` variable populated before compose and writes those directly after send. The gap is that this pattern was not applied to the other two crons.

The unit tests for the write path pass because they mock `_gather_data` to return a dict with `coaching_topics_included` already populated — they do not test the real production data flow from `_gather_data()`.

**Root cause:** The `coaching_topics_included` key is a design artifact that requires someone to populate it (either in gather or compose) — but neither plan's action spec defined where/how that key gets populated for the morning briefing and weekly review crons. The proactive alerts cron took a different, correct approach (local variable), while the other crons adopted a placeholder key that nothing fills.

**Fix options:**
1. Mirror the proactive_alerts pattern: in each cron's run function, derive the topics to be written from `_collect_detected_topics(today_data)` or an equivalent (for morning briefing, topics would need to be derived from the briefing's coaching_data context), write them after send. This requires deciding what counts as a "raised topic" for the morning briefing and weekly review.
2. Simpler: have the prompt include a structured `coaching_topics_included` field in its output JSON (if using structured output), or parse it from the compose output — but this changes the output contract.
3. Simplest: define a fixed list of topics that each cron always "raises" (e.g., if a skipped session is in the gather data, always register `"skipped-session:{type}"`), populate `coaching_topics_included` before send, then write after send.

---

_Verified: 2026-06-06T14:45:00Z_
_Verifier: Claude (gsd-verifier)_
