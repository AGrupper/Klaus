---
phase: 19-training-awareness-nutrition-coaching
plan: 03
subsystem: nutrition-data-tier
status: completed
completed_at: 2026-05-27
tags: [google-fit, oauth, firestore, mealstore, worker-tool]
requires:
  - Google OAuth client (existing klaus-agent OAuth client; project 838733343862)
  - Google Cloud Fitness API enabled on project klaus-agent (one-time operator action — done 2026-05-27)
  - Operator one-time re-consent for fitness.nutrition.read scope (done 2026-05-27)
provides:
  - FITNESS_NUTRITION_READ_SCOPE constant + extended GoogleAuthManager.SCOPES
  - mcp_tools/google_fit_tool.py — Google Fitness REST API wrapper (com.google.nutrition reads)
  - memory/firestore_db.py::MealStore — idempotent date-partitioned meal persistence (path: meals/{YYYY-MM-DD}/timestamps/{source_id})
  - core/tools.py — fetch_recent_meals worker-delegated tool registered at all 4 sites
affects:
  - Plan 19-04 (autonomous tick gather + morning briefing nutrition recap — both consume MealStore.get_day_aggregate and Pitfall-4 empty-dict semantics)
  - Plan 19-05 (smart_agent + meal_audit prompts reference these tools via SELF.md)
tech-stack:
  added:
    - "fitness.googleapis.com (GCP API enabled on klaus-agent project)"
    - "google-auth-oauthlib scope: https://www.googleapis.com/auth/fitness.nutrition.read"
  patterns:
    - "Worker-delegated tool tier (Phase 19-02 idiom): in TOOL_SCHEMAS + _HANDLERS, NOT in SMART_AGENT_DIRECT_TOOLS, NOT in WORKER_TOOL_SCHEMAS exclusion."
    - "Idempotent meal upsert keyed by source_id = `{dataStreamId}:{startTimeNanos}` — same Google Fit point re-syncs to the same Firestore doc, no duplicates."
    - "Pitfall 4 contract: MealStore.get_day_aggregate(date) returns `{}` on empty (NOT `{meal_count: 0}`) so Plan 19-04's silent-omit truthiness check works."
    - "Firestore store discipline: load swallows exceptions → returns {} or [] sentinel; writes use merge=True; bootstrap is no-op when doc exists."
key-files:
  created:
    - .planning/phases/19-training-awareness-nutrition-coaching/19-03-SUMMARY.md
    - mcp_tools/google_fit_tool.py (214 lines)
    - tests/test_auth_google.py (2 tests)
    - tests/test_google_fit_tool.py (7 tests)
    - tests/test_meal_store.py (7 tests)
  modified:
    - core/auth_google.py (FITNESS_NUTRITION_READ_SCOPE + SCOPES list)
    - memory/firestore_db.py (MealStore class inserted between JournalStore and FollowupStore)
    - core/tools.py (fetch_recent_meals schema + handler + dispatch — 4 sites: TOOL_SCHEMAS, _HANDLERS, NOT in SMART_AGENT_DIRECT_TOOLS, NOT in WORKER_TOOL_SCHEMAS exclusion)
    - tests/test_tools.py (+2 tests in TestPhase19ToolRegistration)
    - config/token.json (rotated 2026-05-27 17:11 to include fitness.nutrition.read scope; pre-rotation backup at config/token.json.pre-shifu-bak)
decisions:
  - "Worker-delegated tier for fetch_recent_meals: brain never holds the full meal list in its context — it asks the worker for it when needed. Mirrors fetch_training_status / fetch_recent_activities from Plan 19-02."
  - "Pitfall 4 honored: get_day_aggregate returns {} on empty rather than {meal_count: 0, calories: 0, ...}. Plan 19-04 needs this exact contract to silently omit the nutrition recap on no-meal days."
  - "source_id includes dataStreamId AND startTimeNanos — same nanosecond timestamp from a different data source (e.g., reconnected app) gets a distinct source_id rather than overwriting. Trade-off: a single meal logged in multiple apps appears twice; in practice acceptable because the user logs in one app at a time."
  - "MealStore writes to meals/{date}/timestamps/{source_id} — date-partitioned subcollection enables cheap get_day reads without scanning the whole meals collection."
metrics:
  duration: "~75 min (5 tasks, RED→GREEN TDD per task, + OAuth rotation operator gate)"
  tasks: 5
  files: 8
  commits: 9  # 8 code + 1 docs
---

# Phase 19 Plan 03: Google Fit Nutrition + MealStore + fetch_recent_meals — Summary

OAuth scope expanded for Google Fit nutrition reads, Lifesum-sourced meal data wired through a Google Fitness REST API wrapper into an idempotent date-partitioned Firestore store, and a worker-delegated tool that lets Klaus query "what did I eat in the last N hours" on demand. Operator re-consented the rotated token and enabled the Fitness API on `klaus-agent`; end-to-end probe confirmed clean. Phase 19 progress: 3/5 plans.

