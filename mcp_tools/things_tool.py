"""Things 3 cloud tool — read and write Amit's real to-do list via Things Cloud.

Cultured Code publishes **no** API.  This module speaks the reverse-engineered
Things Cloud sync protocol documented in ``docs/things_protocol.md``, which was
derived empirically by replaying the live journal (``scripts/spike_things_protocol.py``).
It can break on any Things release.

Things Cloud is a **journaled delta protocol**, not a snapshot API: you replay an
append-only log of create/edit/delete records and fold it into current state.  This
module is **stateless** — it fetches, decodes, and encodes; persistence and the
materialized mirror are the job of ``memory.firestore_db.ThingsTaskStore``.

Auth is an account email + password (Things Cloud has no tokens and no 2FA), read
lazily per call from ``THINGS_EMAIL`` / ``THINGS_PASSWORD``.

Safety rails:
  * All writes are gated on ``THINGS_WRITE_ENABLED`` (default off).
  * Deletes are never issued — :func:`build_trash` sets the ``tr`` flag, which is
    recoverable from the Things trash.
  * Unknown payload keys are preserved verbatim on edit, so fields this module
    does not understand survive a round-trip.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

THINGS_BASE = "https://cloud.culturedcode.com/version/1"
_TZ = ZoneInfo("Asia/Jerusalem")

# Journal operation codes ('t').  Honouring DELETE is mandatory — treating it as a
# merge silently resurrects deleted data (see docs/things_protocol.md §2).
OP_CREATE, OP_EDIT, OP_DELETE = 0, 1, 2

# Task6 'tp' — entity type
TP_TODO, TP_PROJECT, TP_HEADING = 0, 1, 2

# Task6 'ss' — status
SS_OPEN, SS_CANCELED, SS_COMPLETED = 0, 2, 3

# Task6 'st' — bucket
ST_INBOX, ST_ANYTIME, ST_SOMEDAY = 0, 1, 2

CLASS_TASK = "Task6"
CLASS_AREA = "Area3"
CLASS_TAG = "Tag4"
CLASS_CHECKLIST = "ChecklistItem3"
CLASS_TOMBSTONE = "Tombstone2"

# Constant across every row observed in the live account.  Echoed verbatim on
# create so new items match what the app produces; never synthesized differently.
_TASK_DEFAULTS = {
    "do": 0, "sb": 0, "dl": [], "dds": None, "rmd": None,
    "acrd": None, "rp": None, "icp": False, "icc": 0, "ix": 0, "ti": 0,
    "lt": False, "tr": False, "lai": None, "icsd": None,
    "rr": None, "rt": [], "tg": [], "pr": [], "ar": [], "agr": [],
    "sp": None, "sr": None, "dd": None, "tir": None, "ato": None,
    "xx": {"sn": {}, "_t": "oo"},
}

_TIMEOUT = 30
_APP_ID = os.environ.get("THINGS_APP_ID", "com.culturedcode.ThingsMac")


class ThingsAuthError(Exception):
    """Raised when THINGS_EMAIL/THINGS_PASSWORD are missing or rejected (401/403)."""


class ThingsUnavailableError(Exception):
    """Raised on network error or unexpected (non-2xx, non-auth) API response."""


class ThingsWriteDisabledError(Exception):
    """Raised when a write is attempted with THINGS_WRITE_ENABLED unset/false."""


# ------------------------------------------------------------------ #
# Credentials, session, request chokepoint                            #
# ------------------------------------------------------------------ #

def _credentials() -> tuple[str, str]:
    email = os.environ.get("THINGS_EMAIL", "").strip()
    password = os.environ.get("THINGS_PASSWORD", "")
    if not email or not password:
        raise ThingsAuthError("THINGS_EMAIL / THINGS_PASSWORD env vars are not set")
    return email, password


def writes_enabled() -> bool:
    """True when THINGS_WRITE_ENABLED is explicitly on.  Defaults to **off**."""
    return os.environ.get("THINGS_WRITE_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _require_writes(action: str) -> None:
    if not writes_enabled():
        raise ThingsWriteDisabledError(
            f"refusing to {action}: THINGS_WRITE_ENABLED is off"
        )


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """Shared keep-alive session — reuses the TLS connection across calls.

    A full journal replay pages back-to-back; a session avoids a fresh TCP + TLS
    handshake per page.  No auth state lives on the session (the Authorization
    header is passed per call), so sharing is safe.
    """
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _headers(auth: str | None = None) -> dict:
    """Base headers.  Things rejects requests that don't look like the Mac app."""
    headers = {
        "Accept": "application/json",
        "Accept-Charset": "UTF-8",
        "Accept-Language": "en-gb",
        "Content-Type": "application/json; charset=UTF-8",
        "User-Agent": os.environ.get("THINGS_USER_AGENT", "ThingsMac/31001504mas"),
        "Schema": os.environ.get("THINGS_SCHEMA_VERSION", "301"),
        "App-Id": _APP_ID,
        "App-Instance-Id": f"-{_APP_ID}",
        "Push-Priority": "5",
    }
    if auth:
        headers["Authorization"] = auth
    return headers


