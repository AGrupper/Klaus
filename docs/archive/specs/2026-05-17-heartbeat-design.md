# Klaus Self-Monitoring Heartbeat — Design

**Date:** 2026-05-17
**Status:** Approved

## Context

Klaus is a deployed Cloud Run agent with several scheduled jobs (morning briefing,
proactive alerts, five-fingers, chat ingestion) and many external dependencies
(Google + TickTick OAuth, Gemini, Pinecone, Telegram). When any of these fail, it
fails **silently** — a cron stops firing, an OAuth token expires, Gemini starts
429ing and Klaus quietly degrades to the Haiku fallback. The codebase leans heavily
on broad `except Exception`, making tool failures invisible by design.

This feature gives Klaus self-awareness: a heartbeat that watches his own runtime,
integrations, and deployment, and proactively tells the user when something is wrong
— with a diagnosis and a suggested fix.

## Goal

A `/cron/heartbeat` endpoint that periodically checks Klaus's own health and sends
tiered Telegram alerts: instant for things broken now, digested for the rest, each
with a remediation hint.

## Watch List

**v1 core — operational (A/B/C/E):**

| ID | Area | What it catches |
|----|------|----------------|
| A | Scheduled-job health | Each cron (`morning-briefing`, `proactive-alerts`, `five-fingers` AM/PM, `ingest-chats`, `ingest-chat-exports`) ran *and succeeded* today; any cron erroring N times in a row |
| B | Integration & token health | Google OAuth refresh failing; TickTick OAuth failing / near expiry; Pinecone 429ing; Gemini quota/429s; Telegram send failures |
| C | Degradation signals | Gemini 3 → Haiku fallback rate climbing; requests creeping toward 300s timeout; Cloud Run 5xx / unhandled-exception spikes |
| E | Deployment health | Last GitHub Actions deploy succeeded; live Cloud Run revision == latest `main` commit |

**v1 add-on — code self-knowledge (F, weekly cadence):**

| ID | Area | What it catches |
|----|------|----------------|
| F | Code self-knowledge | `CLAUDE.md`/docs drift vs real repo structure; aging TODO/FIXME and parked features; repeated-fix clustering in git history |

**Out of scope for v1:** Pipeline freshness (D), self-healing, tool-failure
aggregation. Broader calendar/chat-history watching (original idea) fully dropped.

## Response Behaviour

- **Response type:** report + diagnose — every signal carries a static remediation
  hint (e.g. "TickTick token expired — run `scripts/ticktick_oauth_bootstrap.py`");
  an LLM composer (worker model) turns signals + hints into a clean Telegram message
  with a deterministic plain-text fallback.

- **Severity tiers & delivery:**

| Severity | Examples | Delivery |
|----------|----------|----------|
| Critical | cron didn't run, token fully failing, crash-looping, deploy failed | Instant Telegram ping |
| Warning | token near expiry, fallback rate climbing, 429s returning, revision behind `main` | Daily digest (non-empty only) |
| FYI | docs drift, stale TODOs, parked features, repeated-fix clusters | Weekly digest (non-empty only) |

- Critical alerts during quiet hours are **queued** and delivered at quiet-end.
- Digests are suppressed when empty — no "all clear" spam.

## Architecture

