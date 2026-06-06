---
phase: 23-block-benchmark-tracking
asvs_level: 1
audited: 2026-06-06
result: SECURED
threats_open: 0
threats_total: 15
---

# Phase 23 Security Audit

## Summary

All 15 threats in the Phase 23 register are CLOSED. The 11 `mitigate` threats each have
code-verified mitigations present at the cited files and lines. The 4 `accept` threats are
single-user / intended-UX disclosures with no external surface — documented as accepted LOW
risk below.

---

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-23-01 | Tampering | mitigate | CLOSED | `memory/firestore_db.py:1762-1764` — `if facet not in _BENCHMARK_FACETS: raise ValueError(...)`. Closed set defined at line 1511-1519. |
| T-23-02 | Tampering | mitigate | CLOSED | `memory/firestore_db.py:1558-1593` — `get_current()` resolves by `start_date <= today <= end_date` (line 1584); no `status` filter present. `get_week_num` is module-level pure fn (line 1488); the word `week_num` appears nowhere else in firestore_db.py — never stored. |
| T-23-03 | DoS | mitigate | CLOSED | `memory/firestore_db.py:1591-1593` — `get_current` catches all exceptions, returns `None`. Lines 1608-1610 — `get_all` catches all exceptions, returns `[]`. Lines 1813-1815, 1840-1844 — both BenchmarkStore read paths catch all exceptions and return `[]`. `scripts/seed_training_blocks.py:173-176` — `seed_if_absent` declines overwrite when `existing and not force`. |
| T-23-04 | Info Disclosure | accept | CLOSED | Single-user agent; no public surface. Firestore encryption at rest is GCP-managed. Documented LOW risk — see Accepted Risks below. |
| T-23-05 | Elevation of Privilege | mitigate | CLOSED | `core/tools.py:1044-1049` — all 6 new tools in the `WORKER_TOOL_SCHEMAS` exclusion set. Structural: the set comprehension at line 1019-1051 filters them out before any worker dispatch. |
| T-23-06 | Tampering | mitigate | CLOSED | `memory/firestore_db.py:1762-1764` — store raises `ValueError` on unknown facet. `core/tools.py:1775-1776` — `_handle_log_benchmark` catches `Exception` (superset of `ValueError`) and returns `{"error": str(exc)}`. |
| T-23-07 | DoS | mitigate | CLOSED | `core/tools.py:57` — `update_plan` appears exactly once in `SMART_AGENT_DIRECT_TOOLS`; once in `TOOL_SCHEMAS` (line 731); once in `WORKER_TOOL_SCHEMAS` exclusion (line 1038); once in `_HANDLERS` (line 1836). Comment at line 62 explicitly notes "update_plan NOT re-added". Module imports cleanly (`python -c "import core.tools"` exit 0 per SUMMARY-02). |
| T-23-08 | Info Disclosure | accept | CLOSED | Single-user agent; brain is Amit's own. No external exposure. Documented LOW risk — see Accepted Risks below. |
| T-23-09 | Tampering | mitigate | CLOSED | `core/proactive_alerts.py:115` — Block-4 excluded by `"Race" in label or end_date == "2026-10-10"`. Same check at line 187 in `run_proactive_alerts`. Thresholds are literal constants: `0.70` (line 132) and `1.2` (lines 133, 104). |
| T-23-10 | DoS | mitigate | CLOSED | `core/proactive_alerts.py:194-195` — block-end check wrapped in `try/except logger.warning`. Lines 234-246 — benchmark gate evaluation wrapped in `try/except`. Gate-unknown → PASS: `hrv_pct = None` when `hrv_baseline` is falsy (line 130); `gate_fail` requires `hrv_pct is not None` (line 132) — missing data falls through to `benchmark_window_open` (line 144). Lines 252-254 — early-return guard widened: `not weather_alerts and not overload_alert and not travel_alerts and benchmark_state is None`. Stale-window fires at line 119-120 when `today_iso > end_date`. |
| T-23-11 | Spoofing/Repudiation | mitigate | CLOSED | `core/proactive_alerts.py:191` — `set_benchmark_due(...)` call at line 191; `_already_sent(target_date)` call at line 197. Block-end check textually precedes the dedup gate by 6 lines. `set_benchmark_due` uses `merge=True` (idempotent, per `memory/firestore_db.py:1648`). |
| T-23-12 | Info Disclosure | accept | CLOSED | Single recipient (Amit); numeric HRV/ACWR reason is the intended UX (D-08). LOW risk — see Accepted Risks below. |
| T-23-13 | DoS | mitigate | CLOSED | `core/morning_briefing.py:278-299` — BlockStore gather inside `try/except`, `logger.warning("morning_briefing: block state fetch failed")`. `core/weekly_training_review.py:200-222` — BlockStore/BenchmarkStore gather inside `try/except`, defaults `current_block=None` / `block_benchmarks=[]` on failure. Both use `if block:` guards (morning_briefing.py:285, weekly_training_review.py:205). |
| T-23-14 | Tampering | mitigate | CLOSED | `core/morning_briefing.py:286` — `week_num = (date.fromisoformat(today_iso) - date.fromisoformat("2026-06-21")).days // 7 + 1`. `core/weekly_training_review.py:206` — same inline formula. `week_num` not present in any Firestore write path in either file. |
| T-23-15 | Info Disclosure | accept | CLOSED | Single recipient (Amit); surfacing benchmark numbers is the intended UX (BLOCK-03). LOW risk — see Accepted Risks below. |

---

## Accepted Risks

| Threat ID | Risk | Justification |
|-----------|------|---------------|
| T-23-04 | Personal biometric/lift data in Firestore | Single-user, no public surface. GCP manages encryption at rest. Klaus is a private cloud-hosted personal agent; Firestore access requires GCP project credentials. |
| T-23-08 | Benchmark/lift numbers returned to brain | Brain is the user's own agent (Amit's Gemini instance). No third-party exposure. Data is surfaced by design. |
| T-23-12 | HRV/ACWR numbers in Telegram | Telegram channel is a private bot with a single authorized recipient (Amit's Telegram ID). Numeric biometric reason is the intended D-08 UX. |
| T-23-15 | Benchmark numbers in morning briefing | Same private Telegram channel. Surfacing measured numbers is the core BLOCK-03 user story. |

---

## Unregistered Flags

No unregistered flags. All `## Threat Flags` entries in the four SUMMARY files map to
existing threat IDs:

| Flag (from SUMMARY) | Maps to |
|---------------------|---------|
| input-validation (memory/firestore_db.py) | T-23-01 |
| access-control (core/tools.py) | T-23-05 |
| input-validation (core/tools.py) | T-23-06 |
| dos-resilience (core/proactive_alerts.py) | T-23-10 |
| ordering (core/proactive_alerts.py) | T-23-11 |
| dos-resilience (morning_briefing.py, weekly_training_review.py) | T-23-13 |
| derived-truth (both crons) | T-23-14 |

---

## Additional Verified Items (Post-Review Fixes)

Per `<constraints>`: two post-plan-review fixes are present in the code and verified:

- **WR-02 (created_at overwrite):** `memory/firestore_db.py:1631-1644` — `upsert` reads the
  existing doc first and only stamps `created_at` on first write, preserving the original
  creation timestamp on `--force` re-seeding.

- **IN-02 (log_benchmark date validation):** `memory/firestore_db.py:1766-1773` —
  `log_benchmark` validates the `date` argument with `_date.fromisoformat(date)` before
  constructing the doc id, converting an SDK-opaque error into a clean `ValueError`.
