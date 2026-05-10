# Product Requirements Document (PRD): Personal Hybrid Agent

## 1. Vision
Create a highly personalized, cloud-hosted AI agent that manages scheduling, task organization, and daily workflows. The agent will act autonomously but interface with the user seamlessly across multiple platforms, utilizing a dual-model LLM architecture for cost-efficiency and high-level reasoning.

## 2. Core Features & Workflows
* **Dual-Model Orchestration:** The system will use a fast, cheap model (e.g., Gemini Flash or a small local-in-cloud model) to route requests, fetch data, and handle simple queries. Complex logic and planning will be routed to a primary "Smart" model (TBD).
* **Custom Tooling (MCPs):** The agent will utilize custom-built Python tools to interact with external services, avoiding bloated third-party wrappers.
* **The "Things 3" Queue System:** ✓ Live. The cloud agent pushes tasks (title, notes, deadline, reminder, tags) into a Firestore queue. A launchd daemon on the user's MacBook Air M4 polls the queue every 30s and injects each task into Things 3 via AppleScript. `deadline` sets Things 3's due-date badge; `reminder` (YYYY-MM-DDTHH:MM) sets an `activation date` so Things 3 fires a macOS notification at the scheduled time.
* **Google Workspace Integration:** Direct, persistent connection to Gmail and Google Calendar via a Google Cloud "Internal" OAuth App to prevent token expiration.

## 3. Interfaces
* **Phase 1:** Telegram Bot (Text/Audio processing). ✓ Live.
* **Phase 2:** Web Chat UI with voice capabilities. (Planned)

## 4. External Connections (Phase 7) ✓ Live
* **Weather:** wttr.in — current conditions + forecast for Tel Aviv. No auth required.
* **Readwise:** Daily reading highlights via Readwise API (`READWISE_TOKEN`).
* **Garmin Connect:** Sleep score, HRV, body battery, resting HR via `garminconnect` lib.
* All three registered as callable tools — Claude can invoke them mid-conversation or fan them out when asked for a daily brief.

## 5. Proactive Heartbeat (Parked)
* Code preserved in `attic/heartbeat/` — see `attic/heartbeat/README.md` to revive.

## 6. Five Fingers Practice Helper (Phase 8 — In Progress)

Three proactive flows triggered by Cloud Scheduler (Sun/Wed mornings and evenings, Mon/Thu mornings):

* **Pre-practice (Wed/Sun 10:30):** Klaus reads the calendar to confirm practice is on, runs a recommendation engine against the sub-team roster and attendance history, and sends a Telegram DM with `wa.me` prefilled-message links for 2–3 teammates to ping. Includes a copy-paste Hebrew status block for the captains WhatsApp group. If the calendar event is missing, Klaus asks Amit whether practice is happening before proceeding.
* **Post-practice attendance (Wed/Sun 21:15):** Klaus sends a Telegram inline-keyboard checklist of the 10-person sub-team. Amit taps ✓/✗ per person; results are written to Firestore.
* **Morning-after follow-up (Mon/Thu 10:30):** Klaus cross-references attendance against who was pre-pinged and sends `wa.me` links for anyone who missed practice and wasn't already contacted.

WhatsApp sending is always user-initiated (tap a link or copy-paste a group message) — Klaus never sends autonomously. Roster and attendance are stored in Firestore; a single Hebrew message template lives in `docs/USER.md`.


