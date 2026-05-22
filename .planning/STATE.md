---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: milestone
status: executing
last_updated: "2026-05-22T20:51:57.000Z"
last_activity: 2026-05-22 -- Phase 18 Plan 05 executed — core/tick_brain.py extended with TickBrain.think(system_override) + _parse_response topic_key passthrough; layered purpose strings (tick / tick_fallback / tick_autonomous / tick_autonomous_fallback) preserve INFRA-02 visibility; 10 new tests in TestSystemOverrideAndTopicKey incl. WARNING 1 regression guard; 27/27 green tick-brain + 69/69 green adjacent suites; heartbeat caller unchanged
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 24
  completed_plans: 20
  percent: 83
---

# State — Klaus

## Current Position

Phase: 18 — The Autonomous Engine (Capstone)
Plans: 9 (Wave 1: 01 ✓, 02 ✓, 03 ✓, 04 ✓ · Wave 2: 05 ✓, 06, 07 · Wave 3: 08, 09)
Status: Wave 2 in progress (05 done); next up Plan 06 (autonomous-orchestrator)
Resume file: `.planning/phases/18-autonomous-engine/18-06-autonomous-orchestrator-PLAN.md`
Last activity: 2026-05-22 -- Plan 18-05 executed (2 commits: 8289310 RED — TestSystemOverrideAndTopicKey 10 new tests, ddf9a50 GREEN — TickBrain.think system_override kwarg + layered purpose strings + _parse_response topic_key passthrough; 27/27 tick-brain green; heartbeat caller untouched; AUTO-01 groundwork laid for Plan 06, AUTO-07 parser side complete)

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
- Phase 18: `SMART_AGENT_DIRECT_TOOLS` additions follow insertion order (not alphabetical) — preserves git blame; matches Phase 15/16 convention
- Phase 18: `_handle_schedule_followup` catches `ImportError` alongside `ValueError`/`TypeError`/`OverflowError` so stale Cloud Run images without `python-dateutil` return structured `could_not_parse_when` errors instead of 500
- Phase 18-04: eval fixture contract is locked by `tests/test_evals.py::TestFixtureSchema` — Plan 06's `gather_situation()` must produce a dict with keys `{calendar, ticktick_overdue, unread_email_count, due_followups, hours_since_contact, recent_journal_digest, self_state, today_outreach_log, now_context}` or the fixtures (and the eval harness in Plan 08) drift from production
- Phase 18-04: WARNING 8 regression guard — fixture 0003-due-followup.json `ground_truth.should_speak` must stay `false` (D-13: followup path bypasses tick-brain); guarded by `test_followup_only_fixture_expects_silence`
- Phase 18-05: `TickBrain.think()` now accepts `system_override: str | None = None` (default preserves heartbeat behavior). Layered purpose strings emit 4 buckets to LLMUsageStore: `tick` / `tick_fallback` (heartbeat) and `tick_autonomous` / `tick_autonomous_fallback` (Plan 06 path). The literal `"tick_fallback"` no longer appears in `core/tick_brain.py` — replaced by `fallback_purpose = primary_purpose + "_fallback"` (WARNING 1 fix). `_parse_response` passes through `topic_key` when present + truthy; missing/empty → omitted; non-string coerced via `str()`; safe-mode return unchanged. Heartbeat caller at `core/heartbeat.py:720` is untouched. Test guard: `test_fallback_purpose_preserves_tick_fallback_when_no_override` asserts INFRA-02 visibility is not regressed.

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
- `core/tools.py:39-52` — `SMART_AGENT_DIRECT_TOOLS` frozenset (now 11 members — 8 prior + 3 Phase 18 follow-up tools at lines 49-51)
- `core/tools.py:54–740+` — `TOOL_SCHEMAS` (3 new follow-up schemas at lines 678-715)
- `core/tools.py:758-770` — `WORKER_TOOL_SCHEMAS` exclusion (excludes all 11 direct tools incl. 3 follow-up tools)
- `core/tools.py:1252-1331` — Phase 18 `_handle_schedule_followup` / `_handle_list_followups` / `_handle_cancel_followup` (ImportError caught at line 1281)
- `core/tools.py:1340–1370+` — `_HANDLERS` dict (3 new follow-up lambdas at lines 1358-1360)
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
