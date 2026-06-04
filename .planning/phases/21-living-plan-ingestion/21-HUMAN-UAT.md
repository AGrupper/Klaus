---
status: partial
phase: 21-living-plan-ingestion
source: [21-VERIFICATION.md]
started: 2026-06-04T00:00:00Z
updated: 2026-06-04T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Seed the blueprint into production Firestore
expected: Running `./.venv/bin/python scripts/ingest_blueprint.py` (optionally `--dry-run` first) against production credentials writes the v4.0 structured profile to `users/amit`. Afterward `UserProfileStore.load()` returns non-empty `dated_goals`, `weekly_split`, `nutrition_targets`, `supplement_schedule`, `fueling_timeline`, and `plan_start_date="2026-06-21"`.
result: passed — ingested 2026-06-04; read-back confirmed all 6 structured fields non-empty, plan_start_date=2026-06-21, schema_version=2, dated_goals metrics dict intact

### 2. Conversational update round-trip on the next turn
expected: In a live Telegram session, saying "update my bench goal to 105kg" or "change Thursday to rest day" causes Klaus to call `update_plan`, merge the change (merge=True), and reason against the updated plan on the very next turn — no nagging about individual missed sessions.
result: [pending]

## Summary

total: 2
passed: 1
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
