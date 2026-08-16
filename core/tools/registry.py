"""The deterministic tool registry: one decorator, one dispatcher.

A tool used to be spread across three places that had to agree — an entry in a
1,200-line `TOOL_SCHEMAS` literal, a `_handle_*` function some 1,500 lines
below it, and a row in the `_HANDLERS` dispatch dict. Editing two of the three
shipped a tool that was published but not callable, or callable but invisible;
four test files existed largely to catch that.

Here a tool is one decorated function:

    @tool({
        "name": "check_calendar_free",
        "description": "Check whether a window is free across all calendars.",
        "input_schema": {...},
    })
    def _handle_check_calendar_free(start_iso: str, end_iso: str) -> str:
        ...

Registration happens on import, so the schema and the implementation cannot
disagree — there is only one of each.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# name -> (schema, handler), in registration order so the published catalog is
# stable across restarts.
_REGISTRY: dict[str, tuple[dict, Callable[..., str]]] = {}


class DuplicateToolError(RuntimeError):
    """Raised when two tools claim the same name."""


def tool(schema: dict) -> Callable[[Callable[..., str]], Callable[..., str]]:
    """Register a handler under the MCP schema published for it.

    Args:
        schema: The full tool schema — ``name``, ``description`` and
            ``input_schema``. Published to Claude verbatim; the argument names
            in ``input_schema`` are the handler's keyword arguments and are a
            public contract.

    Returns:
        The decorator. It returns the handler unchanged, so a handler stays
        directly callable and unit-testable without going through dispatch.

    Raises:
        DuplicateToolError: If the name is already registered. Silently
            overwriting would let a rename take one tool offline.
        KeyError: If the schema has no ``name``.
    """
    name = schema["name"]

    def register(handler: Callable[..., str]) -> Callable[..., str]:
        if name in _REGISTRY:
            raise DuplicateToolError(f"Tool {name!r} is already registered")
        _REGISTRY[name] = (schema, handler)
        return handler

    return register


def get_all_schemas() -> list[dict]:
    """Return every registered tool schema, for the MCP catalog."""
    return [schema for schema, _handler in _REGISTRY.values()]


def registered_tools() -> dict[str, Callable[..., str]]:
    """Return ``{name: handler}``. Used by tests and introspection."""
    return {name: handler for name, (_schema, handler) in _REGISTRY.items()}


def dispatch(tool_name: str, args: dict) -> str:
    """Execute a tool by name and return a JSON string result.

    Args:
        tool_name: Registered deterministic tool name.
        args: Arguments matching the tool's input_schema.

    Returns:
        JSON string result from the handler.

    Raises:
        KeyError: If tool_name is not registered.
    """
    if tool_name not in _REGISTRY:
        raise KeyError(
            f"Unknown tool: '{tool_name}'. "
            f"Available: {sorted(_REGISTRY)}"
        )

    logger.info("Tool dispatch: %s args=%s", tool_name, args)
    _schema, handler = _REGISTRY[tool_name]
    try:
        result = handler(**args)
        logger.debug("Tool result (%s): %.200s", tool_name, result)
        return result
    except TypeError as exc:
        # WHY: the LLM occasionally passes wrong argument names. Return a clear
        # error so the model can self-correct on the next iteration.
        error_msg = f"Tool '{tool_name}' received unexpected arguments: {exc}"
        logger.warning(error_msg)
        return json.dumps({"error": error_msg})
    except Exception as exc:
        # WHY: catch ValueErrors (like invalid date formats) and network errors
        # so they don't crash the orchestrator. Feed the error back to the LLM
        # so it can self-correct.
        error_msg = f"Tool '{tool_name}' encountered an error: {type(exc).__name__}: {exc}"
        logger.exception(error_msg)
        return json.dumps({"error": error_msg})
