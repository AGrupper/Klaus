---
phase: 18-autonomous-engine
plan: 08
type: execute
wave: 3
depends_on: [03, 04, 05, 06]
files_modified:
  - scripts/eval_tick_brain.py
  - tests/test_eval_script.py
autonomous: true
requirements: [AUTO-09]
requirements_addressed: [AUTO-09]

must_haves:
  truths:
    - "scripts/eval_tick_brain.py loads all fixtures from evals/tick_brain/fixtures/, runs each through TickBrain.think with autonomous_triage system prompt, scores predicted should_act vs ground_truth.should_speak"
    - "Output: overall precision/recall/F1 plus per-trigger-type breakdown table"
    - "Safe-mode returns (parse_failure / llm_error) are tracked as a separate 'errored' bucket — NOT counted as 'predicted False' (Pitfall 8)"
    - "Safe-mode reason set is {parse_failure, llm_error} — VERIFIED from core/tick_brain.py:139,150,153,174,178 (NOTE 3 fix — 'fallback_failed' is NOT emitted)"
    - "Plan 08 depends on Plan 06 because scripts/eval_tick_brain.py imports core.autonomous._build_triage_prompt (BLOCKER 4 fix)"
    - "Exit code 0 always (measurement tool, not a gate)"
    - "tests/test_eval_script.py invokes the script via subprocess and asserts the output format"
  artifacts:
    - path: "scripts/eval_tick_brain.py"
      provides: "Eval runner — CLI + per-fixture scoring + report"
      min_lines: 150
    - path: "tests/test_eval_script.py"
      provides: "Subprocess-invocation test"
      contains: "test_eval_runs"
  key_links:
    - from: "scripts/eval_tick_brain.py"
      to: "evals/tick_brain/fixtures/*.json (Plan 04)"
      via: "glob.glob('evals/tick_brain/fixtures/*.json')"
      pattern: "glob"
    - from: "scripts/eval_tick_brain.py"
      to: "core/tick_brain.py TickBrain.think (Plan 05 extended)"
      via: "tick_brain.think(prompt, system_override=<autonomous_triage.md>)"
      pattern: "system_override"
    - from: "scripts/eval_tick_brain.py"
      to: "core/autonomous.py _build_triage_prompt (Plan 06)"
      via: "from core.autonomous import _build_triage_prompt"
      pattern: "_build_triage_prompt"
---

<objective>
Build `scripts/eval_tick_brain.py` — the precision/recall scorer that runs
tick-brain against the labeled `SituationSnapshot` fixtures. AUTO-09 names the
script; D-22 specifies overall P/R/F1 plus per-trigger-type breakdown; Pitfall 8
calls out treating parse-failure / llm-error returns as a separate "errored"
bucket (not "predicted False").

Purpose: Phase 18 is a measurement-driven phase. The eval is what turns
"judgment" from vibes into a number. Day-one runs against 5 seeds; the workflow
grows to 20–30 fixtures over the following weeks per D-21. The script must be
idempotent, exit 0 always, and produce a stable, grep-able output format.

**BLOCKER 4 fix:** depends_on now includes Plan 06 (it was missing previously).
`scripts/eval_tick_brain.py` imports `core.autonomous._build_triage_prompt`
so the eval prompt-rendering matches production exactly. Without the dep,
selective execution could run Plan 08 before Plan 06, causing ImportError.
Plan 08 stays in Wave 3 (Wave 2 lands first, so this is purely a metadata
correctness fix, not a wave reshuffle).

Output: One CLI script + one subprocess test.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/18-autonomous-engine/18-CONTEXT.md
@.planning/phases/18-autonomous-engine/18-RESEARCH.md
@.planning/phases/18-autonomous-engine/18-PATTERNS.md
@.planning/phases/18-autonomous-engine/18-04-SUMMARY.md
@.planning/phases/18-autonomous-engine/18-05-SUMMARY.md
@.planning/phases/18-autonomous-engine/18-06-SUMMARY.md
@core/reflection.py
@core/tick_brain.py
@core/autonomous.py

<interfaces>
<!-- CLI shape analog from core/reflection.py:_cli() and TickBrain interface. -->

From core/reflection.py:493-529 (_cli — argparse + load_dotenv + dry-run shape):
```python
def _cli() -> None:
    import argparse
    from dotenv import load_dotenv
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Reflection cron local smoke test")
    parser.add_argument("--date", default=today, help="YYYY-MM-DD to reflect on")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
```

