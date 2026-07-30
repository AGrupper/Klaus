# iOS Shortcut: Sleep-Focus-OFF Morning Trigger — Operator Runbook

**Phase 33 (D-08 / D-13 / D-31)** — closes OCC-02's live trigger by bridging Amit's
iPhone waking up (Sleep Focus turning off) into Klaus's morning briefing.

This is the **exact mirror** of the existing Sleep-Focus-**ON** → `/trigger/nightly`
automation (`docs/DEPLOYMENT.md` § 22), triggered on the opposite Focus transition.
Code, auth, and the Cloud Tasks dispatch path all shipped in plan 33-10; this runbook
is the operator-facing build guide for the one hard human prerequisite (D-31) — Amit
has to build this automation himself, on his own phone, before `/trigger/morning`
does anything.

**There is no backstop for this trigger (D-09).** Unlike the nightly review (which has
`klaus-nightly-backstop` at 01:00 as a safety net), the morning briefing has none — if
the Sleep-Focus-off automation does not fire, there is no briefing that day, by design.
`klaus-morning-briefing` (`*/10 6-10`) remains the fallback until this Shortcut is
confirmed live and the legacy cron is retired (plan 33-13).

## 1. Overview

`POST /trigger/morning` is a bearer-authenticated endpoint that enqueues the morning
briefing compose onto Cloud Tasks and returns immediately (202). It does not compose
the briefing in-request — the full-CPU work happens on `/internal/process-occasion`,
the same tracked-request path every occasion (nightly/morning/weekly) now uses
(`core/task_dispatch.py::enqueue_occasion`, CLAUDE.md invariant: never a Starlette
BackgroundTask).

The trigger fires when Sleep Focus turns **Off** — i.e. Amit's phone leaves the
overnight Focus mode, whether from an alarm, a manual toggle, or waking up before an
alarm. This is functionally "wake-up detection" without any new hardware or app.

## 2. Required permissions

No HealthKit permissions are needed for this automation (contrast with
`docs/healthkit_shortcut.md`). The only iOS permission prompt is Shortcuts' own
request to run automations "without asking" — grant it, or every morning will show
a confirmation banner instead of running silently.

## 3. Build: the Sleep-Focus-OFF Personal Automation

Shortcuts → Automation tab → "+" (top right) → **Create Personal Automation** →
**Focus** → select **Sleep** → set the trigger to **Is Turned Off** → Next.

Add one action: **Get Contents of URL**.

