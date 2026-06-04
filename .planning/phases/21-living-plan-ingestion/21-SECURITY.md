---
phase: 21
slug: living-plan-ingestion
status: secured
threats_open: 0
threats_total: 11
threats_closed: 11
asvs_level: 1
created: 2026-06-04
---

# SECURITY.md — Phase 21: Living Plan Ingestion

**Audit date:** 2026-06-04
**Phase:** 21 — Living Plan Ingestion (Plans 01–04)
**ASVS Level:** 1
**Auditor model:** claude-sonnet-4-6
**block_on:** high
**Result:** SECURED — 11/11 threats closed

---

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence (file:line) |
|-----------|----------|-------------|--------|----------------------|
| T-21-01 | Tampering | accept | CLOSED | `memory/firestore_db.py:188–202` — `bootstrap_if_empty` reads the snapshot first; `if snap.exists: return` (line 190) is the idempotent gate. The write at line 192 only executes when the document is absent. No overwrite of populated data is possible. Risk acceptance is reasonable: single-user document, no external write path in this plan. |
| T-21-02 | DoS | accept | CLOSED | `memory/firestore_db.py:182–202` — entire `bootstrap_if_empty` body is wrapped in `try/except Exception` (line 188/199–202); the except branch logs a warning and returns silently, never re-raises. Startup cannot die from this path. Risk acceptance is reasonable: degraded start (empty profile) is preferable to a crash loop. |
| T-21-03 | Tampering | accept | CLOSED | `core/tools.py:1333` — `_handle_update_training_profile` calls `UserProfileStore.update(patch)` with `merge=True` and no allow-list. Risk acceptance is reasonable: authenticated single-user Telegram brain; `merge=True` cannot delete keys; the only data at stake is Amit's own training targets (low-value target, no PII beyond personal fitness preferences). |
| T-21-04 | Info Disclosure / DoS | mitigate | CLOSED | `core/tools.py:1325,1330` — `_handle_get_training_profile` imports `_jsonsafe_doc` from `memory.firestore_db` and calls `json.dumps(_jsonsafe_doc(store.load()))`. `_jsonsafe_value` (memory/firestore_db.py:745–761) recurses into nested dicts and lists, calling `.isoformat()` on any datetime-like value. Depth coverage confirmed: handles `DatetimeWithNanoseconds` nested inside `weekly_split` or `fueling_timeline`. Test coverage confirmed at `tests/test_tools.py` (`test_get_training_profile_json_safe_with_datetime`). |
| T-21-05 | Tampering | mitigate | CLOSED | Two-layer guard in place. (1) Scaffold layer: `memory/firestore_db.py:141` — `weekly_split: {}` default is an empty dict; the scaffold comment at line 141–142 explicitly states "NO attendance/done/completed booleans". No boolean source field exists for the brain to emit. (2) Prompt layer: `prompts/smart_agent.md:92–96` — "The `weekly_split` is a template, not a contract — **never nag about a single missed session**". Renderer at `core/main.py:329–351` reads only `label`, `modality`, `priority` via `.get()` — no boolean field path exists. |
| T-21-06 | Tampering / data loss | mitigate | CLOSED | `scripts/ingest_blueprint.py:317–325` — without `--force`, `existing.get("plan_start_date")` is checked; if truthy, script logs a warning and returns without writing. `UserProfileStore.update` uses `merge=True` (`memory/firestore_db.py:174`), so re-ingest with `--force` cannot delete keys omitted from the payload. |
| T-21-07 | Tampering | mitigate | CLOSED | `scripts/ingest_blueprint.py:302–305` — `if args.dry_run: print(...); return` executes before any `UserProfileStore` import or Firestore client construction. The `from memory.firestore_db import UserProfileStore` is a lazy import inside the non-dry-run branch (line 309). No Firestore connection is made in dry-run mode, confirmed by the plan-03 SUMMARY note that `--dry-run` runs without GCP credentials. |
| T-21-08 | Tampering / drift | mitigate | CLOSED | `core/main.py:329–351` — renderer reads only `am.get("label")`, `am.get("modality")`, `am.get("priority")` and the same for pm. No boolean field is read or emitted. `tests/test_main_render_smart_system.py:391–402` — `test_weekly_split_no_attendance_words` feeds a full weekly_split and asserts that "attendance", "completed", and "missed" are absent from the rendered snippet. |
| T-21-09 | Info Disclosure | mitigate | CLOSED | `core/main.py:294–296` — `non_empty` dict comprehension excludes keys `"updated_at"`, `"bootstrapped_at"`, `"schema_version"` before any rendering. `tests/test_main_render_smart_system.py:436–444` — `test_meta_keys_excluded` asserts `schema_version`, `bootstrapped_at`, and `updated_at` do not appear in the rendered output. |
| T-21-10 | Repudiation / correctness | mitigate | CLOSED | `prompts/smart_agent.md:121` — "do NOT invent thresholds, targets, or scheduling buffers"; line 129 "Never make up a personalized rule"; line 112 "never invent them if the tool returns nothing". Tier A vs Tier B discipline at lines 105–112 is explicit. `update_plan` named as the update tool at line 116. All three grep gates from the plan's acceptance criteria are satisfied. |
| T-21-SC | Tampering (supply chain) | accept | CLOSED | `scripts/ingest_blueprint.py` imports: `argparse`, `json`, `logging`, `os`, `sys`, `pathlib.Path` (stdlib); `dotenv` (pre-existing project dep); `memory.firestore_db` (project module). No new packages introduced. `requirements.txt` unchanged. Risk acceptance is reasonable: no new pip surface. |

---

## Unregistered Threat Flags from SUMMARY.md

The SUMMARY files for Plans 01–04 each contain a "Threat Flags" or "Threat Surface Scan" section. No unregistered flags were raised by the executor in any of the four SUMMARY files. All threat surface entries in the SUMMARYs map directly to the registered threat IDs above.

One code comment in `core/main.py` references internal fix labels (`CR-21-01`, `WR-21-01`, `WR-21-03`) — these are implementation-quality notes, not new attack surface, and do not require threat registration.

---

## Accepted Risks Log

| Threat ID | Accepted Risk | Rationale |
|-----------|--------------|-----------|
| T-21-01 | Stale scaffold seeds if bootstrap races a concurrent ingest | Single-user, single-document, sequential startup. Race is not plausible. |
| T-21-02 | Startup proceeds with empty profile if Firestore is unreachable | Preferred to a crash loop; profile absence degrades gracefully to empty coaching snippet. |
| T-21-03 | Brain can write arbitrary top-level keys to users/amit without allow-list | Authenticated single-user; merge=True cannot delete; data is personal fitness targets only. |
| T-21-SC | No supply-chain isolation for script runtime | No new dependencies added; existing project dep surface unchanged. |
