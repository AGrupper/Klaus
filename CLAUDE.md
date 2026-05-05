# Master Blueprint: Personal Hybrid Agent

## 1. Project Overview
This project is a custom, cloud-hosted personal AI agent. It uses a dual-model architecture (a fast router model and a smart primary model) to handle scheduling, task management, and tool execution. It bridges cloud-native APIs (Gmail, Google Calendar) with local apps (Things 3) via a cloud database queue. 

## 2. Context Files Reference
Before writing any code, you must read and adhere to the following context files:
* `docs/PRD.md`: The core product requirements and feature goals.
* `docs/TECHNICAL_PLAN.md`: The architecture, hosting, and memory strategy.
* `docs/USER.md`: The user's personal context, routines, and hardcoded scheduling rules.
* `docs/AGENT.md`: The persona, tone, and behavioral directives for the agent.
* `docs/CODING_STANDARDS.md`: The rules for code structure, readability, and formatting.


## 3. Target Directory Structure
Please build and maintain the following scaffold:
```text
Klaus/
├── .env                  # (Ignored in git) Local environment variables
├── .env.example          # Template for environment variables
├── CLAUDE.md             # This file
├── docs/                 # Project documentation and context files
│   ├── PRD.md
│   ├── TECHNICAL_PLAN.md
│   ├── USER.md
│   ├── AGENT.md
│   └── CODING_STANDARDS.md
├── core/
│   ├── main.py           # Application entry point & router
│   ├── auth_google.py    # Google OAuth 2.0 persistent logic
│   └── llm_client.py     # Agnostic LLM API wrapper
├── memory/
│   ├── firestore_db.py   # State and Things 3 Queue logic
│   └── pinecone_db.py    # Vector RAG logic
├── mcp_tools/            # Custom MCP server logic
│   ├── gmail_tool.py
│   ├── calendar_tool.py
│   └── things_queue.py
└── local_mac/
    └── things_poller.py  # Standalone script for macOS to poll Firestore