# Requirements: Klaus — v4.0 Specific Training & Nutrition Coaching

**Defined:** 2026-06-03
**Core Value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do. For v4.0: a genuinely expert, specific hybrid-athlete coach grounded in Amit's blueprint + real data, who drives facet-by-facet improvement and proves it with end-of-block benchmarks toward dated goals.

**Milestone anchor:** Amit's 16-week training cycle Week 1 = **Sunday 2026-06-21**. Block-week math counts from this date; before it Klaus is pre-cycle.

## v1 Requirements

Requirements for this milestone. Each maps to a roadmap phase.

### Living Plan & Profile (PLAN)

- [x] **PLAN-01**: Klaus ingests Amit's Hybrid Athlete blueprint into `UserProfileStore` as **structured fields** (dated goals, AM/PM weekly split *shape*, 6-slot fueling architecture, supplement schedule) — never as a raw markdown blob. **Two kickoff narrowings:** (a) the 16-week aerobic pace/volume table is **loose directional reference only, NOT a tracked target table** — Amit expects to change it freely, so its specific paces/volumes are never treated as contracts; (b) **current-performance baselines are never hand-seeded** — Klaus derives them from real Garmin / `TrainingLogStore` data at read time (Tier B). The profile holds *targets* (Tier A); measured numbers always come from live data.
- [x] **PLAN-02**: The plan is represented as a **flexible guide** (block-level volume / trend targets), not a rigid day-by-day attendance contract.
- [x] **PLAN-03**: Amit can update the plan/profile (goals, split, targets, dates) and Klaus reasons against the updated guide on the next turn.

### Expert Coaching Knowledge & Behavior (COACH)

- [x] **COACH-01**: Klaus carries curated **expert hybrid-athlete coaching knowledge** (concurrent strength/endurance & the interference effect, block periodization, how to execute the specific run/lift/calisthenics sessions, fueling science) injected into his reasoning substrate.
- [x] **COACH-02**: Klaus **names the specific session, the load/pace, and the rationale** in coaching messages instead of giving generic advice.
- [ ] **COACH-03**: Klaus is **strict** — when a session is skipped or a choice is off-plan he names the deficit and the consequence and pushes back, without softening/hedging.
- [ ] **COACH-04**: On recovery-vs-plan conflicts Klaus **cites the data and presents explicit options, leaving the decision to Amit** (advise, never override).
- [ ] **COACH-05**: Coaching is both **proactive** (initiated in the existing crons) and **reactive** (in chat), with **cross-cron de-duplication** so the same point isn't nagged from morning briefing + evening check-in + weekly review on the same day.
- [x] **COACH-06**: The **D-13 no-fabrication guard is released** under a data-presence contract: blueprint goals are citable as *targets* (Tier A); measured numbers (lifts, paces, macros, HRV) are citable only when a real recent record exists (Tier B). Klaus never invents a number.
- [x] **COACH-07**: Klaus treats the blueprint **and Amit's current habits as a critiqueable guide, not gospel**. When his expert knowledge or Amit's data shows part of the plan (training structure, nutrition targets/timing, supplements) is **suboptimal or wrong**, he says so, explains why, and recommends a specific better approach. He *recommends* changes — Amit decides whether to adopt them (via PLAN-03); Klaus never silently rewrites the plan. Critique is **structural** (design-level), not daily micro-tweaks.

### Training Blocks & Benchmark Testing (BLOCK)

- [x] **BLOCK-01**: Klaus tracks the **current training block** (start date 2026-06-21, week number, phase name) and surfaces block context in coaching messages.
- [x] **BLOCK-02**: At **block ends** (deload weeks) Klaus prompts a **benchmark test session** with a standardized protocol and conditions — no periodic mid-block testing.
- [x] **BLOCK-03**: Klaus **records benchmark results** and compares them across blocks to show per-facet improvement over time.

### Nutrition & Supplement Accountability (NUTR)

