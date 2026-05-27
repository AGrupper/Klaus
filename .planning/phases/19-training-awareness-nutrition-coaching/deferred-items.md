# Phase 19 — Deferred Items

Discovered during execution but out of scope for the originating plan. Track here so a future plan can pick them up.

## From Plan 19-01 (2026-05-27)

### Pre-existing: sleep parser type error
- **Symptom:** `parse_and_ingest_wellness` logs `Error parsing sleep file <name>.json: unsupported operand type(s) for /: 'str' and 'int'` for all 10 `*sleepData.json` files.
- **Root cause:** the parser does `wake_dt = datetime.fromtimestamp(end_time / 1000)` and `end_time = entry.get("sleepEndTimestampGMT") or sleep_time`. In modern exports `sleepEndTimestampGMT` (or its sibling `sleepStartTimestampGMT`) is an **ISO 8601 string** like `"2024-10-15T05:42:00.000"`, not a numeric epoch ms. Dividing a string by 1000 raises TypeError.
- **Effect:** sleep_score / sleep_duration / hrv_overnight remain NULL across the backfill. They are nullable columns so this doesn't break Phase 19 schema acceptance — but it does mean the analytics tier won't see sleep data until this is fixed.
- **In scope of:** future plan (likely Plan 19-02 alongside the live Garmin API ingestion which uses different timestamp formats anyway).
- **Fix sketch:** detect numeric vs string and parse via `datetime.fromisoformat` when it's a string.

### Pre-existing: bodyBatteryMax / trainingReadiness gaps in legacy UDS
- **Symptom:** modern Aggregator UDS entries don't carry flat `bodyBatteryMax` / `trainingReadiness` keys; we now extract body_battery_max from the nested `bodyBattery.bodyBatteryStatList` HIGHEST stat (Plan 19-01 added this). training_readiness has no direct equivalent in the Aggregator UDS file and will be NULL across the backfill.
- **Effect:** training_readiness is 100% NULL until live Garmin API ingestion (Plan 19-02) populates it from the Connect web API.
- **In scope of:** Plan 19-02.

### Activity averagePace
- **Symptom:** modern export carries `avgSpeed` (m/s) instead of `averagePace` (min/km). Current parser writes None for avg_pace.
- **Effect:** avg_pace 100% NULL across the activities backfill.
- **In scope of:** Plan 19-02 (or a small follow-up) — compute pace from `avgSpeed` when activityType ∈ {running, walking, hiking}.

### Activity HR/Power TimeInZone arrays
- The export carries detailed `hrTimeInZone_0..6` and `powerTimeInZone_0..5` arrays per activity. Currently dropped. May be valuable for ACWR + intensity-distribution analysis in later Phase 19 waves.
- **In scope of:** Plan 19-03+ (analytics-driven; only worth ingesting if a downstream metric needs them).
