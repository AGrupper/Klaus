---
phase: 26
slug: hub-shell
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-13
reviewed_at: 2026-06-14
---

# Phase 26 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) + vitest (frontend — Wave 0 plan 26-01 installs) |
| **Config file** | pytest: existing; vitest: `frontend/vitest.config.ts` (created by 26-01) |
| **Quick run command** | `pytest -q tests/ -k hub` |
| **Frontend run command** | `cd frontend && npm test -- --run` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~60 seconds (backend) + ~10s (frontend vitest) |

---

## Sampling Rate

- **After every task commit:** Run `pytest -q tests/ -k hub` (backend tasks) or `cd frontend && npm test -- --run` (frontend tasks)
- **After every plan wave:** Run `pytest -q` (full backend suite — hold the 1153+ baseline)
- **Before `/gsd:verify-work`:** Full backend suite + frontend vitest must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 26-01-01 | 01 | 0 | HUB-03/04 | T-26-01-SC | Package legitimacy human-verify before any install (never auto-advanced) | manual | human checkpoint — verify every npm/PyPI pkg on npmjs.com / pypi.org | ✅ W0 | ⬜ pending |
| 26-01-02 | 01 | 0 | HUB-03 | T-26-01-02 | Network-first `index.html` SW (no stale shell blocks deploy) | build | `cd frontend && npm run build && test -f dist/index.html && npm test -- --run` | ✅ W0 | ⬜ pending |
| 26-01-03 | 01 | 0 | HUB-04 | T-26-01-01 | SPA mount registered last — existing routes not shadowed | unit | `pytest -q tests/test_web_server.py -x` (incl. `test_health_still_works`) | ✅ W0 | ⬜ pending |
| 26-02-01 | 02 | 0 | HUB-01 | T-26-02-03 | `session_version` scaffold enables sign-out-everywhere (D-02) | unit | `pytest -q tests/test_firestore_hub_fields.py -x` | ✅ W0 | ⬜ pending |
| 26-02-02 | 02 | 0 | TIME-07 | T-26-02-01 | `daily_note` write best-effort — never blocks the briefing send | unit | `grep daily_note core/morning_briefing.py` + ast parse | ✅ W0 | ⬜ pending |
| 26-02-03 | 02 | 0 | CHAT-01 | — | Seed Wave 0 skip-marked stubs (Nyquist anchor) | unit | `pytest -q tests/test_hub_auth.py tests/test_api_today.py tests/test_hub_chat.py` | ✅ W0 | ⬜ pending |
| 26-03-01 | 03 | 1 | HUB-01 | T-26-03-cookie | Signed session cookie + `compare_digest` + version revocation | unit | `grep require_hub_session/verify_session_cookie/compare_digest` + ast parse | ✅ W0 | ⬜ pending |
| 26-03-02 | 03 | 1 | HUB-01 | T-26-03-csrf | `/api/auth/*` + `SameSite=strict` (CSRF control) | unit | `grep /api/auth/google, revoke-all, samesite="strict"` + ast parse | ✅ W0 | ⬜ pending |
| 26-03-03 | 03 | 1 | HUB-01 | T-26-03-allowlist | Allowlist rejects non-Amit identities; `/api/*` 401 without cookie | unit | `pytest -q tests/test_hub_auth.py -x` (skips flipped to real) | ✅ W0 | ⬜ pending |
| 26-04-01 | 04 | 2 | TIME-01/02/03/05/08 | — | Per-source helpers; meal slot-time caveat (no eating-time inference) | unit | ast helper-presence check (`_today_*`) | ✅ W0 | ⬜ pending |
| 26-04-02 | 04 | 2 | TIME-01/02/05/08 | T-26-04-auth | `/api/today` behind `require_hub_session`; `_jsonsafe_doc`; `asyncio.gather` | unit | `grep require_hub_session/_jsonsafe_doc/asyncio.gather` + ast parse | ✅ W0 | ⬜ pending |
| 26-04-03 | 04 | 2 | TIME-03/08 | — | No DatetimeWithNanoseconds leak; slot-time not eating-time | unit | `pytest -q tests/test_api_today.py -x` (skips flipped to real) | ✅ W0 | ⬜ pending |
| 26-05-01 | 05 | 3 | CHAT-02 | T-26-05-cputrack | `enqueue_hub_message` Cloud Tasks (never Starlette BackgroundTask) | unit | `grep enqueue_hub_message` + `pytest -q tests/test_task_dispatch.py -x` | ✅ W0 | ⬜ pending |
| 26-05-02 | 05 | 3 | CHAT-01/02 | T-26-05-oidc | `/api/chat` session-gated; `/internal/process-hub-message` OIDC-gated | unit | `grep /api/chat, /internal/process-hub-message, enqueue_hub_message` + ast parse | ✅ W0 | ⬜ pending |
| 26-05-03 | 05 | 3 | CHAT-01/02/03/04 | — | Shared Firestore history append/window | unit | `pytest -q tests/test_hub_chat.py -x` (skips flipped to real) | ✅ W0 | ⬜ pending |
| 26-06-01 | 06 | 2 | HUB-01/05 | T-26-06-authgate | `apiFetch` credentials:'include'; 401 → sign-in redirect | build | `cd frontend && npx tsc --noEmit && npm run build && test -f dist/index.html` | ✅ W0 | ⬜ pending |
| 26-06-02 | 06 | 2 | HUB-05 | — | Responsive AppShell/Sidebar/BottomTabs/GlanceRail/DockChat | build | `cd frontend && npx tsc --noEmit && npm run build && test -f dist/index.html` | ✅ W0 | ⬜ pending |
| 26-06-03 | 06 | 2 | HUB-05 | — | Responsive split + auth-gate spec | unit | `cd frontend && npm test -- --run` | ✅ W0 | ⬜ pending |
| 26-07-01 | 07 | 3 | TIME-01/05 | — | `useToday` refetch-on-mount/focus, no timer polling (D-05) | unit | `cd frontend && npx tsc --noEmit && grep refetchOnWindowFocus` | ✅ W0 | ⬜ pending |
| 26-07-02 | 07 | 3 | TIME-02/04 | — | NowLine `scrollIntoView` (D-04); all-day pin; past dimming | build | `cd frontend && npm run build && grep scrollIntoView NowLine.tsx` | ✅ W0 | ⬜ pending |
| 26-07-03 | 07 | 3 | TIME-03 | — | Chronological order, all-day pin, slot labels, D-06 placeholders | unit | `cd frontend && npm test -- --run` | ✅ W0 | ⬜ pending |
| 26-08-01 | 08 | 4 | CHAT-03/04 | T-26-08-04 | Optimistic send (sent only after ACK); 2.5s polling; unread math | unit | `cd frontend && npx tsc --noEmit && grep refetchInterval/2500/last_seen` | ✅ W0 | ⬜ pending |
| 26-08-02 | 08 | 4 | CHAT-03/04 | T-26-08-01 | Message text-render (no `dangerouslySetInnerHTML`); badge wiring | build | `cd frontend && npm run build && grep "Klaus is thinking"` | ✅ W0 | ⬜ pending |
| 26-08-03 | 08 | 4 | CHAT-03/04 | — | Optimistic/thinking/unread spec | unit | `cd frontend && npm test -- --run` | ✅ W0 | ⬜ pending |
| 26-09-01 | 09 | 3 | HUB-03 | T-26-09-01 | Offline indicator + in-flight Skeleton (distinct from D-06) | build | `cd frontend && npm run build && grep "Offline — showing cached data"/onLine` | ✅ W0 | ⬜ pending |
| 26-09-02 | 09 | 3 | HUB-02 | T-26-09-03 | iOS install gate (`isIOS && !standalone && !dismissed`) + apple-touch-icon | build | `cd frontend && npm run build && grep install-banner-dismissed/apple-touch-icon` | ✅ W0 | ⬜ pending |
| 26-09-03 | 09 | 3 | HUB-02/03 | — | Install-banner gate + online/offline toggle spec | unit | `cd frontend && npm test -- --run` | ✅ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky — execution flips these as each task commits.*

