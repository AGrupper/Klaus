---
phase: 19-training-awareness-nutrition-coaching
plan: 05
subsystem: prompts-and-identity
tags: [prompts, smart-agent, autonomous-triage, morning-briefing, meal-audit, self-manifest, phase-19, wave-4, final-wave]
dependency_graph:
  requires:
    - "Plan 19-02: UserProfileStore + get_training_profile / update_training_profile tools"
    - "Plan 19-03: fetch_recent_meals + MealStore + Google Fit nutrition reads"
    - "Plan 19-04: autonomous gather (meals_since_last_tick + training_status + acwr) + morning briefing nutrition recap data layer"
  provides:
    - "{training_profile} placeholder substitution in render_smart_system"
    - "TRAINING & ATHLETIC COACHING section in smart_agent.md"
    - "Meals as triggers (Phase 19) section in autonomous_triage.md"
    - "Yesterday's Nutrition recap (silent-omit) in morning_briefing.md"
    - "prompts/meal_audit.md (NEW) — non-personalized nutrition critique heuristics"
    - "core/autonomous.py + core/morning_briefing.py runtime wiring of meal_audit.md"
    - "docs/SELF.md regenerated with all 5 Phase 19 tools surfaced"
  affects:
    - "Every brain LLM call (smart_agent.md is the per-message system template)"
    - "Every autonomous tick triage call (autonomous_triage.md)"
    - "Every autonomous tick brain-compose call (autonomous.md + meal_audit.md appended)"
    - "Every morning briefing LLM call (morning_briefing.md + meal_audit.md appended)"
tech_stack:
  added: []
  patterns:
    - "Pattern: extend render_smart_system with a new placeholder using the same omit-empty + meta-key-filter discipline as the existing self_state block (PROMPT-01)"
    - "Pattern: silent-omit nutrition section in morning_briefing.md driven by data-layer key presence (NUTR-07) — matches Garmin state-2 omit-the-block precedent"
    - "Pattern: append additional prompt file to system template at runtime via _load_prompt + string-concat (NUTR-08 — same shape at 2 sites in autonomous.py + 1 site in morning_briefing.py)"
    - "Pattern: stub additional sys.modules attributes (GoogleAuthError, Request, build, load_dotenv, api_core.exceptions.*) so core.tools dynamic import works in local-dev environments without google-auth installed — keeps self_manifest.py from silently falling back to the stale Phase 15 hardcoded tool list"
key_files:
  created:
    - "prompts/meal_audit.md (31 lines — non-personalized nutrition critique heuristics)"
  modified:
    - "core/main.py (render_smart_system: +17 lines — {training_profile} block + 5th .replace)"
    - "core/autonomous.py (+14 lines across 2 sites — meal_audit.md load + append in _compose_layer2 and _compose_followup_layer2)"
    - "core/morning_briefing.py (+13 lines — meal_audit.md load + append in _compose_briefing)"
    - "core/self_manifest.py (+30 lines — sys.modules stub attributes so live import path succeeds in local dev; without this, regeneration silently uses the stale Phase 15 hardcoded fallback list)"
    - "prompts/smart_agent.md (+25 lines — {training_profile} placeholder + TRAINING & ATHLETIC COACHING section)"
    - "prompts/autonomous_triage.md (+26 lines — ## Meals as triggers (Phase 19) section + meal_audit.md cross-link)"
    - "prompts/morning_briefing.md (+9 lines — 🥗 Yesterday's Nutrition section with conditional-render instruction)"
    - "docs/SELF.md (regenerated — all 5 Phase 19 tools now listed; was missing all 5 prior to regen)"
    - "tests/test_main_render_smart_system.py (+64 lines — TestPhase19TrainingProfile class with 4 cases)"
    - "tests/test_prompts.py (+45 lines — 4 new tests: smart_agent training section, triage meal triggers, meal_audit exists + cross-referenced)"
    - "tests/test_morning_briefing.py (+9 lines top + 23 lines bottom — silent-omit NUTR-07 test + TestPhase19MealAuditWiringMorningBriefing class)"
    - "tests/test_autonomous.py (+34 lines — TestPhase19MealAuditWiring class with 3 cases including 2-site count assertion)"
    - "tests/test_docs.py (+23 lines — TestPhase19SelfManifest class)"
