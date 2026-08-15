"""Scoped remote MCP servers for Claude conversations and Remote Routines."""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Awaitable, Callable

from jsonschema import Draft202012Validator, FormatChecker
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations
from pydantic import WithJsonSchema

from interfaces.mcp_custom_schemas import custom_tool_schema
from interfaces.mcp_oauth import KlausTokenVerifier, OAuthAuthorizationService


EXPECTED_SKILL_VERSION = "7.2.0"

READ_TOOLS = frozenset(
    {
        "list_calendar_events",
        "check_calendar_free",
        "task_list",
        "get_habit_adherence",
        "recall",
        "fetch_weather",
        "fetch_garmin_today",
        "notion_search",
        "notion_get_page",
        "notion_query_database",
        "get_self_status",
        "get_push_health",
        "list_followups",
        "list_standing_directives",
        "get_training_profile",
        "read_coaching_guide",
        "fetch_training_status",
        "fetch_recent_activities",
        "get_acwr",
        "fetch_recent_meals",
        "fetch_nutrition_trend",
        "get_training_history",
        "get_strength_progress",
        "get_training_context",
        "get_training_reality",
        "get_run_detail",
        "get_plan",
        "get_block_status",
        "get_benchmark_history",
        "get_goal_projection",
    }
)

WRITE_TOOLS = frozenset(
    {
        "create_calendar_event",
        "delete_calendar_event",
        "update_calendar_event",
        "task_create",
        "task_complete",
        "task_reschedule",
        "task_edit",
        "task_delete",
        "notion_create_page",
        "notion_append_blocks",
        "schedule_followup",
        "cancel_followup",
        "set_standing_directive",
        "cancel_standing_directive",
        "update_training_profile",
        "update_plan",
        "log_training",
        "log_benchmark",
        "start_block",
        "end_block",
    }
)

MEMORY_READ_TOOLS = frozenset({"recall"})
MEMORY_WRITE_TOOLS = frozenset({"remember", "forget_memory"})
TRAINING_WRITE_TOOLS = frozenset(
    {
        "update_training_profile",
        "update_plan",
        "log_training",
        "log_benchmark",
        "start_block",
        "end_block",
    }
)

COMMON_CUSTOM_READ_TOOLS = frozenset(
    {
        "get_life_snapshot",
        "query_health_database",
        "list_portfolio_holdings",
        "get_routine_status",
    }
)
COMMON_CUSTOM_WRITE_TOOLS = frozenset(
    {"upsert_portfolio_holding", "prepare_high_risk_action"}
)
INTERACTIVE_CUSTOM_TOOLS = frozenset(
    {"confirm_prepared_action", "list_pending_approvals"}
)
ROUTINE_CUSTOM_TOOLS = frozenset({"publish_review", "publish_portfolio_snapshot"})

INTERACTIVE_TOOLS = frozenset(
    READ_TOOLS
    | WRITE_TOOLS
    | MEMORY_WRITE_TOOLS
    | COMMON_CUSTOM_READ_TOOLS
    | COMMON_CUSTOM_WRITE_TOOLS
    | INTERACTIVE_CUSTOM_TOOLS
)
ROUTINE_TOOLS = frozenset(
    READ_TOOLS
    | (WRITE_TOOLS - TRAINING_WRITE_TOOLS)
    | MEMORY_WRITE_TOOLS
    | COMMON_CUSTOM_READ_TOOLS
    | COMMON_CUSTOM_WRITE_TOOLS
    | ROUTINE_CUSTOM_TOOLS
)

WRITE_LIKE_TOOLS = frozenset(
    WRITE_TOOLS | MEMORY_WRITE_TOOLS | COMMON_CUSTOM_WRITE_TOOLS | {
        "confirm_prepared_action",
        "publish_review",
        "publish_portfolio_snapshot",
    }
)


class MCPToolError(ValueError):
    """Safe policy or validation failure returned to the MCP client."""


CustomHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]
Auditor = Callable[..., Any | Awaitable[Any]]
CalendarOwnershipChecker = Callable[[str, str | None], bool | Awaitable[bool]]


