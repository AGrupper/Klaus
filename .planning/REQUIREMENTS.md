# Requirements: Klaus — Project Shifu (v3.0)

**Defined:** 2026-05-25
**Core Value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Scope note:** This milestone deliberately omits personalized rules, thresholds, and targets (HR zones, lift goals, pace goals, scheduling buffers). The plumbing ships first; the user will populate `UserProfileStore` in a separate session.

---

## v3.0 Requirements (Phases 19–20)

### Postgres Schema (Phase 19)

- [ ] **SCHEMA-01**: `activities` table gains `training_load REAL`, `perceived_exertion SMALLINT`, `feel SMALLINT` columns
- [ ] **SCHEMA-02**: `daily_biometrics` table gains `vo2_max REAL`, `training_load_acute REAL`, `training_load_chronic REAL`, `acwr REAL` columns
- [ ] **SCHEMA-03**: All new columns added via idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` statements that can run repeatedly without error

### Garmin Ingestion (Phase 19)

- [ ] **INGEST-01**: `scripts/ingest_garmin_zip.py` activity parser extracts `trainingLoad`, `perceivedExertion`, `feel` from each activity summary (NULL-safe when fields are absent)
- [ ] **INGEST-02**: UDS parser extracts `vo2MaxValue` and writes it to `daily_biometrics.vo2_max`
- [ ] **INGEST-03**: 3-year historical Garmin export ingests successfully end-to-end into Neon Postgres, sanity-checked via `mcp_tools/database_tool.py` queries (row counts, date ranges, NULL rates documented)

### UserProfileStore (Phase 19)

- [ ] **PROFILE-01**: `UserProfileStore.load()` reads `users/amit` from Firestore; returns `{}` on any failure, never raises
- [ ] **PROFILE-02**: `UserProfileStore.update(patch)` merges fields and stamps `updated_at` via `firestore.SERVER_TIMESTAMP`
- [ ] **PROFILE-03**: `UserProfileStore.bootstrap_if_empty()` creates the document with empty scaffold (`athletic_goals: []`, `training_constraints: []`, `recovery_preferences: {}`, `schema_version: 1`) when missing; no personalized values seeded
- [ ] **PROFILE-04**: `get_training_profile` and `update_training_profile` tools registered brain-direct at all 5 sites in `core/tools.py`

### Garmin Tool Extensions (Phase 19)

- [ ] **GARMIN-01**: `fetch_garmin_training_status()` returns dict with `vo2_max`, `training_status` enum, `load_focus`
- [ ] **GARMIN-02**: `fetch_garmin_activities(days=7)` returns normalized list including `perceived_exertion` and `feel` when Garmin captured them
- [ ] **GARMIN-03**: `compute_acwr(activities_28d)` returns `{"acute": float, "chronic": float, "ratio": float | None}`; returns `None` ratio when chronic baseline is insufficient
- [ ] **GARMIN-04**: `fetch_training_status` and `fetch_recent_activities` registered as worker-delegated tools (not in `SMART_AGENT_DIRECT_TOOLS`)
- [ ] **GARMIN-05**: `core/morning_briefing.py` `_gather_data()` writes fresh daily biometrics + activities into Postgres on each tick (best-effort; Postgres outage does not block briefing)

### Nutrition Tracking via Google Fit (Phase 19)

- [ ] **NUTR-01**: `mcp_tools/google_fit_tool.py` wraps the Google Fitness REST API (`users/me/dataSources` + `users/me/datasets/aggregate` for `com.google.nutrition` data type) using existing Google OAuth; returns normalized meal records (timestamp, calories, protein_g, carbs_g, fat_g, meal_type)
- [ ] **NUTR-02**: `MealStore` in `memory/firestore_db.py` persists meal records to `meals/{date}/{timestamp}` with fields `timestamp`, `calories`, `protein_g`, `carbs_g`, `fat_g`, `meal_type`, `source` (`google_fit` for v0); idempotent on re-sync
- [ ] **NUTR-03**: `fetch_recent_meals(hours)` registered as worker-delegated tool; returns normalized meal list for on-demand queries from the brain
- [ ] **NUTR-04**: `core/autonomous.py` `gather_situation()` (Layer 0) syncs new meals from Google Fit to `MealStore` on each tick and includes meals-since-last-tick in the tick-brain's triage context, so the tick-brain can decide whether to comment proactively mid-day
- [ ] **NUTR-05**: `core/morning_briefing.py` `_gather_data()` aggregates yesterday's meals from `MealStore` (totals + per-meal breakdown + biggest gap) and exposes them to the prompt for the morning nutrition recap
- [ ] **NUTR-06**: `prompts/autonomous_triage.md` updated so the tick-brain treats new meals as a potential trigger to speak up (timing relative to workouts, macro imbalance vs. training context, large gap since last meal); empty `{training_profile}` means generic critique only
- [ ] **NUTR-07**: `prompts/morning_briefing.md` updated to include yesterday's nutrition recap when `MealStore` has data; silently omitted when no meals logged
- [ ] **NUTR-08**: `prompts/meal_audit.md` exists with non-personalized critique guidance (nutrition density, protein adequacy, carb appropriateness vs. training context); referenced by both the autonomous tick (mid-day) and morning briefing (recap)

### Smart-Agent Prompt Integration (Phase 19)

- [ ] **PROMPT-01**: `render_smart_system()` in `core/main.py` injects `{training_profile}` placeholder using the same pattern as `{self_md}` / `{self_state}` / `{journal_digest}`
- [ ] **PROMPT-02**: `prompts/smart_agent.md` gains a TRAINING & ATHLETIC COACHING section with same JARVIS voice, sharper edge for training/nutrition topics; instructs that empty profile means "ask the user, don't invent goals"
- [ ] **PROMPT-03**: `docs/SELF.md` regenerated by `core/self_manifest.py` to list all 7 new tools

### TrainingLogStore (Phase 20)

- [ ] **LOG-01**: `TrainingLogStore.log_session(...)` writes to `training_log/{date}_{slot}` with fields `date`, `type`, `planned`, `completed`, `skipped_reason`, `rpe`, `feel`, `notes`, `source` (`garmin | telegram | manual_chat`), `garmin_activity_id`
- [ ] **LOG-02**: `TrainingLogStore.get_recent(days)` and `get_by_date(date)` return entries for queries
- [ ] **LOG-03**: `log_training` tool registered brain-direct; accepts free-form fields so the brain can log off-grid workouts from conversation ("I lifted at the gym, no watch, RPE 7")
- [ ] **LOG-04**: `get_training_history` tool registered as worker-delegated

### Training Check-in Cron (Phase 20)

- [ ] **CHECKIN-01**: `/cron/training-checkin` endpoint exists in `interfaces/web_server.py` with same OIDC auth pattern as `cron_autonomous_tick`
- [ ] **CHECKIN-02**: Cron first silent-syncs Garmin activities with populated `perceived_exertion` to `training_log` (no Telegram message)
- [ ] **CHECKIN-03**: Cron sends Telegram message only for planned calendar workouts that lack both a Garmin RPE and a log entry; branches into "RPE prompt" or "skipped vs. watch off" based on activity presence
- [ ] **CHECKIN-04**: RPE prompt uses inline keyboard 1–10 buttons (same pattern as five-fingers attendance); after RPE selected, a follow-up message asks for optional notes (`/skip` or timeout to skip)
- [ ] **CHECKIN-05**: Cron is fully silent on days where all planned workouts have either a Garmin RPE sync or an existing log entry
- [ ] **CHECKIN-06**: Cron runs at `0 21 * * *` Asia/Jerusalem (not 21:30, to avoid colliding with `proactive-alerts`)

### Weekly Training Review Cron (Phase 20)

- [ ] **REVIEW-01**: `/cron/weekly-training-review` endpoint exists in `interfaces/web_server.py` with OIDC auth
- [ ] **REVIEW-02**: Weekly review composes from 7-day `training_log`, `activities`, `daily_biometrics`, `meal_audits`, and `UserProfileStore.athletic_goals` (skipped if empty)
- [ ] **REVIEW-03**: `prompts/weekly_training_review.md` exists; produces planned-vs-actual table, HRV/RHR/sleep trend, one suggestion for next week
- [ ] **REVIEW-04**: Cron runs at `0 10 * * 0` Asia/Jerusalem (Sunday 10:00, workweek start in Israel)

### Recovery-Aware Morning Briefing (Phase 20)

- [ ] **RECOVERY-01**: `core/morning_briefing.py` `_gather_data()` computes a `recovery_concern` boolean flag from ACWR, HRV status, sleep score, and today's scheduled workouts
- [ ] **RECOVERY-02**: V0 thresholds (`ACWR > 1.5` + high-intensity; HRV unbalanced/low + low sleep + heavy lifting; consecutive low-sleep days + intense session) are defined in a module-level `RECOVERY_THRESHOLDS` dict with a docstring noting they are starting heuristics to be tuned after 2 weeks of journaled data
- [ ] **RECOVERY-03**: `prompts/morning_briefing.md` and `prompts/proactive_alert.md` read `recovery_concern` and shift tone — direct, metric-anchored, suggesting (not commanding) dialing back intensity

### Cloud Scheduler Bootstrap (Phase 20)

- [ ] **CRON-01**: `scripts/bootstrap_shifu_crons.sh` creates `klaus-training-checkin` and `klaus-weekly-training-review` Cloud Scheduler jobs using the existing `CLOUD_SCHEDULER_SA_EMAIL` OIDC service account
- [ ] **CRON-02**: `docs/DEPLOYMENT.md` gains a "Phase Shifu" section documenting the two new jobs alongside the existing 9 (matching the §19 inventory table convention)

---

## Future Requirements (Deferred to Later Milestones)

- **Personalized profile data**: User-specific HR zones, lift targets, pace goals, scheduling buffers (e.g., Five Fingers / lifting interactions) — to be populated via `update_training_profile` in a separate session once plumbing exists.
- **Recovery threshold tuning**: ACWR / HRV / sleep thresholds will be calibrated from 2+ weeks of journaled data once `training_log` accumulates.
- **Rest-day modeling**: Emerges from `training_log` + calendar; no explicit modeling needed in v0.
- **Food-name fidelity**: v0 uses Google Fit which carries macros + timing but not food names. If food-name awareness matters later (e.g., "that was sushi — sodium is high"), add an iPhone Shortcut → Apple Health → Klaus webhook bridge in a later milestone.
- **Manual screenshot fallback for richer meal detail**: deferred until Google Fit data proves insufficient in practice.

---

## Out of Scope (v3.0)

- **Personal training rules / numeric targets** — explicit user choice. Plan delivers plumbing; values come later via tool calls.
- **Strength tracking beyond RPE** — no per-set weight/rep logging in v0. The training log captures session-level RPE, type, completion, and notes. Per-set tracking deferred.
- **Activity matching across watch-off sessions** — when Garmin has no record, the user tells Klaus in chat; he calls `log_training(source="manual_chat")`. No fancy heuristic matching.
- **Original photo-audit pipeline** — superseded by Google Fit (Lifesum sync) as the canonical meal data source. No Telegram-photo handling, no `log_meal_audit` tool, no router changes.

---

## Traceability

| REQ-ID         | Phase | Status  |
|----------------|-------|---------|
| SCHEMA-01      | 19    | Pending |
| SCHEMA-02      | 19    | Pending |
| SCHEMA-03      | 19    | Pending |
| INGEST-01      | 19    | Pending |
| INGEST-02      | 19    | Pending |
| INGEST-03      | 19    | Pending |
| PROFILE-01     | 19    | Pending |
| PROFILE-02     | 19    | Pending |
| PROFILE-03     | 19    | Pending |
| PROFILE-04     | 19    | Pending |
| GARMIN-01      | 19    | Pending |
| GARMIN-02      | 19    | Pending |
| GARMIN-03      | 19    | Pending |
| GARMIN-04      | 19    | Pending |
| GARMIN-05      | 19    | Pending |
| NUTR-01        | 19    | Pending |
| NUTR-02        | 19    | Pending |
| NUTR-03        | 19    | Pending |
| NUTR-04        | 19    | Pending |
| NUTR-05        | 19    | Pending |
| NUTR-06        | 19    | Pending |
| NUTR-07        | 19    | Pending |
| NUTR-08        | 19    | Pending |
| PROMPT-01      | 19    | Pending |
| PROMPT-02      | 19    | Pending |
| PROMPT-03      | 19    | Pending |
| LOG-01         | 20    | Pending |
| LOG-02         | 20    | Pending |
| LOG-03         | 20    | Pending |
| LOG-04         | 20    | Pending |
| CHECKIN-01     | 20    | Pending |
| CHECKIN-02     | 20    | Pending |
| CHECKIN-03     | 20    | Pending |
| CHECKIN-04     | 20    | Pending |
| CHECKIN-05     | 20    | Pending |
| CHECKIN-06     | 20    | Pending |
| REVIEW-01      | 20    | Pending |
| REVIEW-02      | 20    | Pending |
| REVIEW-03      | 20    | Pending |
| REVIEW-04      | 20    | Pending |
| RECOVERY-01    | 20    | Pending |
| RECOVERY-02    | 20    | Pending |
| RECOVERY-03    | 20    | Pending |
| CRON-01        | 20    | Pending |
| CRON-02        | 20    | Pending |

**Coverage:** 45/45 requirements mapped (26 → Phase 19, 19 → Phase 20). No orphans.
