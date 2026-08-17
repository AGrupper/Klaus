"""The deterministic tool catalog and the registry that builds it.

Replaces four `test_tool_registration_phase*.py` files. Each was written when a
batch of tools shipped, and each asserted the same thing about its own batch:
that the tool appeared in `TOOL_SCHEMAS` *and* in `_HANDLERS`. That check existed
because a tool used to be declared in three places that could disagree — a
schema literal, a handler function, and a dispatch dict.

There is now one declaration per tool, so the classes of drift those tests
guarded cannot be expressed. What remains worth asserting is the catalog itself:
the exact set of published tools, that every schema is well formed, and that
registration is enforced rather than assumed.
"""
from __future__ import annotations

import json

import pytest

import core.tools as tools
from core.tools.registry import DuplicateToolError, tool


# The full published catalog. This is a contract with the Claude Project: the
# skills call these names, so a rename is a breaking change and should have to
# be made deliberately, here, in one place.
EXPECTED_TOOLS = {
    # calendar
    "list_calendar_events", "create_calendar_event", "check_calendar_free",
    "delete_calendar_event", "update_calendar_event",
    # tasks
    "task_create", "task_list", "task_complete", "task_reschedule",
    "task_edit", "task_delete",
    # habits
    "get_habit_adherence",
    # memory
    "remember", "recall", "forget_memory",
    # ambient / self
    "fetch_weather", "fetch_garmin_today", "get_self_status", "get_push_health",
    # follow-ups and directives
    "schedule_followup", "list_followups", "cancel_followup",
    "set_standing_directive", "list_standing_directives", "cancel_standing_directive",
    # plan and reference documents
    "get_training_profile", "read_coaching_guide", "read_user_profile",
    "update_training_profile", "update_plan",
    # garmin
    "fetch_training_status", "fetch_recent_activities", "get_acwr",
    # nutrition
    "fetch_recent_meals", "fetch_nutrition_trend",
    # training log
    "log_training", "get_training_history",
    # cross-domain training reads
    "get_strength_progress", "get_training_context", "get_training_reality",
    "get_run_detail",
    # blocks, benchmarks, projection
    "get_plan", "get_block_status", "log_benchmark", "get_benchmark_history",
    "get_goal_projection", "start_block", "end_block",
}


def test_published_catalog_is_exactly_the_expected_set():
    published = {schema["name"] for schema in tools.get_all_schemas()}
    assert published == EXPECTED_TOOLS, (
        f"added: {sorted(published - EXPECTED_TOOLS)}, "
        f"removed: {sorted(EXPECTED_TOOLS - published)}"
    )


def test_every_published_tool_is_callable():
    """A schema without a handler is a tool Claude can see and cannot use."""
    handlers = tools.registered_tools()
    published = {schema["name"] for schema in tools.get_all_schemas()}
    assert set(handlers) == published


def test_every_handler_can_resolve_the_names_it_calls():
    """A handler that references an undefined global is a tool that raises.

    Having a handler is not the same as having a working one. `fetch_garmin_today`
    and `fetch_weather` both shipped with their backend import stripped by an
    unused-import cleanup, so the module imported cleanly, the catalog looked
    complete, and the tools raised NameError the first time Claude called them —
    found in a live routine run on 2026-08-17, not by this suite.

    Resolving LOAD_GLOBAL against each handler's own globals catches that
    statically, without importing a network client or calling anything. Handlers
    are closures, so the real function has to be unwrapped out of __closure__ —
    checking only the top-level object silently passes everything.
    """
    import builtins
    import dis
    import types

    def unwrap(fn, depth=0):
        found = [fn]
        if depth > 5:
            return found
        for cell in (getattr(fn, "__closure__", None) or ()):
            try:
                value = cell.cell_contents
            except ValueError:  # cell not yet filled
                continue
            if isinstance(value, types.FunctionType):
                found += unwrap(value, depth + 1)
        return found

    builtin_names = set(dir(builtins))
    unresolved = []
    for name, handler in sorted(tools.registered_tools().items()):
        for fn in unwrap(handler):
            code = getattr(fn, "__code__", None)
            if code is None:
                continue
            for instruction in dis.get_instructions(code):
                if "LOAD_GLOBAL" not in instruction.opname:
                    continue
                referenced = instruction.argval
                if referenced in fn.__globals__ or referenced in builtin_names:
                    continue
                unresolved.append(f"{name}: {fn.__module__} references {referenced!r}")

    assert not unresolved, "tools that will raise NameError when called:\n" + "\n".join(
        sorted(set(unresolved))
    )


@pytest.mark.parametrize("schema", tools.get_all_schemas(), ids=lambda s: s["name"])
def test_schema_is_well_formed(schema):
    assert schema["description"].strip(), "a tool with no description is a tool Claude will misuse"
    input_schema = schema["input_schema"]
    assert input_schema["type"] == "object"
    assert isinstance(input_schema.get("properties", {}), dict)
    # Every required argument must actually be declared.
    properties = set(input_schema.get("properties", {}))
    assert set(input_schema.get("required", [])) <= properties


@pytest.mark.parametrize("schema", tools.get_all_schemas(), ids=lambda s: s["name"])
def test_schema_is_json_serialisable(schema):
    """Schemas are published over MCP, so they must survive a round trip."""
    assert json.loads(json.dumps(schema)) == schema


def test_update_plan_is_an_alias_of_update_training_profile():
    """Two names, one write. Claude reaches for both."""
    handlers = tools.registered_tools()
    assert "update_plan" in handlers
    assert "update_training_profile" in handlers
    alias_schema = next(s for s in tools.get_all_schemas() if s["name"] == "update_plan")
    assert alias_schema["input_schema"]["required"] == ["patch"]


def test_registering_a_duplicate_name_is_refused():
    """Silently overwriting would take the first tool offline on a rename."""
    with pytest.raises(DuplicateToolError):

        @tool({"name": "task_list", "description": "x", "input_schema": {"type": "object"}})
        def _shadow() -> str:
            return "{}"


def test_dispatch_rejects_an_unknown_tool_by_raising():
    with pytest.raises(KeyError):
        tools.dispatch("no_such_tool", {})


def test_dispatch_returns_wrong_arguments_as_an_error_payload():
    """A bad call must come back as JSON the model can read and correct, not a crash."""
    result = json.loads(tools.dispatch("task_list", {"not_a_real_argument": 1}))
    assert "error" in result
