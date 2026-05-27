---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: — Project Shifu
status: executing
last_updated: "2026-05-27T09:05:11.283Z"
last_activity: 2026-05-27 -- Phase 19 planning complete
progress:
  total_phases: 2
  completed_phases: 0
  total_plans: 5
  completed_plans: 0
  percent: 0
---

# State — Klaus

## Current Position

Milestone: v3.0 — Project Shifu (Training, Recovery & Nutrition Coach)
Phases planned: 2 (Phase 19 + Phase 20)
Phase: 19 — not started
Plan: —
Status: Ready to execute
Resume file: — (no active plan)
Last activity: 2026-05-27 -- Phase 19 planning complete

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-05-25)

**Core value:** Klaus should surface the right thing at the right time — while knowing exactly what he is and what he can do.
**Current focus:** Phase 19 — Training Awareness & Multimodal Audit (Postgres schema + Garmin ingestion + UserProfileStore + ACWR + meal-photo critique)

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
- Phase 18-08: `scripts/eval_tick_brain.py` (366 lines) is the day-one judgment-quality measurement tool — globs `evals/tick_brain/fixtures/*.json` (5 seeds; growth to 20–30 per AUTO-08), reuses `core.autonomous._build_triage_prompt` so eval prompt is byte-for-byte identical to prod (BLOCKER 4 dep on Plan 06), calls `TickBrain.think(prompt, system_override=<autonomous_triage.md>)`, prints overall Precision/Recall/F1 + per-trigger-type table (overdue/gap/silence/followup/quiet). **Pitfall 8 protection:** `_SAFE_MODE_REASONS = {"parse_failure", "llm_error"}` — VERIFIED literal set from `core/tick_brain.py:154,165,168,189`; safe-mode returns land in the 'errored' bucket and are excluded from TP/FP/TN/FN aggregation so LLM brittleness can't inflate apparent precision/recall. **Exit code 0 always** (D-22: measurement tool, not CI gate). Missing API key → ValueError → caught → tb=None → all-errored report → exit 0. Missing fixtures dir → `0 fixtures loaded` → exit 0. sys.path bootstrap inside the script (`_REPO_ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(_REPO_ROOT))`) so `python scripts/eval_tick_brain.py` works without PYTHONPATH, matching the docstring usage. `--fixtures` default `evals/tick_brain/fixtures`; `--model` exports into `TICK_BRAIN_MODEL` env before TickBrain() construction. `tests/test_eval_script.py::TestEvalScript` has 4 subprocess tests: `_run()` helper strips API keys before invocation so tests validate output structure (Precision:/Recall:/F1:/Errored: + 5 trigger rows) without network or fixture-accuracy dependence.
- Phase 18-07: `interfaces/web_server.py` now exposes **POST /cron/autonomous-tick** at line 363 — OIDC-protected via `_verify_cron_request`, guards on `_application is None → 500`, awaits `core.autonomous.run_autonomous_tick(_application.bot, now)`, calls `_log_cron_run('autonomous-tick', ok=True/False)` on both success and exception paths (failure path re-raises so Cloud Run sees the 500 + consecutive_failures streak ticks up). `core/heartbeat.py:114` registers `'autonomous-tick': 1` in `_CRON_MAX_STALENESS_HOURS` — 1h tolerance = 3 missed 20-min ticks (RESEARCH Pitfall 5). Comment on the preceding `'reflect'` line retitled from `NEW` to `Phase 17` for chronological parity. Imports inside the handler body (not at module top) to keep `/health` cold-start fast — mirrors every other cron handler. Test scaffold `tests/test_web_server.py` created with 5 tests in `TestCronAutonomousTick`; `tests/test_heartbeat.py` extended with `test_autonomous_tick_staleness_threshold_is_one_hour` + `test_all_cron_jobs_have_staleness_entry`. Cloud Scheduler job creation (gcloud snippet) deferred to Plan 18-09's DEPLOYMENT.md.

