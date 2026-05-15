# Product Requirements Document (PRD): Personal Hybrid Agent

## 1. Vision
Create a highly personalized, cloud-hosted AI agent that manages scheduling, task organization, and daily workflows. The agent will act autonomously but interface with the user seamlessly across multiple platforms, utilizing a dual-model LLM architecture for cost-efficiency and high-level reasoning.

## 2. Core Features & Workflows
* **Dual-Model Orchestration:** The system will use a fast, cheap model (e.g., Gemini Flash or a small local-in-cloud model) to route requests, fetch data, and handle simple queries. Complex logic and planning will be routed to a primary "Smart" model (TBD).
* **Custom Tooling (MCPs):** The agent will utilize custom-built Python tools to interact with external services, avoiding bloated third-party wrappers.
* **TickTick Integration:** ✓ Live. The cloud agent writes tasks directly to TickTick via the Open API (developer.ticktick.com). `deadline` (YYYY-MM-DD) sets a due date; `reminder` (YYYY-MM-DDTHH:MM) sets a due datetime with a push notification alarm. Fully cloud-native — no MacBook dependency.
* **Google Workspace Integration:** Direct, persistent connection to Gmail and Google Calendar via a Google Cloud "Internal" OAuth App to prevent token expiration.

## 3. Interfaces
* **Phase 1:** Telegram Bot (Text/Audio processing). ✓ Live.
* **Phase 2:** Web Chat UI with voice capabilities. (Planned)

## 4. External Connections (Phase 7) ✓ Live
* **Weather:** wttr.in — current conditions + forecast for Tel Aviv. No auth required.
* **Readwise:** Daily reading highlights via Readwise API (`READWISE_TOKEN`).
* **Garmin Connect:** Sleep score, HRV, body battery, resting HR via `garminconnect` lib.
* All three registered as callable tools — Claude can invoke them mid-conversation or fan them out when asked for a daily brief.

## 5. Proactive Alerts (Phase 9)

A nightly background job (21:30 Asia/Jerusalem) scans tomorrow's calendar and conditions,
detects problems, and sends a proactive Telegram message in Klaus's voice.

Three alert types:
* **Weather conflicts** — outdoor or workout events scheduled when weather is bad
  (rain ≥ 20%, extreme heat ≥ 38°C, cold ≤ 8°C, or severe conditions).
* **Overloaded day** — not enough breathing room: longest gap < 30 min AND
  total free time < 60 min between first and last event.
* **Travel time validation** — events with a location are checked against Google Routes API
  (traffic-aware). If the predicted drive time exceeds the travel buffer Klaus wrote into
  the event description by more than 5 minutes, an alert is raised.

Detection is template-based (zero LLM cost on quiet days). If any alerts are found,
the structured data is passed to the Smart Agent to compose a single message in Klaus voice.

## 6. Five Fingers Practice Helper (Phase 8) ✓ Live

Three proactive flows triggered by Cloud Scheduler (Sun/Wed mornings and evenings, Mon/Thu mornings):

* **Pre-practice (Wed/Sun 10:30):** Klaus reads the calendar to confirm practice is on, runs a recommendation engine against the sub-team roster and attendance history, and sends a Telegram DM with `wa.me` prefilled-message links for 2–3 teammates to ping. Includes a copy-paste Hebrew status block for the captains WhatsApp group. If the calendar event is missing, Klaus asks Amit whether practice is happening before proceeding.
* **Post-practice attendance (Wed/Sun 21:15):** Klaus sends a Telegram inline-keyboard checklist of the 10-person sub-team. Amit taps ✓/✗ per person; results are written to Firestore.
* **Morning-after follow-up (Mon/Thu 10:30):** Klaus cross-references attendance against who was pre-pinged and sends `wa.me` links for anyone who missed practice and wasn't already contacted.

WhatsApp sending is always user-initiated (tap a link or copy-paste a group message) — Klaus never sends autonomously. Roster and attendance are stored in Firestore; a single Hebrew message template lives in `docs/USER.md`.

## 7. Morning Briefing (Phase 10)

**Goal:** Daily Garmin-sync-anchored morning briefing via Telegram.

**Delivery trigger:** Cloud Scheduler polls every 10 min (06:00–10:15 Asia/Jerusalem). Briefing fires 10–20 min after Garmin sleep data appears. Manual trigger via Telegram ("morning briefing").

**Data sources:** Weather (wttr.in), Google Calendar (today), Gmail (unread, actionable), Garmin health (sleep score, HRV, body battery), TickTick tasks (via Open API, real-time). Readwise: link-only to `https://readwise.io/daily_review`.

**Interactive:** Briefing written into Firestore conversation history so replies are natural follow-up turns. Structured event/task IDs stored in `morning_briefings/{date}` for tool use.

## 8. Notion Integration (Phase 11) ✓ Live

**Access level:** Read + create/append (never edits or deletes existing content).

Five callable tools:
* **notion_search** — full-text search across all shared Notion content; returns pages/databases with IDs, titles, URLs.
* **notion_get_page** — fetches a page's title, text content, flattened properties, and child pages/databases for PARA tree traversal.
* **notion_query_database** — queries a Notion database; returns schema (property names/types) + rows. Call before `notion_create_page` to know the property format.
* **notion_create_page** — creates a new page as a database entry or sub-page; converts plain text / light markdown to Notion blocks.
* **notion_append_blocks** — appends text content to an existing page (e.g. today's journal entry).

Auth: single Notion internal integration token (`NOTION_API_TOKEN`) — does not expire, no OAuth flow required.

Use cases: searching notes, querying PARA databases, logging journal entries, creating project pages.

Proactive scanning and Pinecone memory ingestion are deferred to a later phase.

## §12 — Claude Code Chat-Log Ingestion

**Goal:** Give Klaus real context about what the user works on by ingesting Claude Code conversation logs.

**What it does:**
- Parses structured JSONL session files from `~/.claude/projects/` on the user's machines
- Pushes raw files to a GCS staging bucket via lightweight upload scripts (hourly cron)
- A Cloud Run endpoint (`/cron/ingest-chats`, triggered daily at 04:00 Israel time) processes logs in bounded batches:
  - Embeds conversation chunks → Pinecone (semantic search, kind="chat")
  - Summarizes each session → Notion database (one row per conversation: title, date, project, 2-3 sentence summary, topic labels)
- New agent tool: `search_chat_history(query, k, project?)` — scoped semantic search over chat chunks; excluded from default `recall` to avoid polluting curated memory

**Design constraints:**
- Cloud-only: no new local dependencies beyond the upload scripts + gcloud SDK
- Idempotent: generation-token dedup on GCS, deterministic Pinecone IDs, Notion upsert keyed on Session ID
- Bounded batches: ≤8 files / ≤45s per Cloud Run tick to respect 60s timeout; Firestore tracks progress
- Security: upload SA has only `objectCreator` on the bucket — no AI keys on local machines
- Subagent turns excluded (`isSidechain=true` filtered out)

