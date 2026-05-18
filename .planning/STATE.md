# State — Klaus

## Current Position

Phase: 14 — Foundation: Cost Metering, Tick-Brain & LLM Strategy
Plan: Not yet created (run `/gsd-plan-phase 14`)
Status: Milestone initialized, ready to plan Phase 14
Last activity: 2026-05-18 — Milestone v2.0 Consciousness & Autonomy started

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-05-18)

**Core value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Current focus:** Phase 14 — Cost metering foundation + tick-brain

## Accumulated Context

### Architecture decisions carried forward

- Brain: `gemini-3-flash-preview` (NOT Claude — stale comments being fixed in Phase 14)
- Worker: `gemini-2.5-flash`
- Fallback: `claude-haiku-4-5` (inline try/except in `core/main.py:260–291`)
- `_OpenAIBackend` already wired in `llm_client.py` — Groq needs only a `base_url` param
- Embeddings: `gemini-embedding-2` via AI Studio (NOT Vertex)
- All GCP/Pinecone names lowercase "Klaus" (`0x6B`) — uppercase K causes silent 404s

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
- `core/tools.py:39` — `SMART_AGENT_DIRECT_TOOLS` frozenset (currently 4 members)
- `core/tools.py:45–596` — `TOOL_SCHEMAS`
- `core/tools.py:600–603` — `WORKER_TOOL_SCHEMAS`
- `core/tools.py:633` — lazy-singleton tool pattern
- `core/tools.py:995–1020` — `_HANDLERS` dict
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
