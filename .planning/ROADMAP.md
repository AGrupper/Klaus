# Roadmap: Klaus v2.0 — Consciousness & Autonomy

**Milestone:** v2.0
**Phases:** 14–18
**Requirements:** 41 total | All mapped ✓
**Started:** 2026-05-18

---

## Overview

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|-----------------|
| 14 | Foundation: Cost Metering + Tick-Brain + LLM Strategy | Every LLM call is measured; free tick-brain exists and upgrades heartbeat; model map documented | COST-01–05, TICK-01–05, LLM-01–04, INFRA-02 | 5 |
| 15 | Codebase Self-Knowledge | Klaus can read and search his own deployed source | SELF-01–05 | 3 |
| 16 | Self-Model & State Awareness | Doubt-free manifest + persistent self-state + get_self_status tool | MODEL-01–06 | 4 |
| 17 | Reflection & Journal | Daily reflection cron → journal → self-state evolution loop | JOUR-01–06 | 4 |
| 18 | The Autonomous Engine | Judgment-driven proactive outreach + repeat-suppression + eval harness | AUTO-01–09, INFRA-01 | 5 |

---

## Phase 14 — Foundation: Cost Metering, Tick-Brain & LLM Strategy ✓ Complete 2026-05-18

**Goal:** Every LLM call is measured; the free tick-brain component exists and already upgrades the heartbeat; the model map is documented and stale naming fixed. Caps nothing.

**Requirements:** COST-01, COST-02, COST-03, COST-04, COST-05, TICK-01, TICK-02, TICK-03, TICK-04, TICK-05, LLM-01, LLM-02, LLM-03, LLM-04, INFRA-02

**Key files:**
- `core/pricing.py` (NEW) — `MODEL_PRICING` dict + `compute_cost(model, in_tokens, out_tokens)`
- `core/tick_brain.py` (NEW) — Groq/Qwen3-32B wrapper with Gemini fallback
- `core/llm_client.py` — surface token usage in all 3 backends; add `purpose` param; `base_url` param for OpenAI backend; normalize `max_tokens` across backends
- `memory/firestore_db.py` — new `LLMUsageStore` class (record + summary)
- `core/heartbeat.py` — tick-brain reasoning pass over health signals
- `core/main.py` — fix stale "Claude"/"JARVIS-style" comments
- `.env.example` — add `TICK_BRAIN_*` entries
- `docs/TECHNICAL_PLAN.md` — document LLM-per-purpose map

**Success criteria:**
1. `compute_cost("qwen3-32b", 1000, 500)` returns `0.0`; `compute_cost("gemini-3-flash-preview", 1000, 500)` returns a non-zero float
2. Sending a Telegram message → `llm_usage/{today}` Firestore doc incremented with model, purpose, cost
3. `python -m core.heartbeat --dry-run` shows tick-brain reasoning pass in output
4. Tick-brain falls back cleanly to Gemini when a fake invalid Groq key is set
5. `core/main.py` contains no "JARVIS" or stale "Claude" references in agent-description comments

---

## Phase 15 — Codebase Self-Knowledge ✓ Complete 2026-05-18

**Goal:** Klaus can read and search his own source at conversation time — genuine, always-current codebase self-knowledge.

**Requirements:** SELF-01, SELF-02, SELF-03, SELF-04, SELF-05

**Plans:** 2/2 complete

Plans:
- [x] 15-01-PLAN.md — Create mcp_tools/self_inspect.py with list_own_files, read_own_source, search_own_source
- [x] 15-02-PLAN.md — Register 3 tools in core/tools.py (all 5 sites) + update prompts/smart_agent.md

**Key files:**
- `mcp_tools/self_inspect.py` (NEW) — `list_own_files`, `read_own_source`, `search_own_source`
- `core/tools.py` — register 3 tools at all 5 edit sites (TOOL_SCHEMAS, _HANDLERS, handler functions, SMART_AGENT_DIRECT_TOOLS, WORKER exclusion)
- `prompts/smart_agent.md` — inform Klaus he can inspect his own source

**Success criteria:**
1. Klaus asked "how do you work?" calls `read_own_source` on relevant files
2. `read_own_source('.env')` is denied (returns error, not contents)
3. `search_own_source("LLMUsageStore")` returns correct file locations

---

## Phase 16 — Self-Model & State Awareness

**Goal:** A detailed, doubt-free manifest of everything Klaus is and can do, injected into every conversation — plus a persistent self-state that survives the 6h conversation reset.

**Requirements:** MODEL-01, MODEL-02, MODEL-03, MODEL-04, MODEL-05, MODEL-06

**Plans:** 4 plans

Plans:
- [x] 16-01-PLAN.md — core/self_manifest.py (generate_manifest + _compute_schema_hash) + docs/SELF.md generation + memory/firestore_db.py SelfStateStore
- [x] 16-02-PLAN.md — core/main.py SELF.md + self_state prompt injection + prompts/smart_agent.md placeholders
- [x] 16-03-PLAN.md — core/tools.py get_self_status direct tool (all 5 registration sites)
- [x] 16-04-PLAN.md — core/heartbeat.py SELF.md SHA staleness check + .github/workflows/deploy.yml CI generation step

