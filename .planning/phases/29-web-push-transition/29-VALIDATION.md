---
phase: 29
slug: web-push-transition
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-02
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `29-RESEARCH.md` § Validation Architecture. Task IDs are assigned by the planner;
> the per-task map below is filled in as plans land.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (backend)** | pytest (existing `tests/`, fakes in `tests/fakes.py`) — run **per-file** (full-suite segfault, STATE.md) |
| **Framework (frontend)** | vitest 3.2.4 + @testing-library/react (existing `frontend/src/**/*.test.tsx`) |
| **Config file** | none explicit for pytest; `frontend/package.json` `"test": "vitest"` |
| **Quick run command** | `pytest tests/test_push_sender.py -x -q` / `cd frontend && npx vitest run src/hooks/usePush.test.ts` |
| **Full suite command** | per-file pytest over new+touched files; `cd frontend && npx vitest run` |
| **Estimated runtime** | ~15–30s per file group |

---

## Sampling Rate

- **After every task commit:** Run the touched file's pytest file (`pytest tests/test_<touched>.py -x -q`) or targeted `npx vitest run <file>`
- **After every plan wave:** All phase-29 test files per-file + `cd frontend && npx vitest run` + `npm run build` (SW smoke grep)
- **Before `/gsd:verify-work`:** 1153+ baseline holds (per-file), frontend suite green, build smoke green, then D-20 physical UAT
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| — | — | — | PUSH-01 | TBD | `PushSubscriptionStore` upsert/list_all/delete/record_* (endpoint-hash doc id, `_jsonsafe_doc` reads) | unit | `pytest tests/test_push_subscription_store.py -x` | ❌ W0 | ⬜ pending |
| — | — | — | PUSH-01 | TBD | `POST /api/push/subscribe` validates + upserts; rejects non-https endpoint / missing keys; 401 without session | integration | `pytest tests/test_push_api.py::TestSubscribe -x` | ❌ W0 | ⬜ pending |
| — | — | — | PUSH-01 | — | `usePush` re-validation (granted+null-sub → resubscribe; denied → banner state) | unit | `cd frontend && npx vitest run src/hooks/usePush.test.ts` | ❌ W0 | ⬜ pending |
| — | — | — | PUSH-02 | TBD | `send_push_to_all`: fan-out, per-class TTL, 404/410 delete, failure_count, fresh claims dict, timeout param | unit | `pytest tests/test_push_sender.py -x` | ❌ W0 | ⬜ pending |
| — | — | — | PUSH-02 | — | `send_and_inject` order: D-02 gate → push (executor) → mirror gate → inject; existing callers unaffected | unit | `pytest tests/test_scheduled_message.py -x` | ⚠️ extend | ⬜ pending |
| — | — | — | PUSH-02 | — | sw.ts push handler always calls showNotification inside waitUntil (incl. badge-failure path) | unit | `cd frontend && npx vitest run src/sw.test.ts` | ❌ W0 | ⬜ pending |
| — | — | — | PUSH-02 | — | Push arrives on locked physical iPhone (chat reply + one proactive class) | **manual** | 29-HUMAN-UAT.md (D-20) | ❌ W0 | ⬜ pending |
| — | — | — | PUSH-03 | TBD | `HubSettingsStore` get/update; mirror default ON; `toggle_telegram_mirror` + `get_push_health` in `_HANDLERS` + brain-direct list | unit | `pytest tests/test_hub_settings_store.py tests/test_tools.py -x -k "mirror or push_health"` | ❌ W0 | ⬜ pending |
| — | — | — | PUSH-03 | — | Mirror OFF → no Telegram send, push+inject still run; mirror ON → both | unit | `pytest tests/test_scheduled_message.py -x -k mirror` | ⚠️ extend | ⬜ pending |
| — | — | — | PUSH-03 | — | Heartbeat `_check_push_health` signals (failure-streak, no-subscription, severity by mirror state) | unit | `pytest tests/test_heartbeat.py -x -k push` | ⚠️ extend | ⬜ pending |
| — | — | — | PUSH-04 | — | Badge reconcile hook: setAppBadge(unread), clearAppBadge at 0, RESET_BADGE postMessage | unit | `cd frontend && npx vitest run src/hooks/useAppBadge.test.ts` | ❌ W0 | ⬜ pending |
| — | — | — | PUSH-04 | — | Icon badge visible on iPhone after closed-app push; clears on chat view | **manual** | 29-HUMAN-UAT.md | ❌ W0 | ⬜ pending |
| — | — | — | HUB-03 (regression) | — | Built `dist/sw.js` contains html-cache NetworkFirst + assets CacheFirst + SKIP_WAITING listener | smoke | `cd frontend && npm run build && grep -q html-cache dist/sw.js && grep -q SKIP_WAITING dist/sw.js` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs/waves filled in by planner.*

---

## Wave 0 Requirements

- [ ] `tests/test_push_subscription_store.py` — PUSH-01 store stubs
- [ ] `tests/test_push_api.py` — PUSH-01 routes (model on `tests/test_hub_chat.py` client fixtures)
- [ ] `tests/test_push_sender.py` — PUSH-02 sender (mock `pywebpush.webpush`)
- [ ] `tests/test_hub_settings_store.py` — PUSH-03 flag store
- [ ] `frontend/src/sw.test.ts` — SW handler tests (mocked `self`/`registration`; exclude sw.ts from app tsc build if needed)
- [ ] `frontend/src/hooks/usePush.test.ts`, `useAppBadge.test.ts`
- [ ] `29-HUMAN-UAT.md` — D-20 device checklist + D-21 mirror-week tracking items
- [ ] Install: `pywebpush` in requirements.txt; workbox devDeps (gated per Package Legitimacy Audit — [ASSUMED] tags, human-verify checkpoint)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Push arrives on locked physical iPhone (chat reply + one proactive class, app closed) | PUSH-02 | No automation can exercise APNs + iOS notification rendering (D-20) | 29-HUMAN-UAT.md device checklist |
| Icon badge appears after closed-app push; clears when chat is viewed | PUSH-04 | iOS home-screen badge rendering is device-only | 29-HUMAN-UAT.md |
| Mirror week: every push has a matching Telegram buzz (double-buzz detector) | PUSH-03 | 1-week production observation (D-21) | 29-HUMAN-UAT.md tracked post-phase items |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
