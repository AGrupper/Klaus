# iOS Shortcut: Sleep-Focus-OFF Morning Trigger — Operator Runbook

**Phase 33 (D-08 / D-13 / D-31)** — closes OCC-02's live trigger by bridging Amit's
iPhone waking up (Sleep Focus turning off) into Klaus's morning briefing.

Intended as the mirror of the existing Sleep-Focus-**ON** → `/trigger/nightly`
automation (`docs/DEPLOYMENT.md` § 22), triggered on the opposite transition. Code,
auth, and the Cloud Tasks dispatch path all shipped in plan 33-10; this runbook is the
operator-facing build guide for the one hard human prerequisite (D-31) — Amit has to
build this automation himself, on his own phone, before `/trigger/morning` does
anything.

> **Correction (2026-07-31, from live setup).** The original version of this runbook
> instructed "Focus → Sleep → Is Turned Off" as though it were universally available.
> It is not: Apple excludes Sleep from the Focus automation trigger list, and the
> parity that shipped in an iOS 26 developer beta did not survive to public release —
> it landed in iOS 27. Confirmed absent on iOS 26.5.2. The step is impossible to follow
> as written on any current public iOS. §3.0 now selects the trigger by version; the
> working trigger today is **Alarm → Is Stopped**. The filename is kept for stable
> inbound links.

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

The goal is wake-up detection without new hardware or an app: the phone tells Klaus
that Amit is up, and the briefing composes from that moment. Which iOS event stands in
for "Amit is up" depends on the iOS version — see §3.0. Ideally it is Sleep Focus
turning **off** (covers alarm, manual toggle, and waking before an alarm); on older iOS
it is the alarm being dismissed, or the Sleep Schedule's Wake Up event.

Whatever the trigger, the route contract is identical — a bearer-authenticated POST
with an empty body, deduped server-side per day.

## 2. Required permissions

No HealthKit permissions are needed for this automation (contrast with
`docs/healthkit_shortcut.md`). The only iOS permission prompt is Shortcuts' own
request to run automations "without asking" — grant it, or every morning will show
a confirmation banner instead of running silently.

## 3. Build: the wake-up Personal Automation

### 3.0 Choosing the trigger (READ FIRST — the obvious one may not exist)

Sleep is not an ordinary Focus. Apple **excludes Sleep Focus from the
personal-automation Focus trigger list** — every other Focus (Personal, Work, Do Not
Disturb) can be automated on turn-on/turn-off, but Sleep cannot. Parity appeared in an
iOS 26 developer beta and was **not** kept for the public release; it landed in iOS 27.

**Verified on the actual device (2026-07-31): iOS 26.5.2 — Sleep is NOT in the Focus
automation list.** Do not trust blog posts claiming iOS 26 fixed this; they are
describing the beta. Check the phone before planning around it.

| Phone's iOS | Use this trigger | Notes |
|---|---|---|
| 27 or later | **Focus → Sleep → Is Turned Off** | Preferred. Fires on *any* end of Sleep Focus — alarm, manual toggle, or waking early. On iOS 27 the automation may need to be authored on iPadOS 27 / macOS Tahoe and then enabled on the phone. |
| 26 or earlier | **Alarm → Is Stopped** | The working choice today. Fires when the alarm is dismissed — the same moment Sleep Focus ends. First-class trigger, not schedule-derived. |
| Any | **Wake Up** | Last resort. Tied to the Sleep Schedule, so it may not fire on a night with no schedule set, a disabled alarm, or an early wake. |

**Why this matters more than it looks (D-09).** Plan 33-13 retires the
`morning-briefing-tick` cron, after which the morning briefing has **no backstop**. A
trigger that silently stops firing means no briefing that day and nothing to catch it
except the heartbeat's occasion-health check noticing after the fact. Prefer the
widest-firing trigger the phone supports; the ranking in the table above is by
coverage, not convenience.

**Redundancy is safe.** Two automations pointing at `/trigger/morning` cannot produce
two briefings — `run_morning_briefing_triggered` dedupes on the
`morning_briefings/{date}` state doc (`_TERMINAL_STATUSES`), so whichever request
arrives first wins and the second is a logged no-op. If the phone supports more than
one of the triggers above, building two is strictly safer than building one.

### 3.1 Build steps

Shortcuts → Automation tab → "+" (top right) → **Create Personal Automation** → pick
the trigger chosen in §3.0 → Next.

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
