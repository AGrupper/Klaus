# Milestones — Klaus

## v3.0 Project Shifu (Shipped: 2026-06-02)

**Phases completed:** 5 phases (19, 19.1, 19.2, 19.3, 20), 17 plans, 27 tasks. Verified 19/19 + live UAT. Timeline 2026-05-27 → 2026-06-02 (git `549b0b2..428b782`).

**Key accomplishments:**

- **Training/nutrition data layer (Phase 19):** Postgres schema migration + 3-year Garmin backfill, `UserProfileStore` scaffold, extended Garmin reads (training status, recent activities, `compute_acwr`), `MealStore`, mid-day nutrition coaching + morning recap, smart-agent prompt extension.
- **iOS HealthKit nutrition bridge (19.1–19.3):** Lifesum → HealthKit Shortcut → `/cron/healthkit-sync` → server-side aggregation → `MealStore` (idempotent); fiber threaded end-to-end; both meal read paths repointed off the dead Google Fit source to `MealStore`. Live UAT 6/6.
- **Accountability loop (Phase 20):** `TrainingLogStore` + `PendingPromptStore`, evidence-first training check-in (Garmin-RPE-aware, inline-keyboard watch-off/skip/notes) folded into the 21:30 proactive-alerts cron, `log_training`/`get_training_history` tools.
- **Recovery awareness (Phase 20):** `RECOVERY_THRESHOLDS` v0 + `compute_recovery_concern` (ACWR/HRV/sleep/intensity, D-12 severity, D-13 no-fabrication) surfaced in both the morning briefing and evening alert.
- **Weekly training review (Phase 20):** Sunday 10:00 brain-composed scorecard cron (OIDC route) reading `training_log` + Garmin + biometrics + `MealStore` + goals; 170h heartbeat staleness key.
- **Ops (Phase 20):** Telegram `callback_query` infrastructure, `bootstrap_shifu_crons.sh`, DEPLOYMENT.md Phase Shifu section + SELF.md regen.

**Post-ship hardening** (found in live UAT 2026-06-02, all fixed + deployed): typed training-note capture (not just reply-gesture), orchestrator Bot wiring for confirmations, `training_log` JSON serialization (`SERVER_TIMESTAMP` → ISO), and routing of Klaus-created workouts to the `Training` calendar with bare-"Practice" detection.

**Known deferred items at close:** 2 (see STATE.md § Deferred Items — stale Phase 19 verification/UAT paperwork; functionality verified live in production).

---

## v1.0 — Foundation & Integrations (Phases 1–13) ✓ Complete

**Completed:** 2026-05-18
**Goal:** Build Klaus from scratch — cloud-hosted, fully integrated, proactive where hardcoded.

### Phases Shipped

| Phase | Name | Highlights |
|-------|------|-----------|
| 1 | Auth & Scaffolding | Persistent Google OAuth, project scaffold |
| 2 | Core LLM + Telegram | `llm_client.py` dual-model, Telegram bot webhook |
| 3 | Google Tools | Calendar + Gmail tools (list, create, free/busy, delete) |
| 4 | Task Tool | TickTick Open API — reminder (push alarm) + deadline (silent) |
| 5 | Cloud Run Deploy | Dockerfile, FastAPI web server, GitHub Actions CI/CD, Secret Manager |
| 6 | Memory | Firestore conversation history, Pinecone RAG (gemini-embedding-2) |
| 7 | External Connections | Weather (wttr.in), Readwise, Garmin Connect |
| 8 | Five Fingers | 3 cron flows: pre-practice, attendance, morning-after follow-up |
| 9 | Proactive Alerts | Nightly 21:30 scan: weather conflicts, overloaded day, travel time |
| 10 | Morning Briefing | Garmin-anchored, */10 poll, all data sources, injected into conversation |
| 11 | Notion Integration | 5 tools: search, get_page, query_database, create_page, append_blocks |
| 12 | Chat-Log Ingestion | Claude Code JSONL → Pinecone (kind="chat") + Notion DB |
| 13 | Multi-Source Export | Claude.ai + ChatGPT + Gemini exports → same pipeline |

---

## v2.0 — Consciousness & Autonomy (Phases 14–18) ✓ Shipped 2026-05-23

**Delivered:** Self-aware, judgment-driven autonomous agent with cost visibility and a free always-on mind.

**Phases completed:** 14–18 (24 plans total — 15 in Phases 14–17, 9 in Phase 18).

**Key accomplishments:**

- Every LLM call cost-metered to Firestore (`LLMUsageStore`); 4 priced models in `core/pricing.py`
- Free always-on tick-brain (Groq/Qwen3-32B with Gemini fallback) upgrades heartbeat reasoning
- Klaus can read and search his own deployed source via brain-direct tools (`list_own_files` / `read_own_source` / `search_own_source`)
- Doubt-free self-model: `docs/SELF.md` auto-generated manifest + `SelfStateStore` mutable state + `get_self_status` tool, all injected into every conversation
- Daily reflection cron writes journal entries to Firestore + Pinecone (`kind="self"`) and updates self_state
- The Autonomous Engine: `*/20 7-21` Cloud Scheduler tick triggers `core/autonomous.py`'s 3-layer pipeline (gather → triage → compose), with `OutreachLogStore` repeat-suppression, `FollowupStore` self-scheduled check-backs, OIDC-protected route, and a fixture-based eval harness for tick-brain judgment quality

**Stats:**

- 41 requirements, all complete
- 5 phases, 24 plans, ~180 commits
- Test suite: 465 passing locally (4 local-env-only failures documented in deferred-items.md)
- ~4,345 LOC contributed in Phase 18 alone (28 files)
- 9 Cloud Scheduler jobs running (was 7 pre-milestone; added `klaus-reflect` Phase 17 + `klaus-autonomous-tick` Phase 18)

**Git range:** `feat(14-01)` → `fix(18): post-review cleanup` (commit `0be394e`)

**Deferred at close (live-staging blockers; not phase regressions — see STATE.md § Deferred Items):**

- Phase 16 HUMAN-UAT: 3 pending scenarios (SELF.md cold-start, self_state bootstrap query, get_self_status live dispatch)
- Phase 16 VERIFICATION: human_needed (Firestore + Cloud Run cold-start checks)
- Phase 18 VERIFICATION: human_needed (SC-1/SC-2/SC-4 require live Telegram + Cloud Run; SC-5 requires real `TICK_BRAIN_API_KEY`; SC-3 verified locally)

**Known issues deferred to next housekeeping sprint (see `.planning/phases/18-autonomous-engine/deferred-items.md`):**
M-2 due_at parse defence · M-3 degraded-gather observability · M-4 `id` param shadowing rename · L-1..L-5 (file split, slug collision, tick_total derivation, logger convention, follow-up snapshot enrichment).

**What's next:** Not yet defined. Options include deferred email-send, a Phase 19 hardening sweep, WhatsApp outbound, multi-user support, or a new direction.

---
