# Archive

Historical record of shipped phases, grouped by milestone. These directories were moved out of `.planning/phases/` after their milestone closed, so the active directory stays focused on in-flight work.

Each `<milestone>/phases/<phase>/` directory preserves the full execution paper trail:

- `*-CONTEXT.md` — gathered context, decisions, gray-area resolutions
- `*-RESEARCH.md` — pre-planning research output
- `*-PATTERNS.md` — pattern mapping (where new files modelled on existing analogs)
- `*-VALIDATION.md` — per-task validation strategy
- `*-PLAN.md` — task-by-task execution plan (one per plan within the phase)
- `*-SUMMARY.md` — execution summary (one per completed plan)
- `*-VERIFICATION.md` — goal-backward verification report
- `*-REVIEW.md` — code review findings
- `deferred-items.md` — known issues deferred to a later sweep

For high-level milestone summaries (without per-phase detail) see `.planning/MILESTONES.md`. For the full milestone-scoped roadmap and requirements lists see `.planning/milestones/v<X.Y>-{ROADMAP,REQUIREMENTS}.md`.

## Contents

- `v1.0/phases/08-five-fingers/` — Phase 8 of the v1.0 milestone (Five Fingers practice helper)
- `v2.0/phases/14-foundation/` — Cost metering + tick-brain + LLM strategy
- `v2.0/phases/15-codebase-self-knowledge/` — self-inspect tools
- `v2.0/phases/16-self-model-state-awareness/` — SELF.md manifest + self_state
- `v2.0/phases/17-reflection-journal/` — daily reflection cron + journal
- `v2.0/phases/18-autonomous-engine/` — 3-layer autonomous tick pipeline
