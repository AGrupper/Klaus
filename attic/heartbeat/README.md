# Parked: Heartbeat Feature

Parked on 2026-05-10. Original Phase 7 commit: `4a9d8c3`

## What it does

Cloud Scheduler fires `POST /cron/heartbeat` every 30 minutes. The handler
runs a deterministic detection cycle: upcoming calendar events (next 75 min)
and pending Things 3 tasks with deadlines due/overdue today. Gemini Flash
composes a short Telegram ping only when signals are found — most ticks are
silent. Quiet hours and an enabled flag are configurable in Firestore
`config/heartbeat` without redeploy.

## GCP resources to re-create

- **Cloud Scheduler job:** `Klaus-heartbeat`, region `me-west1`,
  schedule `*/30 * * * *`, OIDC auth.
- **Service account:** `klaus-heartbeat@klaus-agent.iam.gserviceaccount.com`

## Files to un-park

1. `attic/heartbeat/heartbeat.py` → `core/heartbeat.py`
2. `attic/heartbeat/heartbeat_composer.md` → `prompts/heartbeat_composer.md`
3. Copy the `_HEARTBEAT_CONFIG_DEFAULTS` dict and `HeartbeatConfigStore` class
   from `attic/heartbeat/firestore_heartbeat_config.py` back into
   `memory/firestore_db.py` (insert after `UserProfileStore`).

## Wires to re-attach in interfaces/web_server.py

1. Add `import asyncio` to the top-level imports.
2. Add `from core import heartbeat as _heartbeat` to the core imports.
3. Restore the `/cron/heartbeat` route (`cron_heartbeat` function).
4. Restore the `_verify_heartbeat_request` helper function.

## Env vars to restore

In `.env.example` (after the `READWISE_TOKEN` line):

```
# Phase 7: Heartbeat scheduler

# Cloud Run service URL — used as OIDC token audience for /cron/heartbeat auth.
CLOUD_RUN_URL=

# Service account email that Cloud Scheduler uses to call /cron/heartbeat.
CLOUD_SCHEDULER_SA_EMAIL=

# Set to "true" in local dev to skip OIDC verification on /cron/heartbeat.
HEARTBEAT_DEV_BYPASS=false
```

In `.github/workflows/deploy.yml` `--set-env-vars` string, append:

```
,CLOUD_RUN_URL=https://klaus-agent-y2abtypx4q-zf.a.run.app,CLOUD_SCHEDULER_SA_EMAIL=klaus-heartbeat@klaus-agent.iam.gserviceaccount.com
```