def _password_auth() -> str:
    _, password = _credentials()
    # safe="'" mirrors the Mac client's quoting; apostrophes must survive unescaped.
    return f"Password {quote(password, safe=chr(39))}"


def _request(method: str, path: str, *, auth: str | None = None, **kwargs) -> dict:
    """Issue one request against ``THINGS_BASE`` and return parsed JSON.

    Raises:
        ThingsAuthError:        On missing credentials or HTTP 401/403.
        ThingsUnavailableError: On network failure, non-JSON body, or other non-2xx.
    """
    try:
        resp = _get_session().request(
            method, f"{THINGS_BASE}{path}",
            headers=_headers(auth), timeout=_TIMEOUT, **kwargs,
        )
    except requests.RequestException as exc:
        raise ThingsUnavailableError(f"Things Cloud request failed: {exc}") from exc

    if resp.status_code in (401, 403):
        raise ThingsAuthError(
            "Things Cloud rejected the credentials — check THINGS_EMAIL/THINGS_PASSWORD"
        )
    if not resp.ok:
        raise ThingsUnavailableError(
            f"Things Cloud returned HTTP {resp.status_code}: {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise ThingsUnavailableError(f"Things Cloud returned non-JSON: {exc}") from exc


# ------------------------------------------------------------------ #
# Date encoding                                                       #
# ------------------------------------------------------------------ #
#
# Two distinct encodings — never mix them:
#   day fields (sr, dd, tir, icsd)  : int epoch seconds at UTC midnight
#   timestamp fields (cd, md, sp)   : float epoch seconds, sub-second precision

def day_to_iso(epoch: int | float | None) -> str | None:
    """Decode a Things day field to ``YYYY-MM-DD``.  None-safe."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).date().isoformat()


def iso_to_day(iso: str | None) -> int | None:
    """Encode an ISO date to a Things day field (UTC-midnight epoch).  None-safe.

    Accepts a plain ``YYYY-MM-DD`` **or** a full timestamp, truncating the time.
    Klaus's ``hard_deadline_at`` tool schema declares ``format: date-time``, so the
    brain does send timestamps; ``date.fromisoformat`` rejects those outright, which
    would raise inside a write path.  Things only stores day granularity anyway.

    Raises:
        ValueError: If the string is not an ISO date or timestamp at all.
    """
    if not iso:
        return None
    text = iso.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        # Tolerate a trailing 'Z', which datetime.fromisoformat rejected before 3.11.
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return int(
        datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc).timestamp()
    )


def ts_to_iso(epoch: int | float | None) -> str | None:
    """Decode a Things timestamp field to an ISO-8601 UTC string.  None-safe."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def seconds_to_hhmm(seconds: int | None) -> str | None:
    """Decode a reminder offset (seconds after midnight) to ``HH:MM``.  None-safe."""
    if seconds is None:
        return None
    return f"{int(seconds) // 3600:02d}:{(int(seconds) % 3600) // 60:02d}"


def hhmm_to_seconds(hhmm: str | None) -> int | None:
    """Encode ``HH:MM`` to a reminder offset in seconds after midnight.  None-safe."""
    if not hhmm:
        return None
    hours, _, minutes = hhmm.partition(":")
    return int(hours) * 3600 + int(minutes) * 60


def today_iso() -> str:
    """Today in Asia/Jerusalem as ``YYYY-MM-DD`` — Klaus's canonical 'today'."""
    return datetime.now(_TZ).date().isoformat()


# ------------------------------------------------------------------ #
# Read                                                                #
# ------------------------------------------------------------------ #

def fetch_history_key() -> dict:
    """Authenticate and return the account record.

    Returns:
        ``{"history-key", "latest-server-index", "is-empty", "latest-schema-version"}``

    The ``history-key`` is the handle for every subsequent call — treat it as a
    credential.  ``latest-server-index`` is the cheap freshness check: when it
    matches the cached cursor the mirror is up to date and no delta pull is needed.
    """
    email, _ = _credentials()
    return _request(
        "GET", f"/account/{quote(email, safe='')}/own-history-key",
        auth=_password_auth(),
    )


def fetch_items(history_key: str, start_index: int = 0) -> dict:
    """Fetch one page of journal records from ``start_index``.

    Returns the raw envelope: ``{"items": [...], "current-item-index": int,
    "schema": int, ...}``.  The list key is ``items`` — *not* ``updates``.
    """
    return _request(
        "GET", f"/history/{history_key}/items",
        params={"start-index": str(start_index)},
    )


_MAX_JOURNAL_PAGES = 200


def replay_journal(
    history_key: str,
    state: dict[str, dict] | None = None,
    start_index: int = 0,
    max_pages: int = _MAX_JOURNAL_PAGES,
    on_records=None,
) -> tuple[dict[str, dict], int]:
    """Page from ``start_index`` to the head, folding records into ``state``.

    Returns ``(state, cursor)`` where ``cursor`` is the index to resume from next
    time.  Pass the previous cursor and the existing mirror to pull only a delta.

    ``on_records``, if given, is called with each page's flattened records before
    they are folded in — so a caller can track which UUIDs a delta touched without
    reimplementing this pagination.

    **The cursor is ``start + len(items)``, never ``current-item-index``.**  The
    server caps each response (321 elements in the live account) while
    ``current-item-index`` always reports the journal *head*.  Treating the head as
    the next cursor skips every record between the end of page one and the head —
    silently, with no error.  This only looked correct at first because the account
    happened to fit in a single page.

    Raises:
        ThingsAuthError / ThingsUnavailableError: propagated from the transport.
    """
    state = {} if state is None else state
    cursor = start_index
    head = start_index

    for _ in range(max_pages):
        envelope = fetch_items(history_key, cursor)
        items = envelope.get("items") or []
        head = envelope.get("current-item-index", head)

        if not items:
            break

        records = flatten(items)
        if on_records is not None:
            on_records(records)
        apply_records(state, records)
        cursor += len(items)

        if cursor >= head:
            break
    else:
        logger.warning(
            "things: replay hit the %d-page ceiling at index %d (head %s) — "
            "journal may be incomplete", max_pages, cursor, head,
        )

    return state, cursor


def flatten(items: list[dict]) -> list[tuple[str, int, str, dict]]:
    """Flatten journal pages into ordered ``(uuid, op, entity_class, payload)``.

    Each element of ``items`` maps **one or more** UUIDs to
    ``{"t": op, "e": class, "p": payload}``.  A single element batched up to 90
    entities in the live account, so this is a nested flatten, not a map.
    """
    out: list[tuple[str, int, str, dict]] = []
    for element in items or []:
        if not isinstance(element, dict):
            continue
        for uuid, record in element.items():
            if isinstance(record, dict):
                out.append((
                    uuid,
                    record.get("t"),
                    record.get("e") or "UNKNOWN",
                    record.get("p") or {},
                ))
    return out


def apply_records(
    state: dict[str, dict],
    flat: list[tuple[str, int, str, dict]],
) -> dict[str, dict]:
    """Fold journal records into ``state`` in place, returning it.

    Creates carry a complete payload; edits carry a **sparse delta** that merges
    over accumulated state; deletes drop the UUID.  ``Tombstone2`` records are a
    second, independent delete signal keyed by ``dloid``.

    Applying deletes is **mandatory**.  Treating ``op == OP_DELETE`` as a merge
    reported 251 open to-dos for an account that has 52, resurrecting projects and
    areas deleted months earlier — with no error raised.  See
    ``docs/things_protocol.md`` §2.
    """
    for uuid, op, entity_class, payload in flat:
        if op == OP_DELETE:
            state.pop(uuid, None)
            continue
        if uuid not in state:
            state[uuid] = {"_class": entity_class, "_uuid": uuid}
        state[uuid].update(payload)

    for _uuid, _op, entity_class, payload in flat:
        if entity_class == CLASS_TOMBSTONE:
            state.pop(payload.get("dloid"), None)

    return state


# ------------------------------------------------------------------ #
# Normalization — Things payload -> Klaus canonical task              #
# ------------------------------------------------------------------ #

def _notes_text(payload: dict) -> str | None:
    """Extract plain text from the ``nt`` note envelope ``{_t, ch, v, t}``."""
    note = payload.get("nt")
    if isinstance(note, dict):
        return note.get("v") or None
    return note or None


def is_live_todo(payload: dict) -> bool:
    """True for an open, untrashed to-do (excludes projects, headings, done, trash)."""
    return (
        payload.get("_class") == CLASS_TASK
        and payload.get("tp") == TP_TODO
        and payload.get("ss") == SS_OPEN
        and not payload.get("tr")
    )


_MAX_ANCESTOR_DEPTH = 8


def resolve_containers(state: dict[str, dict]) -> dict[str, dict]:
    """Map every task uuid to ``{"project_id", "area_id", "inherited_trashed"}``.

    Things expresses containment **three** ways, and only checking ``pr`` gets it
    badly wrong — in the live account 36 of 52 open to-dos have an empty ``pr``:

      * ``pr`` — a direct link to a project.
      * ``agr`` — an "ancestor group" pointing at a **heading** (``tp == 2``);
        the heading's own ``pr`` names the project.  Headings can nest.
      * neither — the to-do sits loose in Inbox or Someday.

    A to-do's area is its own ``ar`` if set, otherwise its project's ``ar``.

    ``inherited_trashed`` is true when any ancestor carries ``tr``.  **Trashing a
    project in Things does not set ``tr`` on its children** — they simply vanish
    with the parent.  Checking a to-do in isolation therefore keeps showing tasks
    the user has thrown away.

    Depth is bounded so a cyclic ``agr`` chain cannot hang the sync.
    """
    resolved: dict[str, dict] = {}

    def walk(uuid: str, depth: int) -> tuple[str | None, str | None, bool]:
        payload = state.get(uuid)
        if not payload or depth > _MAX_ANCESTOR_DEPTH:
            return None, None, False

        project = (payload.get("pr") or [None])[0]
        area = (payload.get("ar") or [None])[0]
        trashed = False

        parents = list(payload.get("agr") or [])
        if project:
            parents.append(project)

        for ancestor in parents:
            anc = state.get(ancestor)
            if not anc:
                continue
            if anc.get("tr"):
                trashed = True
            anc_project, anc_area, anc_trashed = walk(ancestor, depth + 1)
            trashed = trashed or anc_trashed
            # The ancestor may itself *be* the project (heading -> project).
            if anc.get("_class") == CLASS_TASK and anc.get("tp") == TP_PROJECT:
                anc_project = ancestor
            project = project or anc_project
            area = area or anc_area

        if area is None and project:
            area = ((state.get(project) or {}).get("ar") or [None])[0]
        return project, area, trashed

    for uuid, payload in state.items():
        if payload.get("_class") == CLASS_TASK:
            project, area, trashed = walk(uuid, 0)
            resolved[uuid] = {
                "project_id": project,
                "area_id": area,
                "inherited_trashed": trashed,
            }
    return resolved


def live_todos(state: dict[str, dict]) -> list[dict]:
    """Return the open, untrashed to-dos Klaus reasons over, fully normalized.

    **The single correct way to read the mirror.**  Filtering ``state`` by hand
    keeps going wrong: a to-do is only genuinely live if it is open, untrashed,
    *and* has no trashed ancestor, and its project label only resolves through the
    heading chain.  Callers should use this rather than reimplementing the filter.
    """
    names = build_name_index(state)
    containers = resolve_containers(state)
    return [
        normalize_task(uuid, payload, names, containers)
        for uuid, payload in state.items()
        if is_live_todo(payload)
        and not containers.get(uuid, {}).get("inherited_trashed")
    ]


def normalize_task(
    uuid: str,
    payload: dict,
    names: dict[str, str] | None = None,
    containers: dict[str, dict] | None = None,
) -> dict:
    """Convert a Things ``Task6`` payload into Klaus's canonical task shape.

    Args:
        uuid:       The entity UUID (also the Klaus task id).
        payload:    The materialized Things payload.
        names:      ``{uuid: display name}`` from :func:`build_name_index`.
        containers: ``{uuid: {"project_id", "area_id"}}`` from
                    :func:`resolve_containers`.  Without it, tasks filed under a
                    heading look like loose Inbox items.

    The two-field date split matters: Things ``sr`` (scheduled / "when") maps to
    ``due_date``, while ``dd`` (deadline) maps to ``hard_deadline_at``.  Klaus's
    single ``due_date`` would otherwise flatten two distinct concepts.

    ``priority`` is absent — Things has no priority field.  It lives in the
    Klaus-side sidecar, merged in by ``ThingsTaskStore``.
    """
    names = names or {}
    owner = (containers or {}).get(uuid) or {}
    project = owner.get("project_id") or (payload.get("pr") or [None])[0]
    area = owner.get("area_id") or (payload.get("ar") or [None])[0]
    tag_ids = payload.get("tg") or []

    return {
        "id": uuid,
        "title": payload.get("tt") or "",
        "notes": _notes_text(payload),
        "due_date": day_to_iso(payload.get("sr")),
        "due_time": seconds_to_hhmm(payload.get("ato")),
        "hard_deadline_at": day_to_iso(payload.get("dd")),
        "status": "active" if payload.get("ss") == SS_OPEN else "completing",
        "list_id": project or area or "inbox",
        "project_id": project,
        "project_name": names.get(project) if project else None,
        "area_id": area,
        "area_name": names.get(area) if area else None,
        "tags": [names.get(t, t) for t in tag_ids],
        "tag_ids": list(tag_ids),
        "bucket": {ST_INBOX: "inbox", ST_ANYTIME: "anytime", ST_SOMEDAY: "someday"}.get(
            payload.get("st")
        ),
        # A row carrying `rr` is the recurrence *template*; one carrying `rt` is a
        # spawned instance.  Things generates instances itself — Klaus never does.
        "recurrence": payload.get("rr"),
        "is_recurring_instance": bool(payload.get("rt")),
        "trashed": bool(payload.get("tr")),
        "created_at": ts_to_iso(payload.get("cd")),
        "updated_at": ts_to_iso(payload.get("md")),
        "completed_at": ts_to_iso(payload.get("sp")),
    }


def build_name_index(state: dict[str, dict]) -> dict[str, str]:
    """Map uuid -> display name for projects, areas, and tags."""
    names: dict[str, str] = {}
    for uuid, payload in state.items():
        cls = payload.get("_class")
        if cls in (CLASS_AREA, CLASS_TAG):
            names[uuid] = payload.get("tt") or ""
        elif cls == CLASS_TASK and payload.get("tp") == TP_PROJECT:
            names[uuid] = payload.get("tt") or ""
    return names


# ------------------------------------------------------------------ #
# Write                                                               #
# ------------------------------------------------------------------ #

def new_uuid() -> str:
    """Generate a Things-style 22-character base62 identifier."""
    import secrets
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(22))


