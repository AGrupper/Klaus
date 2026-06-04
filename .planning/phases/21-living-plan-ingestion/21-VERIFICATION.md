---
phase: 21-living-plan-ingestion
verified: 2026-06-04T11:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run python scripts/ingest_blueprint.py against production Firestore to populate users/amit"
    expected: "After ingest, UserProfileStore.load() returns non-empty dated_goals (Oct + Nov peaks with numeric targets), weekly_split (7 days AM/PM), nutrition_targets (protein_g=150, carbs_g=350), supplement_schedule, fueling_timeline (6 slots), plan_start_date='2026-06-21'"
    why_human: "Script requires GCP credentials (GCP_PROJECT_ID + Firestore auth). The mechanism is fully verified — schema, script, renderer, tool handler all correct. The live data population is a one-time operational seed step that cannot be run without production credentials."
  - test: "Say 'update my bench goal to 105kg' in Telegram chat with Klaus"
    expected: "Klaus calls update_plan with a patch containing the modified bench_press_kg value, and on the very next turn references 105kg (not 100kg) when discussing the bench goal"
    why_human: "Verifies the full round-trip: conversational intent → brain tool selection → Firestore write → fresh profile read on next turn. Cannot be tested without a live Telegram session and deployed Klaus."
---

# Phase 21: Living Plan Ingestion — Verification Report

**Phase Goal:** Amit's Hybrid Athlete blueprint lives in `UserProfileStore` as structured fields
that every cron and brain-direct tool can read; the plan is encoded as a flexible weekly template
(volume/trend targets, not day-by-day prescriptions); Amit can update it at any time via the
`update_plan` tool.

