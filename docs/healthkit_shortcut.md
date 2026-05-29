# iOS Shortcut: HealthKit Nutrition Bridge — Operator Runbook

**Phase 19.1** — closes Phase 19 SC #2 on iOS by bridging Apple HealthKit
dietary samples (where Lifesum writes on iPhone) into Klaus's MealStore.

This runbook is the operator-facing build guide for the two iOS Personal
Automations that POST Lifesum-written HealthKit dietary samples to Klaus's
deployed `/cron/healthkit-sync` webhook. Code, schema, observability, and
secret-rotation runbook all shipped in Plans 01–04; this runbook is the last
step before live UAT.

## 1. Overview

Lifesum on iOS writes meal entries to Apple HealthKit (not Google Fit — the
Google Fit consumer iOS app was deprecated in late 2024). This runbook walks
through building two iOS Personal Automations that POST those samples to
Klaus's deployed `/cron/healthkit-sync` webhook.

Bridge architecture: see `docs/SELF.md` § Push endpoints.
Secret rotation: see `docs/DEPLOYMENT.md` § 23.

**Wave 0 reminders (informs the build steps below):**

- Lifesum writes **individual HKQuantitySample records** (Energy / Protein /
  Carbs / Fat / Fiber) — NOT a single Food correlation. Each macro is its own
  sample. The Shortcut must run **one `Find Health Samples` per macro type**
  and then **join the parallel streams by start_date** inside a
  `Repeat with Each` loop to build per-meal records.
- `Get Details of Health Sample → Source` returns the literal source-app
  name string (e.g. `"Lifesum"`), **not** an HKObject UUID. Klaus's
  normalizer (Plan 02) handles this — when `uuid` is `"Lifesum"` /
  `"Apple Health"` / `"Health"` / empty, it falls back to a deterministic
  `healthkit:{start_date_iso}:{calories_int}` source_id. So you can pass
  Source as the `uuid` field and dedup still works.
- `Find Health Samples` **Limit must be left OFF** when iterating. Wave 0
  capture with `Limit: 1` hit a phantom zero-quantity sample at run time.
- Date format from iOS comes through with a `GMT+3` suffix (non-strict
  ISO-8601). Plan 02's Pydantic `@field_validator("start_date", mode="before")`
  rewrites `GMT+N` → `+0N:00` before parsing, so this is OK.

## 2. Required HealthKit permissions

When you first build the Shortcut, iOS will prompt for HealthKit read access.
Grant READ access for:

- Dietary Energy
- Dietary Protein
- Dietary Carbohydrates
- Dietary Fat Total
- (Optional) Dietary Fiber
- (Optional) Dietary Sugar

No WRITE access is needed. No HRV / sleep / workout permissions are needed
in this phase (those stay on Garmin per Phase 19 contract).

## 3. Build: Lifesum-close 2h automation

iOS Shortcuts → Automation → Personal Automation → "+" → App → Lifesum → "Is Closed" → Next.

