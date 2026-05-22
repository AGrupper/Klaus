# Requirements: Klaus — Consciousness & Autonomy (v2.0)

**Defined:** 2026-05-18
**Core Value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.

## v2.0 Requirements (Phases 14–18)

### Cost Metering (Phase 14)

- [x] **COST-01**: Every LLM call records model, purpose, input tokens, output tokens, and computed cost
- [x] **COST-02**: `LLMUsageStore` stores daily and monthly usage in Firestore (`llm_usage/{YYYY-MM-DD}`)
- [x] **COST-03**: `compute_cost()` returns 0.0 (never raises) for unpriced/free models
- [x] **COST-04**: `LLMClient.chat()` accepts an optional `purpose` param and meters automatically
- [x] **COST-05**: All three backends (Anthropic, Gemini, OpenAI) surface token usage in their response envelope

### Tick-Brain (Phase 14)

- [x] **TICK-01**: `core/tick_brain.py` wraps a free Groq/Qwen3-32B LLM client for always-on reasoning
- [x] **TICK-02**: Tick-brain falls back to Gemini 3 Flash on Groq `LLMError` or rate-limit
- [x] **TICK-03**: Parse failures in structured tick-brain output default to safe mode (`should_act=False`)
- [x] **TICK-04**: Tick-brain model is fully config-driven via `TICK_BRAIN_*` env vars
- [x] **TICK-05**: Heartbeat gains a tick-brain reasoning pass over raw health signals (gated: only runs when signals present or weekly digest)

### LLM Strategy (Phase 14)

- [x] **LLM-01**: Stale "Claude"/"JARVIS-style" comments in `core/main.py` are corrected
- [x] **LLM-02**: LLM-per-purpose map (tick-brain, brain, worker, fallback, embeddings) documented in `docs/TECHNICAL_PLAN.md`
- [x] **LLM-03**: `max_tokens` / `max_output_tokens` cap is normalized across all three backends
- [x] **LLM-04**: `_OpenAIBackend` accepts a `base_url` param so Groq can be targeted without mutating the global env var

### Codebase Self-Knowledge (Phase 15)

- [x] **SELF-01**: `list_own_files(subdir=None)` tool lists Klaus's deployed source files
- [x] **SELF-02**: `read_own_source(path)` tool returns file contents; rejects path traversal and a secret denylist (`.env*`, `*secret*`, `*credential*`, `*token*`, OAuth JSON)
- [x] **SELF-03**: `search_own_source(query)` tool full-text searches across source
- [x] **SELF-04**: All three self-inspect tools registered in `core/tools.py` (TOOL_SCHEMAS, _HANDLERS, SMART_AGENT_DIRECT_TOOLS, handler functions, WORKER exclusion)
- [x] **SELF-05**: `prompts/smart_agent.md` tells Klaus he can inspect his own source

### Self-Model & State Awareness (Phase 16)

- [x] **MODEL-01**: `generate_manifest()` auto-generates `docs/SELF.md` by introspecting tool schemas, cron routes, outbound channels, model map, memory stores — including a git SHA/content hash for staleness detection
- [x] **MODEL-02**: `docs/SELF.md` covers every tool, every cron (all 9 including new ones), outbound channels, memory layers, and honest current limits
- [x] **MODEL-03**: `SelfStateStore` persists `identity_summary`, `current_focus`, `recent_context`, `mood`, `updated_at` in Firestore `config/self_state`
- [x] **MODEL-04**: Per-message prompt assembly in `core/main.py` injects SELF.md digest (stable) + self_state (volatile) at the render step, stable-content-first for prompt cache
- [x] **MODEL-05**: `get_self_status` direct tool returns uptime, today's message count, today/month cost, latest heartbeat status (degrades gracefully when journal absent)
- [x] **MODEL-06**: Heartbeat `check_code()` flags stale `SELF.md` by comparing embedded SHA against current repo state (weekly FYI tier)

### Reflection & Journal (Phase 17)

- [x] **JOUR-01**: `run_reflection()` gathers the day (conversation history, message count, LLM cost, heartbeat, calendar) and produces a journal entry + updated self_state fields
- [x] **JOUR-02**: `JournalStore` writes `journal/{date}` docs in Firestore
- [x] **JOUR-03**: Each journal entry is upserted to Pinecone with `kind="self"`
- [x] **JOUR-04**: `kind="self"` added to `_VALID_KINDS` in `memory/pinecone_db.py`; self-recall requires explicit `kinds=["self"]`
- [x] **JOUR-05**: `/cron/reflect` route added to `interfaces/web_server.py` with OIDC auth; Cloud Scheduler runs it daily ~22:00
- [x] **JOUR-06**: Per-message prompt assembly injects a digest of the last ~3 journal entries

### Autonomous Engine (Phase 18)

