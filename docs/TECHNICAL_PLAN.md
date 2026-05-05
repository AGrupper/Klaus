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
4.  **Things 3 Cloud Queue Tool:** Writes structured JSON tasks (Title, Notes, Deadline, Tags) to Firestore.
5.  **Local Mac Poller (Separate Script):** A lightweight daemon running on macOS that watches Firestore and executes AppleScript to create Things 3 to-dos.

## 4. Execution Phases
* **Phase 1:** Auth and scaffolding. Establish persistent Google OAuth.
* **Phase 2:** Build the Router/Main LLM abstraction and the Telegram Bot listener.
* **Phase 3:** Develop the custom Google Calendar and Gmail tools. ✓ Complete — list, create, free/busy, and delete (with workout prep block cleanup) all live and smoke-tested.
* **Phase 4:** Build the Firestore Queue and the local macOS Things 3 injector.