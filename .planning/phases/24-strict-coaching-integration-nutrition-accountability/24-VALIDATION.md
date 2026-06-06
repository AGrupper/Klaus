---
phase: 24
slug: strict-coaching-integration-nutrition-accountability
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-06
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml / pytest.ini |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | REQ-{XX} | T-{N}-01 / — | {expected secure behavior or "N/A"} | unit | `{command}` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*(Populated by the planner per task — see RESEARCH.md "## Validation Architecture" for the sampling targets that prove the 6 success criteria: anti-fabrication SC-1, single-ranked-rec SC-2, cross-cron dedup SC-3, fueling-slot structural-miss SC-4, integrated morning block SC-5, per-facet weekly review + quality trend SC-6.)*

---

## Wave 0 Requirements

- [ ] `tests/` — stubs for COACH-03/04/05, NUTR-01/02/03, PROG-01/03/04
- [ ] `tests/conftest.py` — shared fixtures (existing — verify CoachingTopicStore / MealStore / TrainingLogStore mocks)
- [ ] pytest already installed — no framework install needed

*Existing infrastructure (911-test baseline) covers most phase requirements; new stores/derivations need new test files.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Strict pushback register/tone (no softening) | COACH-03 | LLM prompt output — register is judgment, not assertable in unit test | Live 21:30 check-in with a skipped session; confirm named session + concrete deficit + directional consequence, no hedging |
| Recovery single-ranked-rec phrasing | COACH-04 | LLM prompt output | Trigger an HRV<baseline-vs-top-set conflict; confirm one ranked rec + "your call, Sir", never a menu |
| Integrated morning-briefing block | PROG-03 | LLM prompt output | Confirm session+recovery+fueling weave as one block, not three labeled lines |

*Cross-cron dedup (SC-3), fueling-slot mapping (SC-4), macro thresholds (NUTR-01), and quality derivation (PROG-04) ARE automatable — assert at the gather/gate layer below the prompt.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
