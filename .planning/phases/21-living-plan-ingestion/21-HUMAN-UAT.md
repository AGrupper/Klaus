---
status: complete
phase: 21-living-plan-ingestion
source: [21-VERIFICATION.md]
started: 2026-06-04T00:00:00Z
updated: 2026-06-04T00:00:00Z
---

## Current Test

[all items passed — no tests pending]

## Tests

### 1. Seed the blueprint into production Firestore
expected: Running `./.venv/bin/python scripts/ingest_blueprint.py` (optionally `--dry-run` first) against production credentials writes the v4.0 structured profile to `users/amit`. Afterward `UserProfileStore.load()` returns non-empty `dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, and `plan_start_date="2026-06-21"`.
result: passed — ingested 2026-06-04; read-back confirmed all 6 structured fields non-empty, plan_start_date=2026-06-21, schema_version=2, dated_goals metrics dict intact

### 2. Conversational update round-trip on the next turn
expected: In a live Telegram session, saying "update my bench goal to 105kg" or "change Thursday to rest day" causes Klaus to call `update_plan`, merge the change (merge=True), and reason against the updated plan on the very next turn — no nagging about individual missed sessions.
result: passed — 2026-06-04 live Telegram. "update my bench press goal to 105kg" → Klaus set Oct 31 bench target to 105kg and read back the full merged October Peak (Bench 105kg / Squat 120kg / Half Marathon 1:25:00). merge=True preserved squat + HM; dict-shaped metrics rendered with values (CR-21-01 fix confirmed live).

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