def build_note(text: str | None) -> dict:
    """Build the ``nt`` note envelope.

    The real client stores a checksum in ``ch``; the algorithm is unknown, and 0
    is used here.  Verify note round-trips explicitly during live testing — if
    Things rejects or mangles notes, this is the first thing to suspect.
    """
    return {"_t": "tx", "ch": 0, "v": text or "", "t": 1}


def build_create(
    title: str,
    *,
    notes: str | None = None,
    due_date: str | None = None,
    due_time: str | None = None,
    hard_deadline_at: str | None = None,
    project_id: str | None = None,
    area_id: str | None = None,
    tag_ids: list[str] | None = None,
) -> tuple[str, dict]:
    """Build a create record for a new to-do.  Returns ``(uuid, record)``.

    ``due_date`` becomes ``sr`` (scheduled) and ``hard_deadline_at`` becomes ``dd``
    (deadline) — two separate Things fields.  A dated to-do goes to the Anytime
    bucket; an undated one to Inbox, matching how the app files things.
    """
    uuid = new_uuid()
    now = datetime.now(timezone.utc).timestamp()
    scheduled = iso_to_day(due_date)

    payload = {
        **_TASK_DEFAULTS,
        "tt": title,
        "nt": build_note(notes),
        "tp": TP_TODO,
        "ss": SS_OPEN,
        "st": ST_ANYTIME if scheduled else ST_INBOX,
        "sr": scheduled,
        "tir": scheduled,          # tracks `sr` (63/65 agreement in the live account)
        "dd": iso_to_day(hard_deadline_at),
        "ato": hhmm_to_seconds(due_time),
        "pr": [project_id] if project_id else [],
        "ar": [area_id] if area_id else [],
        "tg": list(tag_ids or []),
        "cd": now,
        "md": now,
    }
    return uuid, {"t": OP_CREATE, "e": CLASS_TASK, "p": payload}


