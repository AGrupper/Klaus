#!/usr/bin/env python3
"""Measure the real Sonnet-5 token count of Klaus's always-on smart_system prompt.

Phase 30.5 Plan 04 — BRAIN-06 / D-08.

Purpose
-------
BRAIN-06's slimming acceptance criteria is "measurably smaller via `count_tokens`
on the real model, before/after numbers recorded" — never a char-count or
`tiktoken` estimate (Sonnet 5 uses a different tokenizer; see
`.planning/phases/30.5-brain-upgrade-sonnet-5/30.5-RESEARCH.md` §"Don't Hand-Roll").
This is a one-off measurement tool, not a pytest fixture and not a CI gate.

What it renders
----------------
Rebuilds the same smart_system assembly `core/main.py::AgentOrchestrator.
render_smart_system()` performs at request time — `{coaching_guide}` (the slim
core digest from docs/COACHING_GUIDE.md) + `{self_md}` (docs/SELF.md, the
compaction target of Task 1) + `prompts/smart_agent.md` (the de-prescription
target of Task 2) — WITHOUT instantiating a full `AgentOrchestrator` (which
needs live Firestore/Google credentials). The volatile, per-request sections
(`{self_state}`, `{journal_digest}`, `{training_profile}`, `{today_date}`,
`{current_time}`) are filled with fixed representative placeholder text instead
of live store reads, so the "before" and "after" measurements differ ONLY in
the two files this plan actually changes.

Usage
-----
    python scripts/measure_prompt_tokens.py
    python scripts/measure_prompt_tokens.py --label "after slimming"

Requires an Anthropic-backed API key in the environment. Checks, in order:
`ANTHROPIC_API_KEY`, `SMART_AGENT_API_KEY` (if `SMART_AGENT_BACKEND=anthropic`,
i.e. post-flip), `SMART_AGENT_FALLBACK_API_KEY` (if
`SMART_AGENT_FALLBACK_BACKEND=anthropic`, i.e. pre-flip — the current
`claude-haiku-4-5` fallback key, which is the only Anthropic key present
before Plan 06 flips the brain). This makes the script work identically
before and after the Plan 06 model flip.

Output
------
Prints `count.input_tokens` (the real Anthropic-tokenizer count) to stdout.
Exit code: 0 on success, 1 on a missing API key or a request failure — with a
clear, non-opaque error message either way.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Model the measurement targets — the real post-flip brain model (BRAIN-01).
# count_tokens works against any model id the account has access to; it does
# not require the brain to already be flipped to Sonnet in this environment.
_MEASURE_MODEL = "claude-sonnet-5"

# Fixed representative placeholder text for the volatile, per-request sections
# of the smart_system prompt. These are NOT slimming targets this plan — kept
# constant across "before" and "after" runs so the measured delta isolates the
# effect of docs/SELF.md (Task 1) and prompts/smart_agent.md (Task 2) changes.
_PLACEHOLDER_SELF_STATE = (
    "**Self-state:**\n"
    "- mood: steady\n"
    "- energy: normal\n"
    "- last_reflection: 2026-07-16"
)
_PLACEHOLDER_JOURNAL_DIGEST = (
    "**Recent journal:**\n"
    "- 2026-07-16 (mood: steady): Quiet day, training on track.\n"
    "- 2026-07-15 (mood: focused): Good lift, hit a new bench PR.\n"
    "- 2026-07-14 (mood: tired): Late shift, short on sleep."
)
_PLACEHOLDER_TRAINING_PROFILE = (
    "**Coaching reference — Amit's training plan:**\n"
    "Goals:\n"
    "  - Bench press (2026-10-01): 100kg\n"
    "  - Half marathon (2026-10-01): 1:25:00\n"
    "Daily targets: 180g protein / 350g carbs\n"
    "Block anchor: 2026-05-01 (Block Week 1)"
)
_PLACEHOLDER_TODAY_DATE = "Friday, 2026-07-17"
_PLACEHOLDER_CURRENT_TIME = "14:30"


def _load_self_md() -> str:
    """Read docs/SELF.md verbatim — the Task 1 compaction target."""
    path = _REPO_ROOT / "docs" / "SELF.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"ERROR: could not read {path}: {exc}") from exc


def _load_smart_agent_template() -> str:
    """Read prompts/smart_agent.md verbatim — the Task 2 de-prescription target."""
    path = _REPO_ROOT / "prompts" / "smart_agent.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"ERROR: could not read {path}: {exc}") from exc


def _load_coaching_guide_slim() -> str:
    """Extract the slim-core digest block from docs/COACHING_GUIDE.md.

    Mirrors `core/main.py::_load_coaching_guide_slim` exactly (same marker
    extraction) without importing core.main, which would pull in the full
    AgentOrchestrator's Firestore/Google credential stack. Returns "" if the
    file or markers are missing rather than raising — this is a measurement
    tool, not production code, and a missing guide shouldn't block the run.
    """
    path = _REPO_ROOT / "docs" / "COACHING_GUIDE.md"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(
        r"<!-- SLIM_CORE_START -->(.*?)<!-- SLIM_CORE_END -->", content, re.DOTALL
    )
    return match.group(1).strip() if match else ""


def render_placeholder_smart_system() -> str:
    """Assemble the smart_system prompt exactly as `render_smart_system` does.

    Stable sections (coaching_guide, self_md, the smart_agent.md template
    body) use their real committed content — these are what BRAIN-06 slims.
    Volatile sections use fixed placeholder text so the measurement isolates
    the slimming effect (D-08).
    """
    template = _load_smart_agent_template()
    return (
        template
        .replace("{coaching_guide}", _load_coaching_guide_slim())
        .replace("{self_md}", _load_self_md())
        .replace("{self_state}", _PLACEHOLDER_SELF_STATE)
        .replace("{journal_digest}", _PLACEHOLDER_JOURNAL_DIGEST)
        .replace("{training_profile}", _PLACEHOLDER_TRAINING_PROFILE)
        .replace("{today_date}", _PLACEHOLDER_TODAY_DATE)
        .replace("{current_time}", _PLACEHOLDER_CURRENT_TIME)
    )


def _resolve_anthropic_api_key() -> str:
    """Find an Anthropic-backed API key regardless of pre/post Plan-06 flip state.

    Checked in order:
      1. ANTHROPIC_API_KEY — explicit override, always wins if set.
      2. SMART_AGENT_API_KEY — valid once SMART_AGENT_BACKEND=anthropic
         (post-flip, Plan 06).
      3. SMART_AGENT_FALLBACK_API_KEY — valid while
         SMART_AGENT_FALLBACK_BACKEND=anthropic (pre-flip today — this is the
         existing claude-haiku-4-5 fallback key, the only Anthropic key
         present in this environment before Plan 06 ships).

    Raises SystemExit with a clear, actionable message if none is usable —
    never crashes opaquely on a KeyError deep inside the SDK.
    """
    explicit = os.environ.get("ANTHROPIC_API_KEY")
    if explicit:
        return explicit

    if os.environ.get("SMART_AGENT_BACKEND") == "anthropic":
        key = os.environ.get("SMART_AGENT_API_KEY")
        if key:
            return key

    if os.environ.get("SMART_AGENT_FALLBACK_BACKEND") == "anthropic":
        key = os.environ.get("SMART_AGENT_FALLBACK_API_KEY")
        if key:
            return key

    raise SystemExit(
        "ERROR: no Anthropic API key found in the environment.\n"
        "Checked ANTHROPIC_API_KEY, SMART_AGENT_API_KEY (needs "
        "SMART_AGENT_BACKEND=anthropic), and SMART_AGENT_FALLBACK_API_KEY "
        "(needs SMART_AGENT_FALLBACK_BACKEND=anthropic).\n"
        "Set one of these before running scripts/measure_prompt_tokens.py."
    )


def measure(rendered_smart_system: str) -> int:
    """Call the real Anthropic count_tokens endpoint and return input_tokens.

    Uses the live `claude-sonnet-5` tokenizer via `anthropic.Anthropic(...)
    .messages.count_tokens(...)` — never a character-count estimate and never
    `tiktoken` (wrong tokenizer family for Anthropic models).
    """
    try:
        import anthropic
    except ImportError as exc:
        raise SystemExit(
            "ERROR: the `anthropic` package is not installed in this "
            "environment. Install it (it's already a project dependency) "
            "before running this script."
        ) from exc

    api_key = _resolve_anthropic_api_key()
    client = anthropic.Anthropic(api_key=api_key)
    try:
        count = client.messages.count_tokens(
            model=_MEASURE_MODEL,
            system=rendered_smart_system,
            messages=[{"role": "user", "content": "placeholder"}],
        )
    except anthropic.APIStatusError as exc:
        raise SystemExit(
            f"ERROR: Anthropic count_tokens call failed ({exc.status_code}): "
            f"{exc.message}"
        ) from exc
    return count.input_tokens


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure the real Sonnet-5 token count of Klaus's always-on "
            "smart_system prompt (docs/SELF.md + prompts/smart_agent.md)."
        )
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Optional label for this run, e.g. 'before' or 'after' — echoed in the output.",
    )
    args = parser.parse_args()

    rendered = render_placeholder_smart_system()
    input_tokens = measure(rendered)

    label = f" [{args.label}]" if args.label else ""
    print(f"input_tokens{label}: {input_tokens}")
    print(f"rendered_chars{label}: {len(rendered)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
