"""Contract tests for authenticated Claude routine review reads."""
from __future__ import annotations

from copy import deepcopy
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.test_review_delivery import (
    assert_public_routine_run,
    expected_public_routine_run,
    hostile_routine_run,
)


os.environ.setdefault("TELEGRAM_ALLOWED_USER_IDS", "123456")
os.environ.setdefault("GCP_PROJECT_ID", "klaus-agent")


_BASE_ENV = {
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "KLAUS_USER_ID": "123456",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
    "PINECONE_API_KEY": "fake",
    "PINECONE_INDEX": "fake-index",
}

REVIEWS = {
    ("nightly", "2026-08-10"): {
        "review_id": "nightly:2026-08-10",
        "correlation_id": "corr-nightly",
        "routine": "nightly",
        "target_date": "2026-08-10",
        "routine_status": "published_claude",
        "review_text": "Nightly review, Sir.\nRecovery was good.",
        "action_ids": ["task-1"],
        "partial_actions": [{"tool": "task_edit", "error": "conflict"}],
        "published_at": "2026-08-10T22:15:00+00:00",
        "remote_trigger_result": {
            "claude_code_session_url": "https://evil.example/code/session_provider",
            "provider_token": "provider-token-must-not-reach-browser",
        },
        "raw_provider_response": "raw-provider-payload-must-not-reach-browser",
        "provider_bearer_token": "bearer-token-must-not-reach-browser",
        "untrusted_url": "https://evil.example/should-not-be-a-review-field",
        "extra_field": "extra-review-data-must-not-reach-browser",
    },
    ("morning", "2026-08-10"): {
        "review_id": "morning:2026-08-10",
        "correlation_id": "corr-morning",
        "routine": "morning",
        "target_date": "2026-08-10",
        "routine_status": "published_fallback",
        "review_text": "Morning fallback, Sir.",
        "action_ids": [],
        "partial_actions": [],
        "published_at": "2026-08-10T07:30:00+00:00",
    },
}

_CLIENT_REVIEW_FIELDS = frozenset({
    "review_id",
    "correlation_id",
    "routine",
    "target_date",
    "routine_status",
    "provider",
    "review_text",
    "structured",
    "action_ids",
    "partial_actions",
    "published_at",
})
_HOSTILE_REVIEW_MARKERS = (
    "remote_trigger_result",
    "provider-token-must-not-reach-browser",
    "raw-provider-payload-must-not-reach-browser",
    "bearer-token-must-not-reach-browser",
    "https://evil.example/should-not-be-a-review-field",
    "extra-review-data-must-not-reach-browser",
)


def _expected_public_review(review: dict, claude_session_url: str) -> dict:
    """Build the API contract's approved review shape from a stored fixture."""
    return {
        **{key: review[key] for key in _CLIENT_REVIEW_FIELDS if key in review},
        "claude_session_url": claude_session_url,
    }


def _assert_no_hostile_review_data(response) -> None:
    """Ensure raw provider fields cannot leak through a serialized API response."""
    for marker in _HOSTILE_REVIEW_MARKERS:
        assert marker not in response.text


def _stub_web_server_imports() -> dict:
    """Stub heavyweight imports before importing the FastAPI application."""
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules):
        if key == "interfaces.web_server" or key.startswith("interfaces.web_server."):
            del sys.modules[key]
    return stubs


class _ReviewStore:
    """In-memory review-store double with production read method shapes."""

    def __init__(self, reviews: dict[tuple[str, str], dict]) -> None:
        self.reviews = reviews

    def get(self, routine: str, target_date: str) -> dict | None:
        record = self.reviews.get((routine, target_date))
        return deepcopy(record) if record else None

    def list_recent(self, _limit: int) -> list[dict]:
        return sorted(
            (deepcopy(record) for record in self.reviews.values()),
            key=lambda record: record["published_at"],
            reverse=True,
        )


