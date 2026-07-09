---
phase: 29
slug: web-push-transition
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-02
updated: 2026-07-09
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `29-RESEARCH.md` § Validation Architecture. Per-task map reconciled
> against the final 10-plan set (2026-07-03, post-checker revision).

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
| 29-03-T1 | 29-03 | 1 | PUSH-01 | T-29-03 | `PushSubscriptionStore` upsert/list_all/delete/record_* (endpoint-hash doc id, `_jsonsafe_doc` reads) | unit | `pytest tests/test_push_subscription_store.py -x` | ❌ W0 (created in-task, tdd) | ⬜ pending |
| 29-06-T1 | 29-06 | 2 | PUSH-01 | T-29-10, T-29-11 | `POST /api/push/subscribe` validates + upserts; rejects non-https endpoint / missing keys; 401 without session; first success stamps `push_enabled_at` | integration | `pytest tests/test_push_api.py -x -k "Subscribe or vapid"` | ❌ W0 (created in-task, tdd) | ⬜ pending |
| 29-09-T1 | 29-09 | 3 | PUSH-01 | T-29-19 | `usePush` re-validation (granted+null-sub → resubscribe; denied → banner state) | unit | `cd frontend && npx vitest run src/hooks/usePush.test.ts` | ❌ W0 (created in-task, tdd) | ⬜ pending |
| 29-04-T1 | 29-04 | 2 | PUSH-02 | T-29-05, T-29-07 | `send_push_to_all`: fan-out, per-class TTL, 404/410 delete, failure_count, fresh claims dict, timeout param; `body=text[:1000]` (documented D-12 deviation, A8) | unit | `pytest tests/test_push_sender.py -x` | ❌ W0 (created in-task, tdd) | ⬜ pending |
| 29-08-T1 | 29-08 | 3 | PUSH-02 | T-29-16 | `send_and_inject` order: D-02 gate → push (executor) → mirror gate → inject; existing callers unaffected | unit | `pytest tests/test_scheduled_message.py -x` | ⚠️ extend | ⬜ pending |
| 29-08-T3 | 29-08 | 3 | PUSH-02 (D-02) | T-29-17 | Chat poll carries `chat_visible=1` while chat visible (client half of the server-side suppression gate) | unit | `cd frontend && npx vitest run src/hooks/useChat.test.tsx` | ⚠️ extend | ⬜ pending |
| 29-07-T2 | 29-07 | 2 | PUSH-02 | T-29-13 | sw.ts push handler always calls showNotification inside waitUntil (incl. badge-failure path) | unit | `cd frontend && npx vitest run src/sw.test.ts` | ❌ W0 (created in-task, tdd) | ⬜ pending |
| 29-10-T3 | 29-10 | 4 | PUSH-02 | — | Push arrives on locked physical iPhone (chat reply + one proactive class) | **manual** | 29-HUMAN-UAT.md (D-20) | ❌ W0 (doc created in 29-02-T3) | ⬜ pending |
| 29-03-T2 + 29-05-T1 | 29-03 / 29-05 | 1 / 2 | PUSH-03 | T-29-08 | `HubSettingsStore` get/set; mirror default ON; `toggle_telegram_mirror` + `get_push_health` in `_HANDLERS` + brain-direct list (no chat_visible_until in tool output) | unit | `pytest tests/test_hub_settings_store.py -x` + `pytest tests/test_tools.py -x -k "mirror or push_health"` | ❌ W0 (created in-task, tdd) | ⬜ pending |
| 29-08-T1 | 29-08 | 3 | PUSH-03 | T-29-18 | Mirror OFF → no Telegram send, push+inject still run; mirror ON → both | unit | `pytest tests/test_scheduled_message.py -x -k mirror` | ⚠️ extend | ⬜ pending |
| 29-05-T2 | 29-05 | 2 | PUSH-03 | — | Heartbeat `_check_push_health` signals (failure-streak, no-subscription, severity by mirror state) | unit | `pytest tests/test_heartbeat.py -x -k push` | ⚠️ extend | ⬜ pending |
| 29-09-T2 | 29-09 | 3 | PUSH-04 | — | Badge reconcile hook: setAppBadge(unread), clearAppBadge at 0, RESET_BADGE postMessage | unit | `cd frontend && npx vitest run src/hooks/useAppBadge.test.ts` | ❌ W0 (created in-task, tdd) | ⬜ pending |
| 29-10-T3 | 29-10 | 4 | PUSH-04 | — | Icon badge visible on iPhone after closed-app push; clears on chat view | **manual** | 29-HUMAN-UAT.md | ❌ W0 (doc created in 29-02-T3) | ⬜ pending |
| 29-07-T3 | 29-07 | 2 | HUB-03 (regression) | T-29-14 | Built `dist/sw.js` contains html-cache NetworkFirst + assets CacheFirst + SKIP_WAITING listener | smoke | `cd frontend && npm run build && grep -q html-cache dist/sw.js && grep -q SKIP_WAITING dist/sw.js` | ❌ W0 (build output) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs = `{plan}-T{task}` from the final 10-plan set.*

---

## Wave 0 Requirements

All Wave-0 test files are created *inside* their owning plan's tdd tasks (test-first), not as a separate pre-wave:

- [ ] `tests/test_push_subscription_store.py` — PUSH-01 store → **29-03-T1** (wave 1)
- [ ] `tests/test_hub_settings_store.py` — PUSH-03 flag store → **29-03-T2** (wave 1)
- [ ] `tests/test_push_sender.py` — PUSH-02 sender (mock `pywebpush.webpush`) → **29-04-T1** (wave 2)
- [ ] `tests/test_push_api.py` — PUSH-01 routes (model on `tests/test_hub_chat.py` fixtures) → **29-06-T1/T2** (wave 2)
- [ ] `frontend/src/sw.test.ts` — SW handler tests (mocked `self`/`registration`) → **29-07-T2** (wave 2)
- [ ] `frontend/src/hooks/usePush.test.ts`, `useAppBadge.test.ts` → **29-09-T1/T2** (wave 3)
- [ ] `frontend/src/hooks/useChat.test.tsx` extension (chat_visible=1 param) → **29-08-T3** (wave 3)
- [ ] `29-HUMAN-UAT.md` — D-20 device checklist + D-21 mirror-week tracking → **29-02-T3** (wave 1)
- [ ] Install: `pywebpush` in requirements.txt → **29-01** (gated checkpoint, wave 1); workbox devDeps → **29-02** (gated checkpoint, wave 1) — per Package Legitimacy Audit [ASSUMED] tags

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Push arrives on locked physical iPhone (chat reply + one proactive class, app closed) | PUSH-02 | No automation can exercise APNs + iOS notification rendering (D-20) | 29-HUMAN-UAT.md device checklist (29-10-T3) |
| Icon badge appears after closed-app push; clears when chat is viewed | PUSH-04 | iOS home-screen badge rendering is device-only | 29-HUMAN-UAT.md (29-10-T3) |
| Mirror week: every push has a matching Telegram buzz (double-buzz detector) | PUSH-03 | 1-week production observation (D-21) | 29-HUMAN-UAT.md tracked post-phase items |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (every auto task in plans 01–10 carries an `<automated>` command; manual-only items routed to 29-HUMAN-UAT.md)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (checkpoints in 29-01/02/10 are never 3-in-a-row)
- [x] Wave 0 covers all MISSING references (each ❌ W0 file is created by a named tdd task above)
- [x] No watch-mode flags (`vitest run` / `pytest -x -q` only)
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner (post-checker revision), 2026-07-03