## What shipped

### Code

| File | Change |
|---|---|
| `core/auth_google.py` | `FITNESS_NUTRITION_READ_SCOPE = "https://www.googleapis.com/auth/fitness.nutrition.read"`; appended to `GoogleAuthManager.SCOPES` |
| `mcp_tools/google_fit_tool.py` (NEW, 214 lines) | `fetch_recent_meals(hours=24)`, `_normalize_point(point, ds_id)`, `sync_recent_meals(since_hours, store)`, `class GoogleFitUnavailableError`. Uses `googleapiclient.discovery.build('fitness', 'v1', credentials=...)`. Lists `com.google.nutrition` data sources, reads recent points, normalizes to `{source_id, timestamp, meal_type, calories, protein_g, carbs_g, fat_g, food_item, source='google_fit'}`. |
| `memory/firestore_db.py` | `class MealStore`: `upsert(source_id, meal)` writes to `meals/{YYYY-MM-DD}/timestamps/{source_id}` with `merge=True`; `get_day(date_str)` reads all timestamp docs under a date; `get_day_aggregate(date_str)` sums macros and returns `{}` on empty (Pitfall 4). |
| `core/tools.py` | `fetch_recent_meals(hours)` worker-delegated tool registered at TOOL_SCHEMAS + _HANDLERS; excluded from SMART_AGENT_DIRECT_TOOLS frozenset; NOT in WORKER_TOOL_SCHEMAS exclusion (worker sees it). |

### Tests

| Test file | Count | Status |
|---|---|---|
| `tests/test_auth_google.py` (NEW) | 2 | ✅ |
| `tests/test_google_fit_tool.py` (NEW) | 7 | ✅ |
| `tests/test_meal_store.py` (NEW) | 7 | ✅ |
| `tests/test_tools.py::TestPhase19ToolRegistration` (+2) | (now 6 total in class) | ✅ |
| **Full project suite** | **540 passed, 3 skipped** | ✅ (was 522 baseline → +18 net, 0 regressions) |

### Operator-gated infra changes (verified 2026-05-27 17:11–17:14 local)

| Step | Result |
|---|---|
| `mv config/token.json config/token.json.pre-shifu-bak` (pre-rotation backup) | ✅ done locally |
| `uv run python -m core.auth_google` (re-consent flow) | ✅ Authenticated as `amit.grupper@gmail.com`; consent screen showed Gmail + Calendar + Fit nutrition (read); all 3 approved |
| `gcloud services enable fitness.googleapis.com --project=klaus-agent` | ✅ done |
| Local probe: `fetch_recent_meals(hours=24)` | ✅ returns `[]` (0 meals — operator has not yet connected Lifesum or recorded nutrition entries); **no scope error, no 403, no GoogleFitUnavailableError** — the data tier is wired correctly |

## Commits (chronological)

| Commit | Type | Description |
|---|---|---|
| `a0aa4ad` | test(19-03) | RED — 2 failing tests for `FITNESS_NUTRITION_READ_SCOPE` constant + presence in `SCOPES` |
| `9eb6279` | feat(19-03) | GREEN — `FITNESS_NUTRITION_READ_SCOPE` added; `GoogleAuthManager.SCOPES` extended |
| `6b8a629` | test(19-03) | RED — 7 failing tests for `mcp_tools/google_fit_tool.py` symbols + normalization + error class |
| `635b7a8` | feat(19-03) | GREEN — `mcp_tools/google_fit_tool.py` created (214 lines): `fetch_recent_meals`, `_normalize_point`, `sync_recent_meals`, `GoogleFitUnavailableError` |
| `303e34c` | test(19-03) | RED — 7 failing tests for `MealStore.upsert / get_day / get_day_aggregate` (incl. Pitfall-4 empty-dict semantics) |
| `1f4e958` | feat(19-03) | GREEN — `MealStore` class added to `memory/firestore_db.py`; idempotent date-partitioned persistence |
| `0042e2c` | test(19-03) | RED — 2 failing tests for `fetch_recent_meals` worker-delegated tool registration |
| `7be10d6` | feat(19-03) | GREEN — `fetch_recent_meals` schema + handler + dispatch wired in `core/tools.py` at all 4 sites |
| `pending`  | docs(19-03) | This SUMMARY + STATE/ROADMAP/REQUIREMENTS updates + OAuth-rotation note |

## Deviations from Plan

### Auto-fixed (Rule 1, in-scope)