**Key files:**
- `core/self_manifest.py` (NEW) — `generate_manifest()` introspects tools + cron routes + channels + models → renders `docs/SELF.md` with git SHA
- `docs/SELF.md` (GENERATED) — exhaustive capability manifest
- `memory/firestore_db.py` — new `SelfStateStore` class (singleton `config/self_state` doc)
- `core/main.py` — inject SELF.md digest + self_state at per-message render step (`:219–222`), stable-first ordering
- `core/tools.py` — new `get_self_status` direct tool
- `core/heartbeat.py` — extend `check_code()` to flag stale SELF.md (weekly FYI)

**Success criteria:**
1. `docs/SELF.md` lists all 9 cron jobs, all tools, all honest limits (Telegram-only, no email send)
2. Klaus asked "what exactly can you do?" gives exhaustive answer including limits without hallucinating
3. `get_self_status` returns today's cost + uptime (journal field blank pre-Phase 17)
4. `docs/SELF.md` SHA/hash check in heartbeat weekly run flags when the file is stale

---

## Phase 17 — Reflection & Journal

**Goal:** Klaus reviews each day and keeps a journal — the loop that makes the self-model persistent and evolving rather than static.

**Requirements:** JOUR-01, JOUR-02, JOUR-03, JOUR-04, JOUR-05, JOUR-06

**Key files:**
- `core/reflection.py` (NEW) — `run_reflection()`: gather day → one main-brain call → journal entry + self_state update
- `prompts/reflection.md` (NEW) — reflection system prompt
- `memory/firestore_db.py` — new `JournalStore` class (`journal/{date}` docs)
- `memory/pinecone_db.py` — add `"self"` to `_VALID_KINDS`
- `interfaces/web_server.py` — new `/cron/reflect` route with OIDC auth
- `core/main.py` — inject last ~3 journal entries digest at per-message render step

**Success criteria:**
1. `POST /cron/reflect` with `CRON_DEV_BYPASS=true` → `journal/{today}` doc created in Firestore
2. Updated `self_state` fields (`current_focus`, `recent_context`, `mood`) visible in Firestore
3. `kind="self"` Pinecone upsert succeeds (no ValueError)
4. Next conversation after reflection shows journal digest in assembled prompt

---

## Phase 18 — The Autonomous Engine (Capstone)

**Goal:** Klaus decides on his own judgment when to reach out — the headline feature — and the judgment is measured.

**Requirements:** AUTO-01, AUTO-02, AUTO-03, AUTO-04, AUTO-05, AUTO-06, AUTO-07, AUTO-08, AUTO-09, INFRA-01

**Key files:**
- `core/autonomous.py` (NEW) — `run_autonomous_tick()` with 3-layer design
- `prompts/autonomous_triage.md` (NEW) — tick-brain triage prompt
- `prompts/autonomous.md` (NEW) — main-brain composition prompt
- `memory/firestore_db.py` — new `FollowupStore` class + outreach log
- `core/tools.py` — new `schedule_followup` direct tool (all 5 edit sites)
- `interfaces/web_server.py` — new `/cron/autonomous-tick` route
- `evals/tick_brain/` (NEW) — 20–30 labeled `SituationSnapshot` fixtures
- `scripts/eval_tick_brain.py` (NEW) — eval runner scoring precision/recall
- `docs/DEPLOYMENT.md` (NEW or UPDATE) — all 9 Cloud Scheduler jobs documented

**Success criteria:**
1. Plant an overdue TickTick task, trigger `/cron/autonomous-tick` → Klaus sends a Telegram message
2. Trigger again immediately → Klaus stays silent (repeat-suppression via outreach log)
3. Trigger on a quiet situation (empty calendar, no overdue tasks, recent contact) → silent + near-zero cost
4. `schedule_followup` in chat + tick after due time → follow-up fires
5. `python scripts/eval_tick_brain.py` runs, scores model against all fixtures, prints precision/recall report

---

## Dependency Order

```
14 Foundation  ←  everything depends on this (cost metering, tick-brain, base_url param)
     │
15 Self-Knowledge  ←  needs tick-brain (Phase 14) for heartbeat upgrade context
     │
16 Self-Model  ←  needs cost data (Phase 14: LLMUsageStore) for get_self_status
     │
17 Journal  ←  needs SelfStateStore (Phase 16) for self_state updates; needs kind="self" (new)
     │
18 Autonomous Engine  ←  needs tick-brain (14), self-inspect (15), journal (17), FollowupStore
```

Each phase is independently shippable and should be committed atomically.

---
*Roadmap created: 2026-05-18*
*Last updated: 2026-05-19 — Phase 16 complete (4/4 plans, MODEL-01–06 verified, human UAT passed)*
