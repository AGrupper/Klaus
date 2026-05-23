---
phase: 18-autonomous-engine
plan: 08
subsystem: eval-harness
tags: [eval, tick-brain, precision-recall, measurement, cli, scoring, autonomous]

# Dependency graph
requires:
  - phase: 18-autonomous-engine/03
    provides: prompts/autonomous_triage.md — the system prompt the eval feeds to TickBrain.think(system_override=...)
  - phase: 18-autonomous-engine/04
    provides: evals/tick_brain/fixtures/*.json — the 5 seed SituationSnapshot fixtures with ground_truth.should_speak labels the eval scores against
  - phase: 18-autonomous-engine/05
    provides: TickBrain.think(prompt, system_override=...) — extended signature the eval calls with the autonomous_triage prompt; safe-mode reason set {parse_failure, llm_error} which the eval treats as 'errored' (Pitfall 8)
  - phase: 18-autonomous-engine/06
    provides: core.autonomous._build_triage_prompt(situation, triage_system) — the production prompt renderer the eval reuses byte-for-byte so eval-vs-production drift is impossible (BLOCKER 4 fix)
provides:
  - scripts/eval_tick_brain.py — CLI eval runner that scores tick-brain predictions vs labeled fixtures and prints overall P/R/F1 + per-trigger-type breakdown (AUTO-09)
  - tests/test_eval_script.py::TestEvalScript — 4 subprocess-invocation tests guarding output structure (exit 0, required strings, per-trigger table, missing-dir handling)
affects:
  - 18-09 (deployment-docs): docs/DEPLOYMENT.md should mention `python scripts/eval_tick_brain.py` as the day-one judgment-quality check + the retroactive-labeling workflow (already documented in evals/tick_brain/README.md from Plan 04)
  - Future eval growth (AUTO-08, 20–30 fixtures): the runner is fixture-count-agnostic — `glob('evals/tick_brain/fixtures/*.json')` scales automatically as labelers add files

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reuse production prompt renderer in the eval — `from core.autonomous import _build_triage_prompt` is called inside `_render_prompt(fixture)` so the eval prompt is byte-for-byte identical to what the autonomous tick sends in production. Eliminates an entire class of 'eval predicts X but prod predicts Y' drift bugs. The dependency is locked by depends_on=[03,04,05,06] in PLAN frontmatter (BLOCKER 4 fix)"
    - "Safe-mode bucket is separate from predicted-False (Pitfall 8) — `_SAFE_MODE_REASONS = {'parse_failure', 'llm_error'}` is the literal, source-verified set of reason strings emitted by core/tick_brain.py:154,165,168,189. A safe-mode return lands in the 'errored' bucket and is excluded from TP/FP/TN/FN aggregation, so a flaky LLM never inflates the apparent precision/recall numbers"
    - "Best-effort-always exit code 0 — measurement tool, not a CI gate (D-22). Missing API key → TickBrain construction raises ValueError → caught → tb=None → all fixtures land in errored bucket → report still prints → exit 0. Missing fixtures dir → glob returns [] → 'X fixtures loaded' message → exit 0. Per-fixture JSON parse errors → logged at ERROR but loop continues. This makes the script safe to chain into any cron / CI workflow without breaking the build"
    - "sys.path bootstrap inside the script itself — `_REPO_ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(_REPO_ROOT))` lets `python scripts/eval_tick_brain.py` work directly without PYTHONPATH=. matching the docstring usage examples. Mirrors the implicit pytest sys.path setup so the subprocess tests and the manual smoke share one import contract"
    - "Subprocess-invocation tests with env-var stripping — test_eval_script.py's `_run()` helper pops TICK_BRAIN_API_KEY/GROQ_API_KEY/SMART_AGENT_API_KEY from the subprocess env before invocation, forcing the script into the all-errored fallback path. Tests then assert the output STRUCTURE (Precision:/Recall:/F1:/Errored: + 5 trigger rows) without requiring network or fixture-accuracy. Output schema is the contract; LLM judgment is not"

key-files:
  created:
    - "scripts/eval_tick_brain.py (366 lines including shebang+docstring) — CLI eval runner: _load_fixtures + _render_prompt + _score_fixture + _errored_result + _confusion + _metrics + _print_report + _build_arg_parser + main"
    - "tests/test_eval_script.py (83 lines) — TestEvalScript with 4 subprocess tests"
    - ".planning/phases/18-autonomous-engine/18-08-SUMMARY.md (this file)"
  modified:
    - ".planning/phases/18-autonomous-engine/deferred-items.md — logged the pre-existing `No module named 'fastapi'` blocker on tests/test_web_server.py + tests/test_heartbeat.py::test_cron_heartbeat_rejects_unauthenticated as out-of-scope for Plan 18-08 (reproduced on HEAD before any changes)"

key-decisions:
  - "Reuse `core.autonomous._build_triage_prompt` instead of re-implementing prompt assembly in the eval — drift between eval and prod is the single largest failure mode for an offline evaluation harness, and a thin import is the only reliable fix. The cost is the extra depends_on=06 (BLOCKER 4 fix); the benefit is eval results that are causally meaningful for prod tuning"
  - "Treat safe-mode as 'errored', not 'predicted False' (Pitfall 8) — counting parse-failures as predicted-silence would mean a model that crashes on every input scores precision=N/A but recall=0%, looking respectable. The 'errored' column called out separately makes LLM brittleness visible as its own metric: e.g. `Errored: 5/5` immediately tells the operator the API key is missing or the model is hard-broken, not that judgment is bad"
  - "Exit 0 always — D-22 explicitly classifies this as a measurement tool. CI gates on judgment quality are premature when n=5; once n≥20 (AUTO-08), a future plan can add `--strict` that exits non-zero below a P/R threshold. For now, the script is a print-and-go report"
  - "Default `--fixtures` to `evals/tick_brain/fixtures` (not required arg) — the no-args invocation `python scripts/eval_tick_brain.py` should Just Work from the repo root. Matches the docstring usage examples and the `python scripts/eval_tick_brain.py` reference in `evals/tick_brain/README.md`. The `--fixtures` flag is for future cases (e.g. running eval against a subset of fixtures during prompt iteration)"
  - "`--model` flag exports into env rather than passing through TickBrain constructor — `TickBrain.__init__` takes no args; it reads `TICK_BRAIN_MODEL` from env. Rather than refactor the constructor or silently ignore the flag, the script sets `os.environ['TICK_BRAIN_MODEL'] = args.model` before construction. Clean, no API change, easy to extend if TickBrain gains a `model_override` kwarg later"
  - "sys.path bootstrap inside the script — Cloud Run and pytest both arrange sys.path implicitly, so the missing case is `python scripts/eval_tick_brain.py` from the shell. Three lines at module top fix it once for all callers; the alternative (require PYTHONPATH=. in docs) is friction the user shouldn't have to remember"

requirements-completed: [AUTO-09]

# Metrics
duration: ~4min
completed: 2026-05-23
---

# Phase 18 Plan 08: Eval Runner Summary

**Ships `scripts/eval_tick_brain.py` — the precision/recall scorer that runs tick-brain against labeled SituationSnapshot fixtures, prints overall P/R/F1 plus per-trigger-type breakdown, and treats safe-mode (parse_failure/llm_error) returns as a separate 'errored' bucket (Pitfall 8). Exit code 0 always (measurement tool, not a CI gate). AUTO-09 complete.**

## Performance

- **Duration:** ~4 min (RED ~1 min, GREEN ~1 min, smoke + regression + SUMMARY ~2 min)
- **Completed:** 2026-05-23
- **Tasks:** 1 (single TDD task in the plan, executed as RED → GREEN with one small refactor for sys.path bootstrap)
- **Commits:** 2 atomic
  - `f9cfce3 test(18-08): add failing subprocess tests for eval_tick_brain.py`
  - `af56f83 feat(18-08): implement eval_tick_brain.py runner for AUTO-09`

## What changed

### `scripts/eval_tick_brain.py` (NEW, 366 lines)

CLI eval runner. Architecture:

1. `_build_arg_parser()` — argparse with `--fixtures` (default: `evals/tick_brain/fixtures`) and `--model` (exports into `TICK_BRAIN_MODEL` env before constructing TickBrain).
2. `_load_fixtures(dir)` — glob `*.json`, parse each, log+skip per-file errors. Returns `[]` on missing dir.
3. `_render_prompt(fixture)` — `from core.autonomous import _build_triage_prompt` (BLOCKER 4 dep). Calls it with `fixture["situation_snapshot"]` so the eval prompt is byte-for-byte identical to prod.
4. `_score_fixture(fixture, tb)` — reads `prompts/autonomous_triage.md` once per call, invokes `tb.think(prompt, system_override=triage_system)`. Pitfall 8 check: if `reason in _SAFE_MODE_REASONS and not should_act`, returns errored result; otherwise returns predicted vs ground_truth + topic_key regex match.
5. `_errored_result(fixture)` — helper for the all-errored fallback path (when TickBrain construction fails) and the Pitfall 8 path.
6. `_confusion(results)` — aggregates TP/FP/TN/FN/errored, skipping errored from the confusion matrix.
7. `_metrics(conf)` — precision, recall, F1 with zero-denominator guard returning 0.0.
8. `_print_report(results)` — overall block + per-trigger table (5 rows: overdue, gap, silence, followup, quiet) with explicit "0 fixtures loaded" path for the empty case.
9. `main()` — orchestration, exit code 0 always.

Three reliability constructs:

- `_SAFE_MODE_REASONS = {"parse_failure", "llm_error"}` — literally verified from `core/tick_brain.py:154,165,168,189`. The literal string for the third (non-emitted) hypothetical reason is NOT in the script source — `grep -c` of that string returns 0 per the plan's done criterion.
- TickBrain construction wrapped in `except Exception` — missing API key → ValueError → caught → `tb = None` → all fixtures errored, report still prints.
- sys.path bootstrap at module top — `python scripts/eval_tick_brain.py` works without `PYTHONPATH=.`.

### `tests/test_eval_script.py` (NEW, 83 lines)

`TestEvalScript` with 4 subprocess tests. `_run()` helper strips `TICK_BRAIN_API_KEY`/`GROQ_API_KEY`/`SMART_AGENT_API_KEY` from subprocess env so every test runs in the all-errored fallback path — no network, no fixture-accuracy dependence.

- `test_eval_runs_exits_zero` — `subprocess.run([..., --fixtures, FIXTURES]); assert returncode == 0`.
- `test_eval_output_contains_required_strings` — assert all of `"Precision:"`, `"Recall:"`, `"F1:"`, `"Errored:"` appear in stdout.
- `test_eval_output_contains_per_trigger_table` — assert `"Per-trigger-type"` header + all 5 trigger names appear in stdout.
- `test_eval_handles_missing_fixtures_dir` — assert exit 0 + `"0 fixtures loaded"` in stdout when `--fixtures /nonexistent/path`.

## Sample output (no API key — all-errored bucket)

```
ERROR Could not construct TickBrain (running with all-errored fallback): TICK_BRAIN_API_KEY is required. Set it in .env (dev) or GCP Secret Manager (Cloud Run).
=== Overall (5 fixtures) ===
Precision: 0.00 (0/0)
Recall:    0.00 (0/0)
F1:        0.00
Errored:   5/5  (parse_failure or llm_error — NOT predicted-False)

=== Per-trigger-type ===
| Trigger    |  TP |  FP |  FN |  TN | Err | Precision | Recall |
|------------|-----|-----|-----|-----|-----|-----------|--------|
| overdue    |   0 |   0 |   0 |   0 |   1 |      0.00 |   0.00 |
| gap        |   0 |   0 |   0 |   0 |   1 |      0.00 |   0.00 |
| silence    |   0 |   0 |   0 |   0 |   1 |      0.00 |   0.00 |
| followup   |   0 |   0 |   0 |   0 |   1 |      0.00 |   0.00 |
| quiet      |   0 |   0 |   0 |   0 |   1 |      0.00 |   0.00 |
```

(With a valid `TICK_BRAIN_API_KEY`, the Errored column drops to 0/5 and the TP/FP/FN/TN columns populate from real Groq/Qwen3-32B predictions on the 5 seed fixtures.)

## Tests

- `tests/test_eval_script.py::TestEvalScript` — 4 tests, all passing.
- Regression sweep on adjacent suites (`tests/test_autonomous.py tests/test_tick_brain.py tests/test_firestore_db.py tests/test_prompts.py tests/test_evals.py tests/test_heartbeat.py tests/test_main_render_smart_system.py tests/test_eval_script.py`): **155 passed, 1 deselected** (the deselected test is `test_cron_heartbeat_rejects_unauthenticated`, blocked by a pre-existing `No module named 'fastapi'` import in the local env — logged in deferred-items.md, reproduces on HEAD before any Plan 18-08 changes, out of scope).
- `tests/test_web_server.py` not run for the same fastapi-env reason.

## Verification of plan's done criteria

| Criterion | Value | Pass |
| --- | --- | --- |
| `scripts/eval_tick_brain.py` exists and ≥ 150 lines | 366 lines | ✓ |
| `python -c "import ast; ast.parse(open('scripts/eval_tick_brain.py').read())"` succeeds | OK: valid Python | ✓ |
| All 4 tests in `TestEvalScript` pass | 4/4 passed | ✓ |
| Manual smoke exits 0 and prints expected strings | exit 0, all 4 labels + 5 trigger rows present | ✓ |
| `grep -c "Precision:" scripts/eval_tick_brain.py` >= 1 | 1 | ✓ |
| `grep -c "Errored:" scripts/eval_tick_brain.py` >= 1 | 1 | ✓ |
| `grep -c "_SAFE_MODE_REASONS" scripts/eval_tick_brain.py` >= 2 | 2 (definition + Pitfall 8 check) | ✓ |
| `grep -c "fallback_failed" scripts/eval_tick_brain.py` == 0 | 0 | ✓ |
| `from core.autonomous import _build_triage_prompt` succeeds at runtime | OK: _build_triage_prompt imported successfully | ✓ |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Missing critical functionality] sys.path bootstrap inside the script**
- **Found during:** Task 1 manual smoke test
- **Issue:** Running `python scripts/eval_tick_brain.py` (as documented in the script's own docstring and in `evals/tick_brain/README.md`) failed with `ModuleNotFoundError: No module named 'core'` because the script depends on `from core.autonomous import _build_triage_prompt` but doesn't add the repo root to sys.path. Only worked with `PYTHONPATH=. python scripts/eval_tick_brain.py`.
- **Fix:** Added 3-line sys.path bootstrap at module top (`_REPO_ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(_REPO_ROOT))`). Now matches the documented usage and is consistent with how pytest implicitly arranges sys.path. The tests already passed because pytest sets up sys.path automatically; this fix is for the human operator running the script from the shell.
- **Files modified:** scripts/eval_tick_brain.py
- **Commit:** Folded into `af56f83 feat(18-08): implement eval_tick_brain.py runner for AUTO-09`

**2. [Rule 1 — Spec compliance] Removed literal `"fallback_failed"` string from the source comment**
- **Found during:** Task 1 grep verification of done criteria
- **Issue:** My initial NOTE 3 doc-comment said `# The literal string "fallback_failed" is NOT emitted anywhere by tick_brain.` which technically contains the literal string, causing `grep -c "fallback_failed" scripts/eval_tick_brain.py` to return 1 instead of the required 0.
- **Fix:** Rephrased the comment to avoid the literal string — same semantic content, different words. Now `grep -c` returns 0.
- **Files modified:** scripts/eval_tick_brain.py
- **Commit:** Folded into `af56f83 feat(18-08): implement eval_tick_brain.py runner for AUTO-09`

### Out-of-scope items logged to deferred-items.md

- `tests/test_web_server.py` + `tests/test_heartbeat.py::test_cron_heartbeat_rejects_unauthenticated`: ImportError on `fastapi` in local env. Reproduced on HEAD before any Plan 18-08 changes — pre-existing environmental issue (fastapi not installed locally; present in Cloud Run image). Logged.

## TDD Gate Compliance

- **RED gate:** `f9cfce3 test(18-08): add failing subprocess tests for eval_tick_brain.py` — 4 tests failing because the script didn't exist (ModuleNotFoundError → FileNotFoundError on subprocess invocation).
- **GREEN gate:** `af56f83 feat(18-08): implement eval_tick_brain.py runner for AUTO-09` — all 4 tests pass.
- **REFACTOR gate:** Not needed (the sys.path + grep-spec fixes were folded into GREEN before commit; the implementation came out clean enough that no separate refactor pass added value).

## Self-Check: PASSED

- scripts/eval_tick_brain.py — FOUND (366 lines)
- tests/test_eval_script.py — FOUND (83 lines)
- Commit f9cfce3 — FOUND in git log
- Commit af56f83 — FOUND in git log
