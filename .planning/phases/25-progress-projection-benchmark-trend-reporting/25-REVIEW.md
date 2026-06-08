---
phase: 25-progress-projection-benchmark-trend-reporting
reviewed: 2026-06-08T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - core/pace_history.py
  - core/projection.py
  - core/tools.py
  - core/weekly_training_review.py
  - prompts/smart_agent.md
  - prompts/weekly_training_review.md
  - tests/test_projection.py
  - tests/test_prompts.py
  - tests/test_tool_registration_phase25.py
  - tests/test_weekly_training_review.py
findings:
  critical: 0
  warning: 6
  info: 4
  total: 10
status: resolved
resolved: 2026-06-08
resolution_commit: pending
---

# Phase 25: Code Review Report

**Reviewed:** 2026-06-08T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** resolved (all 6 warnings + 4 info fixed 2026-06-08, pre-deploy)

## Resolution Summary (2026-06-08)

All 10 findings fixed before the v4.0 deploy, each with regression coverage
(full suite 1058 passed):

- **WR-01** — `project_goal_progress` now skips entries with a missing/blank/unparseable
  date (validates `date.fromisoformat` per row) instead of letting one bad row collapse
  the batch to `no_data`. Tests: `test_malformed_date_entry_is_skipped_not_poisoning`,
  `test_unparseable_date_entry_is_skipped`.
- **WR-02 / IN-02** — same-day readings are now averaged deterministically (order-independent),
  and `fetch_dense_pace_history` aggregates per calendar day in SQL (`GROUP BY date::date`,
  `AVG`) so `LIMIT 20` counts distinct days. Tests: `test_same_date_dedup_is_order_independent`,
  `test_sql_aggregates_per_day`.
- **WR-03** — `_resolve_target` now selects the nearest **upcoming** dated goal relative to
  `today_iso` (order-independent) rather than the first match. Test:
  `test_resolve_target_picks_nearest_upcoming_deadline`.
- **WR-04** — added a direction-normalized `behind_by` field (positive == behind target for
  every facet, including pace); tool description + smart_agent.md + weekly_training_review.md
  steer the brain to read it instead of the sign-flipping raw `gap`. Tests:
  `test_behind_by_positive_means_behind_*`, `test_behind_by_negative_when_ahead`.
- **WR-05** — removed the unreachable `n == 1` branch in `_linear_project`; added a defensive
  `n == 0` guard and documented the `n >= 2` caller contract.
- **WR-06** — `_gather_week_data` loads the UserProfile once and shares a single `BenchmarkStore`
  across blocks 5/6/8 (fail-open: block 8 rebuilds only if an earlier block failed), eliminating
  the double profile load / duplicate store wiring.
- **IN-01** — `fetch_dense_pace_history` now honours `today_iso` (window cutoff derived + validated
  from it; SQL stays injection-free). Test: `test_today_iso_is_honoured_in_window`,
  `test_malformed_today_iso_fails_open`.
- **IN-03** — confidence label uses a source-appropriate noun ("readings" for dense pace,
  "benchmarks" for strength) so dense runs are not mislabelled as benchmarks. Test:
  `test_confidence_label_noun_is_source_appropriate`.
- **IN-04** — the four week-window boundary strings are computed once and reused across the
  Garmin + biometrics blocks.

Security note: the T-25-13 / T-25-15 evidence in `25-SECURITY.md` was updated for the new SQL —
the injection surface is unchanged (validated self-computed ISO date literal, no LLM/user input).

---

## Summary

Phase 25 adds deterministic goal projection (`core/projection.py`), a dense Garmin
pace-history source (`core/pace_history.py`), the brain-direct `get_goal_projection`
tool, and the proactive weekly-review projection gather. Tool registration is correct
at all four sites, the fail-open discipline is consistently applied, and SQL is
parameter-free (CR-01 / T-25-13 mitigations honoured). No Critical issues found.

However, the projection helper has several correctness gaps that the test suite does
not exercise: a single malformed history entry silently collapses the entire
projection to `no_data`; same-date deduplication keeps a *nondeterministic* value
because neither `project_goal_progress` nor the SQL guarantees an ordering tiebreak;
and the `_resolve_target` goal-selection picks the first matching goal with no
preference for the nearest deadline. None are data-corrupting, but each can produce a
silently wrong or misleading number that the brain then quotes to Sir verbatim
("trend → 98kg by Oct 10, ~7kg behind"), which is exactly the trust surface this
phase is meant to protect.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Single malformed history entry collapses the entire projection to `no_data`