- [ ] **AUTO-01**: `run_autonomous_tick()` implements the 3-layer design: Layer 0 (free context gather), Layer 1 (tick-brain judgment), Layer 2 (main-brain composition, only on escalation)
- [ ] **AUTO-02**: `gather_situation()` fetches calendar, TickTick, unread email count, follow-ups, hours-since-contact, recent journal, and today's outreach log
- [x] **AUTO-03**: Repeat-suppression: `outreach_log/{date}` records every escalated send; tick-brain is informed of what was already raised today (store-layer complete Phase 18-01; wiring in Phase 18-06)
- [x] **AUTO-04**: `FollowupStore` stores scheduled follow-ups (`followups` collection: `{due_at, note, created_at, done}`)
- [x] **AUTO-05**: `schedule_followup(when, note)` direct tool lets Klaus schedule his own check-backs mid-conversation
- [ ] **AUTO-06**: `/cron/autonomous-tick` route added; Cloud Scheduler fires `*/20 7-21 * * *`
- [x] **AUTO-07**: `prompts/autonomous_triage.md` (tick-brain) and `prompts/autonomous.md` (main-brain) created with wide-latitude framing
- [ ] **AUTO-08**: Judgment eval harness: `evals/tick_brain/` with ~20–30 labeled `SituationSnapshot` fixtures
- [ ] **AUTO-09**: `scripts/eval_tick_brain.py` scores a candidate model against fixtures (precision/recall on "should speak")

### Infrastructure & Docs (Cross-cutting)

- [ ] **INFRA-01**: `docs/DEPLOYMENT.md` documents all 9 Cloud Scheduler jobs (existing 7 + reflect + autonomous-tick), new Groq secret, and the Five Fingers duplicate job-id quirk
- [x] **INFRA-02**: Groq API key stored in GCP Secret Manager

## Out of Scope

| Feature | Reason |
|---------|--------|
| Email sending | Gmail stays read-only; clean fast-follow after this milestone |
| WhatsApp autonomous outbound | User-initiated only (wa.me links); no change |
| Multi-user support | Single user throughout |
| Spend caps / hard limits | Explicit user choice: measure, never enforce |
| Web chat UI (Phase 2 from PRD) | Deferred; Telegram sufficient |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| COST-01 | Phase 14 | Complete ✓ 2026-05-18 |
| COST-02 | Phase 14 | Complete ✓ 2026-05-18 |
| COST-03 | Phase 14 | Complete ✓ 2026-05-18 |
| COST-04 | Phase 14 | Complete ✓ 2026-05-18 |
| COST-05 | Phase 14 | Complete ✓ 2026-05-18 |
| TICK-01 | Phase 14 | Complete ✓ 2026-05-18 |
| TICK-02 | Phase 14 | Complete ✓ 2026-05-18 |
| TICK-03 | Phase 14 | Complete ✓ 2026-05-18 |
| TICK-04 | Phase 14 | Complete ✓ 2026-05-18 |
| TICK-05 | Phase 14 | Complete ✓ 2026-05-18 |
| LLM-01 | Phase 14 | Complete ✓ 2026-05-18 |
| LLM-02 | Phase 14 | Complete ✓ 2026-05-18 |
| LLM-03 | Phase 14 | Complete ✓ 2026-05-18 |
| LLM-04 | Phase 14 | Complete ✓ 2026-05-18 |
| SELF-01 | Phase 15 | Complete ✓ 2026-05-18 |
| SELF-02 | Phase 15 | Complete ✓ 2026-05-18 |
| SELF-03 | Phase 15 | Complete ✓ 2026-05-18 |
| SELF-04 | Phase 15 | Complete ✓ 2026-05-18 |
| SELF-05 | Phase 15 | Complete ✓ 2026-05-18 |
| MODEL-01 | Phase 16 | Complete ✓ 2026-05-18 |
| MODEL-02 | Phase 16 | Complete ✓ 2026-05-18 |
| MODEL-03 | Phase 16 | Complete ✓ 2026-05-18 |
| MODEL-04 | Phase 16 | Complete ✓ 2026-05-18 |
| MODEL-05 | Phase 16 | Complete ✓ 2026-05-18 |
| MODEL-06 | Phase 16 | Complete ✓ 2026-05-18 |
| JOUR-01 | Phase 17 | Complete ✓ 2026-05-19 |
| JOUR-02 | Phase 17 | Complete ✓ 2026-05-19 |
| JOUR-03 | Phase 17 | Complete ✓ 2026-05-19 |
| JOUR-04 | Phase 17 | Complete ✓ 2026-05-19 |
| JOUR-05 | Phase 17 | Complete ✓ 2026-05-19 |
| JOUR-06 | Phase 17 | Complete ✓ 2026-05-19 |
| AUTO-01 | Phase 18 | Pending |
| AUTO-02 | Phase 18 | Pending |
| AUTO-03 | Phase 18 | Complete ✓ 2026-05-22 (Plan 18-01: store-layer) |
| AUTO-04 | Phase 18 | Complete ✓ 2026-05-22 (Plan 18-01) |
| AUTO-05 | Phase 18 | Complete ✓ 2026-05-22 (Plan 18-02) |
| AUTO-06 | Phase 18 | Pending |
| AUTO-07 | Phase 18 | Complete ✓ 2026-05-22 (Plan 18-03) |
| AUTO-08 | Phase 18 | Pending |
| AUTO-09 | Phase 18 | Pending |
| INFRA-01 | Phase 18 | Pending |
| INFRA-02 | Phase 14 | Complete ✓ 2026-05-18 |

**Coverage:**
- v2.0 requirements: 41 total
- Mapped to phases: 41
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-18*
*Last updated: 2026-05-19 — Phase 17 complete; backfilled Phase 14 & 16 completion markers*
