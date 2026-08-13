"""Tests for mcp_tools/things_tool.py — Things Cloud protocol client.

Covers:
  - apply_records: create/edit merge semantics and the DELETE opcode, which is the
    integration's sharpest edge (ignoring it silently resurrects deleted data).
  - resolve_containers: pr / agr-heading / bare containment, nesting, cycle safety.
  - normalize_task: the sr-vs-dd date split, reminder decoding, tag/project labels.
  - build_*: create defaults, sparse edits, reschedule leaving the deadline alone,
    trash instead of hard delete.
  - date codecs round-tripping.
  - auth + transport error mapping, and the THINGS_WRITE_ENABLED kill switch.

No network — requests is patched at the module level.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

import mcp_tools.things_tool as things


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    monkeypatch.setenv("THINGS_EMAIL", "test@example.com")
    monkeypatch.setenv("THINGS_PASSWORD", "hunter2")
    monkeypatch.delenv("THINGS_WRITE_ENABLED", raising=False)


def _task(**overrides) -> dict:
    base = {
        "_class": "Task6", "tt": "task", "tp": things.TP_TODO,
        "ss": things.SS_OPEN, "st": things.ST_INBOX, "tr": False,
        "pr": [], "ar": [], "agr": [], "tg": [],
        "sr": None, "dd": None, "ato": None, "nt": None,
        "cd": 1776062349.1, "md": 1776062349.2, "sp": None, "rr": None, "rt": [],
    }
    base.update(overrides)
    return base


def _element(uuid: str, op: int, payload: dict, cls: str = "Task6") -> dict:
    return {uuid: {"t": op, "e": cls, "p": payload}}


# ------------------------------------------------------------------ #
# Journal folding — the DELETE opcode                                 #
# ------------------------------------------------------------------ #

def test_flatten_unpacks_multiple_uuids_per_element():
    """One journal element batches many entities — flatten must be nested."""
    items = [{"a": {"t": 0, "e": "Task6", "p": {"tt": "A"}},
              "b": {"t": 0, "e": "Task6", "p": {"tt": "B"}}}]
    assert len(things.flatten(items)) == 2


def test_flatten_tolerates_malformed_elements():
    assert things.flatten([None, "junk", {"a": "not-a-dict"}]) == []
    assert things.flatten(None) == []


def test_edit_merges_as_sparse_delta():
    flat = things.flatten([
        _element("t1", things.OP_CREATE, _task(tt="original", ss=things.SS_OPEN)),
        _element("t1", things.OP_EDIT, {"tt": "renamed"}),
    ])
    state = things.apply_records({}, flat)
    assert state["t1"]["tt"] == "renamed"
    # Untouched keys survive the sparse edit.
    assert state["t1"]["ss"] == things.SS_OPEN


def test_delete_opcode_removes_entity():
    """The bug that reported 251 open to-dos for a 52-task account."""
    flat = things.flatten([
        _element("t1", things.OP_CREATE, _task(tt="doomed")),
        _element("t2", things.OP_CREATE, _task(tt="survivor")),
        _element("t1", things.OP_DELETE, {}),
    ])
    state = things.apply_records({}, flat)
    assert "t1" not in state
    assert "t2" in state


def test_tombstone_removes_referenced_entity():
    """Tombstone2 is a second, independent delete signal keyed by dloid."""
    flat = things.flatten([
        _element("t1", things.OP_CREATE, _task(tt="doomed")),
        _element("tomb", things.OP_CREATE, {"dloid": "t1", "dld": 1.0}, cls="Tombstone2"),
    ])
    state = things.apply_records({}, flat)
    assert "t1" not in state


def test_recreate_after_delete_wins():
    """Journal order decides: a create following a delete resurrects the uuid."""
    flat = things.flatten([
        _element("t1", things.OP_CREATE, _task(tt="v1")),
        _element("t1", things.OP_DELETE, {}),
        _element("t1", things.OP_CREATE, _task(tt="v2")),
    ])
    state = things.apply_records({}, flat)
    assert state["t1"]["tt"] == "v2"


# ------------------------------------------------------------------ #
# Pagination — cursor is start + len(items), never current-item-index  #
# ------------------------------------------------------------------ #

def _paged(pages: list[list[dict]], head: int):
    """Fake fetch_items: serves `pages` keyed by start index, always reporting head."""
    by_start, start = {}, 0
    for page in pages:
        by_start[start] = page
        start += len(page)
    by_start.setdefault(start, [])

    def _fetch(_hk, start_index):
        return {"items": by_start.get(start_index, []), "current-item-index": head}
    return _fetch


def test_replay_advances_by_page_length_not_by_head():
    """The bug that silently dropped every record past page one.

    The server caps each response while current-item-index reports the journal
    head; using the head as the next cursor skips the gap between them.
    """
    pages = [
        [_element(f"a{i}", things.OP_CREATE, _task(tt=f"A{i}")) for i in range(3)],
        [_element(f"b{i}", things.OP_CREATE, _task(tt=f"B{i}")) for i in range(2)],
    ]
    with patch.object(things, "fetch_items", _paged(pages, head=5)):
        state, cursor = things.replay_journal("hk")
    assert cursor == 5
    assert len(state) == 5, "records past the first page were dropped"


def test_replay_single_page_stops_at_head():
    pages = [[_element("a", things.OP_CREATE, _task())]]
    with patch.object(things, "fetch_items", _paged(pages, head=1)):
        state, cursor = things.replay_journal("hk")
    assert cursor == 1 and len(state) == 1


def test_replay_resumes_from_cursor_for_delta_pulls():
    existing = {"old": {"_class": "Task6", "tt": "kept"}}
    page = [_element("new", things.OP_CREATE, _task(tt="fresh"))]
    with patch.object(things, "fetch_items", lambda _hk, i: (
        {"items": page, "current-item-index": 11} if i == 10
        else {"items": [], "current-item-index": 11})):
        state, cursor = things.replay_journal("hk", state=existing, start_index=10)
    assert cursor == 11
    assert set(state) == {"old", "new"}


def test_replay_of_empty_journal_is_a_noop():
    with patch.object(things, "fetch_items",
                      lambda _hk, i: {"items": [], "current-item-index": 0}):
        state, cursor = things.replay_journal("hk")
    assert state == {} and cursor == 0


def test_replay_stops_at_page_ceiling_without_hanging():
    """A server that never advances must not loop forever."""
    with patch.object(things, "fetch_items", lambda _hk, i: {
        "items": [_element("x", things.OP_CREATE, _task())], "current-item-index": 10_000}):
        _, cursor = things.replay_journal("hk", max_pages=5)
    assert cursor == 5


def test_apply_records_accumulates_across_pages():
    """Delta pulls fold into existing mirror state rather than replacing it."""
    state = things.apply_records({}, things.flatten([
        _element("t1", things.OP_CREATE, _task(tt="page one")),
    ]))
    things.apply_records(state, things.flatten([
        _element("t2", things.OP_CREATE, _task(tt="page two")),
    ]))
    assert set(state) == {"t1", "t2"}


# ------------------------------------------------------------------ #
# Container resolution                                                #
# ------------------------------------------------------------------ #

def test_resolves_direct_project_link():
    state = {
        "p1": _task(tt="Klaus", tp=things.TP_PROJECT),
        "t1": _task(pr=["p1"]),
    }
    assert things.resolve_containers(state)["t1"]["project_id"] == "p1"


def test_resolves_project_through_heading():
    """36 of 52 live to-dos reach their project via a heading, not via pr."""
    state = {
        "p1": _task(tt="Meet Things for Mac", tp=things.TP_PROJECT),
        "h1": _task(tt="Boost your productivity", tp=things.TP_HEADING, pr=["p1"]),
        "t1": _task(agr=["h1"]),
    }
    assert things.resolve_containers(state)["t1"]["project_id"] == "p1"


def test_resolves_project_when_ancestor_is_the_project_itself():
    state = {
        "p1": _task(tt="proj", tp=things.TP_PROJECT),
        "t1": _task(agr=["p1"]),
    }
    assert things.resolve_containers(state)["t1"]["project_id"] == "p1"


def test_loose_task_has_no_container():
    resolved = things.resolve_containers({"t1": _task()})
    assert resolved["t1"] == {
        "project_id": None, "area_id": None, "inherited_trashed": False,
    }


def test_area_inherited_from_project():
    state = {
        "a1": {"_class": "Area3", "tt": "Work"},
        "p1": _task(tt="proj", tp=things.TP_PROJECT, ar=["a1"]),
        "t1": _task(pr=["p1"]),
    }
    assert things.resolve_containers(state)["t1"]["area_id"] == "a1"


def test_cyclic_ancestors_terminate():
    """A corrupt agr cycle must not hang the sync."""
    state = {"t1": _task(agr=["t2"]), "t2": _task(agr=["t1"])}
    assert things.resolve_containers(state)["t1"]["project_id"] is None


# ------------------------------------------------------------------ #
# Inherited trash — trashing a project hides its children implicitly  #
# ------------------------------------------------------------------ #

def test_task_in_trashed_project_is_inherited_trashed():
    """Things does not set `tr` on the children of a trashed project."""
    state = {
        "p1": _task(tt="junk", tp=things.TP_PROJECT, tr=True),
        "t1": _task(tt="child", pr=["p1"]),
    }
    assert things.resolve_containers(state)["t1"]["inherited_trashed"] is True


def test_task_under_trashed_heading_is_inherited_trashed():
    state = {
        "p1": _task(tt="proj", tp=things.TP_PROJECT),
        "h1": _task(tp=things.TP_HEADING, pr=["p1"], tr=True),
        "t1": _task(agr=["h1"]),
    }
    assert things.resolve_containers(state)["t1"]["inherited_trashed"] is True


def test_task_in_healthy_project_is_not_inherited_trashed():
    state = {
        "p1": _task(tt="Klaus", tp=things.TP_PROJECT),
        "t1": _task(pr=["p1"]),
    }
    assert things.resolve_containers(state)["t1"]["inherited_trashed"] is False


def test_live_todos_excludes_children_of_trashed_projects():
    """The whole filter, end to end — the shape the store consumes."""
    state = {
        "keep": _task(tt="real task"),
        "p1": _task(tt="junk project", tp=things.TP_PROJECT, tr=True),
        "drop": _task(tt="junk child", pr=["p1"]),
    }
    titles = {t["title"] for t in things.live_todos(state)}
    assert titles == {"real task"}


def test_live_todos_excludes_projects_completed_and_trashed():
    state = {
        "keep": _task(tt="open"),
        "proj": _task(tt="a project", tp=things.TP_PROJECT),
        "done": _task(tt="completed", ss=things.SS_COMPLETED),
        "bin": _task(tt="trashed", tr=True),
    }
    assert {t["title"] for t in things.live_todos(state)} == {"open"}


def test_live_todos_labels_project_through_heading():
    state = {
        "p1": _task(tt="Meet Things for Mac", tp=things.TP_PROJECT),
        "h1": _task(tt="Learn the basics", tp=things.TP_HEADING, pr=["p1"]),
        "t1": _task(tt="child", agr=["h1"]),
    }
    assert things.live_todos(state)[0]["project_name"] == "Meet Things for Mac"


# ------------------------------------------------------------------ #
# Normalization                                                       #
# ------------------------------------------------------------------ #

def test_scheduled_and_deadline_map_to_separate_fields():
    """sr is 'when', dd is the hard deadline — Klaus must not conflate them."""
    payload = _task(sr=things.iso_to_day("2026-08-11"), dd=things.iso_to_day("2026-08-20"))
    out = things.normalize_task("t1", payload)
    assert out["due_date"] == "2026-08-11"
    assert out["hard_deadline_at"] == "2026-08-20"


def test_reminder_offset_decodes_to_clock_time():
    assert things.normalize_task("t1", _task(ato=36000))["due_time"] == "10:00"


def test_notes_extracted_from_envelope():
    payload = _task(nt={"_t": "tx", "ch": 123, "v": "note body", "t": 1})
    assert things.normalize_task("t1", payload)["notes"] == "note body"


def test_notes_read_from_the_paragraph_format():
    """Things uses two note shapes; reading only `v` blanks every t=2 note."""
    payload = _task(nt={"_t": "tx", "t": 2, "ps": [
        {"r": "first line", "ch": 1, "l": 0, "p": 0},
        {"r": "second line", "ch": 2, "l": 0, "p": 0},
    ]})
    assert things.normalize_task("t1", payload)["notes"] == "first line\nsecond line"


def test_empty_paragraph_note_reads_as_none():
    payload = _task(nt={"_t": "tx", "t": 2, "ps": []})
    assert things.normalize_task("t1", payload)["notes"] is None


def test_completed_task_maps_to_completing_status():
    out = things.normalize_task("t1", _task(ss=things.SS_COMPLETED, sp=1776062503.9))
    assert out["status"] == "completing"
    assert out["completed_at"] is not None


def test_labels_resolved_from_name_index():
    state = {
        "p1": _task(tt="Klaus", tp=things.TP_PROJECT),
        "g1": {"_class": "Tag4", "tt": "Errand"},
        "t1": _task(pr=["p1"], tg=["g1"]),
    }
    out = things.normalize_task(
        "t1", state["t1"], things.build_name_index(state), things.resolve_containers(state)
    )
    assert out["project_name"] == "Klaus"
    assert out["tags"] == ["Errand"]


def test_recurring_instance_flagged():
    assert things.normalize_task("t1", _task(rt=["tmpl"]))["is_recurring_instance"] is True


def test_is_live_todo_excludes_projects_completed_and_trashed():
    assert things.is_live_todo(_task()) is True
    assert things.is_live_todo(_task(tp=things.TP_PROJECT)) is False
    assert things.is_live_todo(_task(ss=things.SS_COMPLETED)) is False
    assert things.is_live_todo(_task(tr=True)) is False


# ------------------------------------------------------------------ #
# Date codecs                                                         #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("iso", ["2026-08-11", "2026-01-01", "2026-12-31"])
def test_day_codec_round_trips(iso):
    assert things.day_to_iso(things.iso_to_day(iso)) == iso


@pytest.mark.parametrize("hhmm", ["00:00", "09:30", "23:59"])
def test_time_codec_round_trips(hhmm):
    assert things.seconds_to_hhmm(things.hhmm_to_seconds(hhmm)) == hhmm


def test_codecs_are_none_safe():
    assert things.day_to_iso(None) is None
    assert things.iso_to_day(None) is None
    assert things.seconds_to_hhmm(None) is None
    assert things.hhmm_to_seconds(None) is None


def test_day_field_lands_on_utc_midnight():
    assert things.iso_to_day("2026-08-11") % 86400 == 0


@pytest.mark.parametrize("value", [
    "2026-08-11",
    "2026-08-11T10:00:00",
    "2026-08-11T10:00:00+03:00",
    "2026-08-11T07:00:00Z",
])
def test_iso_to_day_accepts_timestamps_not_just_dates(value):
    """hard_deadline_at is declared `format: date-time`, so the brain sends these."""
    assert things.day_to_iso(things.iso_to_day(value)) == "2026-08-11"


def test_iso_to_day_rejects_junk():
    with pytest.raises(ValueError):
        things.iso_to_day("next tuesday")


# ------------------------------------------------------------------ #
# Write record builders                                               #
# ------------------------------------------------------------------ #

def test_create_files_dated_task_in_anytime_and_undated_in_inbox():
    _, dated = things.build_create("x", due_date="2026-08-11")
    _, undated = things.build_create("x")
    assert dated["p"]["st"] == things.ST_ANYTIME
    assert undated["p"]["st"] == things.ST_INBOX


def test_create_carries_observed_constant_defaults():
    _, rec = things.build_create("x")
    assert rec["t"] == things.OP_CREATE
    for key, value in {"do": 0, "sb": 0, "dl": [], "icp": False, "rr": None}.items():
        assert rec["p"][key] == value


def test_create_sets_tir_alongside_scheduled_date():
    _, rec = things.build_create("x", due_date="2026-08-11")
    assert rec["p"]["tir"] == rec["p"]["sr"]


def test_create_ids_are_unique_and_things_shaped():
    ids = {things.build_create("x")[0] for _ in range(50)}
    assert len(ids) == 50
    assert all(len(i) == 22 and i.isalnum() for i in ids)


# ------------------------------------------------------------------ #
# Note checksum — a wrong value crashes the Things client on launch   #
# ------------------------------------------------------------------ #

def test_note_checksum_is_crc32_of_utf8_text():
    """Verified against all 64 non-empty notes in the live account.

    A mismatched checksum is accepted by the server and then crashes every
    Things client replaying that record. This must never regress.
    """
    import zlib
    text = "Created by Klaus to verify the Things Cloud write path."
    assert things.build_note(text)["ch"] == zlib.crc32(text.encode("utf-8"))


def test_empty_note_checksum_is_zero():
    """142 empty notes in the account carry ch=0, and crc32(b"") == 0."""
    assert things.build_note("")["ch"] == 0
    assert things.build_note(None)["ch"] == 0


def test_note_checksum_is_never_a_placeholder_for_real_text():
    """The exact bug: ch=0 is right for an empty note and catastrophic with text."""
    assert things.build_note("any real note body")["ch"] != 0


@pytest.mark.parametrize("text", [
    "plain ascii",
    "עברית עם ניקוד",
    "emoji 🎓 and — punctuation",
    "multi\nline\nnotes",
    "x" * 5000,
])
def test_note_checksum_handles_unicode_and_length(text):
    import zlib
    note = things.build_note(text)
    assert note["ch"] == zlib.crc32(text.encode("utf-8"))
    assert note["v"] == text
    assert note["_t"] == "tx"


def test_create_embeds_a_correct_note_checksum():
    import zlib
    _, rec = things.build_create("x", notes="hello")
    assert rec["p"]["nt"]["ch"] == zlib.crc32(b"hello")


# ------------------------------------------------------------------ #
# Checklists and recurrence                                           #
# ------------------------------------------------------------------ #

def test_checklist_items_are_separate_entities_linked_by_ts():
    """Checklist rows are ChecklistItem3 records, not a field on the to-do."""
    records = things.build_checklist_items("task-1", ["milk", "eggs"])
    assert len(records) == 2
    for record in records.values():
        assert record["e"] == things.CLASS_CHECKLIST
        assert record["p"]["ts"] == ["task-1"]
        assert record["p"]["ss"] == things.SS_OPEN


def test_checklist_items_preserve_given_order():
    records = things.build_checklist_items("t", ["one", "two", "three"])
    ordered = sorted(records.values(), key=lambda r: -r["p"]["ix"])
    assert [r["p"]["tt"] for r in ordered] == ["one", "two", "three"]


def test_empty_checklist_builds_nothing():
    assert things.build_checklist_items("t", []) == {}


@pytest.mark.parametrize("cadence,fu,offset", [
    ("daily", 16, {"dy": 0}),
    ("weekly", 256, {"wd": 0}),
])
def test_recurrence_cadence_matches_observed_rules(cadence, fu, offset):
    """daily and weekly are confirmed against real rules in the live account."""
    rule = things.build_recurrence(cadence, "2026-08-11")
    assert rule["fu"] == fu
    assert rule["of"] == [offset]
    assert rule["rrv"] == 4


def test_recurrence_rejects_unknown_cadence():
    with pytest.raises(ValueError):
        things.build_recurrence("fortnightly", "2026-08-11")


def test_repeating_template_lives_in_someday_and_is_never_scheduled():
    """Templates carry rr and sit in Someday; only spawned instances get dates."""
    _, record = things.build_repeating_create("water plants", "daily", "2026-08-11")
    payload = record["p"]
    assert payload["rr"]["fu"] == 16
    assert payload["st"] == things.ST_SOMEDAY
    assert payload["sr"] is None
    assert payload["icsd"] == things.iso_to_day("2026-08-11")


def test_repeating_template_carries_no_instance_link():
    """rt belongs to spawned instances; a template must not claim one."""
    _, record = things.build_repeating_create("x", "weekly", "2026-08-11")
    assert record["p"]["rt"] == []


def test_repeating_template_keeps_notes_and_tags():
    import zlib
    _, record = things.build_repeating_create(
        "x", "daily", "2026-08-11", notes="body", tag_ids=["tag-1"],
    )
    assert record["p"]["nt"]["ch"] == zlib.crc32(b"body")
    assert record["p"]["tg"] == ["tag-1"]


def test_edit_is_sparse_so_unknown_fields_survive():
    rec = things.build_edit({"tt": "new title"})
    assert set(rec["p"]) == {"tt", "md"}


def test_reschedule_never_touches_the_deadline():
    """Moving when you'll do something must not move when it's due."""
    rec = things.build_reschedule("2026-08-20")
    assert rec["p"]["sr"] == things.iso_to_day("2026-08-20")
    assert "dd" not in rec["p"]


def test_reschedule_to_none_returns_task_to_inbox():
    rec = things.build_reschedule(None)
    assert rec["p"]["sr"] is None
    assert rec["p"]["st"] == things.ST_INBOX


def test_complete_marks_status_without_spawning_recurrence():
    """Things generates the next instance itself; Klaus must not."""
    rec = things.build_complete()
    assert rec["p"]["ss"] == things.SS_COMPLETED
    assert rec["p"]["sp"] is not None
    assert "rr" not in rec["p"] and "rt" not in rec["p"]


def test_trash_sets_flag_rather_than_issuing_hard_delete():
    rec = things.build_trash()
    assert rec["p"]["tr"] is True
    assert rec["t"] == things.OP_EDIT


# ------------------------------------------------------------------ #
# Transport, auth, and the write kill switch                          #
# ------------------------------------------------------------------ #

def _response(status=200, payload=None, text="") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.text = text
    if payload is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = payload
    return resp


def test_missing_credentials_raise_auth_error(monkeypatch):
    monkeypatch.delenv("THINGS_EMAIL", raising=False)
    with pytest.raises(things.ThingsAuthError):
        things.fetch_history_key()


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_credentials_raise_auth_error(status):
    with patch.object(things, "_get_session") as sess:
        sess.return_value.request.return_value = _response(status, text="nope")
        with pytest.raises(things.ThingsAuthError):
            things.fetch_history_key()


def test_server_error_raises_unavailable():
    with patch.object(things, "_get_session") as sess:
        sess.return_value.request.return_value = _response(503, text="down")
        with pytest.raises(things.ThingsUnavailableError):
            things.fetch_items("hk", 0)


def test_network_failure_raises_unavailable():
    with patch.object(things, "_get_session") as sess:
        sess.return_value.request.side_effect = requests.RequestException("boom")
        with pytest.raises(things.ThingsUnavailableError):
            things.fetch_items("hk", 0)


def test_non_json_body_raises_unavailable():
    with patch.object(things, "_get_session") as sess:
        sess.return_value.request.return_value = _response(200, payload=None)
        with pytest.raises(things.ThingsUnavailableError):
            things.fetch_items("hk", 0)


def test_fetch_items_sends_start_index_and_app_headers():
    with patch.object(things, "_get_session") as sess:
        sess.return_value.request.return_value = _response(200, {"items": []})
        things.fetch_items("hk", 42)
        kwargs = sess.return_value.request.call_args.kwargs
        assert kwargs["params"] == {"start-index": "42"}
        assert kwargs["headers"]["App-Id"] == "com.culturedcode.ThingsMac"
        assert kwargs["timeout"] == things._TIMEOUT


def test_commit_blocked_when_writes_disabled():
    with pytest.raises(things.ThingsWriteDisabledError):
        things.commit("hk", {"t1": {}}, 339)


def test_commit_allowed_when_writes_enabled(monkeypatch):
    monkeypatch.setenv("THINGS_WRITE_ENABLED", "true")
    with patch.object(things, "_get_session") as sess:
        sess.return_value.request.return_value = _response(200, {"server-head-index": 340})
        things.commit("hk", {"t1": {"t": 0, "e": "Task6", "p": {}}}, 339)
        kwargs = sess.return_value.request.call_args.kwargs
        assert kwargs["params"]["ancestor-index"] == "339"


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("", False), ("nope", False),
])
def test_write_flag_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("THINGS_WRITE_ENABLED", value)
    assert things.writes_enabled() is expected


def test_writes_disabled_by_default(monkeypatch):
    monkeypatch.delenv("THINGS_WRITE_ENABLED", raising=False)
    assert things.writes_enabled() is False
