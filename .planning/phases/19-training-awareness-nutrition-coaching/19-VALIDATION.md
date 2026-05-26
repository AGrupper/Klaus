---
phase: 19
slug: training-awareness-nutrition-coaching
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-26
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `19-RESEARCH.md` §Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (auto-discovers from `tests/`) |
| **Config file** | none — pytest auto-discovery |
| **Quick run command** | `pytest tests/test_user_profile_store.py tests/test_meal_store.py tests/test_google_fit_tool.py tests/test_compute_acwr.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~30s quick / ~60s full (465 existing + ~30 new Phase 19) |

---

## Sampling Rate

- **After every task commit:** Run the quick command above (covers files most likely touched).
- **After every plan wave:** Run `pytest tests/ -x` — full suite.
- **Before `/gsd-verify-work`:** Full suite must be green. INGEST-03 (3-year backfill) is a manual operator step.
- **Max feedback latency:** ~60 seconds.

---

## Per-Task Verification Map

| Req ID | Wave | Behavior | Test Type | Automated Command | File Exists |
|--------|------|----------|-----------|-------------------|-------------|
| SCHEMA-01 | 0 | `activities` has 3 new columns | unit (psycopg2 mock) | `pytest tests/test_ingest_schema.py::test_activities_has_phase19_columns -x` | ❌ W0 |
| SCHEMA-02 | 0 | `daily_biometrics` has 4 new columns | unit | `pytest tests/test_ingest_schema.py::test_daily_biometrics_has_phase19_columns -x` | ❌ W0 |
| SCHEMA-03 | 0 | DDL re-run is idempotent | integration | `pytest tests/test_ingest_schema.py::test_setup_schema_idempotent -x` | ❌ W0 |
| INGEST-01 | 0 | parser extracts trainingLoad/perceivedExertion/feel NULL-safe | unit (fixture JSON) | `pytest tests/test_ingest_garmin.py::test_activity_phase19_fields -x` | ❌ W0 |
| INGEST-02 | 0 | parser extracts vo2MaxValue from UDS | unit | `pytest tests/test_ingest_garmin.py::test_uds_vo2_max -x` | ❌ W0 |
| INGEST-03 | 0 | end-to-end backfill row counts + NULL rates | manual operator | (manual via `database_tool`) | manual-only |
| PROFILE-01 | 1 | `load()` returns `{}` on Firestore exception | unit | `pytest tests/test_user_profile_store.py::test_load_returns_empty_on_error -x` | ❌ W1 |
| PROFILE-02 | 1 | `update()` merges + stamps `updated_at` | unit | `pytest tests/test_user_profile_store.py::test_update_merges_and_stamps -x` | ❌ W1 |
| PROFILE-03 | 1 | `bootstrap_if_empty` writes scaffold | unit | `pytest tests/test_user_profile_store.py::test_bootstrap_creates_when_missing -x` AND `test_bootstrap_skips_when_present` | ❌ W1 |
| PROFILE-04 | 1 | both profile tools registered (brain-direct) | unit | `pytest tests/test_tools.py::test_phase19_profile_tools_registered -x` | ❌ W1 |
| GARMIN-01 | 1 | `fetch_training_status` returns 3-key dict | unit (`garminconnect` mock) | `pytest tests/test_garmin_extensions.py::test_training_status_shape -x` | ❌ W1 |
| GARMIN-02 | 1 | `fetch_recent_activities(days=7)` normalized list | unit | `pytest tests/test_garmin_extensions.py::test_recent_activities_shape -x` | ❌ W1 |
| GARMIN-03 | 1 | `compute_acwr` ratio + None on insufficient | unit (no I/O) | `pytest tests/test_compute_acwr.py::test_normal_ratio` AND `test_insufficient_baseline_returns_none` | ❌ W1 |
| GARMIN-04 | 1 | fetch tools in WORKER_TOOL_SCHEMAS only | unit | `pytest tests/test_tools.py::test_phase19_fetch_tools_worker_delegated -x` | ❌ W1 |
| GARMIN-05 | 3 | morning briefing writes biometrics to Postgres (best-effort) | unit (psycopg2 mock) | `pytest tests/test_morning_briefing.py::test_writes_biometrics_to_postgres` AND `test_postgres_outage_does_not_block_briefing` | partial W3 |
| NUTR-01 | 2 | Google Fit nutrition normalization | unit (HTTP fixture) | `pytest tests/test_google_fit_tool.py::test_normalize_point -x` | ❌ W2 |
| NUTR-02 | 2 | MealStore idempotent on source_id | unit | `pytest tests/test_meal_store.py::test_upsert_idempotent_on_source_id -x` | ❌ W2 |
| NUTR-03 | 2 | `fetch_recent_meals` worker-delegated | unit | `pytest tests/test_tools.py::test_fetch_recent_meals_worker_delegated -x` | ❌ W2 |
| NUTR-04 | 3 | autonomous gather extends with meals + training_status + acwr | unit | `pytest tests/test_autonomous.py::test_gather_includes_phase19_keys -x` | partial W3 |
| NUTR-05 | 3 | morning briefing aggregates yesterday's meals | unit | `pytest tests/test_morning_briefing.py::test_aggregates_yesterday_meals -x` | partial W3 |
| NUTR-06 | 4 | autonomous_triage.md mentions meal triggers | unit (grep) | `pytest tests/test_prompts.py::test_triage_mentions_meal_triggers -x` | ❌ W4 |
| NUTR-07 | 4 | recap silently omitted on no-meals day | unit | `pytest tests/test_morning_briefing.py::test_no_nutrition_key_when_empty` AND `test_prompt_omits_section_when_no_nutrition` | ❌ W4 |
| NUTR-08 | 4 | `prompts/meal_audit.md` exists and is referenced | unit | `pytest tests/test_prompts.py::test_meal_audit_exists` AND `test_meal_audit_referenced` | ❌ W4 |
| PROMPT-01 | 4 | `{training_profile}` substitution works | unit | `pytest tests/test_main_render_smart_system.py::test_training_profile_substituted -x` | ❌ W4 |
| PROMPT-02 | 4 | smart_agent.md has training section | unit (grep) | `pytest tests/test_prompts.py::test_smart_agent_has_training_section -x` | ❌ W4 |
| PROMPT-03 | 4 | SELF.md lists 5 new tools | unit (grep) | `pytest tests/test_docs.py::test_self_md_lists_phase19_tools -x` | partial W4 |

*Status legend: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · W{N} = wave gap*

---

## Wave 0 Requirements

- [ ] `tests/test_ingest_schema.py` — stubs for SCHEMA-01, SCHEMA-02, SCHEMA-03
- [ ] `tests/test_ingest_garmin.py` — stubs for INGEST-01, INGEST-02
- [ ] One-shot Garmin export key probe script (not a test) — locks field-name assumptions A1–A4 from RESEARCH.md
- Framework: already installed (`pytest` is project-standard)

## Wave 1 Requirements

- [ ] `tests/test_user_profile_store.py` — covers PROFILE-01..03
- [ ] `tests/test_garmin_extensions.py` — covers GARMIN-01, GARMIN-02
- [ ] `tests/test_compute_acwr.py` — covers GARMIN-03
- [ ] Extend `tests/test_tools.py` — covers PROFILE-04, GARMIN-04 (and NUTR-03 in W2)

## Wave 2 Requirements

- [ ] `tests/test_google_fit_tool.py` — covers NUTR-01
- [ ] `tests/test_meal_store.py` — covers NUTR-02
- [ ] Extend `tests/test_tools.py` — covers NUTR-03
- [ ] OAuth re-consent for `fitness.nutrition.read` scope — operator manual step

## Wave 3 Requirements

- [ ] Extend `tests/test_autonomous.py` — covers NUTR-04 + eval-fixture schema update + 5-fixture backfill
- [ ] Extend `tests/test_morning_briefing.py` — covers NUTR-05, NUTR-07, GARMIN-05

## Wave 4 Requirements

- [ ] Extend `tests/test_prompts.py` — covers NUTR-06, NUTR-08, PROMPT-02
- [ ] Extend `tests/test_main_render_smart_system.py` — covers PROMPT-01
- [ ] Extend `tests/test_docs.py` — covers PROMPT-03
- [ ] Run `python core/self_manifest.py` and commit regenerated `docs/SELF.md`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 3-year Garmin backfill row counts + NULL rates | INGEST-03 | Requires real export zip (~hundreds of MB) + real Neon DB connection; not reproducible in CI | Run `scripts/ingest_garmin_zip.py <export.zip>`. Then via `database_tool` query: `SELECT COUNT(*), COUNT(training_load), COUNT(perceived_exertion), COUNT(feel), COUNT(vo2_max) FROM activities;` and `SELECT COUNT(*), COUNT(resting_heart_rate), COUNT(hrv_overnight_avg), COUNT(body_battery_charged), COUNT(body_battery_drained) FROM daily_biometrics;`. Record counts + NULL rates in execution notes. |
| End-to-end Lifesum → Fit → MealStore → Telegram outreach loop | (Success criterion 2) | Requires real Lifesum entry + real autonomous-tick fire window + real Telegram delivery | Log a meal in Lifesum; wait ~30 min for Fit sync; verify next autonomous tick produces `meals/{date}/{ts}` Firestore doc; verify potential mid-day Telegram message (or no-op with reasoning in tick log). |
| Google Fit OAuth re-consent for `fitness.nutrition.read` scope | NUTR-01 | One-time interactive Google consent screen | Visit Klaus's OAuth consent URL; grant `fitness.nutrition.read`; verify `tokens.json` updated. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
