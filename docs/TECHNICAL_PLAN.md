# Technical Architecture & Implementation Plan

## 1. Stack & Infrastructure
* **Language:** Python 3.11+
* **Hosting:** Google Cloud Run (Scales to zero, native integration with Google Cloud IAM/OAuth).
* **Primary Framework:** Raw Python with standard HTTP libraries and the official MCP Python SDK for tool definition. No LangChain or LlamaIndex.
* **State & Memory Database:** * Firestore (Google Cloud) for the Things 3 Queue and static User Profile configurations.
    * Pinecone (Free Tier) for unstructured memory/RAG.

## 2. Model Architecture
* **Router/Fetcher LLM:** Lightweight model optimized for speed and JSON output.
* **Main Agent/Orchestrator LLM:** Agnostic integration point (TBD). The system must abstract the LLM call so the API endpoint can be swapped by changing an environment variable.

## 3. Tool Development Plan (Custom MCPs)
We will build the following functional blocks:
1.  **Google Auth Manager:** Implements the OAuth 2.0 flow using `credentials.json` from a Google Cloud Project (Internal User Type). Manages token refresh permanently.
2.  **Gmail Tool:** Parses unread emails, summarizes, and extracts action items.
3.  **Calendar Tool:** Reads availability, proposes times, injects events, and deletes events (including paired Get Ready prep blocks for workouts).
4.  **Things 3 Cloud Queue Tool:** Writes structured JSON tasks (Title, Notes, Deadline, Reminder, Tags) to Firestore. `reminder` (YYYY-MM-DDTHH:MM) maps to Things 3's `activation date` for time-of-day notifications.
5.  **Local Mac Poller (Separate Script):** A lightweight daemon running on macOS that watches Firestore and executes AppleScript to create Things 3 to-dos.

## 4. Execution Phases
* **Phase 1:** Auth and scaffolding. Establish persistent Google OAuth. ✓ Complete.
* **Phase 2:** Build the Router/Main LLM abstraction and the Telegram Bot listener. ✓ Complete — dual-model (Claude brain + Gemini Flash hands), `core/llm_client.py`, `core/main.py`, `interfaces/telegram_bot.py`.
* **Phase 3:** Develop the custom Google Calendar and Gmail tools. ✓ Complete — list, create, free/busy, and delete (with workout prep block cleanup) all live and smoke-tested.
* **Phase 4:** Build the Firestore Queue and the local macOS Things 3 injector. ✓ Complete + patched — `memory/firestore_db.py` (FirestoreQueue), `mcp_tools/things_queue.py`, `local_mac/things_poller.py` (launchd daemon, live). Added `reminder` field (YYYY-MM-DDTHH:MM → AppleScript `activation date`). Daemon running at `com.amitgrupper.klaus.things-poller` via `~/Library/LaunchAgents/`.
* **Phase 5:** Cloud Run deployment. ✓ Complete — Dockerfile, `interfaces/web_server.py` (FastAPI + Telegram webhook), GitHub Actions CI/CD with Workload Identity Federation, Secret Manager for all API keys.
* **Phase 6:** Conversation persistence + long-term memory. ✓ Complete — `memory/firestore_conversation.py` (Firestore per-user history), `memory/pinecone_db.py` (Pinecone RAG via gemini-embedding-2), `mcp_tools/memory.py` (remember/recall tools).
* **Phase 7:** External connections. ✓ Complete — `mcp_tools/weather_tool.py` (wttr.in), `mcp_tools/readwise_tool.py` (Readwise API), `mcp_tools/garmin_tool.py` (Garmin Connect), all registered as callable tools.
* **Phase 8 (in progress):** Five Fingers practice helper. Three cron-driven flows (pre-practice, post-practice attendance, morning-after follow-up). `wa.me` prefilled-link delivery via Telegram DM — no autonomous WhatsApp sending. New Firestore collections: `five_fingers_roster`, `five_fingers_practices`. New modules: `mcp_tools/five_fingers/` (composer, recommender, roster, attendance), `core/five_fingers.py`. Two new Cloud Scheduler jobs + OIDC-protected cron endpoints in `interfaces/web_server.py`. Inline-keyboard attendance entry wired into `interfaces/_router.py`.

## 5. Live Infrastructure (as of Phase 7)
* **Cloud Run service:** `Klaus-agent` — region `me-west1`, project `Klaus-agent`
* **Firestore database:** `Klaus-firestore`
  * Collection `things_queue` — Things 3 Mac poller queue
  * Collection `conversations` — per-user conversation history (Phase 6)
  * Collection `five_fingers_roster` — Phase 8 sub-team roster (one doc per teammate)
  * Collection `five_fingers_practices` — Phase 8 attendance log (one doc per practice, ID = YYYY-MM-DD)
* **Pinecone index:** `Klaus-memory` — serverless, AWS, dimension=768, cosine
* **Secrets in Secret Manager:** `Klaus-anthropic-key`, `Klaus-gemini-key`, `Klaus-telegram-token`, `Klaus-telegram-webhook-secret`, `Klaus-google-oauth-token`, `Klaus-pinecone-key`, `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `READWISE_TOKEN`

### Phase 10 components

- `core/morning_briefing.py` — state machine (`handle_tick`), `run_morning_briefing`, data gathering, LLM composition, plain-text fallback, CLI smoke test.
- `core/scheduled_message.py` — shared Telegram send + Firestore conversation injection (used by Phase 9 and Phase 10).
- `mcp_tools/things_snapshot.py` — reads `things_snapshot/latest` from Firestore with staleness tiers.
- `local_mac/things_poller.py` — now also pushes Things 3 snapshot each poll cycle via `push_things_snapshot()`.
- `prompts/morning_briefing.md` — Klaus JARVIS × C-3PO voice + format spec for briefing composition.
- Firestore collections: `morning_briefings/{date}` (state machine + structured metadata), `things_snapshot/latest` (Mac-side task snapshot).
- Cloud Scheduler job: `klaus-morning-briefing-tick`, schedule `*/10 6-10 * * *` Asia/Jerusalem.