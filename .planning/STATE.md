---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: milestone
status: executing
last_updated: "2026-05-20T11:55:00.000Z"
last_activity: 2026-05-20 -- Phase 18 planned — 9 plans, 3 waves, all 10 requirements covered
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 24
  completed_plans: 15
  percent: 62
---

# State — Klaus

## Current Position

Phase: 18 — The Autonomous Engine (Capstone)
Plans: 9 (Wave 1: 01,02,03,04 · Wave 2: 05,06,07 · Wave 3: 08,09)
Status: Ready to execute (`/gsd-execute-phase 18`)
Resume file: `.planning/phases/18-autonomous-engine/18-01-followup-outreach-stores-PLAN.md`
Last activity: 2026-05-20 -- Phase 18 planned (research + validation + patterns + 9 plans, 2 checker iterations, 0 BLOCKER 0 WARNING remaining)

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-05-19)

**Core value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Current focus:** Phase 18 — The Autonomous Engine (judgment-driven proactive outreach + repeat-suppression + eval harness)

## Accumulated Context

### Architecture decisions carried forward

- Brain: `gemini-3-flash-preview` — stale Claude/JARVIS comments fixed in Phase 14
- Worker: `gemini-2.5-flash`
- Fallback: `claude-haiku-4-5` (inline try/except in `core/main.py:260–291`)
- Tick-brain: `qwen3-32b` via Groq (OpenAI-compat) — `core/tick_brain.py`, Gemini fallback
- `_OpenAIBackend` accepts `base_url` param (Phase 14) — no longer reads `OPENAI_BASE_URL` from env
- Embeddings: `gemini-embedding-2` via AI Studio (NOT Vertex)
- All GCP/Pinecone names lowercase "Klaus" (`0x6B`) — uppercase K causes silent 404s
- LLM costs metered via `LLMUsageStore` → Firestore `llm_usage/{date}` after every `LLMClient.chat()` call
- `compute_cost()` in `core/pricing.py` — 4 priced models; free/unknown return 0.0

### Key line references (verified against live codebase — may drift)

- `llm_client.py:34` — `MAX_TOKENS = 4096`
- `llm_client.py:78` — `LLMClient.chat()` (public method, NOT `create()`)
- `llm_client.py:122` — `_AnthropicBackend.chat()`
- `llm_client.py:189` — `_GeminiBackend.chat()`
- `llm_client.py:352` — `_OpenAIBackend` class
- `llm_client.py:363` — `os.getenv("OPENAI_BASE_URL")` (global, to be parameterized)
- `llm_client.py:366` — `_OpenAIBackend.chat()`
- `core/main.py:43` — `MAX_TOOL_ITERATIONS = 8`
- `core/main.py:219–222` — per-message prompt render step
- `core/main.py:241` — `AgentOrchestrator._run_smart_loop`
- `core/main.py:260–291` — inline Gemini→Haiku fallback (reference shape for tick-brain chain)
- `core/tools.py:39` — `SMART_AGENT_DIRECT_TOOLS` frozenset (now 7 members — includes self-inspect)
- `core/tools.py:45–596+` — `TOOL_SCHEMAS` (3 new self-inspect schemas appended)
- `core/tools.py:600–603` — `WORKER_TOOL_SCHEMAS` (excludes all 7 direct tools)
- `core/tools.py:633` — lazy-singleton tool pattern
- `core/tools.py:995–1020+` — `_HANDLERS` dict (3 new self-inspect lambdas)
- `mcp_tools/self_inspect.py` — `list_own_files`, `read_own_source`, `search_own_source` (Phase 15)
- `tests/test_self_inspect.py` — 35 tests, all green
- `core/heartbeat.py:378` — `check_code()`
- `core/heartbeat.py:500` — `_compose_message()`
- `interfaces/web_server.py:227` — `_verify_cron_request` (OIDC auth)
- `interfaces/web_server.py:273` — `_log_cron_run`
- `memory/pinecone_db.py:29` — `_VALID_KINDS = {"fact","chunk","chat"}`
- `memory/pinecone_db.py:112` — `recall()` defaults to `kinds=["fact","chunk"]`
- `core/scheduled_message.py:22` — `send_and_inject`
- `core/proactive_alerts.py:98–100` — `_already_sent` dedup gate

### Existing cron jobs (7 total before this milestone)

1. Heartbeat — hourly (`0 * * * *`)
2. Proactive alerts — `30 21 * * *` Asia/Jerusalem
3. Morning briefing tick — `*/10 6-10 * * *` Asia/Jerusalem
4. Five Fingers morning (Wed/Sun 10:30)
5. Five Fingers evening (Wed/Sun 21:15)
6. Chat ingest — `0 4 * * *` Asia/Jerusalem
7. Chat export ingest — `30 4 * * *` Asia/Jerusalem

Note: Five Fingers morning + evening log the same `_log_cron_run` job-id `five-fingers` — known quirk, document in DEPLOYMENT.md in Phase 18.

### Blockers

None.

### Notes

- `load_dotenv` must always use `override=True` — default silently ignores .env when shell already exports the var
- All GCP/Pinecone resource names are lowercase "Klaus" — uppercase causes silent 404s
