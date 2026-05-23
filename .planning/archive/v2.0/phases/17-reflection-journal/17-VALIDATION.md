---
phase: 17
slug: reflection-journal
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-19
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `17-RESEARCH.md` § "Validation Architecture".

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (14 `test_*.py` files in `tests/`; no `pytest.ini`/`pyproject.toml` config — defaults) |
| **Config file** | none — pytest uses defaults; `tests/__init__.py` present |
| **Quick run command** | `pytest tests/test_reflection.py -x -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~30 seconds (full suite, estimate — all stores mocked, no live I/O) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_reflection.py -x -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

> Task IDs assigned once PLAN.md files exist. The planner/executor fills this row-per-task.
> Requirement → test mapping below is locked from RESEARCH.md and must be honored.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-XX-XX | — | — | JOUR-02 | — | N/A | unit | `pytest tests/test_reflection.py::test_journal_store_roundtrip -x` | ❌ W0 | ⬜ pending |
| 17-XX-XX | — | — | JOUR-04 | — | N/A | unit | `pytest tests/test_reflection.py::test_recall_self_kind -x` | ❌ W0 | ⬜ pending |
| 17-XX-XX | — | — | JOUR-03 | — | N/A | unit | `pytest tests/test_reflection.py::test_remember_self_deterministic_id -x` | ❌ W0 | ⬜ pending |
| 17-XX-XX | — | — | JOUR-01 | — | N/A | unit | `pytest tests/test_reflection.py::test_run_reflection_writes_entry -x` | ❌ W0 | ⬜ pending |
| 17-XX-XX | — | — | JOUR-01 | — | failed gather source isolated | unit | `pytest tests/test_reflection.py::test_gather_source_failure_is_isolated -x` | ❌ W0 | ⬜ pending |
| 17-XX-XX | — | — | D-13 | — | brain+fallback failure → minimal doc | unit | `pytest tests/test_reflection.py::test_reflection_llm_failure_fallback -x` | ❌ W0 | ⬜ pending |
| 17-XX-XX | — | — | D-03 | T-17 V5 | hardened JSON parse of brain output | unit | `pytest tests/test_reflection.py::test_parse_reflection_json_hardened -x` | ❌ W0 | ⬜ pending |
| 17-XX-XX | — | — | JOUR-05 | T-17 V4 | `/cron/reflect` OIDC-authed; `CRON_DEV_BYPASS` dev-only | integration | `pytest tests/test_reflection.py::test_cron_reflect_route -x` | ❌ W0 | ⬜ pending |
| 17-XX-XX | — | — | JOUR-06 | — | digest absent from worker prompt | unit | `pytest tests/test_reflection.py::test_journal_digest_assembly -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_reflection.py` — covers JOUR-01 through JOUR-06 + D-03/D-13. Mock Firestore (`unittest.mock` of `_make_firestore_client`) and `LLMClient.chat`. Pattern references: `tests/test_proactive_alerts.py`, `tests/test_llm_usage_store.py`.
- [ ] `tests/conftest.py` — only if shared fixtures (mock Firestore client, mock `LLMClient`) are needed across files. Existing test files use per-file fixtures and no conftest — per-file fixtures suffice unless duplication grows.
- [ ] Framework install: none — `pytest` is already the project test runner.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `POST /cron/reflect` creates `journal/{today}` doc in live Firestore | JOUR-02 / JOUR-05 | Requires live Firestore project | `CRON_DEV_BYPASS=true` then POST `/cron/reflect`; confirm `journal/{today}` doc exists in Firestore console |
| `self_state` fields updated in live Firestore | JOUR-01 | Requires live Firestore project | After reflect run, confirm `current_focus`, `recent_context`, `mood` updated in `self_state` doc |
| `kind="self"` Pinecone upsert succeeds (no ValueError) | JOUR-03 | Requires live Pinecone index | After reflect run, query Pinecone for vector id `self-{today}` |
| Journal digest appears in next conversation's assembled prompt | JOUR-06 | Requires live conversation render | Send a message post-reflection; confirm `{journal_digest}` block present in smart prompt, absent from worker prompt |
| Cloud Scheduler `reflect` job runs daily ~22:00 Asia/Jerusalem | JOUR-05 | External GCP infra, created post-deploy via gcloud | Verify Cloud Scheduler job after deploy (see DEPLOYMENT.md) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`tests/test_reflection.py`)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