- Phase 18-09: `docs/DEPLOYMENT.md` extended +162 lines (1052 → 1214) with 6 operator-facing additions — **§19 Cloud Scheduler Full Job Inventory** (single master table with all 9 klaus-* job-ids: five-fingers-morning, five-fingers-evening, morning-briefing, proactive-alerts, heartbeat, ingest-chats, ingest-chat-exports, reflect, autonomous-tick — columns: `# | Job ID | Schedule | Endpoint | Phase`); **§14d klaus-reflect gcloud block** (Phase 17 retroactive: `0 22 * * *`, `/cron/reflect`); **§14e klaus-autonomous-tick gcloud block** (Phase 18 NEW: `*/20 7-21 * * *` Asia/Jerusalem, `/cron/autonomous-tick`, pre-flight collision check); **§20 TICK_BRAIN_API_KEY (Groq) Secret** (secret name `klaus-tick-brain-api-key`, `--set-secrets` Cloud Run binding, 4-step rotation: console.groq.com/keys → `gcloud secrets versions add` → redeploy → `gcloud secrets versions disable`); **§21 Known Quirks: Five Fingers job-id collision** with 4-step legacy-job migration paragraph for pre-2026-05 deploys (`gcloud scheduler jobs list --filter="name~five-fingers"` → create new canonical jobs first → `gcloud scheduler jobs delete five-fingers` → verify via Firestore `cron_runs`) — bonus WARNING fix regression-guarded by `test_five_fingers_migration_paragraph_present`; **§22 Firestore Composite Indexes** (single-row table: `followups: status ASC, due_at ASC` — required by `FollowupStore.list_due()`; both `gcloud firestore indexes composite create` and FAILED_PRECONDITION click-link paths documented). `tests/test_docs.py` NEW (89 lines, 8 grep-style completeness assertions in `TestDeploymentCompleteness`, all passing). **Rule 1 deviation:** plan template specified `/cron/morning-briefing` for the inventory table; actual route is `@app.post("/cron/morning-briefing-tick")` at `interfaces/web_server.py:427` — fixed in inventory table to prevent doc-vs-code drift. INFRA-01 satisfied → **Phase 18 complete 9/9 plans → milestone v2.0 complete 5/5 phases**.

