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

**Key files:**
- `core/self_inspect.py` (NEW) — `list_files`, `read_source`, `search_source`
- `core/tools.py` — 3 new direct-call tools: `list_own_files`, `read_own_source`, `search_own_source` (all 5 edit sites)
- `prompts/smart_agent.md` — `SELF-INSPECTION` section

**Success criteria:**
1. Chat: "what files do you have under core/" → Klaus lists them and answers
2. Chat: "show me how delegate_to_worker works" → Klaus reads + paraphrases the actual code
3. Search: "where do we check is_user_authorized?" → grep hits returned with line numbers

---

## Phase 16 — Self-Model & State Awareness ✓ Complete 2026-05-18

**Goal:** Klaus carries a stable self-model (SELF.md) plus mutable self-state (Firestore), and can introspect both via `get_self_status`.

**Requirements:** MODEL-01, MODEL-02, MODEL-03, MODEL-04, MODEL-05, MODEL-06

**Key files:**
- `docs/SELF.md` (NEW) — canonical doubt-free identity manifest
- `memory/firestore_db.py` — new `SelfStateStore` class
- `core/tools.py` — `get_self_status` direct tool (all 5 edit sites)
- `core/main.py` — load `SELF.md` once at startup; inject into smart_system; bootstrap self_state
- `prompts/smart_agent.md` — `{self_md}` + `{self_state}` placeholders
- `docs/TECHNICAL_PLAN.md` — sub-section "Self-Knowledge & Self-State" + LLM-per-purpose map note

**Success criteria:**
1. Chat: "what model are you?" → Klaus answers crisp, no hedging
2. Chat: "what's on your mind today?" → uses `current_focus` from self_state
3. `get_self_status` tool returns the current self_state snapshot
4. self_state bootstrap happens on first startup (config/self_state doc exists with identity_summary)

---

## Phase 17 — Reflection & Journal ✓ Complete 2026-05-19

**Goal:** Daily reflection cron at 22:00 produces a journal entry, evolves self_state, and persists into Pinecone (with new `kind="self"`).

**Requirements:** JOUR-01, JOUR-02, JOUR-03, JOUR-04, JOUR-05, JOUR-06

**Key files:**
- `core/reflection.py` (NEW) — `run_reflection()` orchestrator
- `memory/firestore_db.py` — `JournalStore` class
- `memory/pinecone_db.py` — extend `upsert_episodic` with `kind` param
- `interfaces/web_server.py` — `/cron/reflect` route
- `prompts/reflection.md` (NEW) — first-person reflection prompt
- `core/main.py` — `{journal_digest}` smart-only placeholder

**Success criteria:**
1. `POST /cron/reflect` with `CRON_DEV_BYPASS=true` → `journal/{today}` doc created in Firestore
2. Updated `self_state` fields (`current_focus`, `recent_context`, `mood`) visible in Firestore
3. `kind="self"` Pinecone upsert succeeds (no ValueError)
4. Next conversation after reflection shows journal digest in assembled prompt

---

## Phase 18 — The Autonomous Engine (Capstone)

**Goal:** Klaus decides on his own judgment when to reach out — the headline feature — and the judgment is measured.

**Requirements:** AUTO-01, AUTO-02, AUTO-03, AUTO-04, AUTO-05, AUTO-06, AUTO-07, AUTO-08, AUTO-09, INFRA-01

**Plans:** 9 plans

Plans:
- [x] 18-01-followup-outreach-stores-PLAN.md — FollowupStore + OutreachLogStore + TickLogStore + python-dateutil (AUTO-03, AUTO-04) ✓ 2026-05-22
- [x] 18-02-followup-tools-PLAN.md — 3 follow-up tools at 15 registration sites + smart_agent.md (AUTO-05) ✓ 2026-05-22
- [x] 18-03-autonomous-prompts-PLAN.md — prompts/autonomous_triage.md + prompts/autonomous.md (AUTO-07) ✓ 2026-05-22
- [x] 18-04-eval-seed-fixtures-PLAN.md — 5 seed fixtures + evals/tick_brain/README.md (AUTO-08) ✓ 2026-05-22
- [x] 18-05-tick-brain-extension-PLAN.md — TickBrain.think system_override + _parse_response topic_key (AUTO-01, AUTO-07) ✓ 2026-05-22
- [x] 18-06-autonomous-orchestrator-PLAN.md — core/autonomous.py 3-layer pipeline + pitfall tests (AUTO-01, AUTO-02, AUTO-03) ✓ 2026-05-23
- [x] 18-07-cron-route-and-heartbeat-PLAN.md — /cron/autonomous-tick + heartbeat staleness entry (AUTO-06) ✓ 2026-05-23
- [x] 18-08-eval-runner-PLAN.md — scripts/eval_tick_brain.py precision/recall scorer (AUTO-09) ✓ 2026-05-23
- [ ] 18-09-deployment-docs-PLAN.md — docs/DEPLOYMENT.md 9-cron table + Groq secret + Five Fingers quirk + Firestore index (INFRA-01)

**Waves:** W1 = {18-01, 18-02 (depends on 01), 18-03, 18-04}; W2 = {18-05, 18-06 (depends on 01,02,03,05), 18-07 (depends on 06)}; W3 = {18-08 (depends on 03,04,05,06), 18-09 (depends on 07)}

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
