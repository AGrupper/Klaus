"""Scoped MCP catalogs and gateway policy tests for Klaus v7."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from mcp.server.auth.provider import AccessToken

from tests.test_review_delivery import (
    assert_public_routine_run,
    expected_public_routine_run,
    hostile_routine_run,
)


def _token(*scopes: str, resource: str = "https://klaus.example.com/mcp/interactive"):
    return AccessToken(
        token="opaque",
        client_id="claude",
        scopes=list(scopes),
        expires_at=4_000_000_000,
        resource=resource,
        subject="amit.grupper@gmail.com",
    )


def _oauth_service():
    from interfaces.mcp_oauth import InMemoryOAuthStore, OAuthAuthorizationService

    return OAuthAuthorizationService(
        InMemoryOAuthStore(),
        "https://klaus.example.com",
        "amit.grupper@gmail.com",
    )


def test_interactive_and_routine_servers_have_distinct_tool_catalogs():
    from interfaces.mcp_server import create_mcp_bundle

    bundle = create_mcp_bundle(_oauth_service(), dispatcher=lambda _name, _args: "{}")
    interactive = {tool.name for tool in bundle.interactive._tool_manager.list_tools()}
    routine = {tool.name for tool in bundle.routine._tool_manager.list_tools()}

    assert {"get_life_snapshot", "task_create", "remember"} <= interactive
    assert {"get_life_snapshot", "task_create", "remember"} <= routine
    assert "confirm_prepared_action" in interactive
    assert "confirm_prepared_action" not in routine
    assert "publish_review" in routine
    assert "publish_review" not in interactive
    assert "update_plan" in interactive
    assert "update_plan" not in routine  # training changes are recommendation-only
    assert not {"list_unread_emails", "fetch_readwise_today", "delegate_to_worker"} & (
        interactive | routine
    )


def test_legacy_tools_publish_their_exact_nested_argument_schemas():
    """Claude must see the canonical fields instead of an untyped object."""
    from interfaces.mcp_server import _schema_metadata, create_mcp_bundle

    bundle = create_mcp_bundle(_oauth_service(), dispatcher=lambda _name, _args: "{}")
    tools = {tool.name: tool for tool in bundle.interactive._tool_manager.list_tools()}

    for name, metadata in _schema_metadata().items():
        if name not in tools or not isinstance(metadata.get("input_schema"), dict):
            continue
        expected = metadata["input_schema"]
        actual = tools[name].parameters["properties"]["arguments"]
        assert actual["type"] == expected["type"], name
        assert actual["properties"] == expected["properties"], name
        assert actual.get("required", []) == expected.get("required", []), name

    calendar = tools["list_calendar_events"].parameters
    calendar_arguments = calendar["properties"]["arguments"]
    assert set(calendar_arguments["properties"]) == {"time_min_iso", "time_max_iso"}
    assert set(calendar_arguments["required"]) == {"time_min_iso", "time_max_iso"}
    assert calendar["required"] == ["arguments"]

    task_create = tools["task_create"].parameters
    task_arguments = task_create["properties"]["arguments"]
    assert "title" in task_arguments["properties"]
    assert task_arguments["required"] == ["title"]
    assert set(task_create["required"]) == {"arguments", "idempotency_key"}

    acwr = tools["get_acwr"].parameters
    assert acwr["properties"]["arguments"]["properties"] == {}
    assert "arguments" not in acwr.get("required", [])


def test_custom_tools_publish_exact_nested_argument_schemas():
    """Claude must receive strict, handler-aligned schemas for custom tools."""
    from interfaces.mcp_custom_schemas import CUSTOM_TOOL_SCHEMAS
    from interfaces.mcp_server import create_mcp_bundle

    bundle = create_mcp_bundle(_oauth_service(), dispatcher=lambda _name, _args: "{}")
    interactive = {
        tool.name: tool for tool in bundle.interactive._tool_manager.list_tools()
    }
    routine = {tool.name: tool for tool in bundle.routine._tool_manager.list_tools()}

    for name, expected in CUSTOM_TOOL_SCHEMAS.items():
        tool = routine.get(name) or interactive.get(name)
        assert tool is not None, name
        actual = tool.parameters["properties"]["arguments"]
        assert actual["properties"] == expected["properties"], name
        assert actual.get("required", []) == expected.get("required", []), name
        assert actual["additionalProperties"] is False, name

    publish = routine["publish_review"].parameters["properties"]["arguments"]
    assert set(publish["required"]) == {
        "correlation_id", "routine", "target_date", "text",
        "structured", "action_ids", "partial_actions",
    }
    assert publish["properties"]["routine"]["enum"] == [
        "morning", "nightly", "weekly",
    ]


class _GatewaySideEffectRecorder:
    """Record every operation that schema validation must precede."""

    def __init__(self):
        self.operations = []

    def begin(self, key, *, tool_name, payload, origin):
        self.operations.append(("idempotency_begin", key, tool_name, payload, origin))
        return {"is_new": True, "status": "running"}

    def mark_executed(self, key, result):
        self.operations.append(("idempotency_mark_executed", key, result))

    def complete(self, key):
        self.operations.append(("idempotency_complete", key))

    def fail(self, key, error):
        self.operations.append(("idempotency_fail", key, error))

    def custom_handler(self, arguments):
        self.operations.append(("custom_handler", arguments))
        return {"ok": True}

    def dispatcher(self, tool_name, arguments):
        self.operations.append(("dispatcher", tool_name, arguments))
        return {"ok": True}

    def audit(self, **entry):
        self.operations.append(("audit", entry))

    def check_calendar_ownership(self, event_id, calendar_id):
        self.operations.append(("calendar_ownership", event_id, calendar_id))
        return True


@pytest.mark.parametrize(
    ("endpoint", "tool_name", "arguments", "scopes", "idempotency_key"),
    [
        (
            "interactive",
            "get_life_snapshot",
            {"unexpected": True},
            ("klaus.read",),
            None,
        ),
        (
            "interactive",
            "get_routine_status",
            {},
            ("klaus.read",),
            None,
        ),
        (
            "interactive",
            "prepare_high_risk_action",
            {"action_type": "harmless_probe", "payload": {}},
            ("klaus.read", "klaus.write"),
            "invalid-enum",
        ),
        (
            "routine",
            "publish_review",
            {
                "correlation_id": "routine-1",
                "routine": "nightly",
                "target_date": "2026-99-99",
                "text": "Final review",
                "structured": {},
                "action_ids": [],
                "partial_actions": [],
            },
            ("klaus.read", "klaus.write", "klaus.routine"),
            "invalid-date",
        ),
        (
            "interactive",
            "upsert_portfolio_holding",
            {
                "ticker": "KLAUS",
                "exchange": "TEST",
                "quantity": 1,
                "source_urls": ["not a uri"],
            },
            ("klaus.read", "klaus.write"),
            "invalid-uri",
        ),
        (
            "interactive",
            "upsert_portfolio_holding",
            {
                "ticker": "KLAUS",
                "exchange": "TEST",
                "quantity": 1,
                "observed_at": "sometime yesterday",
            },
            ("klaus.read", "klaus.write"),
            "invalid-date-time",
        ),
    ],
    ids=[
        "unknown-field",
        "missing-required",
        "invalid-enum",
        "invalid-date",
        "invalid-uri",
        "invalid-date-time",
    ],
)
def test_custom_schema_rejects_invalid_arguments_before_any_side_effect(
    endpoint, tool_name, arguments, scopes, idempotency_key
):
    """Strict custom schemas must be enforced before any stateful operation."""
    from interfaces.mcp_server import KlausMCPGateway, MCPToolError

    recorder = _GatewaySideEffectRecorder()
    gateway = KlausMCPGateway(
        dispatcher=recorder.dispatcher,
        custom_handlers={tool_name: recorder.custom_handler},
        idempotency_store=recorder,
        auditor=recorder.audit,
        calendar_ownership_checker=recorder.check_calendar_ownership,
    )
    resource = f"https://klaus.example.com/mcp/{endpoint}"

    with pytest.raises(
        MCPToolError,
        match=f"Invalid arguments for {tool_name}",
    ) as caught:
        asyncio.run(
            gateway.execute(
                endpoint=endpoint,
                tool_name=tool_name,
                arguments=arguments,
                token=_token(*scopes, resource=resource),
                idempotency_key=idempotency_key,
            )
        )

    safe_message = str(caught.value)
    assert len(safe_message) < 160
    for private_value in ("harmless_probe", "not a uri", "sometime yesterday"):
        assert private_value not in safe_message
    assert recorder.operations == []


def test_custom_schema_error_does_not_disclose_dynamic_object_keys():
    """Validation errors must not echo payload-controlled nested object paths."""
    from interfaces.mcp_server import KlausMCPGateway, MCPToolError

    recorder = _GatewaySideEffectRecorder()
    gateway = KlausMCPGateway(
        dispatcher=recorder.dispatcher,
        custom_handlers={
            "publish_portfolio_snapshot": recorder.custom_handler,
        },
        idempotency_store=recorder,
        auditor=recorder.audit,
        calendar_ownership_checker=recorder.check_calendar_ownership,
    )
    secret_quote_key = "customer-secret-123"
    secret_value = "private-price-marker"

    with pytest.raises(
        MCPToolError,
        match="Invalid arguments for publish_portfolio_snapshot",
    ) as caught:
        asyncio.run(
            gateway.execute(
                endpoint="routine",
                tool_name="publish_portfolio_snapshot",
                arguments={
                    "week": "2026-08-09",
                    "quotes": {
                        secret_quote_key: {
                            "price": secret_value,
                        },
                    },
                },
                token=_token(
                    "klaus.read",
                    "klaus.write",
                    "klaus.routine",
                    resource="https://klaus.example.com/mcp/routine",
                ),
                idempotency_key="private-quote-invalid",
            )
        )

    safe_message = str(caught.value)
    assert secret_quote_key not in safe_message
    assert secret_value not in safe_message
    assert recorder.operations == []


def test_custom_schema_allows_valid_arguments_to_reach_handler():
    """Schema enforcement must not block a valid custom handler invocation."""
    from interfaces.mcp_server import KlausMCPGateway

    recorder = _GatewaySideEffectRecorder()
    gateway = KlausMCPGateway(
        dispatcher=recorder.dispatcher,
        custom_handlers={"get_routine_status": recorder.custom_handler},
    )

    result = asyncio.run(
        gateway.execute(
            endpoint="interactive",
            tool_name="get_routine_status",
            arguments={"correlation_id": "routine-1"},
            token=_token("klaus.read"),
        )
    )

    assert result == {"ok": True}
    assert recorder.operations == [
        ("custom_handler", {"correlation_id": "routine-1", "_mcp_origin": "interactive"})
    ]


def test_empty_object_custom_schema_rejects_extras_before_dispatcher():
    """A custom schema remains enforced even if no custom handler is installed."""
    from interfaces.mcp_server import KlausMCPGateway, MCPToolError

    recorder = _GatewaySideEffectRecorder()
    gateway = KlausMCPGateway(dispatcher=recorder.dispatcher)

    with pytest.raises(MCPToolError, match="Invalid arguments for get_life_snapshot"):
        asyncio.run(
            gateway.execute(
                endpoint="interactive",
                tool_name="get_life_snapshot",
                arguments={"probe": "must not dispatch"},
                token=_token("klaus.read"),
            )
        )

    assert recorder.operations == []


def test_legacy_tool_without_custom_schema_preserves_existing_argument_behavior():
    """Only the explicit custom-schema registry is enforced at this boundary."""
    from interfaces.mcp_server import KlausMCPGateway

    recorder = _GatewaySideEffectRecorder()
    gateway = KlausMCPGateway(dispatcher=recorder.dispatcher)

    result = asyncio.run(
        gateway.execute(
            endpoint="interactive",
            tool_name="task_list",
            arguments={"legacy_extra": "still-dispatched"},
            token=_token("klaus.read"),
        )
    )

    assert result == {"ok": True}
    assert recorder.operations == [
        ("dispatcher", "task_list", {"legacy_extra": "still-dispatched"})
    ]


def test_capability_gate_can_mount_a_strictly_read_only_interactive_catalog():
    from interfaces.mcp_server import create_mcp_bundle

    bundle = create_mcp_bundle(
        _oauth_service(), dispatcher=lambda _name, _args: "{}", read_only=True
    )
    interactive = {tool.name for tool in bundle.interactive._tool_manager.list_tools()}
    routine = {tool.name for tool in bundle.routine._tool_manager.list_tools()}

    assert {"get_life_snapshot", "task_list", "recall"} <= interactive
    assert not {"task_create", "remember", "prepare_high_risk_action"} & interactive
    assert routine == set()


def test_every_write_requires_idempotency_key_before_dispatch():
    from interfaces.mcp_server import KlausMCPGateway, MCPToolError

    called = []
    gateway = KlausMCPGateway(dispatcher=lambda name, args: called.append((name, args)))
    with pytest.raises(MCPToolError, match="idempotency_key"):
        asyncio.run(
            gateway.execute(
                endpoint="interactive",
                tool_name="task_create",
                arguments={"title": "Plan week"},
                token=_token("klaus.read", "klaus.write"),
            )
        )
    assert called == []


def test_scope_filtering_is_enforced_inside_tool_execution():
    from interfaces.mcp_server import KlausMCPGateway, MCPToolError

    gateway = KlausMCPGateway(dispatcher=lambda _name, _args: "{}")
    with pytest.raises(MCPToolError, match="klaus.memory"):
        asyncio.run(
            gateway.execute(
                endpoint="interactive",
                tool_name="remember",
                arguments={"text": "Durable fact"},
                token=_token("klaus.read", "klaus.write"),
                idempotency_key="memory-1",
            )
        )


def test_routine_token_cannot_cross_into_interactive_endpoint():
    from interfaces.mcp_server import KlausMCPGateway, MCPToolError

    gateway = KlausMCPGateway(dispatcher=lambda _name, _args: "{}")
    routine_token = _token(
        "klaus.read",
        "klaus.write",
        "klaus.memory",
        "klaus.routine",
        resource="https://klaus.example.com/mcp/routine",
    )
    with pytest.raises(MCPToolError, match="resource"):
        asyncio.run(
            gateway.execute(
                endpoint="interactive",
                tool_name="task_list",
                arguments={},
                token=routine_token,
            )
        )


def test_no_notion_tool_is_served_on_either_endpoint():
    """Notion moved to Claude's own connector — Klaus serves none of it.

    The gateway used to wrap Notion results in an ``untrusted_data`` envelope.
    That wrapper went with the tools; the prompt-injection defence now lives in
    the skills, which tell Claude to treat retrieved pages as untrusted data
    regardless of which connector fetched them.
    """
    from interfaces.mcp_server import INTERACTIVE_TOOLS, ROUTINE_TOOLS

    served = INTERACTIVE_TOOLS | ROUTINE_TOOLS
    assert not [name for name in served if name.startswith("notion_")]


def test_skill_version_is_reported_in_every_tool_metadata():
    from interfaces.mcp_server import EXPECTED_SKILL_VERSION, create_mcp_bundle

    bundle = create_mcp_bundle(_oauth_service(), dispatcher=lambda _name, _args: "{}")
    for server in (bundle.interactive, bundle.routine):
        for tool in server._tool_manager.list_tools():
            assert tool.meta["klaus/skillVersion"] == EXPECTED_SKILL_VERSION


def test_tool_metadata_reports_routine_and_approval_scopes():
    from interfaces.mcp_server import create_mcp_bundle

    bundle = create_mcp_bundle(_oauth_service(), dispatcher=lambda _name, _args: "{}")
    interactive = {
        tool.name: tool for tool in bundle.interactive._tool_manager.list_tools()
    }
    routine = {tool.name: tool for tool in bundle.routine._tool_manager.list_tools()}

    assert "klaus.approve" in interactive["confirm_prepared_action"].meta[
        "klaus/requiredScopes"
    ]
    assert "klaus.routine" in routine["publish_review"].meta[
        "klaus/requiredScopes"
    ]


def test_successful_write_is_deduplicated_and_audited_once():
    from interfaces.mcp_server import KlausMCPGateway

    class FakeIdempotency:
        def __init__(self):
            self.records = {}

        def begin(self, key, *, tool_name, payload, origin):
            if key in self.records:
                return {**self.records[key], "is_new": False}
            record = {
                "idempotency_key": key,
                "tool_name": tool_name,
                "payload": payload,
                "origin": origin,
                "status": "running",
                "is_new": True,
            }
            self.records[key] = record
            return dict(record)

        def mark_executed(self, key, result):
            self.records[key].update(status="executed", result=result)

        def complete(self, key):
            self.records[key]["status"] = "succeeded"

        def fail(self, key, error):
            self.records[key].update(status="failed", error=error)

    calls = []
    audits = []
    gateway = KlausMCPGateway(
        dispatcher=lambda name, args: calls.append((name, args)) or '{"id":"t1"}',
        idempotency_store=FakeIdempotency(),
        auditor=lambda **entry: audits.append(entry),
    )
    kwargs = dict(
        endpoint="interactive",
        tool_name="task_create",
        arguments={"title": "Plan week"},
        token=_token("klaus.read", "klaus.write"),
        idempotency_key="same-request",
    )
    first = asyncio.run(gateway.execute(**kwargs))
    second = asyncio.run(gateway.execute(**kwargs))

    assert first == second == {"id": "t1"}
    assert calls == [("task_create", {"title": "Plan week"})]
    assert len(audits) == 1
    assert audits[0]["idempotency_key"] == "same-request"


@pytest.mark.parametrize("replay_status", ("succeeded", "executed"))
def test_publish_review_replay_sanitizes_legacy_cached_run_without_mutating_it(
    replay_status,
):
    """Legacy cached routine runs must be safe on both gateway replay paths."""
    from interfaces.mcp_server import KlausMCPGateway

    stored_run = hostile_routine_run(status="published_claude")
    cached_result = {
        "review": {"review_id": "morning:2026-08-10", "review_text": "Published."},
        "run": stored_run,
        "delivery": {"sent": 1},
    }
    handler_calls = []
    audit_calls = []

    class ReplayStore:
        def __init__(self):
            self.completed = []

        @staticmethod
        def begin(_key, **_kwargs):
            return {
                "is_new": False,
                "status": replay_status,
                "result": cached_result,
            }

        def complete(self, key):
            self.completed.append(key)

    store = ReplayStore()
    gateway = KlausMCPGateway(
        dispatcher=lambda _name, _arguments: pytest.fail("dispatcher must not run"),
        custom_handlers={
            "publish_review": lambda arguments: handler_calls.append(arguments),
        },
        idempotency_store=store,
        auditor=lambda **entry: audit_calls.append(entry),
    )

    result = asyncio.run(
        gateway.execute(
            endpoint="routine",
            tool_name="publish_review",
            arguments={
                "correlation_id": stored_run["correlation_id"],
                "routine": stored_run["routine"],
                "target_date": stored_run["target_date"],
                "text": "Published.",
                "structured": {},
                "action_ids": [],
                "partial_actions": [],
            },
            token=_token(
                "klaus.read",
                "klaus.write",
                "klaus.routine",
                resource="https://klaus.example.com/mcp/routine",
            ),
            idempotency_key=f"legacy-{replay_status}",
        )
    )

    expected_run = expected_public_routine_run(stored_run)
    assert result == {
        "review": cached_result["review"],
        "run": expected_run,
        "delivery": cached_result["delivery"],
    }
    assert_public_routine_run(result["run"], expected_run)
    assert cached_result["run"] is stored_run
    assert stored_run["remote_trigger_result"]["provider_secret"] == "remote-provider-secret"
    assert handler_calls == []
    if replay_status == "succeeded":
        assert store.completed == []
        assert audit_calls == []
    else:
        assert store.completed == ["legacy-executed"]
        assert len(audit_calls) == 1


@pytest.mark.parametrize("delivery_mode", ["live", "shadow"])
def test_registered_publish_review_structured_output_serializes_atomic_run(
    monkeypatch,
    delivery_mode,
):
    """The real registered MCP converter must serialize live and shadow results."""
    import core.push_sender
    import interfaces.mcp_server as mcp_server
    import memory.firestore_db
    from interfaces.mcp_runtime import build_custom_handlers
    from tests.routine_firestore_fakes import (
        VersionedFirestoreClient,
        transactional_with_retry,
    )

    client = VersionedFirestoreClient(
        server_timestamp=memory.firestore_db.firestore.SERVER_TIMESTAMP
    )
    monkeypatch.setattr("memory.stores.base._make_firestore_client", lambda *_args: client)
    monkeypatch.setattr(
        memory.firestore_db.firestore,
        "transactional",
        transactional_with_retry,
    )
    monkeypatch.setattr(core.push_sender, "send_push_to_all", lambda *_args: {"sent": 1})
    memory.firestore_db.RoutineRunStore("test-project").start(
        routine="morning",
        target_date="2026-08-11",
        trigger="wake",
        correlation_id="mcp-json-safe",
        delivery_mode=delivery_mode,
    )

    class IdempotencyStore:
        @staticmethod
        def begin(*_args, **_kwargs):
            return {"is_new": True, "status": "running"}

        @staticmethod
        def mark_executed(*_args, **_kwargs):
            return None

        @staticmethod
        def complete(*_args, **_kwargs):
            return None

        @staticmethod
        def fail(*_args, **_kwargs):
            return None

    bundle = mcp_server.create_mcp_bundle(
        _oauth_service(),
        custom_handlers=build_custom_handlers(),
        idempotency_store=IdempotencyStore(),
    )
    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: _token(
            "klaus.read",
            "klaus.write",
            "klaus.routine",
            resource="https://klaus.example.com/mcp/routine",
        ),
    )
    tool = bundle.routine._tool_manager.get_tool("publish_review")
    converted = asyncio.run(
        tool.run(
            {
                "arguments": {
                    "correlation_id": "mcp-json-safe",
                    "routine": "morning",
                    "target_date": "2026-08-11",
                    "text": "Serializable morning review.",
                    "structured": {},
                    "action_ids": [],
                    "partial_actions": [],
                },
                "idempotency_key": "mcp-json-safe-once",
            },
            None,
            convert_result=True,
        )
    )

    encoded = converted.model_dump_json()
    assert "Serializable morning review." in encoded
    assert "published_claude" in encoded


def test_routine_cannot_move_or_delete_user_owned_calendar_event():
    from interfaces.mcp_server import KlausMCPGateway, MCPToolError

    gateway = KlausMCPGateway(
        dispatcher=lambda _name, _args: "{}",
        calendar_ownership_checker=lambda _event_id, _calendar_id: False,
    )
    routine_token = _token(
        "klaus.read",
        "klaus.write",
        "klaus.memory",
        "klaus.routine",
        resource="https://klaus.example.com/mcp/routine",
    )
    with pytest.raises(MCPToolError, match="user-created"):
        asyncio.run(
            gateway.execute(
                endpoint="routine",
                tool_name="update_calendar_event",
                arguments={"event_id": "user-event", "start_iso": "2026-08-09T10:00:00+03:00"},
                token=routine_token,
                idempotency_key="move-user-event",
            )
        )


def test_streamable_http_protocol_rejects_unauthorized_and_initializes_with_token():
    service = _oauth_service()
    from interfaces.mcp_server import create_mcp_bundle

    client_registration = service.register_client({
        "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
        "token_endpoint_auth_method": "none",
    })
    verifier = "m" * 64
    import base64
    import hashlib

    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    authorization = service.authorize(
        client_id=client_registration["client_id"],
        redirect_uri=client_registration["redirect_uris"][0],
        scope="klaus.read klaus.write klaus.memory klaus.approve",
        code_challenge=challenge,
        code_challenge_method="S256",
        resource=service.interactive_resource,
        subject="amit.grupper@gmail.com",
    )
    issued = service.exchange_authorization_code(
        code=authorization["code"],
        client_id=client_registration["client_id"],
        redirect_uri=client_registration["redirect_uris"][0],
        code_verifier=verifier,
    )

    bundle = create_mcp_bundle(service, dispatcher=lambda _name, _args: "{}")
    from mcp.server.transport_security import TransportSecuritySettings

    mcp_app = bundle.interactive.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=["testserver"]),
    )
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "klaus-test", "version": "1"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(mcp_app) as client:
        unauthorized = client.post("/", json=initialize, headers=headers)
        authorized = client.post(
            "/",
            json=initialize,
            headers={**headers, "Authorization": f"Bearer {issued['access_token']}"},
        )

    assert unauthorized.status_code == 401
    assert "resource_metadata" in unauthorized.headers["www-authenticate"]
    assert authorized.status_code == 200
    assert authorized.json()["result"]["serverInfo"]["name"] == "Klaus Interactive"
