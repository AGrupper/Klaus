# Roadmap: Klaus

This file is a compact milestone summary. Per-milestone phase detail lives in
`.planning/milestones/`. Active requirements live in `.planning/REQUIREMENTS.md`
(absent between milestones).

---

## v1.0 — Foundation & Integrations (Phases 1–13) ✓ Shipped 2026-05-18

Built Klaus from scratch: cloud-hosted, fully integrated, proactive where
hardcoded. 13 phases — Telegram bot, Gmail + Calendar + TickTick tools,
Cloud Run + CI/CD, Firestore + Pinecone memory, weather/Readwise/Garmin,
Five Fingers helper, proactive alerts, morning briefing, Notion, two chat
ingestion pipelines.

Detail: see `.planning/MILESTONES.md § v1.0`.

---

## v2.0 — Consciousness & Autonomy (Phases 14–18) ✓ Shipped 2026-05-23

Made Klaus self-aware, judgment-driven, cost-transparent: every LLM call
metered, free always-on tick-brain, self-inspect tools, doubt-free SELF.md
manifest + mutable self_state, daily reflection cron, and the autonomous
engine (`*/20 7-21` triage + compose pipeline with repeat-suppression +
eval harness).

**Phases:** 5 · **Plans:** 24 · **Requirements:** 41/41

| # | Phase | Outcome |
|---|-------|---------|
| 14 | Foundation: Cost Metering + Tick-Brain + LLM Strategy | `core/pricing.py`, `LLMUsageStore`, `core/tick_brain.py` (Groq/Qwen3-32B + Gemini fallback), per-purpose model map in `docs/TECHNICAL_PLAN.md` |
| 15 | Codebase Self-Knowledge | `mcp_tools/self_inspect.py` + 3 brain-direct tools (`list_own_files`, `read_own_source`, `search_own_source`) with secret denylist |
| 16 | Self-Model & State Awareness | `docs/SELF.md` auto-generated manifest, `SelfStateStore`, `get_self_status` tool, weekly SHA staleness check |
| 17 | Reflection & Journal | `core/reflection.py` + `JournalStore` + `/cron/reflect` (Cloud Scheduler ~22:00), Pinecone `kind="self"` |
| 18 | The Autonomous Engine | `core/autonomous.py` (3-layer pipeline: gather → triage → compose), `/cron/autonomous-tick` OIDC-protected, `FollowupStore`/`OutreachLogStore`/`TickLogStore`, `schedule_followup`/`list_followups`/`cancel_followup` tools, 5 seed eval fixtures, `scripts/eval_tick_brain.py` runner, full DEPLOYMENT.md |

Detail: see `.planning/milestones/v2.0-ROADMAP.md` and
`.planning/milestones/v2.0-REQUIREMENTS.md`.

**Deferred to staging smoke (see `.planning/STATE.md § Deferred Items`):**
SC-1, SC-2, SC-4 (require live Telegram + Cloud Run + real Groq key) — code
paths verified at unit-test level; final live-fire validation is a manual
operator step. SC-3 (quiet-tick cost ≈ $0) verified locally.

---

## Backlog

(none recorded)

---

## Next Milestone

Not yet defined. Candidates: deferred email-send, Phase 19 hardening sweep
(see `.planning/phases/18-autonomous-engine/deferred-items.md`), WhatsApp
outbound, multi-user, or something entirely new. Run `/gsd-new-milestone`
when ready.