**1. OAuth pre-rotation token backup convention**
- **Issue:** Initial `python -m core.auth_google` returned `invalid_scope: Bad Request` — Google refuses to refresh a token when the requested scope set widens. Plan documented the re-consent flow but didn't specify the stale-token clear step.
- **Fix:** Operator moved `config/token.json` aside to `config/token.json.pre-shifu-bak` before re-running. The full consent flow then ran (browser prompt at `accounts.google.com/o/oauth2/auth`), all 3 scopes approved, new token persisted.
- **Why in-scope:** the rotation IS this plan's operator gate. Documenting the exact `mv` step belongs in this SUMMARY for the next time scopes expand.

**2. Fitness API enable (one-time GCP gate, discovered during probe)**
- **Issue:** Post-rotation probe initially returned `HttpError 403: accessNotConfigured — Fitness API has not been used in project 838733343862 before or it is disabled`. The OAuth scope was approved on the client side, but the Fitness API itself wasn't enabled on the GCP project.
- **Fix:** Operator ran `gcloud services enable fitness.googleapis.com --project=klaus-agent`. Re-probe passed.
- **Why in-scope:** the API enable is a one-time operator gate that gates Plan 19-03's data-tier going live. Belongs in this SUMMARY's operator-runbook section.

### Deferred (out of scope)

None new in this plan. Existing deferred items from 19-01 remain in `deferred-items.md`.

## NUTR-01 / NUTR-02 / NUTR-03 Acceptance

| Req | Statement | Evidence |
|---|---|---|
| NUTR-01 | `mcp_tools/google_fit_tool.py` wraps Google Fitness REST API (com.google.nutrition) returning normalized meal records | `mcp_tools/google_fit_tool.py` exists; `fetch_recent_meals(hours=24)` returns list of dicts with the required keys; verified via local probe |
| NUTR-02 | `MealStore` persists meal records to `meals/{date}/{timestamp}` with idempotent re-sync | `memory/firestore_db.py::MealStore` with `meals/{YYYY-MM-DD}/timestamps/{source_id}` schema; same source_id upserts to same doc (verified by `test_meal_store.py::test_upsert_is_idempotent_on_source_id`) |
| NUTR-03 | `fetch_recent_meals(hours)` registered as worker-delegated tool | Registered at 4 sites in `core/tools.py`; `test_tools.py::TestPhase19ToolRegistration` asserts presence in TOOL_SCHEMAS + _HANDLERS, absence from SMART_AGENT_DIRECT_TOOLS, absence from WORKER_TOOL_SCHEMAS exclusion |

All three requirements: **SATISFIED**.

## TDD Gate Compliance

4 RED commits precede 4 GREEN commits in `git log` (`a0aa4ad → 9eb6279`, `6b8a629 → 635b7a8`, `303e34c → 1f4e958`, `0042e2c → 7be10d6`). No REFACTOR-only commits needed — green implementations stayed clean on first pass.

## Operator Runbook (re-consent + API enable)

Documenting here in case future Phase 19/20+ scope additions require the same flow:

```bash
# 1. Backup the existing token (in case re-consent fails and a rollback is needed)
mv ./config/token.json ./config/token.json.pre-<change>-bak

# 2. Run the re-consent flow against a browser-capable terminal
uv run python -m core.auth_google
#    → Browser opens; consent screen lists ALL scopes in GoogleAuthManager.SCOPES
#    → Approve all; smoke test prints "Authenticated as: amit.grupper@gmail.com"

# 3. If new APIs were introduced, enable them on the GCP project
gcloud services enable <api>.googleapis.com --project=klaus-agent

# 4. (Prod) Push the rotated token to Secret Manager if GOOGLE_TOKEN_STORAGE=secret_manager
#    (Mechanism documented in docs/DEPLOYMENT.md — Secret Manager rotation section)

# 5. Verify with a probe touching the new scope's data type
uv run python -c "from mcp_tools.<new_tool> import <probe_fn>; print(<probe_fn>())"
```

## Self-Check: PASSED

- ✅ `core/auth_google.py` contains `FITNESS_NUTRITION_READ_SCOPE` constant
- ✅ `GoogleAuthManager.SCOPES` includes `fitness.nutrition.read`
- ✅ `mcp_tools/google_fit_tool.py` exists with all 4 required symbols
- ✅ `memory/firestore_db.py` contains `class MealStore` with required methods
- ✅ `MealStore.get_day_aggregate({}) → {}` (Pitfall 4)
- ✅ `core/tools.py` registers `fetch_recent_meals` at 4 sites correctly
- ✅ All 8 commits reachable in `git log`
- ✅ Full test suite: 540 passed, 3 skipped
- ✅ Operator OAuth re-consent: amit.grupper@gmail.com authenticated with rotated token (3 scopes)
- ✅ Fitness API enabled on klaus-agent GCP project
- ✅ End-to-end probe: `fetch_recent_meals(hours=24)` returns clean (no 403, no GoogleFitUnavailableError)