**Entry point:** New Cloud Scheduler job `klaus-heartbeat`, `0 * * * *` (hourly),
OIDC-authed → `POST /cron/heartbeat` on `klaus-agent` Cloud Run. Reuses
`_verify_cron_request` from `interfaces/web_server.py`. Single job; the handler
branches on time-of-day (mirrors `morning_briefing.py`'s tick + state-machine pattern):
- Every tick → Critical checks; instant ping on new incident.
- Once daily → also Warning checks; emit daily digest.
- Once weekly → also F checks; emit weekly digest.

**Observability — Hybrid:**
- *Inside-out (Firestore ledger):* cron handlers write a `heartbeat_runs/{job_id}`
  success doc; `core/main.py` increments a fallback counter in Firestore. Heartbeat
  reads Firestore. Cheap, no new IAM.
- *Outside-in (GCP/GitHub APIs):* Cloud Monitoring for Cloud Run 5xx/latency; GitHub
  Actions API for last deploy; Cloud Run Admin API for live revision vs `main`.
  Covers blind spots (hard crashes, deploy status) that a self-recording Klaus can't see.

**Who watches the watcher:** the daily digest is a liveness signal. A lightweight
dead-man's-switch (e.g. healthchecks.io ping at end of `run_tick`) covers a
hard-down heartbeat.

**`core/heartbeat.py` internals:**

```
run_tick(now)
  ├── load config (HeartbeatConfigStore)
  ├── check quiet hours
  ├── determine tiers (Critical always; Warning if digest hour; FYI if weekly day)
  ├── asyncio.gather(check_cron_health(), check_tokens(),
  │                  check_degradation(), check_deployment(),
  │                  check_code() [weekly only])
  ├── classify → list[Signal]
  ├── IncidentStore dedup/escalation
  ├── _compose_message(signals) → LLM + plain-text fallback
  └── send_and_inject(bot, message, inject_into_conversation=True)
```

**`Signal` dataclass:** `fingerprint`, `severity`, `area`, `title`, `detail`,
`remediation` (static string).

**`IncidentStore`** (Firestore `heartbeat_incidents`): keyed by `fingerprint`;
tracks `first_seen`, `last_pinged`, `status` (open/resolved). New critical → ping +
record. Already-open → silent within `reping_interval_hours`. Signal gone → resolve,
optional "recovered" note.

**Config** (Firestore `config/heartbeat`, tunable without redeploy):
`enabled`, `quiet_start`, `quiet_end`, `timezone`, `digest_hour`,
`weekly_digest_day`, `reping_interval_hours`.

Revive `HeartbeatConfigStore` + quiet-hours helpers from `attic/heartbeat/` into
`memory/firestore_db.py`. The parked calendar/task detection is **not** reused.

## File Changes

| File | Change |
|------|--------|
| `core/heartbeat.py` | **New** — checkers, composer, `run_tick`, CLI smoke test |
| `prompts/heartbeat.md` | **New** — composer system prompt |
| `interfaces/web_server.py` | Add `/cron/heartbeat` route, import |
| `core/main.py` | Increment Firestore fallback counter at the Gemini→Haiku fallback site |
| `core/five_fingers.py` + chat-ingest handlers | Add `record_cron_run(job_id, ok)` calls |
| `memory/firestore_db.py` | Revive `HeartbeatConfigStore`; add `IncidentStore`, `record_cron_run` helper |
| `.env.example` | `CLOUD_RUN_URL`, scheduler SA, GitHub token reference |
| `.github/workflows/deploy.yml` | Append new env vars |

**Infra (one-time):** Cloud Scheduler job `klaus-heartbeat` + service account;
IAM grants (`monitoring.viewer`, `run.viewer`); Secret Manager `klaus-github-token`.

## Implementation Order

1. Detection core — `Signal`, checkers (A/B from ledger), `run_tick` skeleton, `--dry-run` CLI. Revive config. No sending.
2. Self-instrumentation — `record_cron_run` helper + ledger writes in handlers; fallback counter in `main.py`.
3. Outside-in checks — Cloud Monitoring + GitHub/Cloud Run Admin APIs; IAM + secret.
4. Incidents + delivery — `IncidentStore`, tiered composer, `prompts/heartbeat.md`, `send_and_inject`, quiet-hours queue.
5. Wire-up + deploy — route, env vars, Cloud Scheduler job, live verification.
6. F-tier (weekly) — `check_code` for docs drift, stale TODOs, repeated-fix clusters.

## Verification

- `python -m core.heartbeat --dry-run` — runs all checkers, prints signals + composed
  message; no send/write. Pattern from `proactive_alerts.py` / `morning_briefing.py`.
- Synthetic failure (delete a ledger doc or break a token) → confirm Critical detected.
- Run tick twice on same failure → confirm second run silent (dedup).
- Unauthenticated `POST /cron/heartbeat` → rejected by `_verify_cron_request`.
- Live: trigger Cloud Scheduler job manually → Telegram message + Firestore incident.