**Sampling continuity:** every task carries an automated verify (no 3 consecutive tasks without one). Backend Wave 1+ tasks flip the skip-marked stubs seeded by 26-02; frontend tasks verify via `tsc --noEmit` + `npm run build` + vitest `--run`.

---

## Wave 0 Requirements

- [x] `tests/test_hub_auth.py` — stubs for HUB-01 (session auth) — seeded by 26-02 Task 3
- [x] `tests/test_api_today.py` — stubs for TIME-01..05/07/08 (/api/today composition) — seeded by 26-02 Task 3
- [x] `tests/test_hub_chat.py` — stubs for CHAT-01..04 (hub chat + unread badge) — seeded by 26-02 Task 3
- [x] `tests/conftest.py` — existing shared fixtures sufficient (backend plans reuse `_stub_web_server_imports` / `fake_tasks_v2` patterns; no new conftest changes required)
- [x] vitest install — frontend test framework installed by 26-01 Task 2 (`frontend/vitest.config.ts`, jsdom)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| PWA install via Safari "Add to Home Screen" | HUB-02 | iOS install is a manual OS gesture, no API | Open hub in Safari, tap Share → Add to Home Screen, confirm install banner (D-12) appears then dismisses permanently |
| Same exchange visible in Telegram | CHAT-01 | Cross-channel visual confirmation | Send hub chat message, confirm reply appears in Telegram thread |
| Now-line + auto-scroll on open | TIME-04 | Visual/interaction behavior | Open timeline, confirm now-line marker present and view auto-scrolls to it |
| Offline shell load + skeletons | HUB-03 | Requires real network-off / airplane mode | Reload with network off; confirm app shell loads from cache, offline indicator shows, sections degrade to skeletons |

*Owning plans: HUB-02 → 26-09 (Task 3 `<human-check>`); CHAT-01 → 26-05; TIME-04 → 26-07; HUB-03 → 26-09.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (vitest via 26-01; backend stubs via 26-02)
- [x] No watch-mode flags (`--run` used for vitest; pytest non-watch)
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (2026-06-14 — planning; Per-Task Verification Map populated from final 9-plan / 27-task breakdown)
