# Master Blueprint: Personal Hybrid Agent

## 1. Project Overview
This project is a custom, cloud-hosted personal AI agent. It uses a dual-model architecture (a fast router model and a smart primary model) to handle scheduling, task management, and tool execution. It integrates with cloud-native APIs (Gmail, Google Calendar, TickTick) and is fully cloud-hosted with no local Mac dependency.

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
│   ├── llm_client.py     # Agnostic LLM API wrapper
│   └── chat_ingest.py    # Phase 12: Claude Code log parser + GCS→Pinecone/Notion pipeline
├── memory/
│   ├── firestore_db.py   # Firestore state (roster, attendance, conversation store)
│   └── pinecone_db.py    # Vector RAG logic
├── mcp_tools/            # Custom MCP server logic
│   ├── gmail_tool.py
│   ├── calendar_tool.py
│   ├── ticktick_tool.py  # TickTick task integration (add_task, get_today_tasks)
│   └── ticktick_auth.py  # TickTick OAuth 2.0 token management
└── scripts/
    ├── ticktick_oauth_bootstrap.py  # One-time OAuth setup script
    ├── upload_claude_logs.sh        # Mac: push ~/.claude/projects/ to GCS hourly
    └── upload_claude_logs.ps1       # Windows: same for PC