def build_project_create(title: str) -> tuple[str, dict]:
    """Build a Things project, which is the authoritative Hub task list.

    Projects use the same ``Task6`` journal class as to-dos; their ``tp`` value
    distinguishes them.  The remaining observed defaults match a normal Things
    project so the native clients can continue to edit it.
    """
    uuid = new_uuid()
    now = datetime.now(timezone.utc).timestamp()
    payload = {
        **_TASK_DEFAULTS,
        "tt": title,
        "nt": build_note(None),
        "tp": TP_PROJECT,
        "ss": SS_OPEN,
        "st": ST_ANYTIME,
        "cd": now,
        "md": now,
    }
    return uuid, {"t": OP_CREATE, "e": CLASS_TASK, "p": payload}


def build_edit(fields: dict) -> dict:
    """Build an edit record carrying only ``fields`` as a sparse delta.

    Callers pass **raw Things keys**, already encoded.  Only the keys supplied are
    transmitted, so payload keys this module does not understand are left untouched
    on the server rather than being overwritten with defaults.
    """
    return {"t": OP_EDIT, "e": CLASS_TASK, "p": {**fields, "md": datetime.now(timezone.utc).timestamp()}}


def build_complete(completed_at: float | None = None) -> dict:
    """Build an edit record marking a to-do complete.

    Things spawns the next instance of a recurring to-do itself, so this never
    creates a follow-up row — the new instance arrives on the next delta pull.
    """
    stamp = completed_at if completed_at is not None else datetime.now(timezone.utc).timestamp()
    return build_edit({"ss": SS_COMPLETED, "sp": stamp})


