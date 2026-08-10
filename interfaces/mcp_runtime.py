"""Production wiring for OAuth, MCP handlers, audit, and persistence."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from interfaces.mcp_oauth import FirestoreOAuthStore, OAuthAuthorizationService
from interfaces.mcp_server import WRITE_TOOLS, create_mcp_bundle


_RISK_CATEGORIES = frozenset(
    {
        "payment",
        "credentials_security",
        "permanent_bulk_deletion",
        "medical_commitment",
        "first_time_outreach",
    }
)
_SENSITIVE_KEYS = frozenset(
    {"password", "token", "secret", "api_key", "authorization", "credential"}
)


def _settings() -> tuple[str, str]:
    return (
        os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
        os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
    )


def _positive_user_id(value: str, *, setting: str) -> int:
    """Parse a positive canonical Telegram user ID from one setting."""
    try:
        user_id = int(value.strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{setting} must be a positive integer") from exc
    if user_id <= 0:
        raise RuntimeError(f"{setting} must be a positive integer")
    return user_id


def _resolve_single_user_id() -> int:
    """Resolve Klaus's canonical user ID for MCP memory namespaces."""
    explicit = os.environ.get("KLAUS_USER_ID")
    if explicit is not None:
        return _positive_user_id(explicit, setting="KLAUS_USER_ID")

    legacy = os.environ.get("TELEGRAM_ALLOWED_USER_IDS")
    if legacy is not None:
        for candidate in legacy.split(","):
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                return _positive_user_id(candidate, setting="TELEGRAM_ALLOWED_USER_IDS")
            except RuntimeError:
                continue
        raise RuntimeError(
            "TELEGRAM_ALLOWED_USER_IDS must contain at least one positive integer"
        )

    if os.environ.get("ENVIRONMENT", "development").strip().lower() == "production":
        raise RuntimeError(
            "A canonical Klaus user ID is required in production; set KLAUS_USER_ID"
        )
    return 0