class _RunStore:
    """In-memory routine-run double for correlated migration recovery."""

    def __init__(self, runs: dict[str, dict]) -> None:
        self.runs = runs

    def get(self, correlation_id: str) -> dict | None:
        record = self.runs.get(correlation_id)
        return deepcopy(record) if record else None

    def list_recent(self, _limit: int) -> list[dict]:
        return [deepcopy(record) for record in self.runs.values()]


@pytest.fixture
def review_client(monkeypatch):
    """Provide an authenticated client with isolated in-memory review stores."""
    reviews = deepcopy(REVIEWS)
    runs = {
        "corr-nightly": {
            "correlation_id": "corr-nightly",
            "claude_session_url": "https://www.claude.ai/code/session_nightly/?ignored=1",
        },
        "corr-morning": {
            "correlation_id": "corr-morning",
            "remote_trigger_result": {
                "claude_code_session_url": "https://claude.ai/epitaxy/session_morning",
                "provider_token": "never-send-this",
            },
        },
    }
    review_store = _ReviewStore(reviews)
    run_store = _RunStore(runs)
    stubs = _stub_web_server_imports()

    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        import interfaces.hub_auth as hub_auth
        import memory.firestore_db as firestore_db

        monkeypatch.setattr(
            firestore_db, "RoutineReviewStore", lambda *_args, **_kwargs: review_store
        )
        monkeypatch.setattr(
            firestore_db, "RoutineRunStore", lambda *_args, **_kwargs: run_store
        )
        with patch.dict(os.environ, _BASE_ENV):
            ws.app.dependency_overrides[hub_auth.require_hub_session] = (
                lambda: "amit.grupper@gmail.com"
            )
            client = TestClient(ws.app, raise_server_exceptions=True)
            yield client, reviews, runs, ws, hub_auth
            ws.app.dependency_overrides.clear()


def test_review_list_returns_newest_reviews_and_safe_session_links(review_client):
    """The inbox sorts reviews and exposes only normalised session navigation URLs."""
    client, reviews, _runs, _ws, _hub_auth = review_client

    response = client.get("/api/reviews?limit=20")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "reviews": [
            _expected_public_review(
                reviews[("nightly", "2026-08-10")],
                "https://claude.ai/code/session_nightly",
            ),
            _expected_public_review(
                reviews[("morning", "2026-08-10")],
                "https://claude.ai/epitaxy/session_morning",
            ),
        ]
    }
    _assert_no_hostile_review_data(response)


def test_review_detail_returns_full_canonical_review(review_client):
    """A detail read returns the complete stored review in its review envelope."""
    client, reviews, _runs, _ws, _hub_auth = review_client

    response = client.get("/api/reviews/nightly/2026-08-10")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "review": _expected_public_review(
            reviews[("nightly", "2026-08-10")],
            "https://claude.ai/code/session_nightly",
        )
    }
    _assert_no_hostile_review_data(response)


def test_review_detail_recovers_safe_link_from_correlated_legacy_run(review_client):
    """Legacy provider metadata yields only its validated Claude session URL."""
    client, reviews, runs, _ws, _hub_auth = review_client
    reviews[("morning", "2026-08-10")].pop("claude_session_url", None)
    runs["corr-morning"]["remote_trigger_result"] = {
        "claude_code_session_url": "https://www.claude.ai/code/session_legacy/?tracking=1",
        "provider_token": "never-send-this",
    }

    response = client.get("/api/reviews/morning/2026-08-10")

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["claude_session_url"] == "https://claude.ai/code/session_legacy"
    assert "remote_trigger_result" not in review
    assert "provider_token" not in response.text


def test_review_detail_omits_hostile_provider_url(review_client):
    """A non-Claude provider URL is not passed through to the browser."""
    client, reviews, runs, _ws, _hub_auth = review_client
    reviews[("morning", "2026-08-10")].pop("claude_session_url", None)
    runs["corr-morning"]["remote_trigger_result"] = {
        "claude_code_session_url": "https://evil.example/code/session_not-safe",
    }

    response = client.get("/api/reviews/morning/2026-08-10")

    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert "claude_session_url" not in review
    assert "remote_trigger_result" not in review


