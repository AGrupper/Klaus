"""Tests for core/push_sender.py::send_push_to_all (Phase 29 — PUSH-02).

Covers:
  - CLASS_TTL has the exact D-07 values
  - success -> store.record_success, results["sent"]++
  - WebPushException(404) / WebPushException(410) -> store.delete, results["removed"]++
  - WebPushException(other status, e.g. 500) -> store.record_failure, results["failed"]++
  - generic Exception (DNS/timeout) -> store.record_failure, results["failed"]++
  - payload shape: title "Klaus", body text[:1000], class, url
  - every webpush() call carries timeout=10 and the class-specific ttl
  - vapid_claims is a freshly-constructed dict per send (not shared/mutated)
  - _get_vapid_private_key loads from Secret Manager once and caches
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pywebpush import WebPushException

import core.push_sender as push_sender


class _FakeSubscriptionStore:
    """Minimal in-memory double for PushSubscriptionStore, tracking calls."""

    def __init__(self, subs: list[dict]):
        self._subs = subs
        self.deleted: list[str] = []
        self.successes: list[str] = []
        self.failures: list[tuple[str, str]] = []

    def list_all(self) -> list[dict]:
        return self._subs

    def delete(self, endpoint: str) -> None:
        self.deleted.append(endpoint)

    def record_success(self, endpoint: str) -> None:
        self.successes.append(endpoint)

    def record_failure(self, endpoint: str, error: str) -> None:
        self.failures.append((endpoint, str(error)))


def _sub(n: int) -> dict:
    return {
        "endpoint": f"https://push.example/{n}",
        "keys": {"p256dh": f"p256dh-{n}", "auth": f"auth-{n}"},
    }


@pytest.fixture(autouse=True)
def _reset_vapid_cache():
    """Ensure the module-level VAPID key cache doesn't leak across tests."""
    push_sender._VAPID_PRIVATE_KEY = None
    yield
    push_sender._VAPID_PRIVATE_KEY = None


def _patched(store, webpush_mock=None, **webpush_kwargs):
    """Context-manager helper: patch store + vapid key + pywebpush.webpush."""
    if webpush_mock is None:
        webpush_mock = MagicMock(**webpush_kwargs)
    return (
        patch("core.push_sender._get_subscription_store", return_value=store),
        patch("core.push_sender._get_vapid_private_key", return_value="fake-pem"),
        patch("pywebpush.webpush", webpush_mock),
    )


# --------------------------------------------------------------------- #
# CLASS_TTL                                                              #
# --------------------------------------------------------------------- #

def test_class_ttl_exact_d07_values():
    assert push_sender.CLASS_TTL["leave_by"] == 3600
    assert push_sender.CLASS_TTL["habit_nudge"] == 3600
    assert push_sender.CLASS_TTL["chat_reply"] == 86400
    assert push_sender.CLASS_TTL["briefing"] == 86400
    assert push_sender.CLASS_TTL["review"] == 86400
    assert push_sender.CLASS_TTL["alert"] == 86400
    assert push_sender.CLASS_TTL["default"] == 86400


# --------------------------------------------------------------------- #
# success                                                                #
# --------------------------------------------------------------------- #

def test_success_records_success_and_counts_sent():
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(store)
    with p1, p2, p3 as mock_webpush:
        result = push_sender.send_push_to_all("hello world", "chat_reply")

    assert result == {"sent": 1, "failed": 0, "removed": 0}
    assert store.successes == ["https://push.example/1"]
    mock_webpush.assert_called_once()


def test_webpush_called_with_timeout_10_and_class_ttl():
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(store)
    with p1, p2, p3 as mock_webpush:
        push_sender.send_push_to_all("hello", "leave_by")

    _, kwargs = mock_webpush.call_args
    assert kwargs["timeout"] == 10
    assert kwargs["ttl"] == 3600  # leave_by TTL


def test_unknown_message_class_falls_back_to_default_ttl():
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(store)
    with p1, p2, p3 as mock_webpush:
        push_sender.send_push_to_all("hello", "not-a-real-class")

    _, kwargs = mock_webpush.call_args
    assert kwargs["ttl"] == 86400


def test_payload_shape_title_body_class_url():
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(store)
    with p1, p2, p3 as mock_webpush:
        push_sender.send_push_to_all("a short message", "briefing")

    _, kwargs = mock_webpush.call_args
    payload = json.loads(kwargs["data"])
    assert payload["title"] == "Klaus"
    assert payload["body"] == "a short message"
    assert payload["class"] == "briefing"
    assert payload["url"] == "/"


def test_payload_body_truncated_to_1000_chars():
    long_text = "x" * 5000
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(store)
    with p1, p2, p3 as mock_webpush:
        push_sender.send_push_to_all(long_text)

    _, kwargs = mock_webpush.call_args
    payload = json.loads(kwargs["data"])
    assert len(payload["body"]) == 1000
    assert payload["body"] == long_text[:1000]


