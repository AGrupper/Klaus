---
phase: 25
slug: progress-projection-benchmark-trend-reporting
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-07
---

# Phase 25 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml / pytest.ini (existing) |
| **Quick run command** | `pytest tests/test_projection.py -q` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~60–90 seconds (full suite, 1027+ tests) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_projection.py -q`
- **After every plan wave:** Run `pytest -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 25-01-xx | 01 | 1 | PROG-02 | — | numbers computed server-side, never LLM-invented (anti-fabrication) | unit | `pytest tests/test_projection.py -q` | ❌ W0 | ⬜ pending |
| 25-02-xx | 02 | 2 | PROG-02 | — | reactive answer projects a trend, not the goal alone | unit | `pytest tests/test_tools.py -k projection -q` | ❌ W0 | ⬜ pending |
| 25-03-xx | 03 | 2 | PROG-02 | — | Sunday block dedups via structural-critique:projection:<facet> | unit | `pytest tests/test_weekly_training_review.py -k projection -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_projection.py` — unit tests for the deterministic projection helper: 0-point (no-data), 1-point (baseline-only), 2-point and 3-point (project + count-named confidence) cases, BOTH metric directions (strength higher-is-better, pace lower-is-better), irregular time spacing, and weeks-to-deadline computed from an injected `today_iso` (no internal `date.today()` — CR-01 tz lesson).
- [ ] Fixtures for BenchmarkStore history, `UserProfileStore.dated_goals`, and Garmin pace history (reuse existing conftest store fakes where present).

*Existing pytest infrastructure covers framework + most fixtures; new projection test file + fixtures are the only Wave 0 additions.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live reactive answer "am I on track for my October bench target?" on Telegram | PROG-02 | Requires live brain + real Firestore stores | Ask Klaus via Telegram; confirm reply computes a projected number + date + gap, not the goal alone, with a Tier-A-vs-Tier-B distinction |
| Sunday weekly review surfaces a pace-to-deadline line | PROG-02 | Cron-triggered, end-to-end | Trigger `/cron/weekly-review` (or wait for Sunday); confirm one consolidated block with ≥1 dated-goal facet line and confidence label |

*Projection math, confidence tiers, and dedup namespace all have automated verification; only the live brain framing + cron end-to-end are manual.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
