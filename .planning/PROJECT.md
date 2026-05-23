# Klaus — Personal Hybrid Agent

## What This Is

Klaus is a cloud-hosted personal AI agent for Amit that manages scheduling, task management, proactive alerts, and daily workflows. It uses a dual-model architecture (Gemini 3 Flash as the brain, Gemini 2.5 Flash as the worker) with Telegram as the primary interface, integrated with Gmail, Google Calendar, TickTick, Notion, Garmin, and a vector memory store (Pinecone). No local Mac dependency — fully Cloud Run native.

## Core Value

Klaus should act as a genuinely intelligent, proactive companion that surfaces the right thing at the right time — while knowing exactly what he is and what he can do.

## Current Milestone: (none — between milestones)

**Last shipped:** v2.0 Consciousness & Autonomy on 2026-05-23 (5 phases, 24 plans, 41/41 requirements). See `.planning/MILESTONES.md § v2.0` for the closure summary.

**Next:** Not yet defined. Run `/gsd-new-milestone` to start the next cycle.

## Requirements

### Validated

- ✓ Telegram bot interface (webhook, Cloud Run) — Phase 1
- ✓ Dual-model LLM abstraction (`llm_client.py`) — Phase 2
- ✓ Gmail + Google Calendar tools — Phase 3
- ✓ TickTick task tool (reminder + deadline) — Phase 4
- ✓ Cloud Run deployment with CI/CD + Secret Manager — Phase 5
- ✓ Conversation persistence (Firestore) + vector memory (Pinecone RAG) — Phase 6
- ✓ External connections: weather, Readwise, Garmin — Phase 7
- ✓ Five Fingers practice helper (3 cron flows) — Phase 8
- ✓ Proactive evening alerts (21:30 nightly) — Phase 9
- ✓ Morning briefing (Garmin-anchored, */10 cron) — Phase 10
- ✓ Notion integration (5 tools) — Phase 11
- ✓ Claude Code chat-log ingestion → Pinecone + Notion — Phase 12
- ✓ Multi-source AI chat export ingestion (Claude.ai, ChatGPT, Gemini) — Phase 13
- ✓ Every LLM call is cost-metered and stored (Phase 14)
- ✓ Free tick-brain component exists and upgrades the heartbeat (Phase 14)
- ✓ Klaus can read and search his own deployed source files — `list_own_files`, `read_own_source`, `search_own_source` brain-direct tools with secret denylist (Phase 15)
- ✓ SELF.md manifest auto-generated; injected into every conversation (Phase 16)
- ✓ `get_self_status` tool returns uptime, cost, heartbeat status (Phase 16)
- ✓ SelfStateStore persists identity state across 6h conversation resets (Phase 16)
- ✓ Heartbeat weekly SHA check flags stale SELF.md; CI regenerates on every deploy (Phase 16)
- ✓ Daily reflection cron writes journal entries + updates self-state (Phase 17)
- ✓ Autonomous tick engine fires every 20 min, 7-21, with judgment + repeat-suppression (Phase 18)
- ✓ Judgment eval harness scores tick-brain on labeled fixtures (Phase 18)

### Active

(none — between milestones; live-staging verification of SC-1/SC-2/SC-4 outstanding, see STATE.md § Deferred Items)

### Out of Scope

- Email sending — Gmail stays read-only this milestone; clean fast-follow
- WhatsApp autonomous outbound — user-initiated only (wa.me links)
- Multi-user support — single user (Amit) throughout
- Spend caps — cost is measured, never enforced (explicit user choice)

## Context

- **Stack:** Python 3.11+, Cloud Run, Firestore, Pinecone, FastAPI, Telegram Bot API
- **Brain model:** `gemini-3-flash-preview` — stale JARVIS/Claude comments fixed in Phase 14
- **Worker model:** `gemini-2.5-flash`
- **Fallback:** `claude-haiku-4-5` (Anthropic, triggered only on brain failure)
- **Embeddings:** `gemini-embedding-2` via AI Studio (NOT Vertex — AI Studio only)
- **Seven existing cron jobs:** heartbeat (hourly), proactive-alerts (21:30), morning-briefing-tick (*/10 6-10), five-fingers-morning (Wed/Sun 10:30), five-fingers-evening (Wed/Sun 21:15), ingest-chats (04:00), ingest-chat-exports (04:30)
- **Memory:** Klaus's `_OpenAIBackend` already wired in `llm_client.py` — Groq just needs a `base_url` param thread
- **Pinecone valid kinds today:** `{"fact","chunk","chat"}` — Phase 17 adds `"self"`

## Constraints

- **Cloud-only:** No local Mac runtime dependency
- **Outbound:** Telegram to Amit only; no autonomous WhatsApp/email send
- **Single user:** No multi-tenant support
- **Cost model:** Measure everything, cap nothing (user preference)
- **Quiet hours:** Autonomous outreach window `7-21` (cron); reflection at ~22:00

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Gemini 3 Flash as brain (not Claude) | Lower cost, better tool use at scale | ✓ Good |
| Groq/Qwen3-32B for tick-brain | Free tier, fast, doesn't train on data, OpenAI-compat | ✓ Implemented Phase 14 |
| No spend cap | "I want him to be able to do whatever he wants" — explicit user choice | ✓ Implemented Phase 14 |
| Outbound Telegram-only | Clean scope; email send is a fast-follow | ✓ Good |
| `kind="self"` in Pinecone | Journal entries need their own namespace distinct from facts/chat | — Pending |
| Tick every 20 min, 7-21 | ≈42 ticks/day; balances proactivity with quiet hours | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-18 — Phase 15 complete (SELF-01–05 verified; self-inspect tools wired brain-direct)*
