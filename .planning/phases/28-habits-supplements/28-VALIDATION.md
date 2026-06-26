---
phase: 28
slug: habits-supplements
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-26
---

# Phase 28 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `28-RESEARCH.md` § Validation Architecture. Task IDs are assigned by the planner;
> the per-task map below is filled in as plans land.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing; `tests/`, `tests/fakes.py` fakes) |
| **Config file** | none explicit — run **per-file** (full-suite segfaults per STATE.md) |
| **Quick run command** | `pytest tests/test_habit_store.py -x -q` |
| **Full suite command** | `pytest tests/test_habit_store.py tests/test_habits_api.py tests/test_autonomous.py tests/test_proactive_alerts.py -q` |
| **Estimated runtime** | ~15–30s per file group |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_habit_store.py -x -q`
- **After every plan wave:** Run the full per-file group above
- **Before `/gsd:verify-work`:** Full per-file group must be green
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

> Filled in during planning/execution. Requirement→test mapping basis is in
> `28-RESEARCH.md` § Validation Architecture → "Phase Requirements → Test Map".

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | HABIT-01 | — | HabitStore CRUD + toggle log_completion | unit | `pytest tests/test_habit_store.py::TestHabitStore -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | HABIT-03 | T-28-streak | pure reset on missed scheduled day; non-scheduled neutral | unit | `pytest tests/test_habit_store.py::TestStreakComputation -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | HABIT-03 | T-28-dst | DST spring-forward (2026-03-27) does not break streak | unit | `pytest tests/test_habit_store.py::test_streak_survives_spring_forward_dst -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | HABIT-03 | T-28-dst | DST fall-back (2026-10-25) does not break streak | unit | `pytest tests/test_habit_store.py::test_streak_survives_fall_back_dst -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | HABIT-03 | T-28-backfill | yesterday backfill repairs streak; older date 400 | unit+integration | `pytest tests/test_habit_store.py::test_yesterday_backfill_repairs_streak tests/test_habits_api.py::test_checkin_rejects_day_before_yesterday -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | HABIT-04 | — | 365-day grid four-state derivation | unit | `pytest tests/test_habit_store.py::TestGridDerivation -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | HABIT-02 | T-28-backfill | `/api/habits/{id}/checkin` 200 + optimistic state | integration | `pytest tests/test_habits_api.py::TestCheckinEndpoint -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | HABIT-05 | — | `_gather_habit_adherence` returns [] on error (sentinel) | unit | `pytest tests/test_autonomous.py::test_habit_gather_returns_empty_on_error -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | HABIT-05 | — | `get_habit_adherence` tool registered in `core/tools.py` | unit | `pytest tests/test_tools.py -x -k habit` | ❌ W0 | ⬜ pending |
| TBD | TBD | 0 | TIME-06 | — | `/api/today` includes habits due today | integration | `pytest tests/test_api_today.py::test_today_includes_habits -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | — | SLOT_SUPPLEMENTS rewire | T-28-schedule | 21:30 alert reads HabitStore; falls back to dict if empty | unit | `pytest tests/test_proactive_alerts.py -x -k supplement` | extends existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_habit_store.py` — HabitStore CRUD + streak computation + four-state grid + **DST fixtures** (HABIT-01/02/03/04)
- [ ] `tests/test_habits_api.py` — FastAPI `/api/habits/*` endpoints + `require_hub_session` + checkin toggle + yesterday-backfill gate (HABIT-02, TIME-06 API side)
- [ ] Extend (do **not** replace) `tests/test_autonomous.py` and `tests/test_proactive_alerts.py` for HABIT-05 + the SLOT_SUPPLEMENTS rewire
- [ ] Framework install: none — pytest already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Contribution grid renders correctly across breakpoints | HABIT-04 | Visual/responsive — Tailwind `md:` vs inline-`display` gotcha | Open a habit detail on phone + desktop; confirm grid + no leaked phone-only UI |
| One-tap check-off feel (optimistic + toggle) on Today timeline | HABIT-02 / TIME-06 | Touch interaction + optimistic UX | Tap a due habit on phone timeline; confirm instant check + tap-again un-check |
| iOS create/edit + dose-edit bottom sheets | HABIT-01 / HABIT-02 | iOS-Safari z-index/keyboard/blur-before-click traps | Open sheets on iOS; confirm above BottomTabs, keyboard tracking, submit works |
| Per-slot adherence nudge fires once and is deduped vs 21:30 alert | HABIT-05 | Depends on live autonomous tick + tick-brain judgment | Leave a scheduled item unchecked past its slot; confirm at most one nudge, no double-nag |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