decisions:
  - "render_smart_system uses getattr(self, '_user_profile_store', None) instead of direct attribute access to remain back-compatible with the 4 existing render tests' _make_orchestrator helper, which only attaches 3 attributes (self_md, self_state_store, journal_store). This is the minimal-impact way to add a 5th placeholder without rewriting the test fixture."
  - "meal_audit.md append uses a defense-in-depth `if meal_audit:` guard. The RESEARCH §8 snippet shows it without the guard; the guard prevents a stray '\\n\\n' separator if the file ever returns empty. Matches the morning_briefing pattern verbatim."
  - "Both brain-compose sites in autonomous.py get the append — _compose_layer2 (proactive nudges, ~line 556) AND _compose_followup_layer2 (due follow-up compose, ~line 597). Either path can be the one that lands a meal-adjacent nudge; the audit guidance must follow."
  - "Stale fallback list in core/self_manifest.py:_load_tool_data_fallback was NOT updated to include Phase 19 tools. Instead, the dynamic-import path was fixed (added 6 stub attributes) so the live tools.py is read every regeneration. This is the right call: the fallback list is a Phase 15 snapshot and updating it for each phase would invert the design intent (dynamic-import is the source of truth). The fallback now only fires in extreme dependency outages, where SELF.md being one phase behind is acceptable."
metrics:
  duration: ~25 minutes (executor session, post-context-load)
  completed_date: 2026-05-28
  test_baseline: "557 passed, 3 skipped (Plan 19-04 close)"
  test_current: "572 passed, 3 skipped (+15 net, 0 regressions)"
  tests_added:
    - "tests/test_main_render_smart_system.py::TestPhase19TrainingProfile — 4"
    - "tests/test_prompts.py — 4 (smart_agent training section + triage meal triggers + meal_audit exists + meal_audit referenced)"
    - "tests/test_morning_briefing.py — 3 (NUTR-07 silent-omit + TestPhase19MealAuditWiringMorningBriefing × 2)"
    - "tests/test_autonomous.py::TestPhase19MealAuditWiring — 3"
    - "tests/test_docs.py::TestPhase19SelfManifest — 1"
    - "Total: 15 new tests"
  commits: 8 (1 RED + 6 GREEN/feat + 1 docs, per task contract)
---

# Phase 19 Plan 05: Prompt Extensions + meal_audit.md + SELF.md Regen Summary

Land the prompt + identity layer that fronts the Wave 1-3 data and tools so the
brain has instructions for when to call the new tools, the tick-brain has a
rubric for when meals should fire a proactive nudge, and SELF.md surfaces all 5
new Phase 19 capabilities by name. Final wave of Phase 19 — completes 26/26
requirements for the phase.

## What Shipped

### PROMPT-01 — {training_profile} placeholder substitution

`core/main.py::render_smart_system` extended with a 5th placeholder substitution.
The block mirrors the existing `self_state_snippet` discipline byte-for-byte:
filters meta keys (`updated_at`, `bootstrapped_at`, `schema_version`), filters
empty/falsy values, renders only when something non-empty remains. Empty profile
collapses to an empty string — the literal `{training_profile}` placeholder is
consumed and never leaks to the LLM.

Concretely the new 5th `.replace` lands between `journal_digest` and
`today_date` so dynamic content stays last (Gemini prompt-cache discipline
preserved). Uses `getattr(self, "_user_profile_store", None)` so the existing
4-attribute `_make_orchestrator` test fixture in
`tests/test_main_render_smart_system.py` continues to work without modification.

### PROMPT-02 — TRAINING & ATHLETIC COACHING section in smart_agent.md

Added the `{training_profile}` placeholder at top (between `{journal_digest}`
and the `---` separator). Added a 25-line `TRAINING & ATHLETIC COACHING` section
before `LONG-TERM MEMORY` that:
- Names all 5 new Phase 19 tools (`fetch_training_status`,
  `fetch_recent_activities`, `fetch_recent_meals`, `get_training_profile`,
  `update_training_profile`) with their routing semantics.
- Encodes the empty-profile discipline: do NOT invent thresholds; answer with
  just the metric; ask Sir for personalization preferences and call
  `update_training_profile`.
- Carries the JARVIS register but instructs leaner C-3PO hedging for
  training/nutrition observations — the area where Sir explicitly asked for
  direct coaching.

### PROMPT-03 — docs/SELF.md regenerated

