# Master Blueprint: Klaus — Personal Hybrid Agent

## 1. Project Overview

Klaus is a cloud-hosted personal AI agent for Amit Grupper, deployed on Google Cloud Run.
He runs a **dual-model architecture** (brain + worker, with a separate free always-on
tick-brain and an emergency fallback) and integrates with Gmail, Google Calendar,
TickTick, Notion, Pinecone, Firestore, weather/Readwise/Garmin, and the local
Claude Code / multi-AI chat-log pipelines. Telegram is the primary interface.

As of milestone v2.0 (shipped 2026-05-23) Klaus is **self-aware, cost-transparent, and
judgment-driven autonomous** — every LLM call is metered, he can read his own source
code, he carries an auto-generated SELF.md identity manifest plus a persistent
self_state, he writes a daily reflection journal, and a cron-triggered autonomous
tick (`*/20 7-21` Asia/Jerusalem) lets him reach out proactively on his own with
repeat-suppression and an eval harness measuring his judgment quality.

Fully cloud-native — no local Mac runtime dependency.

## 2. Context Files Reference

Before writing any code, read and adhere to these:

- `docs/PRD.md` — product requirements, feature goals, original vision
- `docs/TECHNICAL_PLAN.md` — architecture, hosting, memory strategy, per-purpose model map
- `docs/USER.md` — Amit's personal context, routines, hardcoded scheduling rules
- `docs/AGENT.md` — Klaus's persona, tone, JARVIS/C-3PO voice directives
- `docs/CODING_STANDARDS.md` — code structure, readability, formatting rules
- `docs/SELF.md` — Klaus's own auto-generated capability manifest (regenerated on every deploy via `core/self_manifest.py`)
- `docs/DEPLOYMENT.md` — Cloud Run + Cloud Scheduler + Secret Manager operator runbook
- `.planning/MILESTONES.md` + `.planning/ROADMAP.md` — what shipped, when, what's next

## 3. Model architecture (env-driven)

| Purpose | Model | Backend | Notes |
|---------|-------|---------|-------|
| Brain (smart agent) | `gemini-3.5-flash` | Gemini AI Studio | Orchestration, judgment, every conversation turn |
| Worker (hands) | `deepseek-v4-flash` | OpenAI-compat (DeepSeek API) | Tool execution, structured JSON, data gathering — $0.11/$0.22 per 1M tokens |
| Brain fallback | `claude-haiku-4-5` | Anthropic | Inline fallback on LLMError — diversity hedge |
| Tick-brain | `qwen3-32b` | Groq (OpenAI-compat) | Always-on free reasoning for heartbeat + autonomous tick |
| Tick-brain fallback | `gemini-3.5-flash` | Gemini AI Studio | Used if Groq fails |
| Embeddings | `gemini-embedding-2` | Gemini AI Studio (**NOT Vertex**) | 768-dim, Pinecone cosine |

All model strings come from env vars (`SMART_AGENT_MODEL`, `WORKER_AGENT_MODEL`,
`SMART_AGENT_FALLBACK_MODEL`, `TICK_BRAIN_MODEL`, and matching `_BACKEND`/`_API_KEY`/`_BASE_URL`).
`core/self_manifest.py` reads these at generate-time so `docs/SELF.md` can never drift.

## 4. Live directory layout