- Phase 18-06: `core/autonomous.py` (825 lines) holds the full 3-layer pipeline. **Module-level `_orchestrator_singleton`** via `_get_orchestrator()` (BLOCKER 5a) — `AgentOrchestrator.__init__` runs once per Cloud Run instance, saving ~42 reads of SELF.md + ~42 SelfStateStore bootstraps + ~42 LLMClient triples per day. **AgentOrchestrator.render_smart_system(template)** (Task 0 / core/main.py:221-272) was extracted from `handle_message` so `_compose_layer2` can pre-render `{self_md}/{self_state}/{journal_digest}/{today_date}` BEFORE `_run_smart_loop` (BLOCKER 5b — placeholder injection lives in `handle_message`, NOT `_run_smart_loop`). **Sentinel-return detection** via `_SMART_LOOP_ERROR_SENTINELS = ("I'm afraid I encountered a connectivity",)` (BLOCKER 3) — `_run_smart_loop` RETURNS the connectivity-error string rather than raising, so Layer-2 callers MUST substring-match. **Narrow calendar gap/overload detection** via `_calendar_has_gap_or_overload` (BLOCKER 2) — single non-conflicting event is NOT a signal; only overlapping events OR >2 events in next 2h trigger. **Pitfall 2 guard:** autonomous tick builds synthetic `[{role:user, content}]` freshly and NEVER routes through `handle_message` or appends to `conversation_manager` (only `send_and_inject(inject=True)` writes the assistant turn). **D-10 success-only outreach log:** `OutreachLogStore.append` called ONLY after `send_and_inject` succeeds. **D-13 dedicated follow-up path** (`_compose_followup`) skips tick-brain entirely. **D-14 force-fire** at `defer_count >= 3` overrides LLM "defer" action. **NOTE 2:** defer pushes `original_due + 1h`, not `now + 1h`. **WARNING 4:** `hours_since_contact = None` renders as the literal string `"unknown"` in the triage prompt, never `999.0`. **WARNING 5:** malformed JSON `{...}` block body stripped from polished follow-up text (`_parse_followup_action`). New `FirestoreConversationStore.get_last_user_timestamp(user_id)` returns the doc-level `updated_at` only when a user-role message exists in the messages array (per-message timestamps don't exist in the schema). Test guard: 31 tests in `tests/test_autonomous.py` including explicit named regression coverage for all 5 BLOCKERs and 4 Pitfalls.

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
- `interfaces/web_server.py:363` — Phase 18 `@app.post("/cron/autonomous-tick")` route (AUTO-06)
- `core/heartbeat.py:114` — `_CRON_MAX_STALENESS_HOURS['autonomous-tick'] = 1` (Phase 18)
- `memory/pinecone_db.py:29` — `_VALID_KINDS = {"fact","chunk","chat"}`
- `memory/pinecone_db.py:112` — `recall()` defaults to `kinds=["fact","chunk"]`
- `core/scheduled_message.py:22` — `send_and_inject`
- `core/proactive_alerts.py:98–100` — `_already_sent` dedup gate

### Existing cron jobs (7 deployed; 2 more wired in code awaiting Phase 18-09 deploy)

1. Heartbeat — hourly (`0 * * * *`)
2. Proactive alerts — `30 21 * * *` Asia/Jerusalem
3. Morning briefing tick — `*/10 6-10 * * *` Asia/Jerusalem
4. Five Fingers morning (Wed/Sun 10:30)
5. Five Fingers evening (Wed/Sun 21:15)
6. Chat ingest — `0 4 * * *` Asia/Jerusalem
7. Chat export ingest — `30 4 * * *` Asia/Jerusalem

Documented in docs/DEPLOYMENT.md §14d / §14e (Plan 18-09 complete), Cloud Scheduler job creation pending operator run of the gcloud blocks:

8. Reflect (Phase 17) — `0 22 * * *` Asia/Jerusalem — gcloud block: DEPLOYMENT.md §14d
9. Autonomous tick (Phase 18-07) — `*/20 7-21 * * *` Asia/Jerusalem (43 ticks/day) — gcloud block: DEPLOYMENT.md §14e

Note: Five Fingers morning + evening log the same `_log_cron_run` job-id `five-fingers` — known quirk, **documented Plan 18-09** in DEPLOYMENT.md §21 with a legacy-job migration paragraph for pre-2026-05 deploys.

### Blockers

None.

### Notes

- `load_dotenv` must always use `override=True` — default silently ignores .env when shell already exports the var
- All GCP/Pinecone resource names are lowercase "Klaus" — uppercase causes silent 404s

## Deferred Items

Items acknowledged and deferred at milestone v2.0 close on 2026-05-23. None
are code defects; all are either live-staging blockers (need real services to
verify) or local dev-venv hygiene (CI/Cloud Run env is unaffected). Logged
here per the gsd-complete-milestone audit protocol.

| Category | Item | Status | Resolves when |
|----------|------|--------|---------------|
| uat-gap | 16-HUMAN-UAT.md — 3 pending scenarios (SELF.md cold-start, self_state bootstrap, get_self_status live) | resolved (acknowledged at close) | operator runs SELF.md cold-start test against staging Cloud Run + Telegram |
| verification-gap | 16-VERIFICATION.md status `human_needed` | resolved (acknowledged at close) | operator queries `config/self_state` in live Firestore after first deploy |
| verification-gap | 18-VERIFICATION.md status `human_needed` (SC-1, SC-2, SC-4, SC-5) | resolved (acknowledged at close) | operator triggers `klaus-autonomous-tick` in staging with `TICK_BRAIN_API_KEY` set; verifies Telegram receives the message (SC-1), same-day repeat is suppressed (SC-2), `schedule_followup` fires on time (SC-4), eval runner outputs real precision/recall/F1 (SC-5). SC-3 (quiet-tick cost ≈ $0) already verified locally. |
| env-hygiene | Local pytest fails on `googleapiclient` (test_tools.py), `fastapi` (test_web_server.py), `google.genai` (test_llm_client.py, test_pinecone_embed.py) | open (low priority) | `uv add googleapiclient fastapi google-genai` to dev requirements |
| code-quality | 18-REVIEW.md M-2, M-3, M-4 + L-1..L-5 (8 findings) | open (Phase 19 candidate) | next housekeeping sweep — see `.planning/phases/18-autonomous-engine/deferred-items.md` § "Post-review backlog" |
| docs-drift | `docs/TECHNICAL_PLAN.md` stops at the pre-v2.0 "Phase 15: Multimodal Telegram" and does NOT yet describe v2.0 Phases 15–18 | open (low priority) | next docs sweep (~30–60 min) — see `.planning/MASTER-PLAN-AUDIT.md` § "Documentation drift" |