Toggle **Run Without Asking** on (default since iOS 15.4 for app triggers).
Toggle **Notify When Run** OFF (silent operation; failures still surface via
the explicit Show Notification step #9 below).

Actions, in order:

1. **Find Health Samples** — Type: Dietary Energy / Date: "Started in the last 2 Hours" / Sort: Start Date / Limit: **OFF** → save to Variable `Energy`.
   *(If your iOS version only exposes "Last N Days", use "Today" or "Last 1 Day" and rely on Klaus's idempotent upsert on `source_id` to dedup older repeats.)*
2. **Find Health Samples** — Type: Dietary Protein / same date filter / Limit OFF → `Protein`.
3. **Find Health Samples** — Type: Dietary Carbohydrates / same date filter / Limit OFF → `Carbs`.
4. **Find Health Samples** — Type: Dietary Fat Total / same date filter / Limit OFF → `Fat`.
5. **Set Variable** `samples` to a new (empty) List action.
6. **Repeat with Each** — iterate over `Energy` (the canonical anchor list — every Lifesum meal has an Energy sample). For each item:
   - Use `Get Details of Health Sample` to extract the current Energy sample's `Start Date` → variable `EnergyStart`.
   - Use `Get Details of Health Sample` to extract `Source` → variable `SourceName` (will be the literal string `"Lifesum"`; that's OK).
   - Use `Get Details of Health Sample` to extract `Quantity` → variable `EnergyKcal`.
   - (Join step) Use `Find Health Samples` filtered by Start Date == `EnergyStart` to pull the matching Protein / Carbs / Fat sample (one per macro). Get Details → Quantity for each → variables `ProteinG`, `CarbsG`, `FatG`. If no match (rare; macro stream out of sync), default that macro to 0 via an If action.
   - Build a **Dictionary** with keys:
     - `uuid` → `SourceName` (the literal `"Lifesum"` string is fine — normalizer falls back to a deterministic source_id).
     - `start_date` → `EnergyStart` (ISO-ish format; `GMT+N` suffix is handled server-side).
     - `samples_by_type` → a sub-Dictionary with keys `DietaryEnergyConsumed_kcal` (= `EnergyKcal`), `DietaryProtein_g` (= `ProteinG`), `DietaryCarbohydrates_g` (= `CarbsG`), `DietaryFatTotal_g` (= `FatG`).
     - `metadata` → an empty Dictionary (Lifesum doesn't write `HKMetadataKeyMealTime`; Klaus's hour-bucket fallback covers this).
     - (Optional) `food_item` → human-readable label if you have one; safe to omit.
   - **Add to List** `samples` ← the Dictionary you just built.
7. **End Repeat**.
8. **Dictionary** — top-level wrapper `{"samples": <samples variable>}`.
9. **Get Contents of URL** — Method: POST, URL: `https://klaus-agent-XXXX.run.app/cron/healthkit-sync` (your operator Cloud Run URL, lowercase per CLAUDE.md invariant), Headers: `Authorization: Bearer <paste-token-here>`, `Content-Type: application/json`, Request Body: the wrapper Dictionary from step 8.
10. **If** (Status Code of response) ≠ 200 → **Show Notification** "Klaus meal push failed (status: <code>)" — D-05 notify-on-fail contract.

## 4. Build: 23:55 24h catch-up automation

iOS Shortcuts → Automation → Personal Automation → "+" → Time of Day → 23:55 → Daily → Next.

Toggle **Run Without Asking** on. Toggle **Notify When Run** OFF.

Same action chain as the Lifesum-close automation (steps 1–10 from §3), but
change every `Find Health Samples` date filter from "Started in the last
2 Hours" to **"Started in the last 24 Hours"**. This rescues any meal that
the 2h close-trigger missed (phone locked, app crashed, Shortcut suspended,
push failed mid-flight, etc.).

The catch-up is fully idempotent on Klaus's side — re-pushed samples land on
the same Firestore doc because MealStore.upsert is keyed on `source_id`
(`healthkit:{uuid}` or, for Lifesum's `"Lifesum"` source-name case,
`healthkit:{start_date_iso}:{calories_int}`). No duplicates, no quota burn
from re-pushing.

## 5. iCloud Shortcut share link

Once both automations are built and tested on the iPhone, export the
Shortcuts via Share → Copy iCloud Link and paste the links here:

- Lifesum-close 2h: `<TODO operator: paste iCloud share link here after first-build>`
- 23:55 24h catch-up: `<TODO operator: paste iCloud share link here after first-build>`

These let the bridge be rebuilt on a new device (or shared with future Klaus
maintainers) in ~5 minutes instead of re-walking this entire runbook.

Status: the placeholder is acceptable for Phase 19.1 closure (per threat
register T-19.1-05-06 — accept). The operator can fill these in a follow-up
commit at any time without blocking phase close.

## 6. Security Considerations

- **Authorization header ONLY — NEVER in URL query.** Placing the token in
  the URL query string would leak it via Cloud Run access logs (and any
  intermediate proxy / Cloud Armor log) the moment a request is made. Keep
  it in the `Authorization: Bearer …` header, where Cloud Run access logs
  redact it.
- **TLS-only.** iOS `Get Contents of URL` does not support certificate
  pinning. Cloud Run enforces HTTPS by default and the system root CA set
  on iOS is sufficient for the threat model documented in
  `.planning/phases/19.1-healthkit-nutrition-bridge/19.1-RESEARCH.md`.
- **Token entropy ≥ 32 bytes.** The secret-mint command in `docs/DEPLOYMENT.md` § 23
  uses `python -c "import secrets; print(secrets.token_urlsafe(32))"` —
  do not shorten this. Brute-forcing a 32-byte urlsafe token over Cloud
  Run's scale-up rate is computationally infeasible.
- **Secret name is `klaus-healthkit-webhook-token` (lowercase).** The
  CLAUDE.md GCP/Pinecone resource-naming invariant requires lowercase
  `klaus-` for all resource names. Uppercase `K` causes silent 404s when
  Cloud Run binds the secret.
- **Kill-switch:** if the token leaks, run
  `gcloud secrets versions disable klaus-healthkit-webhook-token --version=<n>`
  and the next push will get 403. No redeploy required (the binding is by
  secret name with `:latest`, so disabling the version is instant).
- **No replay protection** (acceptable risk): MealStore.upsert is idempotent
  on `source_id`, so replayed payloads produce no state delta and no extra
  Firestore writes worth alerting on.
- **Token leakage via shell history** (operator-side): the smoke CLI's
  documented usage exports `HEALTHKIT_WEBHOOK_TOKEN=<value>` which lands
  in shell history. Acceptable for one-shot operator use; run
  `unset HISTFILE` first for paranoid runs.

## 7. Testing

From the operator Mac (after deploying the secret per `docs/DEPLOYMENT.md` § 23
and redeploying Cloud Run):

```bash
export HEALTHKIT_WEBHOOK_TOKEN=<the-token>
export GCP_PROJECT_ID=klaus-agent
python scripts/test_healthkit_push.py \
    --url https://klaus-agent-XXXX.run.app/cron/healthkit-sync \
    --count 2
```

Expected output:

```
POST … → 200 {'upserted': 2}
OK: found 2 Firestore docs with prefix healthkit:test-<ts_marker>-
Delete 2 test docs? [y/N]:
```

Answer `y` at the cleanup prompt so the synthetic test rows don't pollute
production MealStore (T-19.1-05-04).

Then on the iPhone, the live UAT loop:

1. Log a real test meal in Lifesum (any food, any size — a piece of fruit is fine).
2. Close Lifesum (swipe up + flick away, or just background it for ≥3 seconds).
3. Wait ≤10 seconds. If the automation has notify-on-fail enabled (step 10 of §3) and the push failed, you'll see a lock-screen notification "Klaus meal push failed".
4. Verify the Firestore doc landed (from operator Mac):
   ```bash
   python -c "from memory.firestore_db import MealStore; from datetime import date; import os; [print(m.get('source_id'), m.get('calories'), m.get('food_item')) for m in MealStore(project_id=os.environ.get('GCP_PROJECT_ID','klaus-agent'), database=os.environ.get('FIRESTORE_DATABASE','klaus-firestore')).get_day(date.today().isoformat()) if str(m.get('source_id','')).startswith('healthkit:') and not str(m.get('source_id','')).startswith('healthkit:test-')]"
   ```
   Expected: at least one row with `source_id` starting `healthkit:` (NOT `healthkit:test-`) matching the meal you just logged.

## 8. Troubleshooting

| Response | Likely cause | Fix |
|----------|--------------|-----|
| 401 | Missing / malformed `Authorization` header | Re-check the iOS Shortcut's "Get Contents of URL" → Headers entry. Should read `Authorization: Bearer <token>` (single space after Bearer, no quotes around the token). |
| 403 | Token mismatch — Shortcut header drifted from Secret Manager | Rotate per `docs/DEPLOYMENT.md` § 23 step 3 (add a new version, update Cloud Run with `:latest`); re-paste the new token into the Shortcut's Authorization header. |
| 422 | Payload shape doesn't match `HealthKitPayload` (Plan 02) | Compare the Shortcut's emitted JSON body against `tests/fixtures/healthkit_payload_sample.json`. If the wire format drifted (e.g., iOS update changed `Get Details` keys), recapture the fixture via webhook.site, refresh `mcp_tools/healthkit_tool.py` if needed, and bump the fixture-locked schema test. |
| 500 "Server misconfigured" | `HEALTHKIT_WEBHOOK_TOKEN` env unset in Cloud Run | The secret binding was lost on a Cloud Run revision push. Verify with `gcloud run services describe klaus-agent --region=me-west1 --format="value(spec.template.spec.containers[0].env)"`; rebind per `docs/DEPLOYMENT.md` § 23 step 2. |
| No notification, no Firestore doc | iOS automation didn't fire | Open iOS Shortcuts → Automation → check that "Run Without Asking" is ON. Re-toggle if needed (iOS occasionally drops the flag on app updates). Also verify the trigger is "Is Closed" (not "Is Opened" — that fires hourly and creates noise). |
| All macros zero / Energy quantity = 0 | `Find Health Samples` `Limit` is set to 1 | Wave 0 finding: `Limit: 1` hits a phantom zero-quantity sample on some iOS versions. Set Limit to OFF (no value) on every `Find Health Samples` step. |
| Repeated 200s but only 1 Firestore doc instead of N | Shortcut emitted newline-concatenated text instead of a proper JSON array | The Shortcut is using a single Set-Variable + Text template instead of `Repeat with Each` + Add to List. Rebuild step 6 of §3 — the loop is the only way to emit a true `[{...}, {...}]` array. |
| Per-macro quantities don't align (e.g. 4 Energy samples but only 3 Carbs) | One macro stream is out of sync with the others (Lifesum drops a write occasionally) | Add an If action inside the Repeat-with-Each: if the per-meal `Find Health Samples` filter for a macro returns 0 results, default that macro to 0. The 23:55 catch-up will pick up the late-arriving sample. |

Firestore quick-check (from operator Mac):

```bash
python -c "from memory.firestore_db import MealStore; from datetime import date; import os; print(MealStore(project_id=os.environ.get('GCP_PROJECT_ID','klaus-agent'), database=os.environ.get('FIRESTORE_DATABASE','klaus-firestore')).get_day(date.today().isoformat()))"
```

Heartbeat alarm: if `/cron/healthkit-sync` has not landed any successful
write for >48 hours, `core/heartbeat.py` will surface a stale-cron alert in
the next hourly run (Plan 04's `_CRON_MAX_STALENESS_HOURS["healthkit-sync"] = 48`).
