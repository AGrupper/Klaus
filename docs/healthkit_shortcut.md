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

**Wire format — Path B (live UAT revision, 2026-05-30):**

The wire format is a FLAT list of per-quantity samples. One row per
HKQuantitySample. The server groups by `(start_date, food_item)` and
sums same-quantity-type duplicates to reconstruct per-meal records.

```json
{
  "samples": [
    {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00GMT+3", "quantity_type": "DietaryEnergyConsumed_kcal", "value": 324.0, "food_item": null},
    {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00GMT+3", "quantity_type": "DietaryProtein_g", "value": 5.4, "food_item": null},
    {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00GMT+3", "quantity_type": "DietaryCarbohydrates_g", "value": 43.2, "food_item": null},
    {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00GMT+3", "quantity_type": "DietaryFatTotal_g", "value": 14.4, "food_item": null},
    {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00GMT+3", "quantity_type": "DietaryFiber_g", "value": 2.4, "food_item": null}
  ]
}
```

Required keys per row: `uuid`, `start_date`, `quantity_type`, `value`.
Optional: `metadata` (dict), `food_item` (string or null).

Why flat (and not bundled samples_by_type)? Lifesum writes ONE
HKQuantitySample per macro per food item, and HKCorrelation parent IDs
are not exposed through the iOS Shortcuts `Find Health Samples` action.
The original bundled contract therefore could not be populated correctly
from a Shortcut; live UAT confirmed this on 2026-05-30. Server-side
aggregation is the only path that works end-to-end.

**Field / behaviour reminders (carry over from Wave 0):**

- `Get Details of Health Sample → Source` returns the literal source-app
  name string (e.g. `"Lifesum"`), **not** an HKObject UUID. Klaus's
  normalizer handles this — when `uuid` is `"Lifesum"` / `"Apple Health"` /
  `"Health"` / empty, it falls back to a deterministic
  `healthkit:{start_date_iso}:{calories_int}` source_id. So passing Source
  as the `uuid` field is fine and dedup still works.
- `Find Health Samples` **Limit must be left OFF** when iterating. Wave 0
  capture with `Limit: 1` hit a phantom zero-quantity sample at run time.
- Date format from iOS comes through with a `GMT+3` suffix (non-strict
  ISO-8601). The Pydantic `@field_validator("start_date", mode="before")`
  rewrites `GMT+N` → `+0N:00` before parsing, so this is OK.
- Same-`start_date` + same-`food_item` + same-`quantity_type` rows are
  summed by the server. A meal with 3 chicken pieces all tagged the same
  way will see 3 protein samples sum into one per-meal total — desired
  behaviour.

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

## 3. Build: Lifesum-close 2h automation (Path B placeholder)

> **PATH B REDESIGN PENDING** — the step-by-step build below is the OLD
> bundled-samples_by_type design (which proved unbuildable in iOS Shortcuts:
> there is no action to bundle parallel macro streams back into a single
> per-meal dict without HKCorrelation parent IDs, and those IDs are not
> exposed). A simpler Path-B Shortcut design follows naturally from the
> new flat wire format documented in §1 — it is a "dumb flat pipe":
>
> **High-level Path-B Shortcut design (operator to flesh out at next iteration):**
>
> 1. Five separate `Find Health Samples` actions, one per macro type:
>    Dietary Energy / Protein / Carbohydrates / Fat Total / (optional) Fiber.
>    Date filter: "Started in the last 2 Hours". Limit: OFF.
> 2. For each result list, a `Repeat with Each` loop that emits one flat
>    sample dictionary per iteration:
>    `{uuid, start_date, quantity_type, value}` — with `quantity_type`
>    hard-coded for that branch (e.g. `"DietaryEnergyConsumed_kcal"`).
> 3. Concatenate all five lists into one top-level `samples` list.
> 4. POST `{"samples": <list>}` to `/cron/healthkit-sync` with the standard
>    `Authorization: Bearer <token>` header.
> 5. The server's `_aggregate_quantity_samples` groups by
>    `(start_date, food_item)` and reconstructs per-meal records — no
>    client-side bundling required.
>
> No `Get Details → Source` UUID acrobatics, no parallel-stream joining,
> no per-meal Dictionary assembly. The dumb flat pipe is what iOS
> Shortcuts can actually produce; the server does the work.

The historical (deprecated) bundled-samples build steps used to live here.
They are intentionally removed — do NOT attempt to follow them with the
Path-B server. Operator will rebuild the Shortcut against the §1 contract
in a follow-up commit; this runbook section is the placeholder pointer.

## 4. Build: 23:55 24h catch-up automation

iOS Shortcuts → Automation → Personal Automation → "+" → Time of Day → 23:55 → Daily → Next.

Toggle **Run Without Asking** on. Toggle **Notify When Run** OFF.

Same action chain as the Lifesum-close automation (Path-B placeholder
in §3), but change every `Find Health Samples` date filter from
"Started in the last 2 Hours" to **"Started in the last 24 Hours"**.
This rescues any meal that the 2h close-trigger missed (phone locked,
app crashed, Shortcut suspended, push failed mid-flight, etc.).

The catch-up is fully idempotent on Klaus's side — re-pushed samples land on
the same Firestore doc because MealStore.upsert is keyed on `source_id`
(`healthkit:{uuid}` or, for Lifesum's `"Lifesum"` source-name case,
`healthkit:{start_date_iso}:{food_item}:{calories_int}`). No duplicates, no quota burn
from re-pushing.