def test_review_detail_returns_404_when_missing(review_client):
    """A valid routine/date pair without a stored review is not fabricated."""
    client, _reviews, _runs, _ws, _hub_auth = review_client

    response = client.get("/api/reviews/weekly/2026-08-10")

    assert response.status_code == 404


def test_review_detail_rejects_unknown_routine_and_invalid_date(review_client):
    """Path validation rejects unsupported routines and malformed calendar dates."""
    client, _reviews, _runs, _ws, _hub_auth = review_client

    unknown_routine = client.get("/api/reviews/afternoon/2026-08-10")
    invalid_date = client.get("/api/reviews/morning/2026-99-10")

    assert unknown_routine.status_code == 422
    assert invalid_date.status_code == 422


def test_review_routes_require_hub_auth(review_client):
    """Both review reads preserve the Hub session dependency as their auth gate."""
    client, _reviews, _runs, ws, hub_auth = review_client

    def _no_session():
        raise HTTPException(status_code=401, detail="Not authenticated")

    ws.app.dependency_overrides[hub_auth.require_hub_session] = _no_session

    assert client.get("/api/reviews").status_code == 401
    assert client.get("/api/reviews/nightly/2026-08-10").status_code == 401


def test_agent_status_exposes_only_public_routine_run_fields(review_client, monkeypatch):
    """The Hub status payload cannot reveal retained provider diagnostics."""
    client, _reviews, runs, _ws, _hub_auth = review_client
    stored = hostile_routine_run()
    runs.clear()
    runs[stored["correlation_id"]] = stored

    import memory.firestore_db

    class EmbeddingUsage:
        @staticmethod
        def summary(_user_id, _period):
            return {}

    monkeypatch.setattr(memory.firestore_db, "EmbeddingUsageStore", lambda *_args: EmbeddingUsage())

    response = client.get("/api/agent/status")

    assert response.status_code == 200, response.text
    assert_public_routine_run(
        response.json()["recent_runs"][0], expected_public_routine_run(stored)
    )


def test_agent_status_exposes_embedding_and_routes_quota_health(review_client, monkeypatch):
    """Authenticated settings show remaining app limits without credentials."""
    client, _reviews, _runs, _ws, _hub_auth = review_client
    import memory.firestore_db

    class EmbeddingUsage:
        @staticmethod
        def summary(user_id, period):
            assert user_id == "123456"
            assert period == "today"
            return {"embedding_calls": 17, "daily_limit": 200}

    class RoutesUsage:
        @staticmethod
        def summary(user_id):
            assert user_id == "123456"
            return {
                "computation_count": 4,
                "daily_limit": 25,
                "daily_remaining": 21,
                "rolling_minute_count": 2,
                "minute_limit": 5,
                "minute_remaining": 3,
            }

    monkeypatch.setattr(memory.firestore_db, "EmbeddingUsageStore", lambda *_args: EmbeddingUsage())
    monkeypatch.setattr(memory.firestore_db, "RoutesUsageStore", lambda *_args: RoutesUsage())

    response = client.get("/api/agent/status")

    assert response.status_code == 200, response.text
    usage = response.json()["usage"]
    assert usage["gemini_embeddings"]["request_count"] == 17
    assert usage["gemini_embeddings"]["daily_limit"] == 200
    assert usage["gemini_embeddings"]["daily_remaining"] == 183
    assert usage["google_routes"] == {
        "request_count": 4,
        "daily_limit": 25,
        "daily_remaining": 21,
        "rolling_minute_count": 2,
        "minute_limit": 5,
        "minute_remaining": 3,
    }
    assert "key" not in str(usage).lower()
