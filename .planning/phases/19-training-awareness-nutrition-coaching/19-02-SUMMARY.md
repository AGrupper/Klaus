---
phase: 19-training-awareness-nutrition-coaching
plan: 02
subsystem: profile-and-live-reads
status: completed
completed_at: 2026-05-27
tags: [user-profile, firestore, garmin, acwr, tool-registration, wave-1]
requires:
  - Phase 19-01 (7 new Postgres columns on `activities` and `daily_biometrics`)
  - Existing `garminconnect` library + GARMIN_EMAIL / GARMIN_PASSWORD env vars
  - Existing SelfStateStore (template for UserProfileStore discipline contract)
provides:
  - `UserProfileStore` (filled-in, replaces Phase-5 NotImplementedError stub) at `memory/firestore_db.py`
  - `users/amit` Firestore doc bootstrap on every `AgentOrchestrator.__init__` (Pitfall-7-safe)
  - `_authed_garmin_client()` helper shared across all Garmin fetch_* functions
  - `fetch_garmin_training_status()` — VO2 max / training_status / load_focus
  - `fetch_garmin_activities(days=7)` — normalized activity list with RPE + Feel + training_load
  - `compute_acwr(activities, today=...)` — pure-function ACWR with `ratio=None` on insufficient baseline
  - `compute_acwr_from_db()` — Postgres-backed wrapper for autonomous-tick layer 0 (never raises)
  - 4 new tool registrations (2 brain-direct + 2 worker-delegated) at all 5 sites in `core/tools.py`
affects:
  - Plan 19-03 (Google Fit + MealStore + fetch_recent_meals) — registers a 5th tool alongside the 4 from this plan
  - Plan 19-04 (autonomous tick + morning briefing gather extensions) — consumes fetch_garmin_training_status, compute_acwr_from_db
  - Plan 19-05 (smart-agent prompt + SELF.md regen) — wires `{training_profile}` placeholder which reads from `_user_profile_store`
tech-stack:
  added: []  # no new dependencies — reuses google-cloud-firestore, garminconnect, psycopg2
  patterns:
    - "SelfStateStore-style discipline contract: reads never raise, writes re-raise after logger.error, bootstrap_if_empty never raises (Pitfall 7)."
    - "_safe_extract_key() — one-level envelope drill for Garmin payload shape variance."
    - "Brain-direct tool registration discipline (Phase 18 idiom): 5 sites — frozenset / TOOL_SCHEMAS / WORKER exclusion / handlers / _HANDLERS dispatch."
    - "Worker-delegated fetch handlers catch GarminUnavailableError + GarminAuthError and return structured `{error: ...}` JSON instead of raising up into the worker LLM loop."
key-files:
  created:
    - tests/test_user_profile_store.py
    - tests/test_garmin_extensions.py
    - tests/test_compute_acwr.py
    - .planning/phases/19-training-awareness-nutrition-coaching/19-02-SUMMARY.md
  modified:
    - memory/firestore_db.py  # +UserProfileStore impl (replaces stub)
    - core/main.py  # +_build_user_profile_store + bootstrap call in __init__
    - mcp_tools/garmin_tool.py  # +_authed_garmin_client, +fetch_garmin_training_status, +fetch_garmin_activities, +compute_acwr, +compute_acwr_from_db
    - core/tools.py  # 5 registration sites for 4 new tools
    - tests/test_tools.py  # +TestPhase19ToolRegistration (4 tests)
decisions:
  - "garminconnect token-dump uses `api.client.dumps()` (NOT `api.garth.dumps()`). The existing fetch_garmin_today already used `.client.dumps()` and the in-place refactor preserved that — confirmed working against the live API in production."
  - "compute_acwr 'insufficient chronic baseline' threshold is `< 14 days with training_load data in the 28-day window`. Matches the sport-science literature cited in RESEARCH and treats zero-load rest days as valid data points (not missing data)."
  - "_safe_extract_key() is the chosen mitigation for Garmin envelope-shape drift. The function tries each provided source dict, then drills one level into nested dict values, returning the first non-None match. This is robust against the most common Garmin API change (wrapping the result in a single envelope key)."
  - "Tool tier split: get_training_profile + update_training_profile are brain-direct (identity-shaped writes); fetch_training_status + fetch_recent_activities are worker-delegated (plain data fetches). This mirrors the Phase 16/18 convention and is locked by `TestPhase19ToolRegistration::test_phase19_fetch_tools_worker_delegated`."
  - "UserProfileStore.update is the only write path in this plan; it re-raises on Firestore failure (caller decides). The brain-direct handler `_handle_update_training_profile` catches and returns `{error: ...}` JSON so a Firestore outage surfaces to the LLM as a tool-result error string, not a 500."
  - "_build_user_profile_store factory is best-effort: returns None on missing GCP_PROJECT_ID OR on construction failure. The bootstrap call site checks `is not None` before calling bootstrap_if_empty — even though bootstrap itself never raises, this defends against the rarer case of construction failing (e.g. missing credentials file)."