```text
Klaus/
├── .env                    # (gitignored) local env vars
├── .env.example            # template
├── CLAUDE.md               # this file
├── docs/
│   ├── PRD.md              # product requirements
│   ├── TECHNICAL_PLAN.md   # architecture + per-phase technical details
│   ├── USER.md             # Amit's context, routines, scheduling rules
│   ├── AGENT.md            # Klaus's persona + tone
│   ├── CODING_STANDARDS.md # code style
│   ├── SELF.md             # auto-generated capability manifest
│   └── DEPLOYMENT.md       # ops runbook: Cloud Run, crons, secrets, indexes
├── core/
│   ├── main.py             # AgentOrchestrator, _run_smart_loop, render_smart_system
│   ├── auth_google.py      # Google OAuth persistent token mgmt
│   ├── llm_client.py       # Backend-agnostic LLM wrapper (Anthropic / Gemini / OpenAI-compat)
│   ├── tools.py            # All tool schemas + lazy-singleton accessors + _HANDLERS dispatch
│   ├── tick_brain.py       # Groq Qwen3 + Gemini fallback (think + system_override + topic_key)
│   ├── pricing.py          # MODEL_PRICING dict + compute_cost(model, in, out)
│   ├── heartbeat.py        # Hourly cron: stale-cron detection, SELF.md SHA, tick-brain reasoning
│   ├── proactive_alerts.py # 21:30 nightly: weather/overload/travel-time alerts
│   ├── morning_briefing.py # */10 6-10: Garmin-anchored daily briefing state machine
│   ├── five_fingers.py     # Practice helper recommender + composer
│   ├── reflection.py       # Daily 22:00: gather day → journal entry → self_state update
│   ├── autonomous.py       # */20 7-21: 3-layer gather → tick-brain triage → brain compose
│   ├── scheduled_message.py# Telegram send + Firestore conversation injection
│   ├── self_manifest.py    # Auto-generates docs/SELF.md (CI runs on every deploy)
│   ├── chat_ingest.py      # Daily 04:00: parse Claude Code JSONL → Pinecone + Notion
│   └── chat_export_ingest.py # Daily 04:30: ChatGPT/Claude.ai/Gemini Takeout zips → same pipeline
├── memory/
│   ├── firestore_conversation.py # Per-user conversation history
│   ├── firestore_db.py     # All Firestore stores: LLMUsage, SelfState, Journal,
│   │                       #   FiveFingersRoster, Attendance, MorningBriefing,
│   │                       #   Followup, OutreachLog, TickLog
│   └── pinecone_db.py      # MemoryStore: remember/recall + chat upserts
├── mcp_tools/
│   ├── database_tool.py    # Analytical PostgreSQL read-only queries
│   ├── gmail_tool.py       # Read-only Gmail
│   ├── calendar_tool.py    # Google Calendar list/create/free-busy/delete + Get Ready
│   ├── ticktick_tool.py    # TickTick Open API (deadline + reminder)
│   ├── ticktick_auth.py    # TickTick OAuth 2 token mgmt
│   ├── notion_tool.py      # 5 tools: search, get_page, query_db, create_page, append_blocks
│   ├── weather_tool.py     # wttr.in
│   ├── readwise_tool.py    # Daily reading highlights
│   ├── garmin_tool.py      # Sleep, HRV, body battery, resting HR
│   ├── routes_tool.py      # Google Routes API (traffic-aware drive time)
│   ├── memory.py           # remember/recall (Pinecone-backed)
│   ├── self_inspect.py     # list_own_files / read_own_source / search_own_source
│   └── five_fingers/       # composer, recommender, roster, attendance submodule
├── interfaces/
│   ├── web_server.py       # FastAPI: Telegram webhook + /cron/* OIDC-protected routes
│   ├── _router.py          # Telegram message router + photo download
│   └── telegram_bot.py     # Legacy long-poll (dev-only)
├── prompts/
│   ├── smart_agent.md      # Brain system prompt (includes {self_md}, {self_state}, {journal_digest})
│   ├── worker_agent.md     # Worker system prompt
│   ├── autonomous_triage.md# Tick-brain layer-1 judgment prompt (autonomous engine)
│   ├── autonomous.md       # Brain layer-2 compose prompt (autonomous engine)
│   ├── reflection.md       # Reflection cron compose prompt
│   ├── morning_briefing.md # Morning briefing compose prompt
│   ├── proactive_alert.md  # Evening alerts compose prompt
│   ├── heartbeat.md        # Tick-brain heartbeat reasoning prompt
│   └── chat_summary.md     # Chat-ingest summary prompt (Notion DB rows)
├── scripts/
│   ├── eval_tick_brain.py  # Measurement-only judgment eval runner
│   ├── ticktick_oauth_bootstrap.py
│   ├── backfill_notion_titles.py
│   ├── ingest_garmin_zip.py # Parses + ingests Garmin export zip to Postgres
│   ├── upload_claude_logs.{sh,ps1}
│   ├── upload_chat_export.sh
│   ├── run_chat_export_backfill.sh
│   └── smoke_test_{notion,chat_ingest,chat_export}.py
├── evals/
│   └── tick_brain/         # 5 seed fixtures + README — judgment quality harness
└── tests/                  # pytest — 465+ passing locally
```

## 5. Live infrastructure

- **Cloud Run service:** `klaus-agent` in `me-west1`, project `klaus-agent`
- **Firestore database:** `klaus-firestore` (lowercase k — uppercase causes silent 404s)
- **Pinecone index:** `klaus-memory` (768-dim, cosine)
- **9 Cloud Scheduler jobs:** heartbeat (hourly), proactive-alerts (21:30), morning-briefing-tick (*/10 6-10), five-fingers-morning (Wed/Sun 10:30), five-fingers-evening (Wed/Sun 21:15), chat-ingest (04:00), chat-export-ingest (04:30), **klaus-reflect (22:00)**, **klaus-autonomous-tick (*/20 7-21)**

## 6. Invariants

- All GCP/Pinecone resource names lowercase `klaus-` (uppercase = silent 404)
- `load_dotenv` always with `override=True` (default silently ignores `.env` if shell already exported)
- Embeddings via Gemini AI Studio, **never Vertex** (embedding model is AI Studio only)
- Brain never routes through worker first — the brain (`gemini-3.5-flash`) sees every message and decides
- Autonomous tick cost gating: Layer 0 (gather, $0) → Layer 1 (tick-brain Groq, $0) → Layer 2 (brain, costs money) — brain only runs when tick-brain affirmatively says "speak up"
- `OutreachLogStore.append` is gated on `send_and_inject` success (D-10) — no log entry if delivery failed
- `_get_orchestrator()` is a process-wide singleton with double-checked locking — AgentOrchestrator is built once per Cloud Run instance, not 43× per day