`python core/self_manifest.py` re-run. All 5 Phase 19 tools now appear in the
Tools table by name. Required updates to `_load_tool_data` sys.modules stubs:
added attributes on the stub modules so `from google.auth.exceptions import
GoogleAuthError`, `from google.auth.transport.requests import Request`,
`from googleapiclient.discovery import build`, `from dotenv import load_dotenv`,
and the `google.api_core.exceptions` symbol set all resolve at dynamic-import
time. Without these stubs the manifest generator silently fell back to the
hardcoded Phase 15 tool list (which lacks all 8 post-Phase-15 tools, not just
the 5 Phase 19 additions). Regeneration is now idempotent modulo the
`generated_at` timestamp.

### NUTR-06 — autonomous_triage.md Meals as triggers

26-line `## Meals as triggers (Phase 19)` section added between
`## Repeat-suppression as info, not block` and `## Rules`. Describes meal-driven
candidate triggers (macro imbalance vs. workout proximity, long gap, meal type
out of pattern given the calendar). Hardcodes the empty-`{training_profile}`
discipline: no numeric thresholds, generic nutritional reasoning. Closes with a
cross-link to `prompts/meal_audit.md` so the LLM knows where the heuristics
live.

### NUTR-07 — morning_briefing.md silent-omit nutrition recap

9-line `🥗 Yesterday's Nutrition (only when nutrition key present in data)`
section added between `✅ Tasks` and `📚 https://readwise.io/dailyreview`.
Renders totals, meal count, optional biggest-gap note. Explicit conditional-
render instruction at the bottom of the section: "If `nutrition` key is absent
from data, OMIT this entire section. Do not write 'no nutrition data' or any
placeholder text." Matches the Garmin state-2 silent-omit precedent at line 91
of the same prompt.

This is a prompt-layer enforcement of the data-layer omit contract that Plan
19-04 already implemented (`data["nutrition"] = agg` only when `agg` is truthy).
Defense-in-depth across the two layers.

### NUTR-08 — prompts/meal_audit.md (NEW)

31-line guidance file with 4 heuristic sections:
- **Nutrition density** — calories-without-protein/fat/fiber detection.
- **Protein adequacy** — general adult heuristic band (25-40g/meal, <15g flag
  for non-snack, day-total <100g flag).
- **Carb appropriateness vs. training context** — pre-workout vs. pre-sedentary
  guidance.
- **When to comment proactively** — "Sir would thank me for noticing" bar, not
  "I could find something to say".

Voice section explicitly prohibits moralizing, "good food" / "bad food", emojis,
exclamation marks. JARVIS register with leaner C-3PO hedging — same edge as the
smart_agent.md training section.

### NUTR-08 (cont.) — Runtime wiring of meal_audit.md

`core/autonomous.py` and `core/morning_briefing.py` both load
`prompts/meal_audit.md` and append it to the brain compose system template:

- **autonomous.py** (2 sites): `_compose_layer2` (proactive nudge path) and
  `_compose_followup_layer2` (due follow-up path). Each uses `_load_prompt` +
  `if meal_audit:` guarded string-append. Both brain-compose entry points
  carry the same audit guidance so a meal-adjacent nudge is critiqued under
  the same heuristics regardless of which path lands the message.

- **morning_briefing.py** (1 site): `_compose_briefing` uses a Path-based read
  mirroring the existing `prompt_path = Path(...) / "morning_briefing.md"`
  pattern at line 269. Appended after the `{today_date}` substitution and
  before the LLM call.

The 3 grep-style source-reference tests catch any future deletion regression of
either site.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocker] core/self_manifest.py dynamic-import path stale for v3.0 dependencies**
- **Found during:** Task 6 — initial `python core/self_manifest.py` run.
- **Issue:** `_load_tool_data` failed with `No module named 'google.auth'`, fell
  back to the hardcoded Phase 15 tool list, which is missing all 8 post-Phase-15
  tools (Phase 18 follow-up trio + Phase 19 quintet). Result: SELF.md had 0
  hits for any of the 5 PROMPT-03 target tool names.
