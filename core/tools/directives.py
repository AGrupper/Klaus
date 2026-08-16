"""Standing directives — instructions that persist until cancelled.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from core.tools.registry import tool

logger = logging.getLogger(__name__)


@tool({
        "name": "set_standing_directive",
        "description": (
            "Capture one of Amit's lasting behavioral wishes verbatim as a durable standing "
            "directive — a persistent instruction that outlives this conversation (e.g. 'no "
            "training nudges until I'm back from France', 'always suggest 2 restaurant options'). "
            "Capture liberally whenever a remark plausibly reads as a lasting wish — do not ask a "
            "gating question first; your one-line ack is the correction surface. `expires_at` "
            "(ISO 8601 or natural language) and `condition_text` (event-based, e.g. 'while I'm in "
            "France') are both optional — a directive with neither persists indefinitely until "
            "cancelled. Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The wish, captured verbatim."},
                "expires_at": {
                    "type": "string",
                    "description": "Optional ISO 8601 or natural-language hard-date expiry.",
                },
                "condition_text": {
                    "type": "string",
                    "description": "Optional event-based expiry description (e.g. 'while I'm in France').",
                },
                "supersedes": {
                    "type": "string",
                    "description": (
                        "Optional id of an existing directive this refined directive replaces when "
                        "resolving a persona conflict (D-16) — the old directive is marked "
                        "superseded_by this new one. Get the id from a prior list_standing_directives "
                        "call."
                    ),
                },
            },
            "required": ["text"],
        },
    })
def _handle_set_standing_directive(
    text: str,
    expires_at: str | None = None,
    condition_text: str | None = None,
    supersedes: str | None = None,
) -> str:
    """Capture a standing directive verbatim (DIR-01). Origin defaults to
    'user_chat' — capture is user-initiated, unlike self-scheduled follow-ups
    which default to 'klaus_self'.

    `expires_at` is expected as ISO 8601 where possible (the brain should
    pass ISO), but a natural-language string is parsed defensively via the
    same dateutil try/except shape as `_handle_schedule_followup` — the
    field is stored as-received if it isn't parseable as either, since
    `condition_text` is the intended path for non-dated expiries anyway.

    `supersedes` (D-16 persona-conflict resolution): when set to an existing
    directive's id, the new directive is added first, then the old directive
    is flipped to `status="superseded"` + `superseded_by=<new id>` via
    `StandingDirectiveStore.supersede()` — a durable audit link, distinct
    from a plain cancel. Backward compatible: omitting `supersedes` never
    calls `supersede()` (unchanged capture behavior).

    Args:
        text: The wish, captured verbatim.
        expires_at: Optional ISO 8601 or natural-language hard-date expiry.
        condition_text: Optional event-based expiry description.
        supersedes: Optional id of an existing directive this one replaces.

    Returns:
        JSON string of the persisted directive doc, plus a `"superseded"`
        bool key when `supersedes` was provided.
    """
    from datetime import timezone as _tz

    normalized_expiry = expires_at
    if expires_at:
        try:
            due_dt = datetime.fromisoformat(expires_at)
        except (ValueError, TypeError):
            try:
                from dateutil import parser as _dt_parser
                due_dt = _dt_parser.parse(expires_at)
            except (ImportError, ValueError, TypeError, OverflowError):
                due_dt = None
        if due_dt is not None:
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=_tz.utc)
            normalized_expiry = due_dt.astimezone(_tz.utc).isoformat()

    from memory.firestore_db import StandingDirectiveStore
    store = StandingDirectiveStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    result = store.add(
        text=text,
        origin="user_chat",
        context_quote=text,
        expires_at=normalized_expiry,
        condition_text=condition_text,
    )
    if supersedes:
        result = dict(result)
        result["superseded"] = bool(store.supersede(old_id=supersedes, new_directive_id=result["id"]))
    return json.dumps(result)


@tool({
        "name": "list_standing_directives",
        "description": (
            "List Amit's standing directives — active by default; pass include_history=true when "
            "he asks about cancelled/expired/superseded ones too. Returns id, text, origin, "
            "expires_at, condition_text, status for each; self-proposed directives (origin="
            "'klaus_self') are marked accordingly. Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "include_history": {
                    "type": "boolean",
                    "description": "True to include cancelled/expired/superseded directives. Defaults to active-only.",
                },
            },
            "required": [],
        },
    })
def _handle_list_standing_directives(include_history: bool = False) -> str:
    """Return standing directives, stripped of internal fields (D-17/D-18:
    active by default, full history on ask).

    Args:
        include_history: True to include cancelled/expired/superseded
            directives via `list_all()`; False (default) returns only
            `list_active()`.

    Returns:
        JSON string list of {id, text, origin, expires_at, condition_text,
        status}. Self-proposed entries (origin='klaus_self') are preserved
        as-is so the brain can mark them accordingly when presenting.
    """
    from memory.firestore_db import StandingDirectiveStore
    store = StandingDirectiveStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    items = store.list_all() if include_history else store.list_active()
    stripped = [
        {
            "id": d.get("id", ""),
            "text": d.get("text", ""),
            "origin": d.get("origin", ""),
            "expires_at": d.get("expires_at"),
            "condition_text": d.get("condition_text"),
            "status": d.get("status", "active"),
        }
        for d in items
    ]
    return json.dumps(stripped)


@tool({
        "name": "cancel_standing_directive",
        "description": (
            "Cancel a standing directive by id. Idempotent — calling on an already-cancelled "
            "directive is safe. Resolve the id from a prior list_standing_directives call — Amit "
            "may refer to it by number or by natural-language description ('drop the France one'); "
            "no confirmation gate needed. Rejecting a directive Klaus proposed himself (origin "
            "'klaus_self') durably vetoes it (status='vetoed', never deleted) so reflection will "
            "not propose the same or near-same directive again — the veto is itself training "
            "signal (D-13). Amit cancelling his own directive still writes 'cancelled'. Returns "
            "{ok: bool}. Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Directive id from list_standing_directives."},
            },
            "required": ["id"],
        },
    })
def _handle_cancel_standing_directive(id: str) -> str:
    """Cancel a standing directive by id. Idempotent (D-17 — the brain
    resolves a number or natural-language description to an id from a
    prior list_standing_directives call; no command syntax required here).

    Origin-aware routing (DIR-07/D-13, verification gap 2): a directive
    Klaus proposed himself (``origin == "klaus_self"``) is durably VETOED
    (status='vetoed', never hard-deleted) rather than merely cancelled —
    rejecting a self-proposal is training signal that feeds
    `core/reflection.py`'s vetoed_texts guard so the same or near-same
    directive is never re-proposed. A directive Amit stated himself
    (``origin == "user_chat"``) still cancels normally — cancelling one's
    own wish is not an anti-lesson.

    Returns ``{"ok": True}`` whenever the doc exists (even if already
    cancelled/vetoed). Returns ``{"ok": False}`` when the id does not exist.
    """
    from memory.firestore_db import StandingDirectiveStore
    store = StandingDirectiveStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    directive = store.get(id)
    if directive is None:
        return json.dumps({"ok": False})
    if directive.get("origin") == "klaus_self":
        ok = store.veto(id)
    else:
        ok = store.cancel(id)
    return json.dumps({"ok": bool(ok)})
