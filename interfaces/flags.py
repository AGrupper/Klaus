"""Environment feature flags for the Klaus service.

Klaus's rollout is flag-driven: MCP mounting, each Claude routine, and the
per-routine shadow/live cutover are all gated by environment variables so a
surface can be switched off in production without a code change. These readers
live outside web_server because both the composition root and individual route
modules need them, and a second copy of "what counts as true" is how a flag ends
up enabled in one place and disabled in another.
"""
from __future__ import annotations

import os


def _flag_enabled(name: str, *, default: bool = False) -> bool:
    """Return a strict boolean feature flag from the environment."""
    fallback = "true" if default else "false"
    return os.environ.get(name, fallback).strip().lower() in {"1", "true", "yes", "on"}


def _subscription_capability_gate() -> dict:
    """Report the four manual Claude Pro proofs that must precede cutover."""
    checks = {
        "mcp_connector_verified": _flag_enabled("KLAUS_CAPABILITY_MCP_VERIFIED"),
        "private_skill_verified": _flag_enabled("KLAUS_CAPABILITY_SKILL_VERIFIED"),
        "remote_routine_verified": _flag_enabled("KLAUS_CAPABILITY_ROUTINE_VERIFIED"),
        "routine_publish_verified": _flag_enabled("KLAUS_CAPABILITY_PUBLISH_VERIFIED"),
    }
    return {**checks, "passed": all(checks.values())}


def _routine_cutover_enabled(routine: str) -> bool:
    """Return whether one routine has independently cut over to Claude."""
    return (
        _flag_enabled("KLAUS_MCP_ENABLED")
        and _flag_enabled("KLAUS_CLAUDE_ROUTINES_ENABLED")
        and _subscription_capability_gate()["passed"]
        and _flag_enabled(f"KLAUS_ROUTINE_{routine.upper()}_CUTOVER")
    )
