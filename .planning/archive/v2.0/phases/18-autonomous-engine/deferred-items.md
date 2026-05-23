# Deferred Items — Phase 18

## Pre-existing test ordering issue
- **Found during:** 18-01 execution (2026-05-22)
- **Test:** `tests/test_heartbeat.py::test_cron_heartbeat_rejects_unauthenticated`
- **Symptom:** Passes in isolation; fails when run after `test_llm_usage_store.py` or `test_reflection.py` in the same pytest session due to sys.modules google.cloud.firestore mock pollution.
- **Verified pre-existing:** Reproduced on commit `7a4895c` with our changes stashed.
- **Out of scope for Plan 18-01** (Rule 4 — not caused by this task; affects multiple unrelated test files).
- **Recommendation:** A future Phase 18 plan (or test-hygiene chore) should add a per-test `conftest.py` cleanup that restores `sys.modules['google.cloud.firestore']` to a sentinel after each test_*_store.py module finishes. Not blocking the autonomous-engine roadmap.
- [Plan 18-04 / 2026-05-22] tests/test_tools.py ImportError on `googleapiclient` in local env. Pre-existing — not caused by Plan 18-04 changes. CI/Cloud Run env has the package; only the local dev env is missing it. Out of scope.
- [Plan 18-08 / 2026-05-23] `tests/test_web_server.py` ImportError on `fastapi` in local env. Pre-existing — reproduced on HEAD before any Plan 18-08 changes (`No module named 'fastapi'` at `interfaces/web_server.py:32`). CI/Cloud Run env has the package; only the local dev env is missing it. Out of scope for Plan 18-08 (Rule 4: scope boundary).
- [Plan 18-09 / 2026-05-23] Same fastapi local-env block re-encountered (5 tests in `TestCronAutonomousTick` + `test_cron_heartbeat_rejects_unauthenticated`). Confirmed unchanged by Plan 18-09 (docs-only plan touches `docs/DEPLOYMENT.md` + `tests/test_docs.py`). 155/155 non-fastapi tests in the Plan 18-09 regression suite pass cleanly.
- [Master audit / 2026-05-23] `google.genai` local-env import block — 4 tests in `tests/test_llm_client.py` (3) + `tests/memory/test_pinecone_embed.py` (1) fail with `ModuleNotFoundError: No module named 'google.genai'` at `core/llm_client.py:312,397` and `memory/pinecone_db.py:225`. Same family as fastapi/googleapiclient — CI/Cloud Run env has the package; local dev venv missing it. Suggest: `uv add google-genai` to dev requirements when next touching the venv. Not a regression; reproducible on HEAD before any Phase 18 work.

## Post-review backlog (Phase 19 hardening — from 18-REVIEW.md, 2026-05-23)

Landed in `fix(18): post-review cleanup`: H-1, M-1, M-5.

Deferred (low-impact, not blockers; pick up in next housekeeping sweep):
- **M-2** `_compose_followup` parses `followup["due_at"]` without `Z`-suffix / `None` guard (`core/autonomous.py:645`). Mirror `gather_situation`'s `s_raw.replace("Z", "+00:00")` and fall back to "defer 1h from now" on parse failure. Defensive only — `FollowupStore.add` writes proper ISO today.
- **M-3** `gather_situation` silently treats Firestore/Calendar outage as "empty" → tick suppressed with heartbeat `ok=True` (no degraded-mode signal). Add `source_errors: list[str]` to the gathered dict and downgrade `empty` to `False` if any source erred.
- **M-4** `_handle_cancel_followup(id: str)` shadows builtin `id` (`core/tools.py:1321`). Mechanical rename (`id` → `followup_id`) across schema, handler, 3 test sites, prompt doc. Harmless within function scope, but ruff A002 flags it.
- **L-1** `core/autonomous.py` is 825 LOC — past comfortable single-file size. Split `gather_situation` + `_calendar_has_gap_or_overload` into `core/autonomous_gather.py` when the next Layer-0 source is added.
- **L-2** `_synthesize_topic_key` uses `title.lower()[:30]` — collisions silently dedupe two distinct overdue tasks. Append `task_id[:6]` for resistance.
- **L-3** `_TICK_TOTAL_PER_DAY = 43` hard-coded; will drift if cron schedule changes. Either derive from `now` window, or add an inline comment naming the cron contract.
- **L-4** Logger inconsistency (`logger.warning` vs `logger.error`) for similar failures. Add a top-of-file comment naming the convention.
- **L-5** `_compose_followup_layer2` snapshot drops `unread_email_count` + `hours_since_contact` — Layer 2's "is the moment wrong?" judgment runs on less info than triage. Add both fields (exclude `due_followups` to avoid recursion).
