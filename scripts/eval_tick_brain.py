#!/usr/bin/env python3
"""Eval runner — score tick-brain judgment against labeled SituationSnapshot fixtures.

Phase 18 — AUTO-09 / D-22.

Purpose
-------
Phase 18 is a measurement-driven phase. This script turns "judgment" from vibes
into a number. Day-one runs against 5 seed fixtures; the workflow grows to
20–30 fixtures over the following weeks per D-21.

Usage
-----
    python scripts/eval_tick_brain.py
    python scripts/eval_tick_brain.py --fixtures evals/tick_brain/fixtures/
    python scripts/eval_tick_brain.py --model qwen3-32b

Output
------
Overall precision/recall/F1 + per-trigger-type breakdown table.

Buckets per fixture:
    * Predicted True / False           — tick-brain returned should_act
    * Ground truth True / False        — fixture's ground_truth.should_speak
    * Errored (Pitfall 8)              — safe-mode returns (parse_failure /
                                         llm_error) are tracked SEPARATELY,
                                         NOT counted as "predicted False".

Exit code: always 0 — this is a measurement tool, NOT a CI gate.
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

# Ensure the repo root is on sys.path so `from core.autonomous import ...`
# works whether the script is invoked directly (`python scripts/eval_tick_brain.py`)
# or via PYTHONPATH=. This mirrors the import style of every other CLI in the
# repo and removes the need for callers to know the project layout.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger("eval_tick_brain")

# All trigger types present in the fixture inventory. Per-trigger rows are
# rendered in this fixed order so the output is grep-able and diff-stable.
_TRIGGER_TYPES = ["overdue", "gap", "silence", "followup", "quiet"]

# Safe-mode reasons emitted by core/tick_brain.py (VERIFIED — NOTE 3 fix):
#   * lines 154, 165, 168  emit {"should_act": False, "reason": "llm_error"}
#   * line  189            emits {"should_act": False, "reason": "parse_failure"}
# These two strings are the ONLY safe-mode reason values emitted anywhere by
# tick_brain.py — do not extend this set without re-verifying the source.
# Pitfall 8 depends on the literal match here.
_SAFE_MODE_REASONS = {"parse_failure", "llm_error"}

# Path to the autonomous triage system prompt (Plan 03 output). Read at runtime
# and passed to TickBrain.think(..., system_override=...) so eval prompt
# rendering matches production exactly (Pitfall: "use the production prompt").
_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "autonomous_triage.md"
)


# --------------------------------------------------------------------------- #
# Fixture loading                                                             #
# --------------------------------------------------------------------------- #


def _load_fixtures(fixtures_dir: str) -> list[dict]:
    """Glob `*.json` from ``fixtures_dir`` and return parsed fixture dicts.

    Returns ``[]`` (and logs nothing fatal) if the directory is missing or
    empty. Per-file parse errors are logged at ERROR but never raise — the
    eval is best-effort and exit-0-always.
    """
    pattern = os.path.join(fixtures_dir, "*.json")
    paths = sorted(glob.glob(pattern))
    out: list[dict] = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.loads(f.read()))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Could not load %s: %s", p, exc)
    return out


# --------------------------------------------------------------------------- #
# Prompt rendering — reuse production code                                    #
# --------------------------------------------------------------------------- #


def _render_prompt(fixture: dict) -> str:
    """Reuse ``core.autonomous._build_triage_prompt`` so the eval prompt
    matches production byte-for-byte.

    BLOCKER 4: this import requires Plan 06's ``core/autonomous.py``. Plan
    08's ``depends_on`` includes 06 to enforce that ordering — without it,
    selective execution could run Plan 08 first and raise ImportError.
    """
    from core.autonomous import _build_triage_prompt  # noqa: PLC0415 — runtime import keeps CLI startup snappy.
    return _build_triage_prompt(fixture["situation_snapshot"], "")


# --------------------------------------------------------------------------- #
# Per-fixture scoring                                                         #
# --------------------------------------------------------------------------- #


def _score_fixture(fixture: dict, tb) -> dict:
    """Run one fixture through tick-brain. Returns a per-fixture result dict.

    Result schema:
        {
          "id":            str    — fixture id (filename stem)
          "trigger_type":  str    — one of _TRIGGER_TYPES
          "predicted":     bool | None  — None when errored (Pitfall 8)
          "ground_truth":  bool
          "errored":       bool   — True for safe-mode / exception
          "topic_key_ok":  bool   — informational; not part of P/R
        }
    """
    triage_system = (
        _PROMPT_PATH.read_text(encoding="utf-8")
        if _PROMPT_PATH.exists()
        else ""
    )
    prompt = _render_prompt(fixture)
    try:
        verdict = tb.think(prompt, system_override=triage_system)
    except Exception as exc:  # noqa: BLE001 — eval must never crash on a bad LLM call
        logger.warning(
            "fixture %s: think raised %s", fixture.get("id"), exc
        )
        return _errored_result(fixture)

    # Pitfall 8 — safe-mode returns are NOT "predicted False".
    reason = str(verdict.get("reason", ""))
    if reason in _SAFE_MODE_REASONS and not verdict.get("should_act"):
        return _errored_result(fixture)

    predicted = bool(verdict.get("should_act", False))
    gt = bool(fixture["ground_truth"]["should_speak"])

    # topic_key pattern check (informational only — printed in detailed
    # output, never folded into precision/recall).
    topic_ok = True
    if predicted and gt:
        pat = fixture["ground_truth"].get("topic_key_pattern", "")
        if pat:
            topic_ok = bool(re.match(pat, str(verdict.get("topic_key", ""))))

    return {
        "id": fixture.get("id", ""),
        "trigger_type": fixture.get("trigger_type", "quiet"),
        "predicted": predicted,
        "ground_truth": gt,
        "errored": False,
        "topic_key_ok": topic_ok,
    }


def _errored_result(fixture: dict) -> dict:
    """Build a per-fixture result dict for an errored / safe-mode tick."""
    return {
        "id": fixture.get("id", ""),
        "trigger_type": fixture.get("trigger_type", "quiet"),
        "predicted": None,
        "ground_truth": bool(fixture["ground_truth"]["should_speak"]),
        "errored": True,
        "topic_key_ok": False,
    }


# --------------------------------------------------------------------------- #
# Aggregation and metrics                                                     #
# --------------------------------------------------------------------------- #


def _confusion(results: list[dict]) -> dict:
    """Aggregate TP / FP / TN / FN / errored over a list of per-fixture results."""
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
    """Compute precision / recall / F1 from a confusion dict.

    Zero-denominator cases return 0.0 (rather than raising) so the report
    still prints when no positives or no negatives are present.
    """
    tp, fp, fn = conf["tp"], conf["fp"], conf["fn"]
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


# --------------------------------------------------------------------------- #
# Reporting                                                                   #
# --------------------------------------------------------------------------- #


def _print_report(results: list[dict]) -> None:
    """Render the overall + per-trigger report to stdout.

    Logs go to stderr (configured in ``main``); the report uses ``print`` so
    pipelines can grep stdout cleanly.
    """
    total = len(results)
    if total == 0:
        print("0 fixtures loaded — nothing to score.")
        return

    print("=== Per-fixture ===")
    for r in results:
        if r["errored"]:
            verdict = "ERR"
        elif r["predicted"] == r["ground_truth"]:
            verdict = "ok "
        else:
            verdict = "FP " if r["predicted"] else "FN "
        print(
            f"{verdict} {r['id']:<40} pred={str(r['predicted']):<5} "
            f"gt={str(r['ground_truth']):<5} ({r['trigger_type']})"
        )
    print()

    overall = _confusion(results)
    m = _metrics(overall)
    print(f"=== Overall ({total} fixtures) ===")
    print(
        f"Precision: {m['precision']:.2f} "
        f"({overall['tp']}/{overall['tp'] + overall['fp']})"
    )
    print(
        f"Recall:    {m['recall']:.2f} "
        f"({overall['tp']}/{overall['tp'] + overall['fn']})"
    )
    print(f"F1:        {m['f1']:.2f}")
    print(
        f"Errored:   {overall['errored']}/{total}  "
        f"(parse_failure or llm_error — NOT predicted-False)"
    )
    print()
    print("=== Per-trigger-type ===")
    header = (
        f"| {'Trigger':<10} | {'TP':>3} | {'FP':>3} | "
        f"{'FN':>3} | {'TN':>3} | {'Err':>3} | "
        f"{'Precision':>9} | {'Recall':>6} |"
    )
    sep = (
        f"|{'-' * 12}|{'-' * 5}|{'-' * 5}|"
        f"{'-' * 5}|{'-' * 5}|{'-' * 5}|"
        f"{'-' * 11}|{'-' * 8}|"
    )
    print(header)
    print(sep)
    for t in _TRIGGER_TYPES:
        subset = [r for r in results if r["trigger_type"] == t]
        c = _confusion(subset)
        mm = _metrics(c)
        print(
            f"| {t:<10} | {c['tp']:>3} | {c['fp']:>3} | "
            f"{c['fn']:>3} | {c['tn']:>3} | {c['errored']:>3} | "
            f"{mm['precision']:>9.2f} | {mm['recall']:>6.2f} |"
        )


# --------------------------------------------------------------------------- #
# CLI entry point                                                             #
# --------------------------------------------------------------------------- #


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Eval tick-brain judgment against labeled fixtures. "
            "Exits 0 always (measurement tool, not a CI gate)."
        ),
    )
    parser.add_argument(
        "--fixtures",
        default="evals/tick_brain/fixtures",
        help=(
            "Directory containing fixture JSON files "
            "(default: evals/tick_brain/fixtures)."
        ),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("TICK_BRAIN_MODEL", ""),
        help=(
            "Tick-brain model name override. Currently informational only — "
            "TickBrain() reads TICK_BRAIN_MODEL from env, so this flag "
            "exports the value into the env before constructing the client."
        ),
    )
    return parser


def main() -> int:
    """CLI entry point. Always returns 0 — this is a measurement tool."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    # Best-effort .env load — works in dev, harmless in CI.
    # EVAL_SKIP_DOTENV: tests/test_eval_script.py strips the API keys from the
    # subprocess env to force the offline all-errored path; without this knob
    # the override=True load would re-import TICK_BRAIN_API_KEY from .env and
    # turn the structure tests into 25 live LLM calls.
    if not os.getenv("EVAL_SKIP_DOTENV"):
        try:
            from dotenv import load_dotenv  # noqa: PLC0415 — optional dep
            load_dotenv(override=True)
        except ImportError:
            pass

    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(message)s",
    )

    # Honour --model by exporting into env so TickBrain.__init__ picks it up.
    if args.model:
        os.environ["TICK_BRAIN_MODEL"] = args.model

    fixtures = _load_fixtures(args.fixtures)
    if not fixtures:
        print(f"0 fixtures loaded from {args.fixtures!r}.")
        return 0

    # Construct TickBrain. If env-vars are missing (no TICK_BRAIN_API_KEY),
    # __init__ raises ValueError — we catch and fall back to tb=None so the
    # report still prints (all fixtures land in the errored bucket).
    try:
        from core.tick_brain import TickBrain  # noqa: PLC0415
        tb = TickBrain()
    except Exception as exc:  # noqa: BLE001 — eval is best-effort
        logger.error(
            "Could not construct TickBrain (running with all-errored "
            "fallback): %s",
            exc,
        )
        tb = None

    results: list[dict] = []
    for fx in fixtures:
        if tb is None:
            results.append(_errored_result(fx))
        else:
            results.append(_score_fixture(fx, tb))

    _print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
