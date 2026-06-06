---
phase: 24
slug: strict-coaching-integration-nutrition-accountability
status: draft
nyquist_compliant: true
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
| **Quick run command** | `python -m pytest tests/<file> -x -q` (per-file — full suite segfaults on 3.13 grpc GC) |
| **Full suite command** | run per-file in sequence; 911+ baseline must hold |
| **Estimated runtime** | ~5–10s per file |

---

## Sampling Rate

- **After every task commit:** Run the per-file test for the modified file (`python -m pytest tests/<file> -x -q`)
- **After every plan wave:** Run all Phase 24 test files in sequence
- **Before `/gsd:verify-work`:** Full per-file suite green (911+ baseline holds)
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 24-01-01 | 01 | 1 | COACH-05 | T-24-01/03/04 | topic_key internally derived; reads fail-open never crash cron; no PII in logs | unit | `python -m pytest tests/test_coaching_topic_store.py -x -q` | ❌ W0 | ⬜ pending |
| 24-01-02 | 01 | 1 | PROG-04 | T-24-02 | feel==0 → grind (not dropped); notes keywords hardcoded | unit | `python -m pytest tests/test_training_log_store.py tests/test_training_checkin.py -x -q` | ❌ W0 | ⬜ pending |
| 24-02-01 | 02 | 1 | NUTR-01 | T-24-06 | pure fn, no I/O; only own numbers surfaced | unit | `python -m pytest tests/test_proactive_alerts.py -x -q -k macro` | ❌ W0 | ⬜ pending |
| 24-02-02 | 02 | 1 | NUTR-02, NUTR-03 | T-24-05/07 | malformed timestamp skipped; rest-day no false slot miss | unit | `python -m pytest tests/test_proactive_alerts.py -x -q -k "slot or anchor or supplement"` | ❌ W0 | ⬜ pending |
| 24-03-01 | 03 | 1 | COACH-05 | T-24-08/09 | T-22-04 slug normalization preserved; ambiguous → not-found (SC-1) | unit | `python -m pytest tests/test_tools.py -x -q -k coaching_guide` | ⚠️ Partial | ⬜ pending |
| 24-03-02 | 03 | 1 | COACH-03, COACH-04 | T-24-10/11 | sentinel string unchanged; returned text brain-produced (SC-1) | unit | `python -m pytest tests/test_main.py -x -q -k "tool_iterations or double_send or smart_loop" && python -m pytest tests/test_autonomous.py -x -q -k sentinel` | ⚠️ Partial | ⬜ pending |
| 24-04-01 | 04 | 2 | NUTR-01, NUTR-02, NUTR-03, COACH-05 | T-24-12/14/15 | write-after-send (no orphan topic); gather fail-open | unit/integration | `python -m pytest tests/test_proactive_alerts.py -x -q -k "nutrition or dedup or gather or topic"` | ❌ W0 | ⬜ pending |
| 24-04-02 | 04 | 2 | COACH-03, COACH-04 | T-24-13/16 | no fabricated deficit; no dated projection; one-escalation not silence | unit (prompt) + manual | `python -m pytest tests/test_proactive_alerts.py -x -q -k "prompt or skip_pushback or recovery or supplement"` | ❌ W0 | ⬜ pending |
| 24-05-01 | 05 | 2 | PROG-03, COACH-05 | T-24-17/18/21 | write-after-send; gather fail-open; prior-day not silent | unit (gather + prompt) | `python -m pytest tests/test_morning_briefing.py -x -q -k "integrated or coaching or topic or prior"` | ❌ W0 | ⬜ pending |
| 24-05-02 | 05 | 2 | PROG-01, PROG-04, COACH-05 | T-24-19/20 | no dated projection; null quality handled; numbers under Tier A/B | unit (gather + prompt) | `python -m pytest tests/test_weekly_training_review.py -x -q -k "facet or quality or coaching or guide or topic"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Success-Criteria → Task Coverage

| ROADMAP SC | Proven by |
|------------|-----------|
| SC-1 strict skip pushback (named deficit + consequence, no softening) | 24-04-02 (prompt) + manual UAT; numbers from 24-02-01 gather |
| SC-2 recovery single-ranked-rec + "your call, Sir" | 24-04-02 (prompt) + manual UAT |
| SC-3 cross-cron dedup (≤1/day across crons) | 24-01-01 (gate) + 24-04-01 + 24-05-01 + 24-05-02 (wiring) |
| SC-4 fueling-slot structural-miss flagging | 24-02-02 (detection) + 24-04-01 (wiring) |
| SC-5 integrated morning-briefing block | 24-05-01 (prompt) + manual UAT |
| SC-6 per-facet weekly review + quality trend | 24-01-02 (quality field) + 24-05-02 (per-facet + trend) |

---

## Wave 0 Requirements

- [ ] `tests/test_coaching_topic_store.py` — NEW: COACH-05 gate (has_topic/add_topic/topics_today, ArrayUnion string-list dedup, Asia/Jerusalem key, fail-open reads, re-raise write)
- [ ] `tests/test_training_log_store.py` — ADD: log_session accepts/persists `quality` param
- [ ] `tests/test_training_checkin.py` — ADD: derive_session_quality (feel==0 grind Pitfall 4, rpe-only path, notes override), _silent_garmin_sync passes quality
- [ ] `tests/test_proactive_alerts.py` — ADD: _macro_gap_check, _detect_slot_misses/_resolve_anchor_times/SLOT_SUPPLEMENTS, _gather_nutrition_data, dedup gate, write-after-send, prompt assertions
- [ ] `tests/test_tools.py` — ADD: WR-02 hardened fuzzy match (ambiguous→not-found, short-word skip, unambiguous match)
- [ ] `tests/test_main.py` — ADD: MAX_TOOL_ITERATIONS==12, substantive-text-at-exhaustion return, sentinel-string preserved
- [ ] `tests/test_morning_briefing.py` — ADD: coaching_topics today/yesterday gather, post-send write, integrated-block prompt assertion
- [ ] `tests/test_weekly_training_review.py` — ADD: coaching_topics gather, {coaching_guide} injection, per-facet + quality-trend prompt assertion
- [ ] `tests/conftest.py` — verify CoachingTopicStore / MealStore / TrainingLogStore mock fixtures (existing infra)

*Existing 911-test baseline covers most phase requirements; new stores/derivations/helpers need the new test files/cases above.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Strict pushback register/tone (no softening) | COACH-03 | LLM prompt output — register is judgment, not assertable in unit test | Live 21:30 check-in with a skipped session; confirm named session + concrete deficit + directional consequence, no hedging, no dated projection |
| Recovery single-ranked-rec phrasing | COACH-04 | LLM prompt output | Trigger an HRV<baseline-vs-top-set conflict; confirm one ranked rec + "your call, Sir", never a menu |
| Integrated morning-briefing block | PROG-03 | LLM prompt output | Confirm session+recovery+fueling weave as one block, not three labeled lines |
| Per-facet weekly review framing | PROG-01 | LLM prompt output | Confirm per-facet within-block status + quality distribution, no dated "on track for Oct" projection |

*Cross-cron dedup (SC-3), fueling-slot mapping (SC-4), macro thresholds (NUTR-01), and quality derivation (PROG-04) ARE automatable — assert at the gather/gate/pure-fn layer below the prompt.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