- **URL:** `https://<CLOUD_RUN_URL>/trigger/morning`
  (find `<CLOUD_RUN_URL>` via `gcloud run services describe klaus-agent --region=me-west1
  --format 'value(status.url)'`, or reuse the same host as the existing nightly
  automation's URL.)
- **Method:** POST
- **Headers:** `Authorization` → `Bearer <MORNING_TRIGGER_TOKEN>` (the value you
  generated in `docs/DEPLOYMENT.md` § 23's `MORNING_TRIGGER_TOKEN Secret` section —
  do NOT reuse the nightly token; D-13 requires a distinct secret per surface)
- **Request Body:** none required (leave empty — the route ignores the body)

Tap **Done**, then on the automation's summary screen toggle:

- **Run Immediately:** ON (skip the "Run Now / Confirm" prompt — this is what makes
  it fire silently on wake-up)
- **Notify When Run:** OFF (a wake-up notification defeats the purpose of a background
  trigger)

## 4. Expected response

On success the route returns:

```
202 {"accepted": true}
```

That means the compose has been **enqueued**, not sent — the actual briefing arrives
a few seconds later via the normal Telegram/Hub delivery path once
`/internal/process-occasion` finishes composing. A 202 with no message a minute later
is a compose-side issue (check Cloud Run logs), not a Shortcut issue.

## 5. iCloud Shortcut share link

Once the automation is built and tested, export it via Share → Copy iCloud Link and
paste the link here:

- Sleep-Focus-OFF morning trigger: `<TODO operator: paste iCloud share link here after first-build>`

This lets the automation be rebuilt on a new device in under a minute instead of
re-walking this runbook.

## 6. Security Considerations

- **Authorization header ONLY — NEVER in URL query.** Placing the token in the URL
  would leak it via Cloud Run access logs the moment a request is made. Keep it in
  the `Authorization: Bearer …` header, where Cloud Run access logs redact it.
- **TLS-only.** Cloud Run enforces HTTPS by default; the iOS system root CA set is
  sufficient — no certificate pinning available or required in Shortcuts.
- **Token entropy ≥ 32 bytes.** The mint command in `docs/DEPLOYMENT.md`'s
  `MORNING_TRIGGER_TOKEN Secret` section uses
  `python -c "import secrets; print(secrets.token_urlsafe(32))"` — do not shorten this.
- **Distinct secret from `NIGHTLY_TRIGGER_TOKEN` (D-13).** A leaked morning-trigger
  token cannot be used to fire the nightly review, and vice versa — no fallback
  auth path exists between the two routes (`interfaces/web_server.py::
  _verify_morning_trigger_request` checks only `MORNING_TRIGGER_TOKEN`).
- **Secret name is `klaus-morning-trigger-token` (lowercase).** The CLAUDE.md
  GCP/Pinecone resource-naming invariant requires lowercase `klaus-` for all resource
  names. Uppercase `K` causes silent 404s when Cloud Run binds the secret.
- **Kill-switch:** if the token leaks, run
  `gcloud secrets versions disable klaus-morning-trigger-token --version=<n>` and the
  next automation run gets 403. No redeploy required (the binding is by secret name
  with `:latest`, so disabling the version is instant).
- **No replay protection** (acceptable risk): `run_morning_briefing_triggered`'s
  dedup-via-state-doc no-ops a snooze/second alarm/Focus toggled off-on-off (D-12), so
  a replayed trigger produces no duplicate briefing.

## 7. Testing

From the operator Mac, before building the Shortcut, smoke the route directly (see
`docs/DEPLOYMENT.md` § 22 for the full curl sequence):

```bash
curl -i -X POST https://<CLOUD_RUN_URL>/trigger/morning
# expect 401 (no Authorization header)

curl -i -X POST -H "Authorization: Bearer wrong" https://<CLOUD_RUN_URL>/trigger/morning
# expect 403 (token mismatch)

curl -i -X POST -H "Authorization: Bearer <MORNING_TRIGGER_TOKEN>" \
  https://<CLOUD_RUN_URL>/trigger/morning
# expect 202 {"accepted": true} — and a real briefing a few seconds later
```

Run the third call at a time you don't mind receiving a message — it sends a real
briefing, exactly as if you had woken up. Confirm you receive exactly one.

Then, once the Shortcut is built: turn Sleep Focus on and back off manually (or wait
for the next real wake-up) and confirm the briefing arrives without touching the phone.

## 8. Troubleshooting

| Response / symptom | Likely cause | Fix |
|---|---|---|
| 401 | Missing / malformed `Authorization` header | Re-check the Shortcut's "Get Contents of URL" → Headers entry. Should read `Authorization: Bearer <token>` (single space after Bearer, no quotes around the token). |
| 403 | Token mismatch — Shortcut header drifted from Secret Manager | Rotate per `docs/DEPLOYMENT.md`'s `MORNING_TRIGGER_TOKEN Secret` section (add a new version, update Cloud Run with `:latest`); re-paste the new token into the Shortcut's Authorization header. |
| 500 "Server misconfigured" | `MORNING_TRIGGER_TOKEN` env unset in Cloud Run | The secret binding was lost on a Cloud Run revision push, or the secret does not exist yet. Verify with `gcloud run services describe klaus-agent --region=me-west1 --format="value(spec.template.spec.containers[0].env)"`; rebind per `docs/DEPLOYMENT.md`'s `MORNING_TRIGGER_TOKEN Secret` section. |
| 503 | Cloud Tasks dispatch unavailable | Transient — retry. If it persists, check `CLOUD_TASKS_QUEUE`/`CLOUD_TASKS_LOCATION` are set and the queue exists (`gcloud tasks queues list`). |
| 202 but no briefing arrives | The compose itself failed on `/internal/process-occasion` | Check Cloud Run logs for the `occasion-morning` cron-run record; `core/heartbeat.py::check_occasion_health` will also surface staleness. |
| Two briefings on the same morning | `klaus-morning-briefing` (legacy cron) and the new Shortcut both fired | Expected and safe during the D-31 dark-ship / observation window — `run_morning_briefing_triggered`'s dedup-via-state-doc should prevent an actual duplicate *send*. If you see two full briefings, stop and report before plan 33-13 retires the legacy cron. |
| No notification, no briefing, no log entry | iOS automation didn't fire | Open iOS Shortcuts → Automation → confirm "Run Immediately" is ON. Re-toggle if needed (iOS occasionally drops the flag on app updates). Also verify the trigger is "Is Turned Off" (not "Is Turned On" — that would fire the nightly review's trigger condition instead). |

Cross-reference: `docs/DEPLOYMENT.md` § 22 (Push-driven endpoints) and the
`MORNING_TRIGGER_TOKEN Secret` subsection for the full secret create/rotate/kill-switch
runbook.