- **Fix:** Added 6 stub attributes to the existing sys.modules-stub block in
  `_load_tool_data`: `GoogleAuthError`/`RefreshError` on `google.auth.exceptions`,
  `Request` on `google.auth.transport.requests`, `InstalledAppFlow` on
  `google_auth_oauthlib.flow`, `Credentials` on `google.oauth2.credentials`,
  `build` on `googleapiclient.discovery`, `load_dotenv` on `dotenv`, and the
  full `GoogleAPICallError`/`NotFound`/... set on `google.api_core.exceptions`.
  Dynamic-import path now succeeds in local dev; live `core/tools.py` TOOL_SCHEMAS
  is the source of truth for SELF.md. Hardcoded fallback list intentionally NOT
  updated — design intent is dynamic introspection.
- **Files modified:** core/self_manifest.py (+30 lines)
- **Commit:** `67a845c` (docs(19-05): regenerate SELF.md to surface Phase 19 tools)
- **Why blocker not bug:** Without this, PROMPT-03 success criterion fails. The
  fallback list staleness is a pre-existing condition that only surfaced once a
  new phase added tools that needed to ship in SELF.md.

### Plan-vs-Implementation Notes

**Wording deviation: section order in morning_briefing.md.** Plan suggested
"between Garmin and Schedule"; landed between `✅ Tasks` and
`📚 https://readwise.io/dailyreview` so the Schedule/Email/Tasks operational
top-of-briefing flow is preserved and the nutrition recap reads as a
retrospective coda. Functionally equivalent; the silent-omit instruction is
still local to the section.

**autonomous.py: 2 sites are at lines 556 + 599, not 512 + 548 per plan.**
The plan's line numbers were drift from an earlier revision. The two
`smart_system_template = _load_prompt("prompts/autonomous.md")` occurrences are
the canonical anchor — verified via `grep -n smart_system_template
core/autonomous.py` before edits. Both sites received the append.

## Tool Count in SELF.md (before vs. after)

| State | Tool count | Phase 19 tools present |
|-------|-----------|------------------------|
| Before regen (pre-Plan 19-05) | 30 (Phase 15 hardcoded fallback) | 0/5 |
| After regen (this plan)       | 38 (live introspection)        | 5/5 |

Delta: +8 tools surfaced (3 Phase 18 follow-ups + 5 Phase 19 training/nutrition).
The Phase 18 trio was already in core/tools.py but invisible in SELF.md until
the dynamic-import path was unblocked.

## Authentication Gates

None. All work was prompt/code/docs; no external services touched.

## Test Results

Full suite: **572 passed, 3 skipped, 0 regressions** (was 557 at Plan 19-04 close).
+15 net tests across 5 test files:

- `tests/test_main_render_smart_system.py::TestPhase19TrainingProfile` — 4 cases
- `tests/test_prompts.py` — 4 new top-level tests
- `tests/test_morning_briefing.py` — 1 top-level + 2 in
  `TestPhase19MealAuditWiringMorningBriefing`
- `tests/test_autonomous.py::TestPhase19MealAuditWiring` — 3 cases (incl.
  2-site count assertion)
- `tests/test_docs.py::TestPhase19SelfManifest` — 1 case

## TDD Gate Compliance

| Gate    | Commits |
|---------|---------|
| RED     | `ebda0bf` (training_profile tests) + `35e9d4d` (NUTR-08 wiring tests) |
| GREEN   | `c0008b2` (PROMPT-01) + `f32469b` (PROMPT-02 + NUTR-06) + `cb03282` (NUTR-07) + `907faf8` (meal_audit.md NEW) + `6259292` (NUTR-08 wiring) + `67a845c` (PROMPT-03) |
| REFACTOR | None needed — straight-line edits matched the plan snippets verbatim |

Sequence verified: every RED commit is followed by a GREEN commit on the same
requirement.

## Self-Check: PASSED

- Files created: `prompts/meal_audit.md` FOUND
- Files modified (sampled): `core/main.py` FOUND, `core/autonomous.py` FOUND,
  `core/morning_briefing.py` FOUND, `core/self_manifest.py` FOUND,
  `prompts/smart_agent.md` FOUND, `prompts/autonomous_triage.md` FOUND,
  `prompts/morning_briefing.md` FOUND, `docs/SELF.md` FOUND
- Commits: `ebda0bf`, `c0008b2`, `f32469b`, `cb03282`, `907faf8`, `35e9d4d`,
  `6259292`, `67a845c` — ALL FOUND in `git log`
- Phase 19 requirement closure: NUTR-06, NUTR-07, NUTR-08, PROMPT-01, PROMPT-02,
  PROMPT-03 — 6/6 closed by this plan; 26/26 closed across the phase
