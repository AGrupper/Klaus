# Milestones — Klaus

## v1.0 — Foundation & Integrations (Phases 1–13) ✓ Complete

**Completed:** 2026-05-18
**Goal:** Build Klaus from scratch — cloud-hosted, fully integrated, proactive where hardcoded.

### Phases Shipped

| Phase | Name | Highlights |
|-------|------|-----------|
| 1 | Auth & Scaffolding | Persistent Google OAuth, project scaffold |
| 2 | Core LLM + Telegram | `llm_client.py` dual-model, Telegram bot webhook |
| 3 | Google Tools | Calendar + Gmail tools (list, create, free/busy, delete) |
| 4 | Task Tool | TickTick Open API — reminder (push alarm) + deadline (silent) |
| 5 | Cloud Run Deploy | Dockerfile, FastAPI web server, GitHub Actions CI/CD, Secret Manager |
| 6 | Memory | Firestore conversation history, Pinecone RAG (gemini-embedding-2) |
| 7 | External Connections | Weather (wttr.in), Readwise, Garmin Connect |
| 8 | Five Fingers | 3 cron flows: pre-practice, attendance, morning-after follow-up |
| 9 | Proactive Alerts | Nightly 21:30 scan: weather conflicts, overloaded day, travel time |
| 10 | Morning Briefing | Garmin-anchored, */10 poll, all data sources, injected into conversation |
| 11 | Notion Integration | 5 tools: search, get_page, query_database, create_page, append_blocks |
| 12 | Chat-Log Ingestion | Claude Code JSONL → Pinecone (kind="chat") + Notion DB |
| 13 | Multi-Source Export | Claude.ai + ChatGPT + Gemini exports → same pipeline |

---

## v2.0 — Consciousness & Autonomy (Phases 14–18) ← Current

**Started:** 2026-05-18
**Goal:** Self-aware, judgment-driven autonomous agent with cost visibility and a free always-on mind.

See `.planning/ROADMAP.md` for phase details.