**File:** `core/projection.py:210-262`
**Issue:** During dedup, `entry_date = entry.get("date", "")` defaults a missing/empty
date to `""`. That empty string is stored in `seen_dates` and later fed to
`date.fromisoformat(unique_points_by_date[0][0])` (line 257) / `date.fromisoformat(date_str)`
(line 262). `date.fromisoformat("")` raises `ValueError`, which is caught by the
function-level `except Exception` and returns the catch-all `no_data` result. The
effect: one entry with a missing or malformed date in an otherwise-valid 5-point
history wipes out the entire projection and Klaus reports "no measured data" for a
facet that actually has data. Real `BenchmarkStore` / Garmin rows should always have a
date, but the helper is documented as "never raises / fails open" and a partial
gather (e.g. a row with a null `activity_date` that slips past `pace_history`'s guard)
should degrade gracefully, not erase all good points.
**Fix:** Skip entries that lack a usable date instead of letting them poison the batch:
```python
for entry in history:
    entry_date = entry.get("date") or ""
    entry_value = entry.get("value")
    if entry_value is None or not entry_date:
        continue
    try:
        date.fromisoformat(entry_date)  # validate up front
    except ValueError:
        continue
    if entry_date not in seen_dates:
        seen_dates[entry_date] = float(entry_value)
```

### WR-02: Same-date dedup keeps a nondeterministic value (no ordering tiebreak)

**File:** `core/projection.py:206-217`; `core/pace_history.py:44-57`
**Issue:** The dedup comment claims it keeps "the most recent value per date ...
keeping the first in a date-desc sorted list," but `project_goal_progress` never sorts
`history` — it trusts the caller's order and keeps the first occurrence per date
(`if entry_date not in seen_dates`). For `threshold_pace` the caller is
`fetch_dense_pace_history`, whose SQL is `ORDER BY date DESC` with **no secondary
sort**. When Sir runs two qualifying runs on the same calendar day (a hard run + an
easy run, both ≥3 km), Postgres returns them in an arbitrary order, so the pace kept
for that day is nondeterministic — the same query can yield a different projected
pace on different runs. This directly undermines the "numbers are never LLM-invented /
deterministic" guarantee in the tool description (`core/tools.py:991-995`).
**Fix:** Make the choice deterministic at the source. In `core/pace_history.py`, add a
stable tiebreak and aggregate per day, e.g. order by `date DESC, duration_sec ASC` (or
`AVG(pace)` grouped by `activity_date`) so a fixed value is selected. Equivalently,
sort `history` deterministically inside `project_goal_progress` before dedup and make
the "which value wins" rule explicit rather than order-dependent.

### WR-03: `_resolve_target` picks the first matching goal, ignoring deadline proximity

**File:** `core/projection.py:122-154`
**Issue:** Both the `threshold_pace` branch and the standard branch iterate
`dated_goals` and return on the **first** goal whose metrics contain the facet. If two
dated goals both specify a facet (e.g. an October goal of `bench_press_kg: 100` and a
December goal of `bench_press_kg: 110`), the result depends purely on the list order
returned by `UserProfileStore.load()` — not on which deadline is nearest or relevant.
The brain then quotes a `target_value`/`target_date` pair that may belong to the wrong
milestone. The current fixture only has one goal per facet so tests never catch this,
but the data model explicitly supports multiple dated goals.
**Fix:** Decide and document the selection rule (nearest upcoming deadline relative to
`today_iso` is the natural choice) and sort candidates accordingly before picking:
```python
candidates = [g for g in dated_goals if (g.get("metrics") or {}).get(metric_key) is not None]
candidates.sort(key=lambda g: g.get("target_date") or "9999-12-31")
# pick the earliest deadline >= today_iso, else the latest past one
```

### WR-04: `gap` sign is direction-blind, so its meaning flips between facets

**File:** `core/projection.py:294-299`
**Issue:** `gap = projected_value - target_value` is computed identically for
higher-is-better and lower-is-better facets, while `on_track` *is* direction-aware. For
`bench_press_1rm` a negative gap means "behind"; for `threshold_pace` (lower sec/km is
better) a negative gap means "ahead." The weekly-review prompt and `smart_agent.md`
instruct the model to "cite the computed number and gap (e.g. '~7kg behind')," so the
LLM must infer the sign convention per facet from `on_track` rather than reading `gap`
directly. This is an easy place for the brain to narrate a pace result backwards
("7 sec/km behind" when actually ahead). `on_track` saves correctness, but a raw signed
`gap` with inconsistent meaning is a latent mis-report waiting to happen.
**Fix:** Either normalize `gap` to a signed "shortfall" that is consistent across
directions (positive = behind target for every facet), or add an explicit
`gap_direction` / `behind_by` field so the consumer never has to combine `gap` and
`on_track` to recover the sign.

### WR-05: Dead `n == 1` branch in `_linear_project` masks the real contract

**File:** `core/projection.py:109-111`
**Issue:** `_linear_project` handles `n == 1` by returning the single point's value, but
`project_goal_progress` already returns `baseline_only` for one unique-date point
(line 239-251) and only calls `_linear_project` when `n >= 2` (line 274). The branch is
unreachable from the only caller. Dead code here is mildly dangerous: it implies
`_linear_project` is safe to call with one point, but with zero points it would raise
`ZeroDivisionError` at `t_mean = sum(ts) / n`, so the function is not actually robust to
small inputs the way the dead branch suggests.
**Fix:** Remove the `n == 1` branch (caller guarantees `n >= 2`), or, if the helper is
meant to be independently reusable, guard `n == 0` as well and document the contract.

### WR-06: Projection gather re-loads UserProfile and instantiates stores redundantly

**File:** `core/weekly_training_review.py:200-271`
**Issue:** Block #6 (lines 200-222) and block #8 (lines 249-271) each independently call
`os.environ["GCP_PROJECT_ID"]`, build a `BenchmarkStore`, and block #8 calls
`UserProfileStore(...).load()` a second time even though block #5 (line 187) already
loaded the same profile. Beyond the duplication, the projection block calls
`_benchmarks.get_facet_history(facet, n=10)` once per facet inside the loop (5 calls)
plus `fetch_dense_pace_history` — five separate store round-trips that the gather does
not need to re-derive. This is a maintainability/consistency hazard: two profile loads
in the same gather can return two different snapshots if the document changes mid-run,
and the duplicated env/store wiring is error-prone to keep in sync.
**Fix:** Load the profile once near the top of `_gather_week_data`, thread
`dated_goals` and a single `BenchmarkStore` instance into the projection block, and
reuse them. (Performance is out of v1 scope; the finding is the duplicated-load
correctness/maintainability risk, not the query count.)

## Info

### IN-01: `pace_history.fetch_dense_pace_history` ignores its `today_iso` argument entirely

**File:** `core/pace_history.py:26-57`
**Issue:** `today_iso` is accepted but never used — the SQL uses server-side `NOW()`.
The docstring explains this is "for signature parity / future use," which is reasonable,
but an unused required parameter is a footgun: a caller may assume passing a back-dated
`today_iso` changes the window (it does not), producing surprising results during
backfills or tests. The 90-day window is silently anchored to wall-clock server time,
not the caller's date.
**Fix:** Either drop the parameter until a caller actually needs it, or honour it by
binding the window to `today_iso` (still as hardcoded-literal SQL, computing the cutoff
in Python and embedding only an ISO date literal you control).

### IN-02: `pace_history` SQL `ORDER BY date DESC` but selects `date::date` — `LIMIT 20` can drop same-day runs unpredictably

**File:** `core/pace_history.py:44-57`
**Issue:** Combined with WR-02, the `LIMIT 20` is applied to row order that has no
secondary sort key. With dense Garmin data (multiple runs/day) the 20-row cap can
truncate at an arbitrary point within a day, so the set of dates that survive into the
projection is itself nondeterministic across runs.
**Fix:** Aggregate per day in SQL (e.g. `GROUP BY activity_date`) before `LIMIT`, so the
limit counts distinct days, not raw activities.

### IN-03: `confidence` tiers blur "unique benchmarks" with "unique dates" for dense Garmin data

**File:** `core/projection.py:279-287`
**Issue:** Confidence is "high" at `n >= 4` unique dates. For `threshold_pace` fed by
`fetch_dense_pace_history`, four ordinary training runs in two weeks yield "high
confidence" on a noisy day-to-day pace signal, while a deliberate strength benchmark
every block yields only "low." The label "from N benchmarks" is also a misnomer for the
Garmin path — those are runs, not benchmarks.
**Fix:** Either widen the high-confidence threshold for the dense path or relabel the
confidence string per source ("from N runs" vs "from N benchmarks") so the brain does
not overstate certainty.

### IN-04: Duplicate `last_start_str` / `this_start_str` recomputation in biometrics block

**File:** `core/weekly_training_review.py:121,131,139`
**Issue:** `last_start_str` is computed at line 121, then `(week_start - timedelta(days=1)).isoformat()`
is recomputed inline at line 139, and `this_start_str` is recomputed at 131. Minor
duplication that invites drift if the window boundaries are ever adjusted.
**Fix:** Compute the four window-boundary strings once at the top of the block and reuse.

---

_Reviewed: 2026-06-08T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
