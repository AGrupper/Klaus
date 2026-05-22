# Deferred Items — Phase 18

## Pre-existing test ordering issue
- **Found during:** 18-01 execution (2026-05-22)
- **Test:** `tests/test_heartbeat.py::test_cron_heartbeat_rejects_unauthenticated`
- **Symptom:** Passes in isolation; fails when run after `test_llm_usage_store.py` or `test_reflection.py` in the same pytest session due to sys.modules google.cloud.firestore mock pollution.
- **Verified pre-existing:** Reproduced on commit `7a4895c` with our changes stashed.
- **Out of scope for Plan 18-01** (Rule 4 — not caused by this task; affects multiple unrelated test files).
- **Recommendation:** A future Phase 18 plan (or test-hygiene chore) should add a per-test `conftest.py` cleanup that restores `sys.modules['google.cloud.firestore']` to a sentinel after each test_*_store.py module finishes. Not blocking the autonomous-engine roadmap.
- [Plan 18-04 / 2026-05-22] tests/test_tools.py ImportError on `googleapiclient` in local env. Pre-existing — not caused by Plan 18-04 changes. CI/Cloud Run env has the package; only the local dev env is missing it. Out of scope.