def dispatch_for_single_user(tool_name: str, arguments: dict) -> Any:
    """Set Klaus's identity before running a legacy core tool dispatcher call."""
    from core.tools import dispatch, set_current_user_id

    set_current_user_id(_resolve_single_user_id())
    return dispatch(tool_name, arguments)


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in _SENSITIVE_KEYS)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _reject_embedded_secrets(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _is_sensitive_key(key) and value not in (None, ""):
                raise ValueError(
                    "Prepared actions may reference a credential by name but cannot store raw secrets"
                )
            _reject_embedded_secrets(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_embedded_secrets(item)


def _normalise_publish_review(arguments: dict) -> tuple[str, dict]:
    """Accept the canonical payload and Claude's observed ``review`` alias."""
    structured = arguments.get("structured")
    if structured is None:
        structured = arguments.get("review")
    if structured is None:
        structured = {}
    if not isinstance(structured, dict):
        raise ValueError("structured review must be an object")

    text = str(arguments.get("text") or "").strip()
    if not text:
        text = str(structured.get("text") or structured.get("summary") or "").strip()
    if not text:
        raise ValueError("review content is required")
    return text, structured


def _require_nonempty_string(mapping: dict, field: str, *, parent: str) -> str:
    value = str(mapping.get(field) or "").strip()
    if not value:
        raise ValueError(f"{parent}.{field} is required")
    return value


def _validate_publish_review(
    arguments: dict[str, Any],
) -> tuple[str, dict, list[str], list[dict]]:
    """Validate a callback fully before it can mutate a routine publication."""
    text, structured = _normalise_publish_review(arguments)
    action_ids = arguments.get("action_ids")
    partial_actions = arguments.get("partial_actions")
    if not isinstance(action_ids, list):
        raise ValueError("action_ids must be an array")
    if not isinstance(partial_actions, list):
        raise ValueError("partial_actions must be an array")
    if str(arguments.get("routine") or "") == "nightly":
        reflection = structured.get("reflection")
        self_state = structured.get("self_state")
        if not isinstance(reflection, dict):
            raise ValueError("structured.reflection must be an object")
        if not isinstance(self_state, dict):
            raise ValueError("structured.self_state must be an object")
        for field in ("summary", "mood", "current_focus", "recent_context"):
            _require_nonempty_string(
                reflection,
                field,
                parent="structured.reflection",
            )
        if not isinstance(reflection.get("highlights"), list):
            raise ValueError("structured.reflection.highlights must be an array")
        for field in ("mood", "current_focus", "recent_context"):
            _require_nonempty_string(
                self_state,
                field,
                parent="structured.self_state",
            )
    return text, structured, [str(item) for item in action_ids], list(partial_actions)


def build_custom_handlers() -> dict[str, Any]:
    """Return lazy production handlers for Klaus-specific MCP tools."""

    async def life_snapshot(arguments: dict) -> dict:
        from core.life_snapshot import build_life_snapshot

        return await build_life_snapshot()

    def query_health(arguments: dict) -> dict:
        from mcp_tools.database_tool import query_health_database

        query = str(arguments.get("sql_query") or "")
        if not query:
            raise ValueError("sql_query is required")
        max_rows = max(1, min(int(arguments.get("max_rows") or 200), 200))
        return {"rows": query_health_database(query, max_rows=max_rows)}

    def list_holdings(arguments: dict) -> dict:
        from memory.firestore_db import PortfolioHoldingStore

        return {"holdings": PortfolioHoldingStore(*_settings()).list_active()}

    def upsert_holding(arguments: dict) -> dict:
        from memory.firestore_db import PortfolioHoldingStore

        clean = {key: value for key, value in arguments.items() if key != "_mcp_origin"}
        return PortfolioHoldingStore(*_settings()).upsert(clean)

    def publish_portfolio(arguments: dict) -> dict:
        from core.portfolio import build_portfolio_snapshot
        from memory.firestore_db import PortfolioHoldingStore, PortfolioSnapshotStore

        clean = {key: value for key, value in arguments.items() if key != "_mcp_origin"}
        snapshots = PortfolioSnapshotStore(*_settings())
        recent = snapshots.list_recent(1)
        snapshot = build_portfolio_snapshot(
            week=str(clean.get("week") or ""),
            holdings=PortfolioHoldingStore(*_settings()).list_active(),
            quotes=dict(clean.get("quotes") or {}),
            fx_rates=dict(clean.get("fx_rates") or {}),
            last_valid=recent[0] if recent else None,
            observed_at=str(clean.get("observed_at") or datetime.now(ZoneInfo("UTC")).isoformat()),
        )
        return snapshots.write_weekly(snapshot)

    def get_routine(arguments: dict) -> dict:
        from memory.firestore_db import RoutineRunStore

        correlation_id = str(arguments.get("correlation_id") or "")
        if not correlation_id:
            raise ValueError("correlation_id is required")
        return {"run": RoutineRunStore(*_settings()).get(correlation_id)}

    def publish_review(arguments: dict) -> dict:
        text, structured, action_ids, partial_actions = _validate_publish_review(arguments)

        from core.review_delivery import (
            normalise_claude_session_url,
            routine_review_path,
            routine_review_title,
        )
        from core.push_sender import send_push_to_all
        from memory.firestore_db import (
            BehavioralFeedbackStore,
            JournalStore,
            RoutineReviewStore,
            RoutineRunStore,
            SelfStateStore,
        )

        correlation_id = str(arguments.get("correlation_id") or "")
        routine = str(arguments.get("routine") or "")
        target_date = str(arguments.get("target_date") or "")
        runs = RoutineRunStore(*_settings())
        current = runs.get(correlation_id)
        if not current:
            raise ValueError("routine run not found")
        if current.get("routine") != routine or current.get("target_date") != target_date:
            raise ValueError("routine callback does not match its queued run")
        reflection = structured.get("reflection")
        self_state = structured.get("self_state")
        if routine == "nightly" and (
            not isinstance(reflection, dict) or not isinstance(self_state, dict)
        ):
            raise ValueError(
                "nightly publish requires structured reflection and self_state objects"
            )
        review_id = f"{routine}:{target_date}"
        if current.get("delivery_mode") == "shadow":
            run = runs.transition_claude_publication(
                correlation_id, review_id=review_id
            )
            run = runs.patch(
                correlation_id,
                shadow_review={
                    "routine": routine,
                    "target_date": target_date,
                    "text": text,
                    "structured": structured,
                    "action_ids": action_ids,
                    "partial_actions": partial_actions,
                },
            )
            return {
                "review": run.get("shadow_review"),
                "run": run,
                "delivery": {"shadow": True, "push_sent": False},
            }
        # Claim the publication atomically before any user-visible side effect.
        # This makes the timeout/Claude race resolve to one initial publisher;
        # a callback arriving after fallback becomes a silent late upgrade.
        run = runs.transition_claude_publication(
            correlation_id, review_id=review_id
        )
        status = str(run["status"])
        if routine == "nightly":
            JournalStore(*_settings()).set(
                target_date,
                {**reflection, "source": "claude_subscription", "correlation_id": correlation_id},
            )
            SelfStateStore(*_settings()).set(
                {**self_state, "source": "claude_subscription", "reflection_date": target_date}
            )
            feedback_store = BehavioralFeedbackStore(*_settings())
            for index, proposal in enumerate(structured.get("behavioral_feedback") or []):
                if not isinstance(proposal, dict):
                    continue
                pattern = str(proposal.get("pattern") or "").strip()
                if not pattern:
                    continue
                feedback_store.record(
                    pattern=pattern,
                    evidence=[str(item) for item in proposal.get("evidence") or []],
                    source="nightly",
                    feedback_id=hashlib.sha256(
                        f"{correlation_id}:{index}:{pattern}".encode("utf-8")
                    ).hexdigest()[:32],
                )
        session_url = normalise_claude_session_url(current.get("claude_session_url"))
        if "claude_session_url" not in current:
            remote_result = current.get("remote_trigger_result")
            session_url = normalise_claude_session_url(
                remote_result.get("claude_code_session_url")
                if isinstance(remote_result, dict)
                else None
            )
        review_fields = {
            "routine": routine,
            "target_date": target_date,
            "correlation_id": correlation_id,
            "status": status,
            "text": text,
            "structured": structured,
            "action_ids": action_ids,
            "partial_actions": partial_actions,
        }
        if session_url:
            review_fields["claude_session_url"] = session_url
        review = RoutineReviewStore(*_settings()).publish(**review_fields)
        delivery = (
            {"late_upgrade": True, "push_sent": False}
            if status == "late_upgraded"
            else send_push_to_all(
                text,
                "briefing",
                routine_review_path(routine, target_date),
                routine_review_title(routine),
            )
        )
        return {"review": review, "run": run, "delivery": delivery}

    def prepare_action(arguments: dict) -> dict:
        from memory.firestore_db import PendingApprovalStore

        action_type = str(arguments.get("action_type") or "")
        if action_type not in _RISK_CATEGORIES:
            raise ValueError("unsupported high-risk action category")
        payload = arguments.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        _reject_embedded_secrets(payload)
        return PendingApprovalStore(*_settings()).prepare(
            action_type=action_type,
            payload=payload,
            origin=str(arguments.get("_mcp_origin") or "unknown"),
            expires_in_seconds=max(60, min(int(arguments.get("expires_in_seconds") or 900), 3600)),
            action_id=arguments.get("action_id"),
            risk_category=action_type,
        )

    def list_approvals(arguments: dict) -> dict:
        from memory.firestore_db import PendingApprovalStore

        return {"approvals": PendingApprovalStore(*_settings()).list_pending()}

    def confirm_action(arguments: dict) -> dict:
        from core.tools import dispatch
        from memory.firestore_db import PendingApprovalStore

        store = PendingApprovalStore(*_settings())
        confirmed = store.confirm(
            str(arguments.get("action_id") or ""),
            str(arguments.get("payload_hash") or ""),
        )
        payload = confirmed.get("payload") or {}
        tool_name = payload.get("tool_name") if isinstance(payload, dict) else None
        tool_arguments = payload.get("arguments") if isinstance(payload, dict) else None
        if tool_name in WRITE_TOOLS and isinstance(tool_arguments, dict):
            execution = dispatch(str(tool_name), tool_arguments)
            try:
                execution = json.loads(execution)
            except (TypeError, json.JSONDecodeError):
                execution = {"result": execution}
            return {"approval": confirmed, "execution": execution}
        return {
            "approval": confirmed,
            "execution": {"state": "confirmed_pending_executor"},
        }

    return {
        "get_life_snapshot": life_snapshot,
        "query_health_database": query_health,
        "list_portfolio_holdings": list_holdings,
        "upsert_portfolio_holding": upsert_holding,
        "publish_portfolio_snapshot": publish_portfolio,
        "get_routine_status": get_routine,
        "publish_review": publish_review,
        "prepare_high_risk_action": prepare_action,
        "list_pending_approvals": list_approvals,
        "confirm_prepared_action": confirm_action,
    }


def audit_mcp_write(**entry) -> None:
    """Append an immutable action record after every MCP write executes."""
    from memory.firestore_db import ActionLogStore

    now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    arguments = _redact(entry.get("arguments") or {})
    detail = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)[:1000]
    ActionLogStore(*_settings()).append(
        now.date().isoformat(),
        {
            "id": str(entry.get("idempotency_key") or "")[:256],
            "action": str(entry.get("tool_name") or "unknown"),
            "detail": detail,
            "occasion": str(entry.get("origin") or "mcp"),
            "at": now.isoformat(),
            "disclosed": False,
            "origin": "claude_subscription",
        },
    )


def calendar_is_klaus_owned(event_id: str, calendar_id: str | None) -> bool:
    from core.tools import _get_calendar_tool

    if not event_id:
        return False
    return _get_calendar_tool().is_klaus_owned(event_id, calendar_id)


def create_production_mcp_bundle(
    oauth_service: OAuthAuthorizationService, *, read_only: bool = False,
):
    from memory.firestore_db import ActionIdempotencyStore

    return create_mcp_bundle(
        oauth_service,
        dispatcher=dispatch_for_single_user,
        custom_handlers=build_custom_handlers(),
        idempotency_store=ActionIdempotencyStore(*_settings()),
        auditor=audit_mcp_write,
        calendar_ownership_checker=calendar_is_klaus_owned,
        read_only=read_only,
    )


def create_production_oauth_service() -> OAuthAuthorizationService:
    public_url = (
        os.environ.get("KLAUS_PUBLIC_URL")
        or os.environ.get("CLOUD_RUN_URL")
        or "http://localhost:8080"
    ).rstrip("/")
    redirect_hosts = frozenset(
        host.strip()
        for host in os.environ.get(
            "KLAUS_OAUTH_REDIRECT_HOSTS", "claude.ai,claude.com"
        ).split(",")
        if host.strip()
    )
    return OAuthAuthorizationService(
        store=FirestoreOAuthStore(*_settings()),
        issuer_url=public_url,
        allowed_subject=os.environ.get("HUB_ALLOWED_EMAIL", "amit.grupper@gmail.com"),
        allowed_redirect_hosts=redirect_hosts,
    )
