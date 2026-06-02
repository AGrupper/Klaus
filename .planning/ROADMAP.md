# Roadmap: Klaus

This file is a compact milestone summary. Per-milestone phase detail lives in
`.planning/milestones/`. Active requirements live in `.planning/REQUIREMENTS.md`
(absent between milestones).

---

## Milestones

- ✅ **v1.0 — Foundation & Integrations** — Phases 1–13 (shipped 2026-05-18)
- ✅ **v2.0 — Consciousness & Autonomy** — Phases 14–18 (shipped 2026-05-23)
- ✅ **v3.0 — Project Shifu** — Phases 19–20 (shipped 2026-06-02)
- 📋 **v4.0 — Personalized Training & Nutrition Plan** — next (not yet scoped)

---

## v3.0 — Project Shifu (Phases 19–20) ✓ Shipped 2026-06-02

Gave Klaus athletic-coaching capability: he reads his own 3-year Garmin training
history from Postgres, ingests Lifesum nutrition via the iOS HealthKit bridge,
holds the user accountable to logged sessions with an evidence-first 21:30
training check-in, surfaces recovery state (ACWR / HRV / sleep) in the morning
briefing and evening alert, and sends a Sunday weekly training review.
Plumbing + accountability loop — **personalized targets/prescriptions are
deferred to v4.0** (the `UserProfileStore` scaffold stays empty until then, so
coaching is qualitative under the D-13 no-fabrication guard).

**Phases:** 5 (19, 19.1, 19.2, 19.3, 20) · **Plans:** 17 · **Tasks:** 27 · Verified 19/19 + live UAT

| # | Phase | Outcome |
|---|-------|---------|
| 19 | Training Awareness & Nutrition Coaching | Postgres schema + 3yr Garmin backfill, `UserProfileStore` scaffold, ACWR/training-status/activities reads, `MealStore`, mid-day nutrition coaching + morning recap |
| 19.1 | HealthKit Nutrition Bridge | Lifesum → HealthKit → `/cron/healthkit-sync` → `MealStore` (server-side aggregation, idempotent); live UAT 6/6 |
| 19.2 | Fiber Through Reasoning Layer *(inserted)* | `DietaryFiber_g` threaded through normalizer → `MealStore` totals → `meal_audit` + briefings |
| 19.3 | Meal Read Paths → MealStore *(inserted)* | Both meal read paths repointed off the dead Google Fit source to `MealStore` |
| 20 | Accountability Crons & Recovery Briefing | `TrainingLogStore` + `PendingPromptStore`, evidence-first check-in (inline keyboards, Garmin-RPE-aware) folded into 21:30 cron, `recovery_concern` in briefing + alert, Sunday weekly review, `bootstrap_shifu_crons.sh` |

Detail: see `.planning/milestones/v3.0-ROADMAP.md` and
`.planning/milestones/v3.0-REQUIREMENTS.md`.

**Post-ship hardening** (found in live UAT 2026-06-02, all fixed + deployed):
typed training-note capture (not just reply-gesture), orchestrator Bot wiring for
confirmations, `training_log` JSON serialization (`SERVER_TIMESTAMP`), and routing
of Klaus-created workouts to the `Training` calendar (+ bare "Practice" detection).

---

## v2.0 — Consciousness & Autonomy (Phases 14–18) ✓ Shipped 2026-05-23

Made Klaus self-aware, judgment-driven, cost-transparent: every LLM call
metered, free always-on tick-brain, self-inspect tools, auto-generated SELF.md
manifest + mutable self_state, daily reflection cron, and the autonomous
engine (`*/20 7-21` triage + compose pipeline with repeat-suppression +
eval harness).

**Phases:** 5 · **Plans:** 24 · **Requirements:** 41/41

Detail: see `.planning/milestones/v2.0-ROADMAP.md` and
`.planning/milestones/v2.0-REQUIREMENTS.md`.

---

## v1.0 — Foundation & Integrations (Phases 1–13) ✓ Shipped 2026-05-18

Built Klaus from scratch: cloud-hosted, fully integrated, proactive where
hardcoded. 13 phases — Telegram bot, Gmail + Calendar + TickTick tools,
Cloud Run + CI/CD, Firestore + Pinecone memory, weather/Readwise/Garmin,
Five Fingers helper, proactive alerts, morning briefing, Notion, two chat
ingestion pipelines.

Detail: see `.planning/MILESTONES.md § v1.0`.

---

## Backlog

(none recorded)

---

## Next Milestone

**v4.0 — Personalized Training & Nutrition Plan (next).** Take Amit's goals
document + Klaus's real data (3yr Garmin history, nutrition, and the now-flowing
`training_log`) → populate `UserProfileStore` with concrete, **data-grounded**
targets and unlock prescriptive coaching (releases the D-13 "no invented numbers"
guard so recovery advice, the weekly review, and check-ins can name real numbers).
Not yet scoped — start with `/gsd-new-milestone`.

Other deferred candidates: recurring "daily review" skill (check-in persistence /
re-surfacing unanswered prompts), `MealAuditStore` (persisted nutrition critique),
deferred email-send, WhatsApp outbound, multi-user.
