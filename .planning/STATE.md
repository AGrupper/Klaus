---
gsd_state_version: 1.0
milestone: v4.0
milestone_name: Specific Training & Nutrition Coaching
status: planning
last_updated: "2026-06-03T11:23:40.027Z"
last_activity: 2026-06-03
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State — Klaus

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-06-03 — Milestone v4.0 started

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-06-02)

**Core value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Current focus:** Planning v4.0 — ingest Amit's goals doc + populate `UserProfileStore` with data-grounded targets → prescriptive coaching. Start with `/gsd-new-milestone`.

## Architecture (current)

- Brain `gemini-3.5-flash` (AI Studio) · Worker `deepseek-v4-flash` (DeepSeek) · Fallback `claude-haiku-4-5` (Anthropic, inline) · Tick-brain `qwen3-32b` (Groq, free) + Gemini fallback
- Embeddings `gemini-embedding-2` via AI Studio (NOT Vertex)
- All GCP/Pinecone names lowercase `klaus-` (uppercase = silent 404); `load_dotenv(override=True)` always
- Postgres holds the 3-year Garmin backfill (`activities` + `daily_biometrics`, ACWR columns); `MealStore` (Firestore) holds nutrition; `TrainingLogStore` holds sessions
- LLM costs metered via `LLMUsageStore`; `compute_cost()` in `core/pricing.py`
- `_get_orchestrator()` is a process-wide singleton; `orchestrator.bot` is set at startup (v3.0 fix, for typed-note confirmations)
- Full per-phase implementation notes: phase `*-SUMMARY.md` files + `.planning/milestones/v{1,2,3}.0-*`

## Cron jobs (8 deployed)

1. heartbeat — `0 * * * *`
2. proactive-alerts — `30 21 * * *` (also runs the 21:30 training check-in, v3.0)
3. morning-briefing-tick — `*/10 6-10 * * *`
4. chat-ingest — `0 4 * * *`
5. chat-export-ingest — `30 4 * * *`
6. klaus-reflect — `0 22 * * *`
7. klaus-autonomous-tick — `*/20 7-21 * * *`
8. klaus-weekly-training-review — `0 10 * * 0` (v3.0)

Plus push-driven `/cron/healthkit-sync`. *(Five Fingers crons removed; Google Fit deprecated — commit `91e218e`.)*

## Blockers

None.

## Notes

- **Test env:** full `pytest tests/` segfaults in one process (grpc/protobuf cyclic-GC, on Python 3.13 **and** 3.14) — verify **per-file**. `conftest.py` disables GC to prevent the hard crash; ~100 pre-existing cross-test-isolation failures remain (separate cleanup). See `feedback_python_version` memory.
- **Firestore `SERVER_TIMESTAMP`** reads back as `DatetimeWithNanoseconds` — ISO-convert before `json.dumps` in any read tool (bit `MealStore` + `TrainingLogStore`; helper `memory/firestore_db.py::_jsonsafe_doc`). See `feedback_firestore_timestamp_json` memory.
- **Security:** the GitHub PAT currently sits in `.git/config`'s remote URL in plaintext — rotate it and move the remote to SSH or a credential helper.

## Deferred Items

Items acknowledged and deferred at milestone close. None are code defects; all are
live-staging blockers (need real services), stale sign-off paperwork (functionality
verified live), or local dev-env hygiene.

| Category | Item | Status | Resolves when |
|----------|------|--------|---------------|
| verification-gap | 19-VERIFICATION.md status `human_needed` | acknowledged at v3.0 close | Phase 19 functionality verified live (SC#2 closed by 19.1, meal paths 2026-05-31); paperwork sign-off only |
| uat-gap | 19-HUMAN-UAT.md (status resolved, 0 pending scenarios) | acknowledged at v3.0 close | no action — already resolved |
| feature-followup | Weekly review reports "Garmin activities unavailable" | open (low priority) | confirm whether the 14-day activities/biometrics fetch is failing vs genuinely empty (no workouts logged on the watch) |
| verification-gap | v2.0 SC-1/SC-2/SC-4 live-staging verification (16-/18-VERIFICATION.md) | acknowledged at v2.0 close | operator triggers staging crons with real Telegram + Cloud Run + Groq key |
| code-quality | 18-REVIEW.md M-2..M-4 + L-1..L-5 (8 findings) | open (housekeeping) | `.planning/phases/18-autonomous-engine/deferred-items.md` § Post-review backlog |
| docs-drift | `docs/TECHNICAL_PLAN.md` stops before v2.0 Phases 15–18 | open (low priority) | next docs sweep |

## Operator Next Steps

- Start v4.0 with `/gsd-new-milestone` (have the goals document ready as input).
- Optional, any time: rotate the GitHub token; investigate the weekly-review Garmin gap; the ~100 pre-existing test-isolation failures.