## 4b. Build: 02:00 full-day reconcile automation

iOS Shortcuts → Automation → Personal Automation → "+" → Time of Day → 02:00 → Daily → Next.

Toggle **Run Without Asking** on. Toggle **Notify When Run** OFF.

**Identical action chain to the 23:55 catch-up (§4)** — five `Find Health
Samples` actions (one per macro: Energy / Protein / Carbohydrates / Fat
Total / Fiber), same flat `{"samples": [...]}` wire format, same
`Authorization: Bearer <token>` header — with two differences:

1. Date filter on every `Find Health Samples`: **"Started in the last
   26 hours"** (not 24 — the 2h overlap guarantees the full previous
   calendar day is covered even if the automation fires late).
2. POST to **`/cron/healthkit-reconcile`** (not `/cron/healthkit-sync`).

Why a separate endpoint: the reconcile route treats the payload as
**authoritative for yesterday** (Asia/Jerusalem). It upserts everything
incoming and deletes any stale HealthKit-sourced Firestore doc in
yesterday's date bucket that the payload no longer contains — fixing both
*missing* meals (an intraday push that never fired) and *stale/duplicate*
meals (an entry edited or deleted in Lifesum after it synced). The morning
briefing's meal audit then always reads a complete, corrected previous day.

Safety properties (server-side, nothing to configure in the Shortcut):

- An **empty payload deletes nothing** — a failed/empty query can never
  wipe a day.
- Only docs with `source == "healthkit"` are ever deleted; Google-Fit or
  other-source rows are untouched.
- Meals in the 26h window that fall **outside yesterday** (e.g. today
  00:00–02:00) get plain idempotent upserts — deletes never happen outside
  the target date.
- Optional `?date=YYYY-MM-DD` query param overrides the target date for
  manual backfills (operator use only; the automation should not set it).

Once this automation is live, the 23:55 24h catch-up (§4) becomes
**optional** — the 2h close-trigger (§3) plus the 02:00 reconcile cover
everything it did. Recommended: keep the 2h close-trigger (it feeds the
autonomous tick's same-day meal awareness) and retire the 23:55 one.

Heartbeat: a missed night surfaces via
`_CRON_MAX_STALENESS_HOURS["healthkit-reconcile"] = 30` in
`core/heartbeat.py` — the next morning's hourly heartbeat flags it.

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
| 422 | Payload shape doesn't match `HealthKitPayload` (flat Path-B contract) | Each row must carry `uuid`, `start_date`, `quantity_type`, `value`. Compare against `tests/fixtures/healthkit_payload_sample.json`. If the wire format drifted (e.g., iOS update changed `Get Details` keys), recapture the fixture via webhook.site, refresh `mcp_tools/healthkit_tool.py` if needed, and bump the fixture-locked schema test. |
| 500 "Server misconfigured" | `HEALTHKIT_WEBHOOK_TOKEN` env unset in Cloud Run | The secret binding was lost on a Cloud Run revision push. Verify with `gcloud run services describe klaus-agent --region=me-west1 --format="value(spec.template.spec.containers[0].env)"`; rebind per `docs/DEPLOYMENT.md` § 23 step 2. |
| No notification, no Firestore doc | iOS automation didn't fire | Open iOS Shortcuts → Automation → check that "Run Without Asking" is ON. Re-toggle if needed (iOS occasionally drops the flag on app updates). Also verify the trigger is "Is Closed" (not "Is Opened" — that fires hourly and creates noise). |
| All macros zero / Energy quantity = 0 | `Find Health Samples` `Limit` is set to 1 | Wave 0 finding: `Limit: 1` hits a phantom zero-quantity sample on some iOS versions. Set Limit to OFF (no value) on every `Find Health Samples` step. |
| Repeated 200s but only 1 Firestore doc instead of N | Shortcut emitted newline-concatenated text instead of a proper JSON array | The Shortcut is using a single Set-Variable + Text template instead of `Repeat with Each` + Add to List. Rebuild the per-macro emit loop — the loop is the only way to emit a true `[{...}, {...}]` array. |
| All meals collapsing to one Firestore doc | All flat samples share the same `start_date` and `food_item` and are being summed into a single per-meal group | Path B is doing exactly what it should — same `(start_date, food_item)` IS one meal. If you want distinct meals, ensure either `start_date` or `food_item` differs per meal in the Shortcut's emit loop. |
| Per-macro quantities don't align (e.g. 4 Energy samples but only 3 Carbs) | One macro stream is out of sync with the others (Lifesum drops a write occasionally) | In Path B this is automatic — each macro is its own row, and missing rows just leave that macro at 0 in the aggregated meal. The 23:55 catch-up will re-push the late-arriving sample on the next day's 24h window. |

Firestore quick-check (from operator Mac):

```bash
python -c "from memory.firestore_db import MealStore; from datetime import date; import os; print(MealStore(project_id=os.environ.get('GCP_PROJECT_ID','klaus-agent'), database=os.environ.get('FIRESTORE_DATABASE','klaus-firestore')).get_day(date.today().isoformat()))"
```

Heartbeat alarm: if `/cron/healthkit-sync` has not landed any successful
write for >48 hours, `core/heartbeat.py` will surface a stale-cron alert in
the next hourly run (Plan 04's `_CRON_MAX_STALENESS_HOURS["healthkit-sync"] = 48`).