@lru_cache(maxsize=None)
def _custom_tool_validator(tool_name: str) -> Draft202012Validator | None:
    """Build and cache the validator for one explicitly registered custom tool."""
    schema = custom_tool_schema(tool_name)
    if schema is None:
        return None
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_custom_tool_arguments(
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    """Reject malformed custom-tool arguments without echoing their payload."""
    validator = _custom_tool_validator(tool_name)
    if validator is None:
        return
    violation = next(validator.iter_errors(arguments), None)
    if violation is None:
        return
    rule = str(violation.validator or "schema")
    # ``absolute_path`` can include attacker-controlled keys from maps such as
    # portfolio quotes.  Return only schema-owned context to the remote client.
    raise MCPToolError(f"Invalid arguments for {tool_name}: schema rule {rule} failed")


class KlausMCPGateway:
    """Server-side scope, endpoint, idempotency, and trust boundary."""

    def __init__(
        self,
        *,
        dispatcher: Callable[[str, dict], Any],
        custom_handlers: dict[str, CustomHandler] | None = None,
        idempotency_store: Any | None = None,
        auditor: Auditor | None = None,
        calendar_ownership_checker: CalendarOwnershipChecker | None = None,
        interactive_resource: str = "https://klaus.example.com/mcp/interactive",
        routine_resource: str = "https://klaus.example.com/mcp/routine",
        read_only: bool = False,
    ) -> None:
        self._dispatcher = dispatcher
        self._custom_handlers = custom_handlers or {}
        self._idempotency_store = idempotency_store
        self._auditor = auditor
        self._calendar_ownership_checker = calendar_ownership_checker
        self._resources = {
            "interactive": interactive_resource,
            "routine": routine_resource,
        }
        self._read_only = read_only

    @staticmethod
    def _require_scopes(token: AccessToken, required: set[str]) -> None:
        missing = required - set(token.scopes)
        if missing:
            raise MCPToolError(f"Missing required scope: {', '.join(sorted(missing))}")

    async def execute(
        self,
        *,
        endpoint: str,
        tool_name: str,
        arguments: dict[str, Any],
        token: AccessToken,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if self._read_only:
            catalog = READ_TOOLS | MEMORY_READ_TOOLS | COMMON_CUSTOM_READ_TOOLS
            if endpoint == "routine":
                catalog = frozenset()
        else:
            catalog = INTERACTIVE_TOOLS if endpoint == "interactive" else ROUTINE_TOOLS
        if tool_name not in catalog:
            raise MCPToolError(f"Tool {tool_name!r} is not available on {endpoint}")
        expected_resource = self._resources[endpoint]
        if token.resource != expected_resource:
            raise MCPToolError("Token resource does not match this MCP endpoint")

        required = {"klaus.read"}
        if tool_name in WRITE_LIKE_TOOLS:
            required.add("klaus.write")
            if not idempotency_key or not idempotency_key.strip():
                raise MCPToolError("idempotency_key is required for every write")
        if tool_name in MEMORY_READ_TOOLS | MEMORY_WRITE_TOOLS:
            required.add("klaus.memory")
        if tool_name in ROUTINE_CUSTOM_TOOLS:
            required.add("klaus.routine")
        if tool_name == "confirm_prepared_action":
            required.add("klaus.approve")
        self._require_scopes(token, required)

        if not isinstance(arguments, dict):
            raise MCPToolError("arguments must be an object")
        _validate_custom_tool_arguments(tool_name, arguments)
        if endpoint == "routine" and tool_name in {
            "update_calendar_event",
            "delete_calendar_event",
        }:
            if self._calendar_ownership_checker is None:
                owned = False
            else:
                owned = self._calendar_ownership_checker(
                    str(arguments.get("event_id") or ""),
                    arguments.get("calendar_id"),
                )
                if asyncio.iscoroutine(owned):
                    owned = await owned
            if not owned:
                raise MCPToolError(
                    "Routines cannot move or delete a user-created calendar event"
                )
        claim = None
        if tool_name in WRITE_LIKE_TOOLS and self._idempotency_store is not None:
            claim = await asyncio.to_thread(
                self._idempotency_store.begin,
                idempotency_key,
                tool_name=tool_name,
                payload=arguments,
                origin=endpoint,
            )
            if not claim.get("is_new"):
                status = claim.get("status")
                if status == "succeeded":
                    return self._outward_result(
                        tool_name, dict(claim.get("result") or {})
                    )
                if status == "executed":
                    result = dict(claim.get("result") or {})
                    await self._audit(
                        endpoint, tool_name, arguments, idempotency_key or "", result
                    )
                    await asyncio.to_thread(self._idempotency_store.complete, idempotency_key)
                    return self._outward_result(tool_name, result)
                raise MCPToolError(f"Idempotent write is already {status}")

        executed = False
        try:
            handler = self._custom_handlers.get(tool_name)
            if handler:
                handler_arguments = {**arguments, "_mcp_origin": endpoint}
                if inspect.iscoroutinefunction(handler):
                    result = await handler(handler_arguments)
                else:
                    result = await asyncio.to_thread(handler, handler_arguments)
                    if asyncio.iscoroutine(result):
                        result = await result
            else:
                result = await asyncio.to_thread(self._dispatcher, tool_name, arguments)
            result = self._normalise_result(result)
            if claim is not None:
                await asyncio.to_thread(
                    self._idempotency_store.mark_executed, idempotency_key, result
                )
                executed = True
            if tool_name in WRITE_LIKE_TOOLS:
                await self._audit(
                    endpoint, tool_name, arguments, idempotency_key or "", result
                )
            if claim is not None:
                await asyncio.to_thread(self._idempotency_store.complete, idempotency_key)
        except Exception as exc:
            if claim is not None and claim.get("is_new") and not executed:
                await asyncio.to_thread(
                    self._idempotency_store.fail, idempotency_key, str(exc)
                )
            raise
        if tool_name.startswith("notion_"):
            return {"untrusted_data": True, "source": "notion", "data": result}
        return result

    @staticmethod
    def _normalise_result(result: Any) -> dict[str, Any]:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                result = {"result": result}
        if not isinstance(result, dict):
            result = {"data": result}
        return result

    @staticmethod
    def _outward_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
        """Sanitize stored results only where the routine-run contract applies."""
        if tool_name != "publish_review" or "run" not in result:
            return result
        from core.review_delivery import public_routine_run

        return {**result, "run": public_routine_run(result.get("run"))}

    async def _audit(
        self,
        endpoint: str,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        result: dict[str, Any],
    ) -> None:
        if self._auditor is None:
            return
        audited = self._auditor(
            origin=endpoint,
            tool_name=tool_name,
            arguments=arguments,
            idempotency_key=idempotency_key,
            result=result,
        )
        if asyncio.iscoroutine(audited):
            await audited


@dataclass(slots=True)
class MCPServerBundle:
    interactive: MCPServer
    routine: MCPServer
    gateway: KlausMCPGateway


@lru_cache(maxsize=1)
def _schema_metadata() -> dict[str, dict[str, Any]]:
    """Return canonical retained schemas without the removed self manifest."""
    from core.tools import get_all_schemas
    from interfaces.mcp_custom_schemas import CUSTOM_TOOL_SCHEMAS

    metadata = {
        schema["name"]: {
            "purpose": schema.get("description", schema["name"]),
            "input_schema": schema.get("input_schema", {}),
        }
        for schema in get_all_schemas()
    }
    metadata.update({
        name: {"purpose": name.replace("_", " ").capitalize(), "input_schema": schema}
        for name, schema in CUSTOM_TOOL_SCHEMAS.items()
    })
    return metadata


def _register_tool(server: MCPServer, gateway: KlausMCPGateway, endpoint: str, name: str) -> None:
    metadata = _schema_metadata()
    is_write = name in WRITE_LIKE_TOOLS

    async def invoke(
        arguments: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        token = get_access_token()
        if token is None:
            raise MCPToolError("Authenticated MCP access token is required")
        return await gateway.execute(
            endpoint=endpoint,
            tool_name=name,
            arguments=arguments or {},
            token=token,
            idempotency_key=idempotency_key,
        )

    invoke.__name__ = f"{endpoint}_{name}"
    canonical = metadata.get(name, {})
    description = str(canonical.get("purpose") or "") or {
        "get_life_snapshot": "Return Klaus's compact normalized life snapshot.",
        "query_health_database": "Run a bounded read-only health SQL query.",
        "list_portfolio_holdings": "List active portfolio holdings and provenance.",
        "get_routine_status": "Read the latest routine run state.",
        "upsert_portfolio_holding": "Create or update a portfolio holding.",
        "prepare_high_risk_action": "Queue an immutable high-risk action for approval.",
        "confirm_prepared_action": "Confirm and execute an exact prepared action.",
        "list_pending_approvals": "List high-risk actions awaiting the user.",
        "publish_review": (
            "Publish the final, one-shot Claude routine review callback. Never call "
            "this tool with schema probes, placeholders, or test content."
        ),
        "publish_portfolio_snapshot": "Persist a weekly ILS portfolio valuation.",
    }.get(name, f"Klaus tool: {name}")

    # MCPServer derives the published JSON schema from the callable signature.
    # Keep the stable outer ``arguments`` envelope used by the gateway, but
    # annotate it with the canonical retained tool schema so clients can see the
    # exact field names, types, and required set.  Without this, every tool is
    # advertised as an unrestricted object and models must guess parameter
    # names (for example start_date instead of time_min_iso).
    input_schema = canonical.get("input_schema") or custom_tool_schema(name)
    arguments_annotation: Any = dict[str, Any]
    if isinstance(input_schema, dict):
        arguments_annotation = Annotated[
            dict[str, Any],
            WithJsonSchema(input_schema),
        ]
    arguments_required = is_write or bool(
        isinstance(input_schema, dict) and input_schema.get("required")
    )
    parameters = [
        inspect.Parameter(
            "arguments",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=(inspect.Parameter.empty if arguments_required else None),
            annotation=arguments_annotation,
        )
    ]
    if is_write:
        parameters.append(
            inspect.Parameter(
                "idempotency_key",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=str,
            )
        )
    invoke.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=parameters,
        return_annotation=dict[str, Any],
    )
    server.add_tool(
        invoke,
        name=name,
        description=(
            f"{description} Pass the original tool fields inside `arguments`. "
            + ("A unique idempotency_key is required." if is_write else "")
        ),
        annotations=ToolAnnotations(
            readOnlyHint=not is_write,
            destructiveHint=name in {"delete_calendar_event", "task_delete"},
            idempotentHint=bool(is_write),
            openWorldHint=name.startswith("notion_") or name == "fetch_weather",
        ),
        meta={
            "klaus/skillVersion": EXPECTED_SKILL_VERSION,
            "klaus/endpoint": endpoint,
            "klaus/requiredScopes": sorted(
                {"klaus.read"}
                | ({"klaus.write"} if is_write else set())
                | ({"klaus.memory"} if name in MEMORY_READ_TOOLS | MEMORY_WRITE_TOOLS else set())
                | ({"klaus.routine"} if name in ROUTINE_CUSTOM_TOOLS else set())
                | ({"klaus.approve"} if name == "confirm_prepared_action" else set())
            ),
        },
        structured_output=True,
    )


def create_mcp_bundle(
    oauth_service: OAuthAuthorizationService,
    *,
    dispatcher: Callable[[str, dict], Any] | None = None,
    custom_handlers: dict[str, CustomHandler] | None = None,
    idempotency_store: Any | None = None,
    auditor: Auditor | None = None,
    calendar_ownership_checker: CalendarOwnershipChecker | None = None,
    read_only: bool = False,
) -> MCPServerBundle:
    """Construct independently authenticated stateless MCP servers."""
    if dispatcher is None:
        from core.tools import dispatch

        dispatcher = dispatch
    gateway = KlausMCPGateway(
        dispatcher=dispatcher,
        custom_handlers=custom_handlers,
        idempotency_store=idempotency_store,
        auditor=auditor,
        calendar_ownership_checker=calendar_ownership_checker,
        interactive_resource=oauth_service.interactive_resource,
        routine_resource=oauth_service.routine_resource,
        read_only=read_only,
    )
    interactive = MCPServer(
        "Klaus Interactive",
        version="7.2.0",
        instructions="Use get_life_snapshot first. Klaus backend data is authoritative.",
        token_verifier=KlausTokenVerifier(oauth_service, oauth_service.interactive_resource),
        auth=AuthSettings(
            issuer_url=oauth_service.issuer_url,
            resource_server_url=oauth_service.interactive_resource,
            required_scopes=["klaus.read"],
        ),
    )
    routine = MCPServer(
        "Klaus Routines",
        version="7.2.0",
        instructions="Use get_life_snapshot first. Routines cannot approve actions.",
        token_verifier=KlausTokenVerifier(oauth_service, oauth_service.routine_resource),
        auth=AuthSettings(
            issuer_url=oauth_service.issuer_url,
            resource_server_url=oauth_service.routine_resource,
            required_scopes=["klaus.read"],
        ),
    )
    interactive_tools = (
        READ_TOOLS | MEMORY_READ_TOOLS | COMMON_CUSTOM_READ_TOOLS
        if read_only
        else INTERACTIVE_TOOLS
    )
    routine_tools = frozenset() if read_only else ROUTINE_TOOLS
    for name in sorted(interactive_tools):
        _register_tool(interactive, gateway, "interactive", name)
    for name in sorted(routine_tools):
        _register_tool(routine, gateway, "routine", name)
    return MCPServerBundle(interactive=interactive, routine=routine, gateway=gateway)
