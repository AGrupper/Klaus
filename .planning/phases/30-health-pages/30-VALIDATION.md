---
phase: 30
slug: health-pages
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-06
---

# Phase 30 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend, per-file execution — full-suite single invocation segfaults on grpc/protobuf GC); vitest + @testing-library/react (frontend) |
| **Config file** | `pytest.ini`/`pyproject.toml` (backend, unmodified); `frontend/vitest.config.ts` (frontend, unmodified) |
| **Quick run command** | Backend: `pytest tests/test_health_<area>_api.py -x` · Frontend: `cd frontend && npx vitest run <file>` |
| **Full suite command** | Backend: per-file pytest loop (baseline 1720+ green) · Frontend: `cd frontend && npm test` (baseline 122+ green) |
| **Estimated runtime** | ~5–15s per file quick; minutes for full loops |

---

## Sampling Rate

- **After every task commit:** Run the relevant single test file (`pytest tests/test_health_X.py -x` or `npx vitest run <file>`)
- **After every plan wave:** Full backend per-file loop + `cd frontend && npm test`
- **Before `/gsd:verify-work`:** Both full suites green (1720+ backend, 122+ frontend baselines must hold)
- **Max feedback latency:** ~30 seconds per quick run

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | HLTH-01 | — | `GET /api/health/training` behind session auth; range-filtered merged strength+run+benchmark entries | integration | `pytest tests/test_health_training_api.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HLTH-01 | — | `BenchmarkStore.get_range()` returns docs in [start,end], newest-first, `[]` on error | unit | `pytest tests/test_firestore_db.py -k benchmark_get_range -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HLTH-01 | — | `TrainingHistoryPage` renders mixed log with modality color-coding + drill-down | component | `npx vitest run src/components/health/training/TrainingLog.test.tsx` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HLTH-02 | — | `GET /api/health/nutrition` returns per-day/weekly series + `missing_dates` (never zero-filled) + targets | integration | `pytest tests/test_health_nutrition_api.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HLTH-02 | — | `SlotAdherenceGrid` keys cells on slot LABEL only (never derived time) | component | `npx vitest run src/components/health/nutrition/SlotAdherenceGrid.test.tsx` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HLTH-03 | — | `GET /api/health/sleep` returns HRV/sleep/body-battery series + `pipeline_active` flag distinct from empty range | integration | `pytest tests/test_health_sleep_api.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HLTH-03 | — | Postgres range reader returns `[]` on connection failure, never raises | unit | `pytest tests/test_health_sleep_api.py -k range_reader -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-08 | — | Charts render a visible break (not zero, not interpolated) for `null` points | component | `npx vitest run src/components/charts/LineChart.test.tsx -t gap` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-07 | — | >90-day ranges weekly-bucketed; ≤90-day daily | unit | `pytest tests/test_health_*.py -k weekly_bucket -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_health_training_api.py` — HLTH-01 stubs (mirror `tests/test_api_today.py` `_stub_web_server_imports` pattern)
- [ ] `tests/test_health_nutrition_api.py` — HLTH-02 stubs
- [ ] `tests/test_health_sleep_api.py` — HLTH-03 stubs (needs a Postgres-mock fixture; reuse existing psycopg2-mocking convention from garmin/database tool tests)
- [ ] `BenchmarkStore.get_range` unit tests — add to the file that already tests `BenchmarkStore` (locate via `grep -rn "BenchmarkStore" tests/`)
- [ ] `frontend/src/components/charts/LineChart.test.tsx` + `BarChart.test.tsx` — gap-rendering (D-08) is highest-value
- [ ] `frontend/src/components/health/**/*.test.tsx` — one smoke test per new page component minimum (follow `ContributionGrid.test.tsx` convention)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Deployed hub pages render correctly on iPhone Safari | HLTH-01/02/03 | SPA/auth paths have no CI coverage (frontend/dist absent from CI); prior phases hit deploy-only bugs | Open deployed hub URL on iPhone, navigate to each health page, verify charts render and range picker works |
| `klaus-biometric-sync` pipeline liveness | HLTH-03 | Scheduler registration/backfill state is a production concern, not testable locally | Check Cloud Scheduler job list + `daily_biometrics` row recency; verify "pipeline isn't syncing yet" guard displays when stale |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
