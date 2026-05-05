# Product Requirements Document (PRD): Personal Hybrid Agent

## 1. Vision
Create a highly personalized, cloud-hosted AI agent that manages scheduling, task organization, and daily workflows. The agent will act autonomously but interface with the user seamlessly across multiple platforms, utilizing a dual-model LLM architecture for cost-efficiency and high-level reasoning.

## 2. Core Features & Workflows
* **Dual-Model Orchestration:** The system will use a fast, cheap model (e.g., Gemini Flash or a small local-in-cloud model) to route requests, fetch data, and handle simple queries. Complex logic and planning will be routed to a primary "Smart" model (TBD).
* **Custom Tooling (MCPs):** The agent will utilize custom-built Python tools to interact with external services, avoiding bloated third-party wrappers.
* **The "Things 3" Queue System:** Because Things 3 is local-only, the cloud agent will push tasks into a lightweight cloud database (Queue). A local Python chron-job/script running on the user's MacBook Air M4 will poll this queue and inject tasks into Things 3 locally via AppleScript.
* **Google Workspace Integration:** Direct, persistent connection to Gmail and Google Calendar via a Google Cloud "Internal" OAuth App to prevent token expiration.

## 3. Interfaces
* **Phase 1:** Telegram Bot (Text/Audio processing).
* **Phase 2:** Web Chat UI with voice capabilities.


