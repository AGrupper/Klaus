"""Smoke tests for repo CLI scripts (phase 19.1+).

Subprocess pattern — runs each script with --help and asserts exit 0.
Avoids importing the scripts directly so import-time side effects don't
leak into the pytest process.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_healthkit_push_script_help_exits_zero():
    """HEALTHKIT-08 — CLI is importable AND prints --help text."""
    script = _REPO_ROOT / "scripts" / "test_healthkit_push.py"
    assert script.exists(), f"missing CLI: {script}"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"non-zero exit: stderr={result.stderr}"
    assert (
        "HealthKit" in result.stdout or "healthkit" in result.stdout.lower()
    ), f"--help output missing 'HealthKit': {result.stdout[:300]}"