**Verified:** 2026-06-04T11:00:00Z
**Status:** human_needed (automated checks all pass; live Firestore population and conversational
update round-trip require human confirmation)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | `UserProfileStore.load()` returns non-empty `dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, and `plan_start_date` — not a raw blob | VERIFIED (mechanism) / HUMAN (live data) | `_SCAFFOLD` has all 6 keys; `ingest_blueprint.py --dry-run` produces correct JSON; live Firestore seed requires operator action |
| 2 | Weekly split stored as template (session priorities + modalities), NOT per-session attendance booleans | VERIFIED | `_SCAFFOLD["weekly_split"] == {}`; `build_profile_dict()` emits only `label/modality/priority`; `grep` finds no attendance/completed/done keys; `test_weekly_split_no_attendance_words` passes |
| 3 | Amit can say "update my bench goal" and Klaus reasons against updated plan on next turn | VERIFIED (mechanism) / HUMAN (conversational) | `update_plan` in `_HANDLERS` dispatches to `_handle_update_training_profile`; `merge=True` on Firestore; renderer calls `store.load()` fresh per turn; 9 new tests verify dispatch + pass-through |
| 4 | `training_profile` prompt section reflects blueprint fields framed as coaching reference guide, not rigid contract | VERIFIED | Header "**Coaching reference — Amit's training plan:**"; prompt section has "template, not a contract — never nag about a single missed session"; Tier A/B discipline present; anti-fabrication "do NOT invent" preserved; `{training_profile}` placeholder at line 7 unchanged |

**Score:** 4/4 truths verified (mechanism/code level). Two truths have human items for live
operational confirmation.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|---------|--------|---------|
| `memory/firestore_db.py` | `UserProfileStore._SCAFFOLD` v4.0 + schema_version 2 | VERIFIED | 6 structured keys + `schema_version: 2` + `athletic_goals` retained confirmed by direct import |
| `scripts/ingest_blueprint.py` | Idempotent blueprint → structured Firestore ingest with dry-run/force | VERIFIED | `build_profile_dict()` pure function; `--dry-run` works without GCP creds; `--force` idempotency gate; 22 tests pass |
| `tests/test_ingest_blueprint.py` | Tests for builder (pure function, no Firestore) | VERIFIED | 22 tests, 7 test classes, including `TestNo16WeekTable` and baseline-key absence check |
| `core/tools.py` | Extended update schema + `update_plan` alias + JSON-safe get handler | VERIFIED | `update_plan` in `SMART_AGENT_DIRECT_TOOLS`, `TOOL_SCHEMAS`, and `_HANDLERS`; `_jsonsafe_doc` used in get handler; 33 tests pass |
| `tests/test_tools.py` | Tests for `update_plan` dispatch + JSON-safe get handler | VERIFIED | 9 new tests in `TestPhase21UpdatePlanAlias`; all pass |
| `core/main.py` | Coaching-reference prose rendering of structured profile in `render_smart_system` | VERIFIED | Per-key conditional-append renderer; CR-21-01 fix (dict metrics); WR-21-01 fix (aerobic note); 30 tests pass |
| `prompts/smart_agent.md` | Reframed TRAINING & ATHLETIC COACHING section | VERIFIED | All grep gates pass: "template, not a contract", "never nag", "Tier A"/"Tier B", "update_plan", "do NOT invent", `{training_profile}` placeholder intact |
| `tests/test_main_render_smart_system.py` | Tests for structured-field prose rendering | VERIFIED | 11 new tests including `test_real_ingest_payload_renders_all_targets` (the integration test added for CR-21-01) |
| `tests/test_user_profile_store.py` | Updated scaffold + schema_version 2 assertions | VERIFIED | `schema_version == 2` assertion; `test_bootstrap_seeds_v4_structured_keys`; `test_bootstrap_seeds_weekly_split_as_empty_dict` |
| `tests/test_user_profile_store_v4_scaffold.py` | Standalone _SCAFFOLD regression guard | VERIFIED | 10 tests, all pass |
| `tests/test_weekly_training_review.py` | v4.0 schema compat + athletic_goals regression guard | VERIFIED | `test_weekly_review_athletic_goals_from_full_v4_schema` and absent-key variant pass |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `_SCAFFOLD` field names | `scripts/ingest_blueprint.py` key names | shared string constants | WIRED | `build_profile_dict()` returns exactly the 6 keys that `_SCAFFOLD` defines |
| `core/tools.py _handle_update_training_profile` | `memory/firestore_db.py UserProfileStore.update` | `merge=True` patch write | WIRED | Confirmed in handler body; `test_update_plan_calls_store_update` asserts |
| `core/tools.py _handle_get_training_profile` | `memory/firestore_db.py _jsonsafe_doc` | timestamp stripping before `json.dumps` | WIRED | `from memory.firestore_db import UserProfileStore, _jsonsafe_doc` in handler |
| `_HANDLERS["update_plan"]` | `_handle_update_training_profile` | lambda alias | WIRED | `"update_plan": lambda args: _handle_update_training_profile(**args)` at line 1495 |
| `core/main.py render_smart_system` | `UserProfileStore.load()` | fresh per-turn load → prose snippet | WIRED | `profile = self._user_profile_store.load()` inside renderer; substituted into prompt via `.replace("{training_profile}", training_profile_snippet)` |
| `prompts/smart_agent.md {training_profile}` | `core/main.py training_profile_snippet` | placeholder substitution | WIRED | Placeholder at line 7 confirmed; `.replace("{training_profile}", ...)` at line 421 |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `render_smart_system` training_profile snippet | `non_empty` dict from `profile` | `self._user_profile_store.load()` → Firestore `users/amit` | Yes (after operator seed step) | VERIFIED (mechanism). Data flows correctly once `ingest_blueprint.py` populates Firestore. |
| `_handle_get_training_profile` | `store.load()` result | Firestore `users/amit` | Yes (after seed) | VERIFIED — JSON-safe via `_jsonsafe_doc` recursive (WR-21-03 fix in fafcc69) |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `ingest_blueprint.py --dry-run` produces valid JSON with correct fields | `python scripts/ingest_blueprint.py --dry-run \| python -c "..."` | plan_start_date='2026-06-21', 7-day split, 6 fueling slots, dict metrics | PASS |
| `build_profile_dict()` produces no attendance booleans | `json.dumps(build_profile_dict()).lower()` — grep attendance/completed | Not found | PASS |
| Renderer produces key:value metric output (CR-21-01) | Direct simulation with dict metrics | "bench_press_kg 100, squat_kg 120, half_marathon_time 1:25:00" in output | PASS |
| `_SCAFFOLD` has 6 structured keys + schema_version 2 | Direct import and assertion | All 6 keys present, schema_version==2, athletic_goals retained | PASS |
| `update_plan` registered in SMART_AGENT_DIRECT_TOOLS and _HANDLERS | `grep update_plan core/tools.py` | Lines 56, 693, 1495 | PASS |
| Prompt contains "template, not a contract" and "never nag" | `grep -ni` | Line 94 confirmed | PASS |
| Prompt contains Tier A / Tier B discipline | `grep -ni "Tier A\|Tier B"` | Lines 89, 105, 106, 107, 109 | PASS |
| `{training_profile}` placeholder at prompt line 7 | `grep -n "{training_profile}"` | Line 7 confirmed | PASS |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| PLAN-01 | 21-01, 21-03 | Blueprint ingested as structured fields, not raw blob; no 16-week table as target rows; no hand-seeded baselines | SATISFIED (mechanism) | `_SCAFFOLD` 6 structured keys; `build_profile_dict()` produces correct shape; `aerobic_reference_note` is a single string, not rows; `TestTopLevelKeys::test_no_current_performance_baseline_keys` passes |
| PLAN-02 | 21-01, 21-04 | Flexible guide (template), not rigid day-by-day attendance contract | SATISFIED | `weekly_split == {}` default; renderer emits only `label/modality/priority`; prompt says "never nag about a single missed session"; `test_weekly_split_no_attendance_words` passes |
| PLAN-03 | 21-02, 21-04 | Amit can update plan; Klaus reasons against updated plan on next turn | SATISFIED (mechanism) | `update_plan` alias fully wired; `merge=True`; renderer re-reads fresh per turn; prompt names `update_plan` as user-facing tool |

All three required requirement IDs (PLAN-01, PLAN-02, PLAN-03) are satisfied at the code/mechanism level. REQUIREMENTS.md maps all three to Phase 21 (rows 76-78 in traceability table).

No orphaned Phase 21 requirements found. All other requirement IDs (COACH-*, BLOCK-*, NUTR-*, PROG-*) are mapped to later phases (22-25).

---

## Code Review Fix Verification (fafcc69)

The code review (21-REVIEW.md) identified one critical defect and three warnings. All were resolved in commit fafcc69.

| Finding | ID | Fix Verified |
|---------|-----|-------------|
| `dated_goals` dict metrics rendered as keys only (all values dropped) | CR-21-01 (BLOCKER) | `isinstance(metrics, dict)` branch at `core/main.py:318` confirmed; end-to-end test `test_real_ingest_payload_renders_all_targets` passes; spot-check output shows "bench_press_kg 100, squat_kg 120, half_marathon_time 1:25:00" |
| `aerobic_reference_note` silently dropped by renderer | WR-21-01 | `aerobic_note = nutrition_targets.get("aerobic_reference_note")` at `core/main.py:368` confirmed |
| Renderer tests used list fixture contradicting ingest dict contract | WR-21-02 | `test_dated_goals_renders_dict_metric_values` + `test_real_ingest_payload_renders_all_targets` added, both pass |
| `_jsonsafe_doc` shallow (nested datetimes would still break `get_training_profile`) | WR-21-03 | `_jsonsafe_value` recursive helper at `memory/firestore_db.py:745-761` confirmed; recurses into dicts and lists |

CR-21-01 fix validated: the old code path (`", ".join(str(m) for m in metrics)` on a dict) would have produced "bench_press_kg, squat_kg, half_marathon_time". The new path produces "bench_press_kg 100, squat_kg 120, half_marathon_time 1:25:00". This is confirmed both by direct code inspection and by the behavioral spot-check.

The two info items (IN-01: extra kwargs raise TypeError; IN-02: idempotency gate keys on plan_start_date) were acknowledged as pre-existing / low-risk and not fixed, consistent with the review disposition.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | No TBD/FIXME/XXX markers found in any phase-modified file |

No unresolved debt markers in `memory/firestore_db.py`, `core/tools.py`, `core/main.py`, `scripts/ingest_blueprint.py`, or `prompts/smart_agent.md`.

The `plan_start_date: ""` empty default in `_SCAFFOLD` is a documented, intentional stub (populated by ingest script). Not an anti-pattern.

---

## Human Verification Required

### 1. Production Firestore Seed

**Test:** Run `python scripts/ingest_blueprint.py` (without --dry-run) against production Firestore using a shell with `GCP_PROJECT_ID` set and valid GCP credentials.

**Expected:** Command exits 0. Subsequent `get_training_profile` tool call from Klaus returns a JSON object with non-empty `dated_goals` (2 goals with numeric metrics), `weekly_split` (7 days with AM/PM sessions), `nutrition_targets` (`protein_g=150`, `carbs_g=350`, `fueling_slots` list, `aerobic_reference_note` string), `fueling_timeline` (6 slots), `supplement_schedule` (4 entries), `plan_start_date="2026-06-21"`.

**Why human:** Script requires production GCP credentials. The mechanism is fully verified in code; this step populates the live Firestore document.

### 2. Conversational Update Round-Trip

**Test:** In Telegram, say "update my bench goal to 105kg" to Klaus.

**Expected:** Klaus calls `update_plan` with a patch (e.g. `{"dated_goals": [...updated list...]}`), confirms with Amit, writes to Firestore. On the very next turn, when asked about the bench target, Klaus cites 105kg (not 100kg) — proving the renderer re-reads the profile fresh and the update propagated.

**Why human:** Requires a live Telegram session with the deployed Klaus instance. Tests the full conversational path: intent parsing → tool selection → Firestore write → fresh profile read.

---

## Gaps Summary

No blocker gaps. All four observable truths are verified at the code and mechanism level. The two human items are operational confirmation steps (live data seed + conversational round-trip), not failures of the implementation.

The code review blocker (CR-21-01) was fixed in commit fafcc69 and the fix is verified by direct code inspection, behavioral spot-check, and a new integration test (`test_real_ingest_payload_renders_all_targets`) that feeds actual `build_profile_dict()` output through the renderer — the exact cross-plan test the original test suite missed.

---

_Verified: 2026-06-04T11:00:00Z_
_Verifier: Claude (gsd-verifier)_