def test_vapid_claims_is_fresh_dict_per_send_not_shared():
    """pywebpush mutates the claims dict it's handed (Pitfall 5) — each send
    must pass a newly-constructed dict so mutation on one send can't corrupt
    the next.
    """
    seen_claims_ids = []

    def _mutating_webpush(**kwargs):
        claims = kwargs["vapid_claims"]
        seen_claims_ids.append(id(claims))
        claims["aud"] = "mutated"  # simulate pywebpush's in-place mutation

    store = _FakeSubscriptionStore([_sub(1), _sub(2)])
    p1, p2, p3 = _patched(store, webpush_mock=MagicMock(side_effect=_mutating_webpush))
    with p1, p2, p3:
        push_sender.send_push_to_all("hello")

    assert len(seen_claims_ids) == 2
    assert seen_claims_ids[0] != seen_claims_ids[1]


# --------------------------------------------------------------------- #
# 404 / 410 -> delete                                                    #
# --------------------------------------------------------------------- #

def test_404_deletes_subscription_and_counts_removed():
    resp = MagicMock(status_code=404)
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(
        store, webpush_mock=MagicMock(side_effect=WebPushException("gone", response=resp))
    )
    with p1, p2, p3:
        result = push_sender.send_push_to_all("hello")

    assert result == {"sent": 0, "failed": 0, "removed": 1}
    assert store.deleted == ["https://push.example/1"]
    assert store.failures == []


def test_410_deletes_subscription_and_counts_removed():
    resp = MagicMock(status_code=410)
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(
        store, webpush_mock=MagicMock(side_effect=WebPushException("gone", response=resp))
    )
    with p1, p2, p3:
        result = push_sender.send_push_to_all("hello")

    assert result == {"sent": 0, "failed": 0, "removed": 1}
    assert store.deleted == ["https://push.example/1"]


# --------------------------------------------------------------------- #
# other WebPushException status -> record_failure                       #
# --------------------------------------------------------------------- #

def test_500_records_failure_and_counts_failed():
    resp = MagicMock(status_code=500)
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(
        store, webpush_mock=MagicMock(side_effect=WebPushException("server error", response=resp))
    )
    with p1, p2, p3:
        result = push_sender.send_push_to_all("hello")

    assert result == {"sent": 0, "failed": 1, "removed": 0}
    assert store.deleted == []
    assert len(store.failures) == 1
    endpoint, error = store.failures[0]
    assert endpoint == "https://push.example/1"
    assert "500" in error


# --------------------------------------------------------------------- #
# generic exception (DNS/timeout) -> record_failure                     #
# --------------------------------------------------------------------- #

def test_generic_exception_records_failure_and_counts_failed():
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(
        store, webpush_mock=MagicMock(side_effect=RuntimeError("DNS resolution failed"))
    )
    with p1, p2, p3:
        result = push_sender.send_push_to_all("hello")

    assert result == {"sent": 0, "failed": 1, "removed": 0}
    endpoint, error = store.failures[0]
    assert endpoint == "https://push.example/1"
    assert "DNS resolution failed" in error


# --------------------------------------------------------------------- #
# multi-subscription fan-out mixes outcomes correctly                   #
# --------------------------------------------------------------------- #

def test_mixed_outcomes_across_multiple_subscriptions():
    resp_404 = MagicMock(status_code=404)

    def _side_effect(**kwargs):
        endpoint = kwargs["subscription_info"]["endpoint"]
        if endpoint.endswith("/2"):
            raise WebPushException("gone", response=resp_404)
        return None

    store = _FakeSubscriptionStore([_sub(1), _sub(2), _sub(3)])
    p1, p2, p3 = _patched(store, webpush_mock=MagicMock(side_effect=_side_effect))
    with p1, p2, p3:
        result = push_sender.send_push_to_all("hello")

    assert result == {"sent": 2, "failed": 0, "removed": 1}
    assert store.deleted == ["https://push.example/2"]
    assert store.successes == ["https://push.example/1", "https://push.example/3"]


# --------------------------------------------------------------------- #
# _get_vapid_private_key: Secret Manager load + cache                   #
# --------------------------------------------------------------------- #

def test_get_vapid_private_key_loads_from_secret_manager_and_caches(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "klaus-agent")

    mock_response = MagicMock()
    mock_response.payload.data = b"-----BEGIN PRIVATE KEY-----fake-vapid-key"
    mock_client = MagicMock()
    mock_client.access_secret_version.return_value = mock_response
    mock_client_cls = MagicMock(return_value=mock_client)

    with patch("google.cloud.secretmanager.SecretManagerServiceClient", mock_client_cls):
        key1 = push_sender._get_vapid_private_key()
        key2 = push_sender._get_vapid_private_key()

    assert key1 == "-----BEGIN PRIVATE KEY-----fake-vapid-key"
    assert key2 == key1
    # Cached: only one Secret Manager round trip across both calls.
    mock_client.access_secret_version.assert_called_once()
    request = mock_client.access_secret_version.call_args.kwargs["request"]
    assert request["name"] == (
        "projects/klaus-agent/secrets/klaus-vapid-private-key/versions/latest"
    )
