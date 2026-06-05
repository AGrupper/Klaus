---
phase: 22-expert-coaching-knowledge-d-13-release
plan: 04
subsystem: api
tags: [coaching, smart-agent-prompt, d-13-release, data-presence-contract, prompt-engineering]

# Dependency graph
requires:
  - phase: 22-01
    provides: docs/COACHING_GUIDE.md slim core injected as {coaching_guide}
  - phase: 22-02
    provides: render_smart_system {coaching_guide} substitution resolving the placeholder
provides:
  - "{coaching_guide} placeholder in prompts/smart_agent.md before {self_md} (stable prefix)"
  - "Recency-windowed Tier A/B data-presence contract replacing the blanket D-13 no-fabrication guard"
  - "Specificity bar: every coaching point names session type + load/pace + one-line rationale"
  - "Structural-critique posture: blunt-expert, structural-only, once-per-conversation, recommend-not-rewrite"
affects: [autonomous, morning_briefing, proactive_alerts, future-coaching-phases]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Data-presence contract as the sole anti-fabrication mechanism after guard removal (windows + staleness caveat + 3x upper bound + no-data fallback)"

key-files:
  created: []
  modified:
    - prompts/smart_agent.md

key-decisions:
  - "Removed the blanket 'do NOT invent thresholds' guard ONLY in the same edit that installed the recency-windowed Tier A/B contract — never removed alone (T-22-11)"
  - "Recency windows: lifts ≤14d, pace ≤7d, nutrition ≤2d, Garmin always fresh; 3x upper bounds (42/21/6d) degrade to no-data"
  - "No-data behavior cites the blueprint goal as 'your target', never an invented number (D-08)"
  - "Critique is recommend-not-rewrite: update_plan/update_training_profile fire only on explicit confirmation (D-12, honors PLAN-03)"

patterns-established:
  - "Klaus is now a prescriptive coach: real numbers under a strict data-presence contract, specific session/load/rationale, volunteered structural critique"

requirements-completed: [COACH-06, COACH-02, COACH-07]

# Metrics
duration: ~3min (code) + live human-verify gate
completed: 2026-06-05
---

# Phase 22 Plan 04: D-13 Guard Release + Coaching Contract Hardening

**Released the blanket no-fabrication guard under a recency-windowed Tier A/B data-presence contract, added a specificity bar and a recommend-not-rewrite structural-critique posture to prompts/smart_agent.md — verified live with zero fabricated numbers (COACH-06/02/07)**

## Performance

- **Tasks:** 3/3 (2 code + 1 blocking human-verify)
- **Files modified:** 1 (`prompts/smart_agent.md`)
- **Deployed:** Cloud Run revision `klaus-agent-00085-zl8`

## Accomplishments
- `{coaching_guide}` placeholder added before `{self_md}` (stable-prefix caching).
- **Blanket D-13 no-fabrication guard removed**, replaced in the same edit by the recency-windowed Tier A/B data-presence contract: Tier A targets always citable; Tier B actuals recency-gated (lifts ≤14d / pace ≤7d / nutrition ≤2d / Garmin always fresh); within-window → cite; past-window → cite + staleness caveat; beyond 3× (42/21/6d) or no data → *"I don't have a recent X logged, Sir"* + blueprint goal as "your target."
- Specificity bar: session type + load/pace + one-line rationale on every coaching point, with the wrong-vs-right example and the `read_coaching_guide(topic)` mini-lesson tie.
- Structural-critique posture: blunt-expert tone, structural-only scope, once-per-conversation suppression, `update_plan` only on explicit confirmation.

## Task Commits

1. **Task 1: Placeholder + Tier A/B recency contract (D-13 guard removal)** — `45b4d9c` (feat)
2. **Task 2: Specificity bar + structural-critique posture** — `fb06db6` (feat)
3. **Task 3: Live human-verify smoke (SC-1/SC-3/SC-4)** — approved by Amit on Telegram (see below)

**Merge to main:** `b5b6919` · **SUMMARY:** this file

## Live Verification (Task 3 — blocking gate, PASSED)

Run on Telegram against revision 00085, 2026-06-05:

- **SC-1 (no-data, T-22-11 BLOCKING):** *"What was my last bench press?"* → *"I do not have a recent bench press logged… Your target remains 100kg by October 18."* Enumerated the repositories checked (Firestore / Notion / Garmin), confirmed none expose per-exercise load, cited the 100kg Oct target + ~92kg working estimate. **No fabricated number.** ✅
- **SC-3 (specificity):** *"What should I do today?"* → Friday template: 14 km long run, Zone 2 (4:50–5:30/km), rationale (aerobic base for Oct 1:25 half), HRV-unbalanced caution to 12 km, PM mobility/sauna. Session + load + rationale. ✅
- **SC-4 (structural critique):** *"Review my nutrition targets."* → named protein target (150g vs 181g actual), cited ~2.0 g/kg concurrent-training floor, diagnosed structural timing flaws (8h fasting gap + 1,448 kcal dinner backload vs HRV/sleep), and **offered** *"Shall I proceed with updating your formal blueprint protein target to 180g/day, Sir?"* — did not silently rewrite. ✅
- **Bonus:** On *"I weigh 73kg,"* Klaus recognized it had been on the `[ASSUMED ~80kg]` baseline (the exact flag from the guide's protein-timing section), recomputed 150g → 2.05 g/kg = optimal, and walked back its earlier "borderline" critique. The assumption/recency contract works end-to-end. ✅

## Decisions Made
See key-decisions frontmatter. The guard-removal + contract-install were a single atomic edit by design (T-22-11).

## Deviations from Plan
None - plan executed exactly as written; code shipped in Tasks 1-2, gate passed in Task 3.

## Issues Encountered
A non-blocking UX wrinkle surfaced during live verification: data-verification-heavy queries (bench press, nutrition review) occasionally emit *"This request required more processing steps than expected"* **immediately followed by the correct full answer** — the brain trips its tool-iteration cap while exhaustively verifying data presence (Firestore→Notion→Garmin) under the new contract, sends the fallback, then still completes. The D-13 safety gate itself held (no fabrication). Logged as a follow-up todo (raise the iteration cap or suppress the premature fallback when an answer lands); does not block Phase 22.

## User Setup Required
None - prompt-only change, deployed via the standard push-to-main pipeline.

## Next Phase Readiness
- COACH-06/02/07 delivered and verified live. Klaus is now a prescriptive coach under a strict data-presence contract.
- Phase 22 complete pending the standard close-out gates.

---
*Phase: 22-expert-coaching-knowledge-d-13-release*
*Completed: 2026-06-05*
