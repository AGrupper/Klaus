---
phase: 22
slug: expert-coaching-knowledge-d-13-release
status: validated
nyquist_compliant: partial
wave_0_complete: true
created: 2026-06-04
validated: 2026-06-05
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
| 22-02-01 | 02 | 0 | COACH-01 | — | `{coaching_guide}` substitution resolves (first in render chain) | unit | `pytest tests/test_main_render_smart_system.py -x -k coaching_guide` | ✅ | ✅ green |
| 22-02-01 | 02 | 0 | COACH-01 | T-22-01 | slim core < 350 lines / < 15000 chars | unit | `pytest tests/test_main_render_smart_system.py -x -k slim_core_size` | ✅ | ✅ green |
| 22-02-02 | 02 | 0 | COACH-01 | T-22-05 | read_coaching_guide brain-direct only, not in worker schemas | unit | `pytest tests/test_tools.py -x -k read_coaching_guide` | ✅ | ✅ green |
| 22-02-02 | 02 | 0 | COACH-01 | T-22-04 | handler returns section for known topic (no path interpolation) | unit | `pytest tests/test_tools.py -x -k handle_read_coaching_guide` | ✅ | ✅ green |
| 22-02-02 | 02 | 0 | COACH-01 | T-22-04 | handler returns error JSON for unknown topic — never raises | unit | `pytest tests/test_tools.py -x -k coaching_guide_unknown_topic` | ✅ | ✅ green |
| 22-02-01 | 02 | 1 | Regression | — | no unresolved placeholders after `{coaching_guide}` | unit | `pytest tests/test_main_render_smart_system.py -x -k no_unresolved_placeholders` | ✅ | ✅ green |
| 22-03-02 | 03 | 1 | Regression | T-22-08 | briefing/alert compose has no literal `{coaching_guide}` | unit | `pytest tests/test_main_render_smart_system.py -x -k no_literal_placeholder` | ✅ | ✅ green |
| 22-04-03 | 04 | 2 | COACH-06 | T-22-11 | no invented Tier B number; staleness caveat for past-window | manual smoke | See SC-1 below | N/A | ✅ live-verified |
| 22-04-03 | 04 | 2 | COACH-02 | — | names session type + load + rationale | manual smoke | See SC-3 below | N/A | ✅ live-verified |
| 22-04-03 | 04 | 2 | COACH-07 | — | structural critique, recommends not rewrites | manual smoke | See SC-4 below | N/A | ✅ live-verified |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Wave-2 manual-smoke rows live-verified on Telegram against Cloud Run revision `klaus-agent-00085-zl8` (2026-06-05), documented in 22-04-SUMMARY.md §Live Verification and 22-VERIFICATION.md.*

---

## Wave 0 Requirements

- [x] `tests/test_main_render_smart_system.py` — extended with `{coaching_guide}` substitution test, slim-core-size guard, briefing/alert no-literal-placeholder tests (9 green)
- [x] `tests/test_tools.py` — `read_coaching_guide` registration tests added: schema present, handler dispatch, brain-direct-only exclusion, known-topic hit, unknown-topic error JSON (7 green, `TestPhase22CoachingGuideTool`)
- [x] `docs/COACHING_GUIDE.md` — exists (1139 lines) with `<!-- SLIM_CORE_START/END -->` and all 10 `<!-- SECTION: slug -->` markers

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

- [x] All tasks have `<automated>` verify or are documented manual-only with rationale
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test stubs + guide-with-markers) — all green
- [x] No watch-mode flags
- [x] Feedback latency < 10s (quick run: 9 render + 7 tool tests in <0.5s)
- [x] `nyquist_compliant: partial` set in frontmatter (COACH-01 + regression fully automated; COACH-02/06/07 behavioral SCs are manual-only by nature, live-verified)

**Approval:** validated 2026-06-05 — automated wiring COVERED + green; behavioral success criteria manual-only and live-verified.

---

## Validation Audit 2026-06-05

| Metric | Count |
|--------|-------|
| Automated rows audited | 7 |
| COVERED (green) | 7 |
| MISSING / PARTIAL | 0 |
| Gaps filled by auditor | 0 (none needed) |
| Manual-only (live-verified) | 3 (COACH-06/02/07) |

**Finding:** Stale pre-execution draft (`status: draft`, placeholder `22-XX` IDs, `nyquist_compliant: false`) reconciled against the executed phase. All 7 automated rows map to real, passing tests (`tests/test_main_render_smart_system.py`, `tests/test_tools.py`) — confirmed green this audit. The 3 Wave-2 behavioral success criteria (no-data fabrication contract, coaching specificity, structural critique) depend on live LLM judgment and are legitimately manual-only; all three were live-verified on Telegram (rev `klaus-agent-00085-zl8`, 2026-06-05) per 22-VERIFICATION.md (9/9 must-haves, 4/4 SCs). No auditor spawn required — no MISSING or red gaps to fill. Verdict: **PARTIAL** (fully automated where automatable; manual-only behavior verified live).
