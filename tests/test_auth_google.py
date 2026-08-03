"""Tests for core/auth_google.py — OAuth scope constants, SCOPES list, and
the explicit Google API socket timeout wiring.

Phase 19 Plan 03 adds FITNESS_NUTRITION_READ_SCOPE for Google Fit nutrition
reads (Lifesum-sourced meal sync). The scope addition invalidates the cached
token, so operator must re-consent before deploy (Pitfall 1).

The timeout tests below cover the production fix for recurring
`TimeoutError: The read operation timed out` calendar-gather failures
(2026-08-01..03): every Gmail/Calendar service now gets an explicit, bounded,
env-configurable httplib2 socket timeout instead of relying on an SDK
default, mirroring the LLM_TIMEOUT_SECONDS invariant.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_fitness_scope_constant_exists():
    """PHASE 19-03 NUTR-01: FITNESS_NUTRITION_READ_SCOPE constant is defined."""
    from core.auth_google import FITNESS_NUTRITION_READ_SCOPE
    assert FITNESS_NUTRITION_READ_SCOPE == "https://www.googleapis.com/auth/fitness.nutrition.read"


def test_scopes_list_excludes_fitness():
    """PHASE 19-03 NUTR-01: GoogleAuthManager.SCOPES does NOT contain the fitness scope."""
    from core.auth_google import GoogleAuthManager, FITNESS_NUTRITION_READ_SCOPE
    assert FITNESS_NUTRITION_READ_SCOPE not in GoogleAuthManager.SCOPES


def _mgr_with_stub_creds() -> "object":
    from core.auth_google import GoogleAuthManager

    mgr = GoogleAuthManager(credentials_path="unused", token_storage=MagicMock())
    mgr.get_credentials = MagicMock(return_value=MagicMock())
    return mgr


def test_authorized_http_defaults_to_30_second_timeout(monkeypatch):
    """No GOOGLE_API_TIMEOUT_SECONDS set → defaults to 30s, not httplib2's
    own undocumented default."""
    monkeypatch.delenv("GOOGLE_API_TIMEOUT_SECONDS", raising=False)
    mgr = _mgr_with_stub_creds()

    with patch("core.auth_google.httplib2.Http") as http_cls:
        mgr._authorized_http()

    http_cls.assert_called_once_with(timeout=30.0)


def test_authorized_http_respects_env_override(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_TIMEOUT_SECONDS", "12")
    mgr = _mgr_with_stub_creds()

    with patch("core.auth_google.httplib2.Http") as http_cls:
        mgr._authorized_http()

    http_cls.assert_called_once_with(timeout=12.0)


def test_authorized_http_wraps_credentials_via_authorizedhttp(monkeypatch):
    """The bounded-timeout httplib2.Http must actually be handed to the
    credentials-refreshing AuthorizedHttp wrapper, not built standalone."""
    monkeypatch.delenv("GOOGLE_API_TIMEOUT_SECONDS", raising=False)
    mgr = _mgr_with_stub_creds()
    creds = mgr.get_credentials()

    with patch("core.auth_google.httplib2.Http") as http_cls, \
         patch("core.auth_google.AuthorizedHttp") as authed_cls:
        http_instance = http_cls.return_value
        result = mgr._authorized_http()

    authed_cls.assert_called_once_with(creds, http=http_instance)
    assert result is authed_cls.return_value


def test_gmail_service_passes_http_not_credentials(monkeypatch):
    """build() must receive http= (our timeout-bounded client), never
    credentials= directly — passing both raises in googleapiclient, and
    credentials= alone is exactly the path that silently inherits whatever
    default timeout the SDK happens to pick."""
    monkeypatch.delenv("GOOGLE_API_TIMEOUT_SECONDS", raising=False)
    mgr = _mgr_with_stub_creds()

    with patch("core.auth_google.build") as build_fn:
        mgr.gmail_service()

    _, kwargs = build_fn.call_args
    assert "http" in kwargs
    assert "credentials" not in kwargs
    assert kwargs["cache_discovery"] is False


def test_calendar_service_passes_http_not_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_TIMEOUT_SECONDS", raising=False)
    mgr = _mgr_with_stub_creds()

    with patch("core.auth_google.build") as build_fn:
        mgr.calendar_service()

    _, kwargs = build_fn.call_args
    assert "http" in kwargs
    assert "credentials" not in kwargs
