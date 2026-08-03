"""Tests for GmailTool — timeout degradation and bounded-retry wiring.

Companion to tests/test_calendar_tool.py's timeout-degradation coverage:
production fix for recurring `TimeoutError: The read operation timed out`
failures against Google's discovery-client APIs (2026-08-01..03). A raw
socket-level TimeoutError/ssl.SSLError is not an HttpError — GmailTool must
still catch it and degrade to its documented empty/error sentinel rather than
letting it propagate.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import mcp_tools.gmail_tool as gmail


def _tool():
    return gmail.GmailTool(MagicMock())


def _chain(result):
    """Return a mock request object whose .execute() yields result (or raises)."""
    c = MagicMock()
    if isinstance(result, Exception):
        c.execute.side_effect = result
    else:
        c.execute.return_value = result
    return c


def test_list_unread_degrades_gracefully_on_timeout_error():
    t = _tool()
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value = _chain(
        TimeoutError("The read operation timed out")
    )
    with patch.object(t, "_get_service", return_value=service):
        result = t.list_unread()
    assert result == []


def test_list_unread_passes_bounded_num_retries_on_list_call():
    t = _tool()
    service = MagicMock()
    list_chain = _chain({"messages": []})
    service.users.return_value.messages.return_value.list.return_value = list_chain
    with patch.object(t, "_get_service", return_value=service):
        t.list_unread()
    list_chain.execute.assert_called_once_with(num_retries=1)


def test_list_unread_skips_message_on_timeout_but_returns_others():
    """A timeout fetching one message's metadata must not drop the whole
    batch — matches the existing per-message HttpError skip behaviour."""
    t = _tool()
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value = _chain(
        {"messages": [{"id": "m1"}, {"id": "m2"}]}
    )

    def _get(userId=None, id=None, format=None, metadataHeaders=None):
        if id == "m1":
            return _chain(TimeoutError("The read operation timed out"))
        return _chain({
            "snippet": "hi",
            "payload": {"headers": [
                {"name": "From", "value": "a@b.com"},
                {"name": "Subject", "value": "Hello"},
                {"name": "Date", "value": "2026-08-03"},
            ]},
        })

    service.users.return_value.messages.return_value.get.side_effect = _get
    with patch.object(t, "_get_service", return_value=service):
        result = t.list_unread()
    assert len(result) == 1
    assert result[0]["id"] == "m2"


def test_get_message_degrades_gracefully_on_ssl_timeout():
    import ssl

    t = _tool()
    service = MagicMock()
    service.users.return_value.messages.return_value.get.return_value = _chain(
        ssl.SSLError("record layer failure")
    )
    with patch.object(t, "_get_service", return_value=service):
        result = t.get_message("m1")
    assert result["error"]
    assert result["id"] == "m1"


def test_mark_read_degrades_gracefully_on_timeout_error():
    t = _tool()
    service = MagicMock()
    service.users.return_value.messages.return_value.modify.return_value = _chain(
        TimeoutError("The read operation timed out")
    )
    with patch.object(t, "_get_service", return_value=service):
        result = t.mark_read("m1")
    assert result["marked_read"] is False
    assert "error" in result