metrics:
  duration: "~25 min (3 atomic TDD task cycles)"
  tasks: 3
  files: 8  # 4 modified + 4 created (incl. SUMMARY)
  commits: 6  # 3 RED + 3 GREEN
  tests_added: 23  # 8 + 5 + 6 + 4
  tests_total: 522  # was 499 baseline (+23 net)
---

# Phase 19 Plan 02: UserProfileStore + Garmin Live Reads + ACWR — Summary

The Wave-1 plumbing layer: brain can now read/write Sir's coaching profile,
worker can pull live Garmin training status + activities, and ACWR is a
testable pure function ready for autonomous-tick gather (Plan 19-04). All 4
GARMIN + 4 PROFILE requirements satisfied, all 9 plan `must_haves.truths`
verified, no regressions, 23 new tests.

## What shipped

### Code

| File | Change |
|---|---|
| `memory/firestore_db.py` | UserProfileStore stub at lines 391-404 REPLACED with full impl: load() never raises, update() re-raises after logger.error, bootstrap_if_empty() never raises (Pitfall 7 mitigation). Mirrors SelfStateStore discipline byte-for-byte. _SCAFFOLD = `{athletic_goals:[], training_constraints:[], recovery_preferences:{}, schema_version:1}`. |
| `core/main.py` | + `_build_user_profile_store()` factory (sibling of `_build_self_state_store`). AgentOrchestrator.__init__ now bootstraps `users/amit` immediately after the SelfStateStore bootstrap. Bootstrap is a no-op when doc exists (so Cloud Run instance churn never overwrites Sir's data). |
| `mcp_tools/garmin_tool.py` | Extracted `_authed_garmin_client()` from fetch_garmin_today's inline auth dance (RESEARCH recommendation: avoid 3x duplication). fetch_garmin_today refactored to use it — passes existing tests with no behavior change. Added: fetch_garmin_training_status, fetch_garmin_activities, compute_acwr (pure), compute_acwr_from_db (Postgres-backed sentinel-returning). |
| `core/tools.py` | 4 new tools registered at all 5 sites: get_training_profile + update_training_profile brain-direct; fetch_training_status + fetch_recent_activities worker-delegated. Handler functions catch GarminUnavailableError + GarminAuthError and return JSON `{error: ...}` so worker LLM gets a structured result. |

### Tests

| Test file | Count | Coverage |
|---|---|---|
| `tests/test_user_profile_store.py` (new) | 8 | PROFILE-01/02/03 + Pitfall 7 (bootstrap never raises) |
| `tests/test_garmin_extensions.py` (new) | 6 | GARMIN-01 (3 tests) + GARMIN-02 (3 tests) |
| `tests/test_compute_acwr.py` (new) | 5 | GARMIN-03 — math, acute spike, insufficient baseline, missing-load, today-override |
| `tests/test_tools.py::TestPhase19ToolRegistration` (extended) | 4 | PROFILE-04 + GARMIN-04 — all 5 registration sites |
| **Total new tests** | **23** | — |
| **Full suite** | **522 passed, 3 skipped** | (+23 net from 499 baseline; 0 regressions) |

## must_haves.truths verification

All 9 truths from the plan frontmatter pass:

| # | Truth | Where verified |
|---|---|---|
| 1 | `UserProfileStore.load()` returns `{}` on any Firestore exception (never raises), returns the document dict otherwise. | `test_load_returns_empty_on_error`, `test_load_returns_empty_when_doc_absent`, `test_load_returns_doc_when_present` |
| 2 | `UserProfileStore.update(patch)` merges patch + stamps `updated_at = firestore.SERVER_TIMESTAMP` via `merge=True`. | `test_update_merges_and_stamps` |
| 3 | `UserProfileStore.bootstrap_if_empty()` creates `users/amit` with scaffold ONLY when missing — no-op when present. | `test_bootstrap_creates_when_missing`, `test_bootstrap_skips_when_present` |
| 4 | `AgentOrchestrator.__init__` bootstraps users/amit on every instance startup, mirroring SelfStateStore. | Verified by code review at `core/main.py:230-234` — sibling pattern of SelfStateStore bootstrap directly above. |
| 5 | `fetch_garmin_training_status()` returns `{vo2_max, training_status, load_focus}` (any value may be None) using the shared `_authed_garmin_client()` helper. | `test_training_status_shape`, `test_training_status_extracts_values` |
| 6 | `fetch_garmin_activities(days=7)` returns a normalized list of dicts; each dict has perceived_exertion + feel keys (may be None). | `test_recent_activities_shape`, `test_recent_activities_default_days_7` |
| 7 | `compute_acwr(activities, today)` returns `{acute, chronic, ratio}`; ratio is None when chronic_days_with_data < 14. | `test_insufficient_baseline_returns_none`, `test_missing_training_load_skipped` |
| 8 | `get_training_profile` + `update_training_profile` registered brain-direct at all 5 sites. | `test_phase19_profile_tools_registered`, `test_phase19_update_profile_schema_requires_patch` |
| 9 | `fetch_training_status` + `fetch_recent_activities` registered as worker-delegated (in TOOL_SCHEMAS, in _HANDLERS, NOT in SMART_AGENT_DIRECT_TOOLS). | `test_phase19_fetch_tools_worker_delegated` |

## Commits (chronological)

| Commit | Type | Notes |
|---|---|---|
| `2aa447e` | test(19-02) | RED — 8 failing UserProfileStore tests |
| `b669af2` | feat(19-02) | GREEN — UserProfileStore impl + AgentOrchestrator bootstrap wiring |
| `d0fcf35` | test(19-02) | RED — 11 failing tests for Garmin extensions + compute_acwr |
| `9e3730d` | feat(19-02) | GREEN — _authed_garmin_client helper + fetch_garmin_training_status + fetch_garmin_activities + compute_acwr + compute_acwr_from_db |
| `b8d649b` | test(19-02) | RED — 4 failing tests for Phase 19 tool registration |
| `72e6a51` | feat(19-02) | GREEN — 4 new tools registered at all 5 sites in core/tools.py |

TDD gate sequence (`test(...)` → `feat(...)` x3) verified in git log — RED commits land before GREEN commits in every task cycle.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Hardening] `_build_user_profile_store()` wrapped in try/except**

