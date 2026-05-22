"""Tests for AgentOrchestrator.render_smart_system — Phase 18-06 Task 0.

The render method is a pure refactor extraction from handle_message. It
substitutes the 4 standard placeholders {self_md}, {self_state},
{journal_digest}, {today_date} into a smart-system template.

It is invoked by:
  - handle_message (per-message chat path) — extracted from inline render
  - core/autonomous.py:_compose_layer2 (per-tick autonomous path) — Plan 18-06

Test strategy
-------------
Firestore + google.* are mocked at the sys.modules level using the same
_install_firestore_mock() pattern from tests/test_reflection.py so that
core.main can be imported with no real Google API libraries installed.
"""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Firestore + google.* mock — installed BEFORE any core.main import
# ---------------------------------------------------------------------------

def _install_firestore_mock() -> None:
    """Install mock google.cloud.firestore + auth stubs into sys.modules."""
    if "google.cloud.firestore" not in sys.modules:
        google_mod = sys.modules.setdefault("google", MagicMock())
        google_cloud_mod = sys.modules.setdefault("google.cloud", MagicMock())
        firestore_mock = MagicMock()

        class _Increment:
            def __init__(self, value):
                self.value = value
            def __repr__(self):
                return f"Increment({self.value!r})"

        firestore_mock.Increment = _Increment
        firestore_mock.SERVER_TIMESTAMP = object()
        firestore_mock.ArrayUnion = MagicMock()

        sys.modules["google.cloud.firestore"] = firestore_mock
        google_cloud_mod.firestore = firestore_mock
        google_mod.cloud = google_cloud_mod

        api_core = sys.modules.setdefault("google.api_core", MagicMock())
        exc_mod = MagicMock()
        exc_mod.GoogleAPICallError = Exception
        sys.modules["google.api_core.exceptions"] = exc_mod
        api_core.exceptions = exc_mod

        fv1 = sys.modules.setdefault("google.cloud.firestore_v1", MagicMock())
        bq = MagicMock()
        bq.FieldFilter = MagicMock()
        sys.modules["google.cloud.firestore_v1.base_query"] = bq
        fv1.base_query = bq

    # Unconditionally install auth + googleapiclient stubs so core/auth_google,
    # core/tools (imported transitively by core.main) load cleanly without the
    # real Google libraries.
    sys.modules.setdefault("google.auth", MagicMock())
    sys.modules.setdefault("google.auth.exceptions", MagicMock())
    sys.modules.setdefault("google.auth.transport", MagicMock())
    sys.modules.setdefault("google.auth.transport.requests", MagicMock())
    sys.modules.setdefault("google.oauth2", MagicMock())
    sys.modules.setdefault("google.oauth2.credentials", MagicMock())
    sys.modules.setdefault("google.oauth2.service_account", MagicMock())
    sys.modules.setdefault("google_auth_oauthlib", MagicMock())
    sys.modules.setdefault("google_auth_oauthlib.flow", MagicMock())
    sys.modules.setdefault("googleapiclient", MagicMock())
    sys.modules.setdefault("googleapiclient.errors", MagicMock())
    sys.modules.setdefault("googleapiclient.discovery", MagicMock())

    dotenv_mod = MagicMock()
    dotenv_mod.load_dotenv = MagicMock()
    sys.modules.setdefault("dotenv", dotenv_mod)


_install_firestore_mock()


# ---------------------------------------------------------------------------
# Orchestrator factory
# ---------------------------------------------------------------------------

def _make_orchestrator(
    *,
    self_md: str = "SELF.MD-CONTENT",
    self_state_store=None,
    journal_store=None,
):
    """Construct an AgentOrchestrator with all heavy dependencies stubbed.

    The orchestrator is NOT initialised via __init__ (which would talk to
    LLM backends and Firestore). Instead, we manually attach the four
    attributes that render_smart_system reads.
    """
    from core.main import AgentOrchestrator
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._self_md_content = self_md
    orchestrator._self_state_store = self_state_store
    orchestrator._journal_store = journal_store
    orchestrator._smart_prompt_template = (
        "SMART_PROMPT\n{self_md}\n---\n{self_state}\n---\n"
        "{journal_digest}\n---\n{today_date}\nEND"
    )
    return orchestrator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_render_substitutes_self_md():
    """{self_md} is replaced with the orchestrator's _self_md_content."""
    orch = _make_orchestrator(self_md="Klaus-identity-block")
    out = orch.render_smart_system("Header\n{self_md}\nFooter")
    assert "Klaus-identity-block" in out
    assert "{self_md}" not in out