def build_reschedule(due_date: str | None, due_time: str | None = None) -> dict:
    """Build an edit record moving the **scheduled** date only.

    Deliberately never touches ``dd`` — rescheduling when you'll work on something
    must not silently move its hard deadline.
    """
    scheduled = iso_to_day(due_date)
    fields: dict = {"sr": scheduled, "tir": scheduled}
    fields["st"] = ST_ANYTIME if scheduled else ST_INBOX
    if due_time is not None:
        fields["ato"] = hhmm_to_seconds(due_time)
    return build_edit(fields)


def build_trash() -> dict:
    """Build an edit record moving a to-do to the Things trash.

    Klaus never issues a hard delete (``OP_DELETE``).  Trashing is recoverable by
    hand from the app; a journal delete is not.
    """
    return build_edit({"tr": True})


def commit(history_key: str, records: dict[str, dict], ancestor_index: int) -> dict:
    """Push ``records`` to Things Cloud.  Returns the commit response.

    Args:
        history_key:    From :func:`fetch_history_key`.
        records:        ``{uuid: {"t", "e", "p"}}`` — the same shape reads return.
        ancestor_index: The cursor this write is based on; the server rejects a
                        commit whose ancestor is behind the true head, which is
                        what stops Klaus clobbering a concurrent phone edit.

    Raises:
        ThingsWriteDisabledError: When THINGS_WRITE_ENABLED is off.
    """
    _require_writes(f"commit {len(records)} record(s)")
    logger.info("things: committing %d record(s) at ancestor-index=%d",
                len(records), ancestor_index)
    return _request(
        "POST", f"/history/{history_key}/commit",
        params={"ancestor-index": str(ancestor_index), "_cnt": str(len(records))},
        json=records,
    )
