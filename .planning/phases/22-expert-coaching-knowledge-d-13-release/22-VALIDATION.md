---
phase: 22
slug: expert-coaching-knowledge-d-13-release
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-04
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | none — run from project root |
| **Quick run command** | `python -m pytest tests/test_main_render_smart_system.py tests/test_tools.py -x` |
| **Full suite command** | `python -m pytest tests/ --ignore=tests/test_google_fit_tool.py -x` (774 passing baseline) |
| **Estimated runtime** | ~5–10s quick · ~60s full |

> **Note:** Full `pytest tests/` in one process can segfault (grpc/protobuf GC, Python 3.13). Run new tests per-file; use full suite for the baseline check.

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_main_render_smart_system.py tests/test_tools.py -x`
- **After every plan wave:** Run full suite on affected files
- **Before `/gsd:verify-work`:** Full suite green + SC-1/SC-2/SC-3/SC-4 behavioral smoke tests pass
- **Max feedback latency:** ~10 seconds (quick run)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 22-XX | — | 0 | COACH-01 | — | N/A | unit | `pytest tests/test_main_render_smart_system.py -x -k coaching_guide` | ❌ W0 | ⬜ pending |
| 22-XX | — | 0 | COACH-01 | — | slim core < 350 lines / < 15000 chars | unit | `pytest tests/test_main_render_smart_system.py -x -k slim_core_size` | ❌ W0 | ⬜ pending |
| 22-XX | — | 0 | COACH-01 | — | read_coaching_guide brain-direct only, not in worker schemas | unit | `pytest tests/test_tools.py -x -k read_coaching_guide` | ❌ W0 | ⬜ pending |
| 22-XX | — | 0 | COACH-01 | — | handler returns section for known topic | unit | `pytest tests/test_tools.py -x -k handle_read_coaching_guide` | ❌ W0 | ⬜ pending |
| 22-XX | — | 0 | COACH-01 | — | handler returns error JSON for unknown topic | unit | `pytest tests/test_tools.py -x -k coaching_guide_unknown_topic` | ❌ W0 | ⬜ pending |
| 22-XX | — | 1 | Regression | — | no unresolved placeholders after `{coaching_guide}` | unit | `pytest tests/test_main_render_smart_system.py -x -k no_unresolved_placeholders` | ✅ extend | ⬜ pending |
| 22-XX | — | 1 | Regression | — | briefing prompt has no literal `{coaching_guide}` | unit | `pytest tests/test_main_render_smart_system.py -x -k briefing_no_literal_placeholder` | ❌ W0 | ⬜ pending |
| 22-XX | — | 2 | COACH-06 | — | no invented Tier B number; staleness caveat for past-window | manual smoke | See SC-1 below | N/A | ⬜ pending |
| 22-XX | — | 2 | COACH-02 | — | names session type + load + rationale | manual smoke | See SC-3 below | N/A | ⬜ pending |
| 22-XX | — | 2 | COACH-07 | — | structural critique, recommends not rewrites | manual smoke | See SC-4 below | N/A | ⬜ pending |

*Task IDs are placeholders — the planner assigns final `22-NN-MM` IDs. Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_main_render_smart_system.py` — extend with `{coaching_guide}` substitution test, slim-core-size guard, briefing-no-literal-placeholder test
- [ ] `tests/test_tools.py` — add `read_coaching_guide` registration tests (schema present, handler dispatch, brain-direct-only exclusion, unknown-topic error JSON)
- [ ] `docs/COACHING_GUIDE.md` — must exist with `<!-- SLIM_CORE_START/END -->` and `<!-- SECTION: slug -->` markers before code tests can read it

---

## Manual-Only Verifications

These success criteria are prompt-behavioral — automated unit tests verify wiring, but the coaching *behavior* requires a live smoke test.

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| No-data behavior | COACH-06 (SC-1) | Depends on live LLM judgment over empty `TrainingLogStore` | Telegram: "What was my last bench press?" with no recent log. Expect: "I don't have a recent bench logged, Sir" + cites Oct 100kg as "your target." Fail: invents a number or omits qualifier. |
| Cron specificity | COACH-02 (SC-2) | Cron compose path, live LLM | `python -m core.morning_briefing --dry-run --date <tomorrow>`. Expect: names scheduled session type + plan target (pace/load). Fail: generic "strength session." |
| Chat specificity bar | COACH-02 (SC-3) | Live LLM judgment | Telegram on a Tuesday (Upper A): "What should I do tonight?" Expect: "top-set bench, ~92kg heavy triple — main strength stimulus toward 100kg Oct target." Fail: "do your strength session." |
| Structural critique | COACH-07 (SC-4) | Live LLM judgment + adoption boundary | Telegram: "Review my nutrition targets." Expect: names protein target, cites 1.6–2.0g/kg floor for concurrent training, offers to update via `update_plan`. Fail: ignores issue OR silently modifies plan. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (test stubs + guide-with-markers)
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s (quick run)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