def test_render_self_state_none_substitutes_empty_string():
    """When _self_state_store is None, {self_state} -> '' (not literal placeholder)."""
    orch = _make_orchestrator(self_state_store=None)
    out = orch.render_smart_system("A\n{self_state}\nB")
    assert "{self_state}" not in out
    # The placeholder line collapsed to an empty replacement, not the literal token.
    assert "A\n\nB" in out


def test_render_journal_none_substitutes_empty_string():
    """When _journal_store is None, {journal_digest} -> '' (not literal placeholder)."""
    orch = _make_orchestrator(journal_store=None)
    out = orch.render_smart_system("X\n{journal_digest}\nY")
    assert "{journal_digest}" not in out
    assert "X\n\nY" in out


def test_render_today_date_substituted():
    """{today_date} is replaced with the result of _today_israel()."""
    orch = _make_orchestrator()
    with patch("core.main._today_israel", return_value="Saturday, May 23, 2026"):
        out = orch.render_smart_system("Date: {today_date}")
    assert "Saturday, May 23, 2026" in out
    assert "{today_date}" not in out


def test_render_no_unresolved_placeholders():
    """After rendering, none of the 4 placeholder tokens remain in the output."""
    orch = _make_orchestrator()
    template = (
        "{self_md}\n{self_state}\n{journal_digest}\n{today_date}\n"
        "{self_md}\n{today_date}"  # repeated tokens still replaced
    )
    out = orch.render_smart_system(template)
    for token in ("{self_md}", "{self_state}", "{journal_digest}", "{today_date}"):
        assert token not in out, f"placeholder {token} survived render"


def test_render_self_state_populated_block():
    """When _self_state_store returns non-empty state, the rendered block lists fields."""
    fake_store = MagicMock()
    fake_store.get.return_value = {
        "current_focus": "phase 18 wave 2",
        "mood": "focused",
        "updated_at": "ignored",
        "bootstrapped_at": "ignored",
        "empty_field": "",  # blank values are filtered out per D-05
    }
    orch = _make_orchestrator(self_state_store=fake_store)
    out = orch.render_smart_system("{self_state}")
    assert "current_focus: phase 18 wave 2" in out
    assert "mood: focused" in out
    # Bookkeeping fields are filtered
    assert "updated_at" not in out
    assert "bootstrapped_at" not in out
    # Empty field omitted (D-05)
    assert "empty_field" not in out
    assert "**Self-state:**" in out


def test_render_journal_digest_populated_block():
    """When _journal_store has recent entries, render includes a digest block."""
    fake_store = MagicMock()
    fake_store.get_recent.return_value = [
        {
            "date": "2026-05-21",
            "mood": "focused",
            "summary": "shipped plan 05",
            "highlights": ["green tests"],
        },
        {
            "date": "2026-05-20",
            "mood": "ok",
            "summary": "wave 1 wrap",
            "highlights": [],
        },
    ]
    orch = _make_orchestrator(journal_store=fake_store)
    out = orch.render_smart_system("{journal_digest}")
    assert "**Recent journal:**" in out
    assert "2026-05-21" in out
    assert "shipped plan 05" in out
    assert "green tests" in out  # highlight line included
    assert "2026-05-20" in out


def test_handle_message_uses_render_smart_system():
    """Regression: handle_message calls render_smart_system (not the inline render)."""
    import inspect
    from core.main import AgentOrchestrator

    source = inspect.getsource(AgentOrchestrator.handle_message)
    # The new contract: handle_message must call self.render_smart_system.
    assert "self.render_smart_system" in source, (
        "handle_message should delegate render to render_smart_system"
    )
    # The old inline render block (constructing smart_system via 4 .replace calls)
    # must no longer appear in handle_message.
    assert ".replace(\"{self_md}\"" not in source, (
        "handle_message still contains inline render — refactor incomplete"
    )
