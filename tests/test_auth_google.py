"""Tests for core/auth_google.py — OAuth scope constants and SCOPES list.

Phase 19 Plan 03 adds FITNESS_NUTRITION_READ_SCOPE for Google Fit nutrition
reads (Lifesum-sourced meal sync). The scope addition invalidates the cached
token, so operator must re-consent before deploy (Pitfall 1).
"""
from __future__ import annotations


def test_fitness_scope_constant_exists():
    """PHASE 19-03 NUTR-01: FITNESS_NUTRITION_READ_SCOPE constant is defined."""
    from core.auth_google import FITNESS_NUTRITION_READ_SCOPE
    assert FITNESS_NUTRITION_READ_SCOPE == "https://www.googleapis.com/auth/fitness.nutrition.read"


def test_scopes_list_includes_fitness():
    """PHASE 19-03 NUTR-01: GoogleAuthManager.SCOPES contains the fitness scope."""
    from core.auth_google import GoogleAuthManager, FITNESS_NUTRITION_READ_SCOPE
    assert FITNESS_NUTRITION_READ_SCOPE in GoogleAuthManager.SCOPES
