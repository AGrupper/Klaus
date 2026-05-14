# Technical Architecture & Implementation Plan

## 1. Stack & Infrastructure
* **Language:** Python 3.11+
* **Hosting:** Google Cloud Run (Scales to zero, native integration with Google Cloud IAM/OAuth).
* **Primary Framework:** Raw Python with standard HTTP libraries and the official MCP Python SDK for tool definition. No LangChain or LlamaIndex.
* **State & Memory Database:** * Firestore (Google Cloud) for conversation history, roster, attendance, and briefing state. TickTick Open API for task management.
    * Pinecone (Free Tier) for unstructured memory/RAG.

## 2. Model Architecture
* **Smart Agent (brain):** Gemini 3 Flash Preview (`gemini-3-flash-preview`) — complex reasoning, tool orchestration, conversation. Fallback: Claude Haiku 4.5 (`claude-haiku-4-5`).
* **Worker Agent (hands):** Gemini 2.5 Flash (`gemini-2.5-flash`) — fast structured JSON output, data fetching, routing.
* Both backends are abstracted in `core/llm_client.py`; swappable via env vars (`SMART_AGENT_BACKEND`, `SMART_AGENT_MODEL`, etc.).

## 3. Tool Development Plan (Custom MCPs)
We will build the following functional blocks:
1.  **Google Auth Manager:** Implements the OAuth 2.0 flow using `credentials.json` from a Google Cloud Project (Internal User Type). Manages token refresh permanently.
2.  **Gmail Tool:** Parses unread emails, summarizes, and extracts action items.
3.  **Calendar Tool:** Reads availability, proposes times, injects events, and deletes events (including paired Get Ready prep blocks for workouts).
4.  **TickTick Task Tool:** Writes tasks directly to TickTick via Open API. `reminder` (YYYY-MM-DDTHH:MM) sets a timed due date with a push notification alarm. `deadline` (YYYY-MM-DD) sets a silent due date. Fully cloud-native — no Mac dependency.

## 4. Execution Phases
* **Phase 1:** Auth and scaffolding. Establish persistent Google OAuth. ✓ Complete.
* **Phase 2:** Build the Router/Main LLM abstraction and the Telegram Bot listener. ✓ Complete — dual-model (Claude brain + Gemini Flash hands), `core/llm_client.py`, `core/main.py`, `interfaces/telegram_bot.py`.
* **Phase 3:** Develop the custom Google Calendar and Gmail tools. ✓ Complete — list, create, free/busy, and delete (with workout prep block cleanup) all live and smoke-tested.
* **Phase 4:** Build task tool. ✓ Originally Things 3 queue (Firestore + Mac daemon). Replaced by TickTick Open API — `mcp_tools/ticktick_tool.py`, `mcp_tools/ticktick_auth.py`. Fully cloud-native, no Mac dependency. `reminder` → dueDate + push alarm; `deadline` → silent due date.
* **Phase 5:** Cloud Run deployment. ✓ Complete — Dockerfile, `interfaces/web_server.py` (FastAPI + Telegram webhook), GitHub Actions CI/CD with Workload Identity Federation, Secret Manager for all API keys.
* **Phase 6:** Conversation persistence + long-term memory. ✓ Complete — `memory/firestore_conversation.py` (Firestore per-user history), `memory/pinecone_db.py` (Pinecone RAG via gemini-embedding-2), `mcp_tools/memory.py` (remember/recall tools).
* **Phase 7:** External connections. ✓ Complete — `mcp_tools/weather_tool.py` (wttr.in), `mcp_tools/readwise_tool.py` (Readwise API), `mcp_tools/garmin_tool.py` (Garmin Connect), all registered as callable tools.
* **Phase 8:** Five Fingers practice helper. ✓ Complete — three cron-driven flows (pre-practice, post-practice attendance, morning-after follow-up). `wa.me` prefilled-link delivery via Telegram DM — no autonomous WhatsApp sending. New Firestore collections: `five_fingers_roster`, `five_fingers_practices`. New modules: `mcp_tools/five_fingers/` (composer, recommender, roster, attendance), `core/five_fingers.py`. Two new Cloud Scheduler jobs + OIDC-protected cron endpoints in `interfaces/web_server.py`. Inline-keyboard attendance entry wired into `interfaces/_router.py`.
* **Phase 9:** Proactive evening alerts. ✓ Complete — nightly Cloud Scheduler job (`30 21 * * *` Asia/Jerusalem) scans tomorrow's calendar and detects weather conflicts, overloaded days, and travel-time violations. Template-based detection (zero LLM cost on quiet days); Smart Agent composes message when alerts exist. `core/proactive_alerts.py` refactored to use `core/scheduled_message.py` (shared Telegram send + Firestore conversation injection). Cloud Scheduler job: `Klaus-proactive-alerts`.
* **Phase 10:** Morning briefing. ✓ Complete — Garmin-sync-anchored daily briefing via Telegram. State machine in Firestore (`morning_briefings/{date}`), polled every 10 min by Cloud Scheduler (`*/10 6-10 * * *` Asia/Jerusalem). Data sources: weather, calendar, Gmail, Garmin, TickTick tasks (real-time Open API, replaces Things 3 snapshot). Briefing injected into conversation history as assistant turn. Manual trigger via Smart Agent tool `run_morning_briefing`. Key modules: `core/morning_briefing.py`, `prompts/morning_briefing.md`. Cloud Scheduler job: `Klaus-morning-briefing-tick`.

## 5. Live Infrastructure (as of Phase 10)
* **Cloud Run service:** `Klaus-agent` — region `me-west1`, project `Klaus-agent`
* **Firestore database:** `Klaus-firestore`
  * Collection `conversations` — per-user conversation history (Phase 6)
  * Collection `five_fingers_roster` — Phase 8 sub-team roster (one doc per teammate)
  * Collection `five_fingers_practices` — Phase 8 attendance log (one doc per practice, ID = YYYY-MM-DD)
  * Collection `morning_briefings/{date}` — Phase 10 state machine + structured metadata
* **Pinecone index:** `Klaus-memory` — serverless, AWS, dimension=768, cosine
* **Cloud Scheduler jobs:**
  * `Klaus-proactive-alerts` — `30 21 * * *` Asia/Jerusalem (Phase 9)
  * `Klaus-morning-briefing-tick` — `*/10 6-10 * * *` Asia/Jerusalem (Phase 10)
* **Secrets in Secret Manager:** `Klaus-anthropic-key`, `Klaus-gemini-key`, `Klaus-telegram-token`, `Klaus-telegram-webhook-secret`, `Klaus-google-oauth-token`, `Klaus-pinecone-key`, `Klaus-home-address`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `READWISE_TOKEN`, `TICKTICK_CLIENT_ID`, `TICKTICK_CLIENT_SECRET`, `TICKTICK_ACCESS_TOKEN`, `TICKTICK_REFRESH_TOKEN`