---
phase: 26
slug: hub-shell
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-13
---

# Phase 26 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) + vitest (frontend — Wave 0 installs) |
| **Config file** | pytest: existing; vitest: none — Wave 0 installs |
| **Quick run command** | `pytest -q tests/ -k hub` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest -q tests/ -k hub`
- **After every plan wave:** Run `pytest -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | REQ-{XX} | T-{N}-01 / — | {expected secure behavior or "N/A"} | unit | `{command}` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*(Planner fills this map from the per-plan tasks during planning.)*

---

## Wave 0 Requirements

- [ ] `tests/test_hub_auth.py` — stubs for HUB-01 (session auth)
- [ ] `tests/test_api_today.py` — stubs for TIME-01..05/07/08 (/api/today composition)
- [ ] `tests/test_hub_chat.py` — stubs for CHAT-01..04 (hub chat + unread badge)
- [ ] `tests/conftest.py` — shared fixtures (extend existing)
- [ ] vitest install — frontend test framework (if frontend unit tests planned)

*Planner refines against final task breakdown.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| PWA install via Safari "Add to Home Screen" | HUB-02 | iOS install is a manual OS gesture, no API | Open hub in Safari, tap Share → Add to Home Screen, confirm install banner (D-12) appears then dismisses permanently |
| Same exchange visible in Telegram | CHAT-01 | Cross-channel visual confirmation | Send hub chat message, confirm reply appears in Telegram thread |
| Now-line + auto-scroll on open | TIME-04 | Visual/interaction behavior | Open timeline, confirm now-line marker present and view auto-scrolls to it |

*Planner refines against final task breakdown.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
