"""Subprocess-invocation tests for scripts/eval_tick_brain.py (AUTO-09).

Phase 18 — Plan 08. These tests validate the *structure* of the eval runner's
output, not the accuracy of tick-brain's predictions. They force the
TICK_BRAIN_API_KEY env-var to empty so the script falls back to the
all-errored bucket without making network calls.
"""
from __future__ import annotations

import os
import subprocess
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "eval_tick_brain.py")
FIXTURES = os.path.join(REPO_ROOT, "evals", "tick_brain", "fixtures")


def _run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the eval script via subprocess with API keys cleared.

    Clearing TICK_BRAIN_API_KEY (and GROQ_API_KEY) forces TickBrain.__init__ to
    raise ValueError, which the script catches and falls back to tb=None — all
    fixtures land in the 'errored' bucket. This tests output structure without
    network dependence.
    """
    env_full = os.environ.copy()
    # Forcibly delete API keys so TickBrain construction fails predictably.
    for k in ("TICK_BRAIN_API_KEY", "GROQ_API_KEY", "SMART_AGENT_API_KEY"):
        env_full.pop(k, None)
    if env:
        env_full.update(env)
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        env=env_full,
        cwd=REPO_ROOT,
        timeout=60,
    )


class TestEvalScript:
    """Subprocess tests for the eval runner (AUTO-09)."""

    def test_eval_runs_exits_zero(self):
        """Script must exit 0 even with no API key and all fixtures errored."""
        result = _run(["--fixtures", FIXTURES])
        assert result.returncode == 0, (
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    def test_eval_output_contains_required_strings(self):
        """Output must contain all four canonical metric labels."""
        result = _run(["--fixtures", FIXTURES])
        stdout = result.stdout
        for required in ("Precision:", "Recall:", "F1:", "Errored:"):
            assert required in stdout, (
                f"Missing {required!r} in output:\n{stdout}"
            )

    def test_eval_output_contains_per_trigger_table(self):
        """Output must contain the per-trigger-type breakdown with all 5 rows."""
        result = _run(["--fixtures", FIXTURES])
        stdout = result.stdout
        assert "Per-trigger-type" in stdout, (
            f"Missing per-trigger header in output:\n{stdout}"
        )
        for trigger in ("overdue", "gap", "silence", "followup", "quiet"):
            assert trigger in stdout, (
                f"Missing trigger row {trigger!r} in output:\n{stdout}"
            )

    def test_eval_handles_missing_fixtures_dir(self):
        """A missing fixtures directory must exit 0 and report 0 fixtures."""
        result = _run(["--fixtures", "/nonexistent/path/that/does/not/exist"])
        assert result.returncode == 0, (
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "0 fixtures loaded" in result.stdout, (
            f"Missing '0 fixtures loaded' marker in output:\n{result.stdout}"
        )