From core/tick_brain.py (Plan 05 extension):
```python
TickBrain.think(prompt: str, tools=None, system_override: str | None = None) -> dict
# Returns dict with at least {should_act, reason}; optionally {draft, topic_key}.
# On parse failure: {should_act: False, reason: 'parse_failure'} (no topic_key key).
# On LLMError after fallback: {should_act: False, reason: 'llm_error'}.
# VERIFIED safe-mode reasons (NOTE 3 fix): only "parse_failure" and "llm_error" are
# ever emitted by tick_brain.py (lines 139, 150, 153, 174, 178). "fallback_failed"
# is NOT emitted — do not include it in _SAFE_MODE_REASONS.
```

From core/autonomous.py (Plan 06):
```python
_build_triage_prompt(situation: dict, triage_system: str) -> str
# Produces the user-message content for the triage call (situation snapshot + self_state + ...).
# Plan 08 imports this — hence the depends_on Plan 06.
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Implement scripts/eval_tick_brain.py + tests/test_eval_script.py</name>
  <files>scripts/eval_tick_brain.py, tests/test_eval_script.py</files>
  <read_first>
    - core/tick_brain.py (Plan 05 output — `TickBrain.think` extended signature + safe-mode return shapes; **VERIFIED** exact `reason` strings: "parse_failure" and "llm_error" only)
    - core/autonomous.py (Plan 06 output — `_build_triage_prompt` signature; reuse it so eval prompt-rendering matches production exactly)
    - core/reflection.py:493-529 (CLI shape reference — argparse + load_dotenv)
    - evals/tick_brain/fixtures/0001-overdue-task.json (Plan 04 output — fixture schema to consume)
    - evals/tick_brain/README.md (Plan 04 — confirm key names and ground_truth structure)
    - tests/test_evals.py (Plan 04 — pattern for parametrized per-fixture tests, although Plan 08 tests are subprocess-style)
    - .planning/phases/18-autonomous-engine/18-CONTEXT.md (D-21, D-22)
    - .planning/phases/18-autonomous-engine/18-RESEARCH.md (section "scripts/eval_tick_brain.py shape" lines 281-302; Pitfall 8)
    - .planning/phases/18-autonomous-engine/18-PATTERNS.md (section "scripts/eval_tick_brain.py (NEW)" lines 663-690)
  </read_first>
  <behavior>
    For `scripts/eval_tick_brain.py`:
    - Invoking with no args: runs against all `evals/tick_brain/fixtures/*.json`; prints overall + per-trigger table; exits 0.
    - Invoking with `--fixtures <dir>`: uses that directory instead.
    - Invoking with `--model <name>`: passes that model name into `TickBrain(model_override=...)` if supported, else `TICK_BRAIN_MODEL` env (whatever the existing `TickBrain.__init__` accepts — read it first; if it doesn't accept a model param, document the flag as "currently ignored, reserved for future" and still print/parse it).
    - Output format MUST contain the strings: `Precision:`, `Recall:`, `F1:`, `Errored:`, and a per-trigger table with rows `overdue`, `gap`, `silence`, `followup`, `quiet`.
    - Output is plain text on stdout; logs go to stderr.

    For `tests/test_eval_script.py`:
    - `test_eval_script_exits_zero`: subprocess.run script with `--fixtures evals/tick_brain/fixtures`; assert returncode == 0. **Mock the actual LLM call** — set `TICK_BRAIN_API_KEY=` (empty) and ensure the script handles missing API gracefully (the safe-mode `parse_failure`/`llm_error` path); the test asserts the script runs and produces the output structure even when all predictions are "errored."
    - `test_eval_script_output_contains_required_strings`: assert stdout contains `Precision:`, `Recall:`, `F1:`, `Errored:`, and per-trigger table header.
    - `test_eval_script_handles_missing_fixtures_dir`: subprocess with `--fixtures /nonexistent/path`; assert exit code 0 AND stdout indicates "0 fixtures loaded" or similar.

    Alternative test approach (simpler, more deterministic): use `monkeypatch` + direct `_score_fixture` call rather than subprocess — but RESEARCH explicitly lists subprocess as the test type. Use subprocess but mock the TickBrain LLM client at module-level if needed (the test mostly verifies output structure, not LLM accuracy).
  </behavior>
  <action>
    Step A — Create `scripts/eval_tick_brain.py`. Skeleton:

    ```python
    """Eval runner — score tick-brain judgment against labeled SituationSnapshot fixtures.

    Phase 18 — AUTO-09 / D-22.

    Usage:
        python scripts/eval_tick_brain.py
        python scripts/eval_tick_brain.py --fixtures evals/tick_brain/fixtures/
        python scripts/eval_tick_brain.py --model qwen3-32b

    Output:
        Overall precision/recall/F1 + per-trigger-type breakdown table.
        Errored bucket (parse_failure / llm_error) tracked separately per Pitfall 8.
    """
    from __future__ import annotations

    import argparse
    import glob
    import json
    import logging
    import os
    import re
    import sys
    from pathlib import Path

    logger = logging.getLogger("eval_tick_brain")

    _TRIGGER_TYPES = ["overdue", "gap", "silence", "followup", "quiet"]
    # NOTE 3 fix — VERIFIED safe-mode reasons emitted by core/tick_brain.py.
    # tick_brain.py:139,150,153 emit "llm_error"; lines 174,178 emit "parse_failure".
    # "fallback_failed" is NOT emitted anywhere — do not include it.
    _SAFE_MODE_REASONS = {"parse_failure", "llm_error"}
    _PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "autonomous_triage.md"


    def _load_fixtures(fixtures_dir: str) -> list[dict]:
        paths = sorted(glob.glob(os.path.join(fixtures_dir, "*.json")))
        out = []
        for p in paths:
            try:
                with open(p, encoding="utf-8") as f:
                    out.append(json.loads(f.read()))
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Could not load %s: %s", p, exc)
        return out


    def _render_prompt(fixture: dict) -> str:
        """Reuse core.autonomous._build_triage_prompt so eval matches production exactly.

        BLOCKER 4 — this import requires Plan 06's core/autonomous.py to exist;
        Plan 08's depends_on includes 06 to enforce that ordering.
        """
        from core.autonomous import _build_triage_prompt
        return _build_triage_prompt(fixture["situation_snapshot"], "")


    def _score_fixture(fixture: dict, tb) -> dict:
        """Run one fixture through tick-brain. Returns {predicted, ground_truth, errored, trigger_type}."""
        triage_system = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
        prompt = _render_prompt(fixture)
        try:
            verdict = tb.think(prompt, system_override=triage_system)
        except Exception as exc:
            logger.warning("fixture %s: think raised: %s", fixture.get("id"), exc)
            return {
                "id": fixture.get("id", ""),
                "trigger_type": fixture.get("trigger_type", "quiet"),
                "predicted": None,
                "ground_truth": bool(fixture["ground_truth"]["should_speak"]),
                "errored": True,
                "topic_key_ok": False,
            }
        # Pitfall 8 — treat safe-mode as errored, not as predicted-False.
        reason = str(verdict.get("reason", ""))
        if reason in _SAFE_MODE_REASONS and not verdict.get("should_act"):
            return {
                "id": fixture.get("id", ""),
                "trigger_type": fixture.get("trigger_type", "quiet"),
                "predicted": None,
                "ground_truth": bool(fixture["ground_truth"]["should_speak"]),
                "errored": True,
                "topic_key_ok": False,
            }
        predicted = bool(verdict.get("should_act", False))
        gt = bool(fixture["ground_truth"]["should_speak"])
        # topic_key pattern check (informational; not part of P/R but printed in detailed output)
        topic_ok = True
        if predicted and gt:
            pat = fixture["ground_truth"].get("topic_key_pattern", "")
            if pat:
                topic_ok = bool(re.match(pat, verdict.get("topic_key", "")))
        return {
            "id": fixture.get("id", ""),
            "trigger_type": fixture.get("trigger_type", "quiet"),
            "predicted": predicted,
            "ground_truth": gt,
            "errored": False,
            "topic_key_ok": topic_ok,
        }


    def _confusion(results: list[dict]) -> dict:
        """Aggregate TP/FP/TN/FN/errored from a list of per-fixture results."""
        tp = fp = tn = fn = errored = 0
        for r in results:
            if r["errored"]:
                errored += 1
                continue
            if r["predicted"] and r["ground_truth"]:
                tp += 1
            elif r["predicted"] and not r["ground_truth"]:
                fp += 1
            elif not r["predicted"] and not r["ground_truth"]:
                tn += 1
            else:
                fn += 1
        return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "errored": errored}


    def _metrics(conf: dict) -> dict:
        """Compute precision, recall, F1 from a confusion dict."""
        tp, fp, fn = conf["tp"], conf["fp"], conf["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        return {"precision": precision, "recall": recall, "f1": f1}


    def _print_report(results: list[dict]) -> None:
        total = len(results)
        if total == 0:
            print("0 fixtures loaded — nothing to score.")
            return
        overall = _confusion(results)
        m = _metrics(overall)
        print(f"=== Overall ({total} fixtures) ===")
        print(f"Precision: {m['precision']:.2f} ({overall['tp']}/{overall['tp']+overall['fp']})")
        print(f"Recall:    {m['recall']:.2f} ({overall['tp']}/{overall['tp']+overall['fn']})")
        print(f"F1:        {m['f1']:.2f}")
        print(f"Errored:   {overall['errored']}/{total}  (parse_failure or llm_error — NOT predicted-False)")
        print()
        print("=== Per-trigger-type ===")
        print(f"| {'Trigger':<10} | {'TP':>3} | {'FP':>3} | {'FN':>3} | {'TN':>3} | {'Err':>3} | {'Precision':>9} | {'Recall':>6} |")
        print(f"|{'-'*12}|{'-'*5}|{'-'*5}|{'-'*5}|{'-'*5}|{'-'*5}|{'-'*11}|{'-'*8}|")
        for t in _TRIGGER_TYPES:
            subset = [r for r in results if r["trigger_type"] == t]
            c = _confusion(subset)
            mm = _metrics(c)
            print(f"| {t:<10} | {c['tp']:>3} | {c['fp']:>3} | {c['fn']:>3} | {c['tn']:>3} | {c['errored']:>3} | {mm['precision']:>9.2f} | {mm['recall']:>6.2f} |")


    def main() -> int:
        parser = argparse.ArgumentParser(description="Eval tick-brain judgment against labeled fixtures.")
        parser.add_argument(
            "--fixtures",
            default="evals/tick_brain/fixtures",
            help="Directory containing fixture JSON files (default: evals/tick_brain/fixtures).",
        )
        parser.add_argument(
            "--model",
            default=os.environ.get("TICK_BRAIN_MODEL", ""),
            help="Tick-brain model name override (currently passed through to TickBrain if supported).",
        )
        args = parser.parse_args()

        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
        except ImportError:
            pass
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(message)s")

        fixtures = _load_fixtures(args.fixtures)
        if not fixtures:
            print(f"0 fixtures loaded from {args.fixtures!r}.")
            return 0

        try:
            from core.tick_brain import TickBrain
            tb = TickBrain()
        except Exception as exc:
            logger.error("Could not construct TickBrain (running with all-errored fallback): %s", exc)
            tb = None

        results = []
        for fx in fixtures:
            if tb is None:
                results.append({
                    "id": fx.get("id", ""),
                    "trigger_type": fx.get("trigger_type", "quiet"),
                    "predicted": None,
                    "ground_truth": bool(fx["ground_truth"]["should_speak"]),
                    "errored": True,
                    "topic_key_ok": False,
                })
            else:
                results.append(_score_fixture(fx, tb))

        _print_report(results)
        return 0


    if __name__ == "__main__":
        sys.exit(main())
    ```

    Step B — Create `tests/test_eval_script.py`:

    ```python
    """Subprocess-invocation tests for scripts/eval_tick_brain.py (AUTO-09)."""
    from __future__ import annotations

    import os
    import subprocess
    import sys

    import pytest


    REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    SCRIPT = os.path.join(REPO_ROOT, "scripts", "eval_tick_brain.py")
    FIXTURES = os.path.join(REPO_ROOT, "evals", "tick_brain", "fixtures")


    def _run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
        env_full = os.environ.copy()
        if env:
            env_full.update(env)
        # Force missing API key so the script falls back to the all-errored bucket
        # without requiring network. This tests the structure of the script, not the
        # tick-brain model's accuracy.
        env_full.setdefault("TICK_BRAIN_API_KEY", "")
        env_full.setdefault("GROQ_API_KEY", "")
        return subprocess.run(
            [sys.executable, SCRIPT, *args],
            capture_output=True, text=True, env=env_full, cwd=REPO_ROOT, timeout=60,
        )


    class TestEvalScript:

        def test_eval_runs_exits_zero(self):
            result = _run(["--fixtures", FIXTURES])
            assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

        def test_eval_output_contains_required_strings(self):
            result = _run(["--fixtures", FIXTURES])
            stdout = result.stdout
            for required in ("Precision:", "Recall:", "F1:", "Errored:"):
                assert required in stdout, f"Missing {required!r} in output:\n{stdout}"

        def test_eval_output_contains_per_trigger_table(self):
            result = _run(["--fixtures", FIXTURES])
            stdout = result.stdout
            assert "Per-trigger-type" in stdout
            for t in ("overdue", "gap", "silence", "followup", "quiet"):
                assert t in stdout, f"Missing trigger row {t!r} in output:\n{stdout}"

        def test_eval_handles_missing_fixtures_dir(self):
            result = _run(["--fixtures", "/nonexistent/path"])
            assert result.returncode == 0
            assert "0 fixtures loaded" in result.stdout
    ```

    Step C — Run the tests. **Important:** the eval script imports `core.tick_brain` which requires the API key env-vars. The tests set `TICK_BRAIN_API_KEY=""` to force the all-errored bucket — this validates the structure of the output without making network calls. If the TickBrain constructor itself fails on missing API key, the script catches it and runs with `tb = None`, producing all-errored results (still valid output structure). Adjust the test if TickBrain construction has other failure modes — read `core/tick_brain.py` to confirm.

    Step D — Manual smoke from project root: `python scripts/eval_tick_brain.py --fixtures evals/tick_brain/fixtures` should print the report and exit 0 (with everything in the Errored bucket if no API key set).
  </action>
  <verify>
    <automated>test -f scripts/eval_tick_brain.py && python -c "import ast; ast.parse(open('scripts/eval_tick_brain.py').read())" && pytest tests/test_eval_script.py -x</automated>
  </verify>
  <done>
    - `scripts/eval_tick_brain.py` exists and is at least 150 lines
    - `python -c "import ast; ast.parse(open('scripts/eval_tick_brain.py').read())"` succeeds (file is valid Python)
    - All 4 tests in `TestEvalScript` pass
    - Manual smoke: `python scripts/eval_tick_brain.py --fixtures evals/tick_brain/fixtures` exits 0 and prints expected strings
    - `grep -c "Precision:" scripts/eval_tick_brain.py` >= 1
    - `grep -c "Errored:" scripts/eval_tick_brain.py` >= 1
    - `grep -c "_SAFE_MODE_REASONS" scripts/eval_tick_brain.py` >= 2 (definition + use — Pitfall 8 protection)
    - `grep -c "fallback_failed" scripts/eval_tick_brain.py` == 0 (NOTE 3 — string is not emitted by tick_brain.py)
  </done>
</task>

</tasks>

<verification>
1. `pytest tests/test_eval_script.py -x` — all 4 tests pass
2. Manual smoke: `cd /Users/amitgrupper/Desktop/Klaus && python scripts/eval_tick_brain.py` exits 0 and produces the expected output structure
3. `grep -E "(Precision|Recall|F1|Errored)" scripts/eval_tick_brain.py | wc -l` >= 4 (the 4 output labels)
4. `grep -c "fallback_failed" scripts/eval_tick_brain.py` == 0 (NOTE 3)
</verification>

<success_criteria>
- Eval script exists, runs, exits 0 in all tested conditions (5 fixtures, missing dir, missing API key).
- Output format: overall P/R/F1/Errored + per-trigger table with all 5 trigger types.
- Pitfall 8 protected — safe-mode returns counted as Errored, not predicted-False.
- Subprocess-invoked test passes.
- BLOCKER 4: depends_on includes Plan 06 so `from core.autonomous import _build_triage_prompt` will succeed when Plan 08 runs.
- NOTE 3: `_SAFE_MODE_REASONS = {"parse_failure", "llm_error"}` — verified from tick_brain.py source.
</success_criteria>

<output>
After completion, create `.planning/phases/18-autonomous-engine/18-08-SUMMARY.md` listing:
- LOC of `scripts/eval_tick_brain.py`
- Sample of the output when run against the 5 seed fixtures (with no API key — all-errored)
- Test counts
- Confirmation that the `from core.autonomous import _build_triage_prompt` import succeeds at runtime (Plan 06 dep)
</output>
