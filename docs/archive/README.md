# Archived documentation

Everything in this directory is **historical**. It records how something was
built at a point in time. None of it is authoritative about how Klaus works
today, and none of it is read at runtime.

Read it to understand *why* a decision was made. Do not read it to learn what
the system currently does — much of it describes components that no longer
exist, including the Telegram bot, the in-cloud Gemini/DeepSeek reasoning
runtime, the Groq tick-brain, the Notion connector and the Hub chat surface.

For current behaviour, see the living docs in `docs/`:

| Question | Document |
|---|---|
| How is Klaus put together? | `docs/ARCHITECTURE.md` |
| What is Klaus for? | `docs/PRD.md` |
| Who is Amit, and what does Klaus need to know about him? | `docs/USER.md` |
| How should Klaus behave and speak? | `docs/AGENT.md` |
| How is code written here? | `docs/CODING_STANDARDS.md` |
| How does it get to production? | `docs/DEPLOYMENT.md` |
| What is the security boundary? | `docs/SECURITY.md` |

## Contents

- `TECHNICAL_PLAN.md` — the pre-v7 technical architecture. Superseded by
  `docs/ARCHITECTURE.md`.
- `PRD-pre-v7.md` — the pre-v7 product requirements, kept for the reasoning
  behind features that survived into v7.
- `plans/` — completed implementation plans, one per feature, dated.
- `specs/` — the design documents those plans were built from, dated.
