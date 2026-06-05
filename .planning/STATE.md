---
gsd_state_version: 1.0
milestone: v4.0
milestone_name: Specific Training & Nutrition Coaching
status: ready_to_plan
stopped_at: Phase 22 complete (4/4) — ready to discuss Phase 23
last_updated: 2026-06-05T05:54:38.560Z
last_activity: 2026-06-04 -- Phase 22 execution started
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 8
  completed_plans: 8
  percent: 20
---

# State — Klaus

## Current Position

Phase: 23
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-05

Progress: [░░░░░░░░░░] 0%

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-03)

**Core value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Current focus:** Phase 23 — block + benchmark tracking

## Architecture (current)

- Brain `gemini-3.5-flash` (AI Studio) · Worker `deepseek-v4-flash` (DeepSeek) · Fallback `claude-haiku-4-5` (Anthropic, inline) · Tick-brain `qwen3-32b` (Groq, free) + Gemini fallback
- Embeddings `gemini-embedding-2` via AI Studio (NOT Vertex)
- All GCP/Pinecone names lowercase `klaus-` (uppercase = silent 404); `load_dotenv(override=True)` always
- Postgres holds the 3-year Garmin backfill; `MealStore` + `TrainingLogStore` in Firestore; `UserProfileStore` scaffold exists but is empty (this is the Phase 21 target)
- 8 cron jobs deployed (see Notes below); no new cron jobs planned for v4.0

## Accumulated Context

### Decisions

Recent decisions affecting v4.0 (full log in PROJECT.md):

- [v4.0 research]: `docs/COACHING_GUIDE.md` injected as `{coaching_guide}` via `_load_coaching_guide()` — same startup-cache pattern as `_load_self_md()`. NOT Pinecone RAG.
- [v4.0 research]: D-13 release is prompt-only. Tier A (blueprint goals) citable as targets; Tier B (measured data) citable only within recency window (lifts ≤14d, pace ≤7d, nutrition ≤2d). Same commit as guard removal.
- [v4.0 research]: Block-end benchmark trigger via `benchmark_due` flag in `BlockStore` checked by the existing 21:30 cron — no 8th scheduler job.
- [v4.0 research]: `BlockStore` + `BenchmarkStore` as dedicated Firestore stores (not extending `TrainingLogStore`). Doc ID `{date}_{facet}` makes benchmark logging idempotent.
- [v4.0 research]: Cross-cron coaching dedup via `OutreachLogStore` extension (or thin `CoachingTouchStore`), covering morning briefing + evening check-in + weekly review + autonomous tick. Not just the autonomous tick.
- [v4.0 research]: Plan_start_date = 2026-06-21 (Week 1 anchor). Week number always derived from `(today - plan_start_date).days // 7 + 1` — never hardcoded.

### Pending Todos

None captured yet.

### Blockers/Concerns

None.

## Deferred Items

Carried forward from v3.0 close:

| Category | Item | Status | Resolves when |
|----------|------|--------|---------------|
| verification-gap | 19-VERIFICATION.md `human_needed` | acknowledged | Phase 19 functionality verified live; paperwork only |
| feature-followup | Weekly review "Garmin activities unavailable" | open (low priority) | confirm 14-day fetch vs genuinely empty watch |
| verification-gap | v2.0 SC-1/SC-2/SC-4 live-staging | acknowledged | operator triggers staging crons |
| code-quality | 18-REVIEW.md M-2..M-4 + L-1..L-5 | open (housekeeping) | next housekeeping sprint |
| docs-drift | `docs/TECHNICAL_PLAN.md` stops before v2.0 | open (low priority) | next docs sweep |

## Notes

- **Test env:** full `pytest tests/` segfaults in one process (grpc/protobuf GC, Python 3.13) — verify per-file. 630+ passing baseline must hold after every v4.0 phase.
- **Firestore SERVER_TIMESTAMP** reads back as `DatetimeWithNanoseconds` — ISO-convert before `json.dumps` in any read tool. See `_jsonsafe_doc` helper in `memory/firestore_db.py`.
- **Cron jobs (8):** heartbeat (hourly), proactive-alerts (21:30), morning-briefing (*/10 6-10), chat-ingest (04:00), chat-export-ingest (04:30), reflect (22:00), autonomous-tick (*/20 7-21), weekly-training-review (Sun 10:00). Plus push-driven `/cron/healthkit-sync`.

## Session Continuity

Last session: 2026-06-04T08:48:33.323Z
Stopped at: Phase 22 context gathered
Resume file: .planning/phases/22-expert-coaching-knowledge-d-13-release/22-CONTEXT.md
