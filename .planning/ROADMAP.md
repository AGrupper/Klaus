# Roadmap: Klaus

This file is a compact milestone summary. Per-milestone phase detail lives in
`.planning/milestones/`. Active requirements live in `.planning/REQUIREMENTS.md`
(absent between milestones).

---

## Milestones

- ✅ **v1.0 — Foundation & Integrations** — Phases 1–13 (shipped 2026-05-18)
- ✅ **v2.0 — Consciousness & Autonomy** — Phases 14–18 (shipped 2026-05-23)
- ✅ **v3.0 — Project Shifu** — Phases 19–20 (shipped 2026-06-02)
- ✅ **v4.0 — Specific Training & Nutrition Coaching** — Phases 21–25 (shipped 2026-06-08)

---

## v4.0 — Specific Training & Nutrition Coaching (Phases 21–25) — Shipped 2026-06-08

Transformed Klaus from a qualitative coach into a genuinely expert, specific
hybrid-athlete coach — grounded in Amit's living blueprint + real Garmin/nutrition
data, driving facet-by-facet improvement across training blocks, proven by
end-of-block benchmarks and pace/strength projections toward the dated Oct/Nov goals.
Deployed to Cloud Run rev `klaus-agent-00091-4vz` (image `159cb1e`).

**Phases:** 5 (21–25) · **Plans:** 20 · **Requirements:** 20/20 · Suite 1058 passing · Audit `integration_ok`

| # | Phase | Outcome |
|---|-------|---------|
| 21 | Living Plan Ingestion | Blueprint → `UserProfileStore` structured fields (dated goals, weekly-split template, 6-slot fueling, supplements); `update_plan` tool — a living, critiqueable guide (PLAN-01/02/03) |
| 22 | Expert Coaching Knowledge + D-13 Release | `docs/COACHING_GUIDE.md` slim core on every brain call + `read_coaching_guide`; D-13 guard released under the Tier A/B data-presence contract — names real numbers, structural critique (COACH-01/02/06/07) |
| 23 | Block + Benchmark Tracking | `BlockStore` (date-range, auto transition) + `BenchmarkStore` (5-facet closed set), 4-block 16-week seed, 6 brain-direct tools, block-end benchmark state machine + HRV/ACWR gate in the 21:30 cron (BLOCK-01/02/03) |
| 24 | Strict Coaching Integration + Nutrition Accountability | `CoachingTopicStore` cross-cron dedup, macro/fueling-slot/supplement accountability, strict pushback + recovery-conflict framing, integrated morning block, session-quality at log time (COACH-03/04/05, NUTR-01/02/03, PROG-01/03/04) |
| 25 | Progress Projection + Benchmark Trend Reporting | Deterministic `project_goal_progress` + `get_goal_projection` tool + dense Garmin pace history; on-track/behind trajectories in the Sunday weekly review (PROG-02) |

Detail: see `.planning/milestones/v4.0-ROADMAP.md`,
`.planning/milestones/v4.0-REQUIREMENTS.md`, and
`.planning/milestones/v4.0-MILESTONE-AUDIT.md`.

---

## v3.0 — Project Shifu (Phases 19–20) — Shipped 2026-06-02

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

---

## v2.0 — Consciousness & Autonomy (Phases 14–18) — Shipped 2026-05-23

Made Klaus self-aware, judgment-driven, cost-transparent: every LLM call
metered, free always-on tick-brain, self-inspect tools, auto-generated SELF.md
manifest + mutable self_state, daily reflection cron, and the autonomous
engine (`*/20 7-21` triage + compose pipeline with repeat-suppression +
eval harness).

**Phases:** 5 · **Plans:** 24 · **Requirements:** 41/41

Detail: see `.planning/milestones/v2.0-ROADMAP.md` and
`.planning/milestones/v2.0-REQUIREMENTS.md`.

---

## v1.0 — Foundation & Integrations (Phases 1–13) — Shipped 2026-05-18

Built Klaus from scratch: cloud-hosted, fully integrated, proactive where
hardcoded. 13 phases — Telegram bot, Gmail + Calendar + TickTick tools,
Cloud Run + CI/CD, Firestore + Pinecone memory, weather/Readwise/Garmin,
Five Fingers helper, proactive alerts, morning briefing, Notion, two chat
ingestion pipelines.

Detail: see `.planning/MILESTONES.md § v1.0`.

---

## Backlog

- ✅ **Fix `hours_since_contact`** — done 2026-06-12. The trigger was doubly
  dead: (1) the gather read a `TELEGRAM_USER_ID` env var that exists nowhere
  in the deployment, so it queried user 0 and returned null on all 823 live
  ticks — now reads the first entry of `TELEGRAM_ALLOWED_USER_IDS` like every
  other call site; (2) the Layer-0 empty gate ignored `hours_since_contact`
  entirely, so a silence-only day could never reach tick-brain even with
  data — long silence (≥ 8h, `_SILENCE_TRIGGER_HOURS`, same threshold as
  `_infer_trigger_type`) now counts as a salient signal. **Behavioral note
  for Amit:** during multi-day absences, every tick past 8h-since-contact now
  consults the (free) tick-brain, which may judge an occasional check-in
  worth sending — previously structurally impossible. If that feels chatty,
  tune the threshold or the triage prompt's silence guidance, and mint
  fixtures from the new outreach logs.
- ✅ **Tune `prompts/autonomous_triage.md` against the expanded eval** —
  done 2026-06-12. Restructured the triage prompt for qwen (hard
  followup-silence rule + ordered vetoes→signals→silence decision
  procedure) and fixed two request-shape bugs found during tuning
  (`TICK_BRAIN_MAX_TOKENS=2048` — the global 4096 budget made every Groq
  request 413 on the 6000-TPM per-request admission check and silently
  re-route to metered Gemini; `TICK_BRAIN_TEMPERATURE=0.6` — provider
  default ~1.0 made borderline verdicts flip run-to-run). Post-tuning:
  P 0.83–0.90 / R 0.73–0.91 / F1 0.80–0.87 over three runs, WARNING-8
  violations 0/6 (was 3/3), aged-overdue recall preserved. Full numbers in
  `evals/tick_brain/README.md § Baselines`.
- **Deploy the Groq tick-brain fix + tuned triage prompt (ready as of
  2026-06-12)** — ships together: the 2026-06-11 `core/tick_brain.py`
  fixes (model id `qwen/qwen3-32b`, `<think>` strip), the 2026-06-12
  request-shape fixes (max_tokens 2048, temperature 0.6 — without the
  max_tokens fix the Groq primary still never runs), and the tuned
  `prompts/autonomous_triage.md`. No Cloud Run env changes needed — all
  new knobs default correctly in code. Next-day verification: `llm_usage`
  should show `tick_autonomous_calls` > 0 for the first time ever.