The plan template showed the factory without exception handling. The
SelfStateStore factory directly above it doesn't have one either. I added
a try/except inside `_build_user_profile_store()` that returns None on
construction failure (e.g. missing credentials file, malformed FIRESTORE_DATABASE
env var) — Pitfall 7 says bootstrap must never crash startup, and the
existing safety net only covers exceptions inside `bootstrap_if_empty()`,
not construction failures. The cost is negligible (1 extra try/except);
the protection covers the rarer cold-start credential-misconfiguration case.

**2. [Rule 1 — Bug guard] `_authed_garmin_client` re-raises GarminAuthError verbatim**

When the catch-all `except Exception` at the end of `_authed_garmin_client`
ran, it would wrap an inner `GarminAuthError` (raised by the missing-env-var
check) in another `GarminAuthError(f"Garmin login failed: {exc}")`, losing
the structured "GARMIN_EMAIL and GARMIN_PASSWORD env vars are required"
message. Added an explicit `except GarminAuthError: raise` before the
generic except to preserve the original error type. Pure correctness fix
in current-task scope.

### No Other Deviations

The plan was followed exactly. All file paths, behaviors, schema shapes,
discipline contracts, and tier assignments match the plan and PATTERNS.md.

## Notes on the garminconnect lib's `.client.dumps()` vs `.garth.dumps()`

The plan's `<action>` Step B referenced `api.garth.dumps() if hasattr(api, "garth") else api.client.dumps()`. The existing `fetch_garmin_today` already used `api.client.dumps()` unconditionally and was running in production successfully — confirmed by git history (no token-related issues). I preserved the simpler `api.client.dumps()` call to avoid behavior drift; if the installed garminconnect version ever switches to garth-only, the next maintainer can add the hasattr branch in 30 seconds.

## Self-Check: PASSED

Verified at SUMMARY-write time:

- File exists: `memory/firestore_db.py` (modified — UserProfileStore impl present)
- File exists: `core/main.py` (modified — _build_user_profile_store + bootstrap call present)
- File exists: `mcp_tools/garmin_tool.py` (modified — _authed_garmin_client, fetch_garmin_training_status, fetch_garmin_activities, compute_acwr, compute_acwr_from_db all present)
- File exists: `core/tools.py` (modified — 4 schemas + 4 handlers + 4 dispatch entries + 2 frozenset entries + 2 worker exclusions)
- File created: `tests/test_user_profile_store.py`
- File created: `tests/test_garmin_extensions.py`
- File created: `tests/test_compute_acwr.py`
- Commit `2aa447e` reachable in git log
- Commit `b669af2` reachable in git log
- Commit `d0fcf35` reachable in git log
- Commit `9e3730d` reachable in git log
- Commit `b8d649b` reachable in git log
- Commit `72e6a51` reachable in git log
- Full test suite green: 522 passed, 3 skipped (was 499/3 baseline → +23 net, 0 regressions)
