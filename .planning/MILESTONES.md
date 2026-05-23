# Milestones — Klaus

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