- [ ] **NUTR-01**: Klaus checks **macro adherence** against the 150g protein / 350g carb targets using `MealStore` data — and, per COACH-07, flags when **the targets/architecture themselves look suboptimal** for Amit's training load and recommends a better structure (e.g. protein too low for volume, carbs not periodized to long-run days).
- [ ] **NUTR-02**: Klaus maps logged meals to the **6-slot fueling timeline** and flags **structural misses** (e.g. missed post-AM-run reload, missing pre-bed supplements) — not marginal macro micro-adjustments.
- [ ] **NUTR-03**: Klaus tracks **supplement timing** against the blueprint schedule and flags gaps (advisory/inference, tied to the fueling-slot windows).

### Progress Toward Goals (PROG)

- [ ] **PROG-01**: The **Sunday weekly review** reports **per-facet progress** (strength top-set trends, threshold volume vs target, ACWR) with block-relative framing.
- [x] **PROG-02**: Klaus **projects strength/pace trends toward the dated Oct/Nov goals** and reports on-track / behind.
- [ ] **PROG-03**: The **morning briefing** frames today's named session + recovery state + the relevant fueling reminder together.
- [ ] **PROG-04**: Klaus captures a **session-quality annotation** (e.g. strong / neutral / grind) at logging time so the weekly review can surface quality trends.

## v2 Requirements

Deferred to a future milestone. Tracked but not in this roadmap.

### Carried-forward (DEFER)

- **DEFER-01**: Recurring "daily review" skill — check-in persistence / re-surfacing.
- **DEFER-02**: `MealAuditStore` — persisted nutrition critique history (currently live-read only, D-21).

## Out of Scope

Explicitly excluded — anti-features from research, documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Periodic / mid-block goal testing | Amit's philosophy: test at block ends + the dated deadlines only. Mid-cycle testing fatigues the athlete and gives false readouts. |
| Coach-override on recovery-vs-plan | Amit's rule is "advise, I decide." Klaus presents options; never commands or silently decides. |
| Daily macro-by-macro micro-optimization / CICO calorie math | Daily marginal tweaks ("add 12g carbs to lunch") are noise. **Structural** critique of the targets/architecture is in scope (COACH-07, NUTR-01); per-day micro-swaps are not. |
| *Silent / autonomous* plan modification | Klaus may **recommend** changes to a suboptimal plan (COACH-07) — but he never *silently rewrites* the blueprint or 16-week progression. Amit adopts changes via PLAN-03. |
| Real-time in-session HR-zone monitoring | Klaus is cron/Telegram-driven, not a live system. Comment on completed sessions, never simulate live feedback. |
| Injury diagnosis / medical management | Outside qualification and data. Flag warning-sign patterns and suggest rest/physio; never diagnose. |
| Klaus parsing meals from chat text | `MealStore` is populated by the working HealthKit/Lifesum pipeline. A parallel text parser would duplicate and diverge. |

## Traceability

Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PLAN-01 | Phase 21 | Complete |
| PLAN-02 | Phase 21 | Complete |
| PLAN-03 | Phase 21 | Complete |
| COACH-01 | Phase 22 | Complete |
| COACH-02 | Phase 22 | Complete |
| COACH-06 | Phase 22 | Complete |
| COACH-07 | Phase 22 | Complete |
| BLOCK-01 | Phase 23 | Complete |
| BLOCK-02 | Phase 23 | Complete |
| BLOCK-03 | Phase 23 | Complete |
| COACH-03 | Phase 24 | Pending |
| COACH-04 | Phase 24 | Pending |
| COACH-05 | Phase 24 | Pending |
| NUTR-01 | Phase 24 | Pending |
| NUTR-02 | Phase 24 | Pending |
| NUTR-03 | Phase 24 | Pending |
| PROG-01 | Phase 24 | Pending |
| PROG-03 | Phase 24 | Pending |
| PROG-04 | Phase 24 | Pending |
| PROG-02 | Phase 25 | Complete |

**Coverage:**
- v1 requirements: 20 total
- Mapped to phases: 20 (100%)
- Unmapped: 0

---
*Requirements defined: 2026-06-03*
*Last updated: 2026-06-03 — traceability filled after roadmap creation*
