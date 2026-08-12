"""Tests for memory/things_store.py — the Things-backed task store.

Covers:
  - the TaskStore contract: list/get/get_overdue/get_summary/get_today_and_overdue.
  - read discipline: never raise; serve the stale mirror with a staleness_warning
    when Things Cloud is unreachable (what keeps the morning briefing alive).
  - write discipline: re-raise; trash instead of hard delete; no recurrence spawn.
  - the Klaus-only sidecar (priority et al.) merging over Things payloads.
  - freshness throttling and full-replay-vs-delta selection.

No network, no Firestore — things_tool and the Firestore handle are both patched.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from mcp_tools.things_tool import ThingsAuthError, ThingsUnavailableError
import memory.things_store as store_mod
from memory.things_store import ThingsTaskStore


@pytest.fixture(autouse=True)
def _clean_cache():
    store_mod.reset_cache()
    yield
    store_mod.reset_cache()


def _payload(**overrides) -> dict:
    base = {
        "_class": "Task6", "tt": "a task", "tp": 0, "ss": 0, "st": 0, "tr": False,
        "pr": [], "ar": [], "agr": [], "tg": [],
        "sr": None, "dd": None, "ato": None, "nt": None,
        "cd": 1776062349.1, "md": 1776062349.2, "sp": None, "rr": None, "rt": [],
    }
    base.update(overrides)
    return base


def _store(sidecar: dict | None = None) -> ThingsTaskStore:
    """A store whose Firestore handle is a no-op double."""
    store = ThingsTaskStore(project_id="p", database="d")
    fs = MagicMock()
    fs.collection.return_value.document.return_value.get.return_value.exists = False
    fs.collection.return_value.stream.return_value = []
    store._fs = MagicMock(return_value=fs)
    store._load_sidecar = MagicMock(return_value=sidecar or {})
    return store


@contextmanager
def _patch_things(state: dict, head: int = 1, cursor: int = 1):
    """Patch the protocol client to serve `state` from a healthy Things Cloud.

    Yields the mocks so tests can assert on call counts and arguments.
    """
    mocks = {
        "fetch_history_key": MagicMock(
            return_value={"history-key": "hk", "latest-server-index": head}),
        "replay_journal": MagicMock(return_value=(state, cursor)),
    }
    with patch.object(store_mod.things, "fetch_history_key", mocks["fetch_history_key"]), \
         patch.object(store_mod.things, "replay_journal", mocks["replay_journal"]):
        yield mocks


# ------------------------------------------------------------------ #
# Reads                                                               #
# ------------------------------------------------------------------ #

def test_list_returns_live_todos():
    state = {"t1": _payload(tt="real"), "t2": _payload(tt="done", ss=3)}
    with _patch_things(state):
        tasks = _store().list()
    assert [t["title"] for t in tasks] == ["real"]


def test_list_excludes_children_of_trashed_projects():
    """The store must inherit things_tool's containment rules, not reinvent them."""
    state = {
        "p1": _payload(tt="junk", tp=1, tr=True),
        "t1": _payload(tt="child", pr=["p1"]),
        "t2": _payload(tt="keep"),
    }
    with _patch_things(state):
        assert [t["title"] for t in _store().list()] == ["keep"]


def test_list_filters_by_project_id():
    state = {
        "p1": _payload(tt="Klaus", tp=1),
        "t1": _payload(tt="in project", pr=["p1"]),
        "t2": _payload(tt="loose"),
    }
    with _patch_things(state):
        assert [t["title"] for t in _store().list(list_id="p1")] == ["in project"]


def test_list_inbox_filters_by_bucket():
    state = {
        "t1": _payload(tt="inbox one", st=0),
        "t2": _payload(tt="anytime one", st=1),
    }
    with _patch_things(state):
        assert [t["title"] for t in _store().list(list_id="inbox")] == ["inbox one"]


def test_get_returns_single_task():
    with _patch_things({"t1": _payload(tt="found")}):
        assert _store().get("t1")["title"] == "found"


def test_get_unknown_id_returns_none():
    with _patch_things({}):
        assert _store().get("nope") is None


def test_get_overdue_uses_scheduled_date():
    import mcp_tools.things_tool as things
    state = {
        "t1": _payload(tt="late", sr=things.iso_to_day("2026-08-01")),
        "t2": _payload(tt="today", sr=things.iso_to_day("2026-08-11")),
        "t3": _payload(tt="undated"),
    }
    with _patch_things(state):
        assert [t["title"] for t in _store().get_overdue("2026-08-11")] == ["late"]


def test_get_summary_counts_due_today_and_overdue():
    import mcp_tools.things_tool as things
    state = {
        "t1": _payload(sr=things.iso_to_day("2026-08-01")),
        "t2": _payload(sr=things.iso_to_day("2026-08-11")),
        "t3": _payload(sr=things.iso_to_day("2026-08-11")),
    }
    with _patch_things(state):
        assert _store().get_summary("2026-08-11") == {"due_today": 2, "overdue": 1}


# ------------------------------------------------------------------ #
# The ticktick_overdue cron contract                                  #
# ------------------------------------------------------------------ #

def test_today_and_overdue_preserves_legacy_shape():
    """The autonomous engine, its prompts, and 25 eval fixtures depend on this."""
    import mcp_tools.things_tool as things
    state = {
        "t1": _payload(tt="late", sr=things.iso_to_day("2026-08-01")),
        "t2": _payload(tt="now", sr=things.iso_to_day("2026-08-11")),
    }
    with _patch_things(state):
        result = _store().get_today_and_overdue("2026-08-11")

    # Subset, not equality: extra keys are additive and safe, missing ones break
    # the autonomous engine and the eval fixtures.
    assert {"today", "overdue", "due_today", "staleness_warning"} <= set(result)
    assert result["today"] == [{"title": "now", "tags": []}]
    assert result["overdue"] == [{"title": "late", "due": "2026-08-01", "tags": []}]
    assert result["due_today"] == []
    assert result["staleness_warning"] is None


def test_today_and_overdue_adds_upcoming_without_breaking_legacy_keys():
    """New keys are additive — existing readers and eval fixtures still work."""
    import mcp_tools.things_tool as things
    state = {"t1": _payload(tt="soon", sr=things.iso_to_day("2026-08-14"))}
    with _patch_things(state):
        result = _store().get_today_and_overdue("2026-08-11")
    assert {"today", "overdue", "due_today", "staleness_warning"} <= set(result)
    assert [t["title"] for t in result["upcoming"]] == ["soon"]
    assert result["open_count"] == 1


# ------------------------------------------------------------------ #
# The coming week — what Amit actually asked for                      #
# ------------------------------------------------------------------ #

def test_upcoming_includes_scheduled_within_the_window():
    import mcp_tools.things_tool as things
    state = {
        "t1": _payload(tt="in range", sr=things.iso_to_day("2026-08-14")),
        "t2": _payload(tt="too far", sr=things.iso_to_day("2026-09-30")),
        "t3": _payload(tt="undated"),
    }
    with _patch_things(state):
        assert [t["title"] for t in _store().get_upcoming("2026-08-11")] == ["in range"]


def test_upcoming_includes_deadline_only_tasks():
    """A to-do due Friday but never scheduled must not be invisible."""
    import mcp_tools.things_tool as things
    state = {"t1": _payload(tt="due friday", sr=None, dd=things.iso_to_day("2026-08-14"))}
    with _patch_things(state):
        found = _store().get_upcoming("2026-08-11")
    assert [t["title"] for t in found] == ["due friday"]
    assert found[0]["kind"] == "deadline"


def test_upcoming_reports_which_date_put_it_in_range():
    import mcp_tools.things_tool as things
    state = {"t1": _payload(tt="both", sr=things.iso_to_day("2026-08-13"),
                            dd=things.iso_to_day("2026-08-15"))}
    with _patch_things(state):
        entry = _store().get_upcoming("2026-08-11")[0]
    assert entry["kind"] == "scheduled" and entry["date"] == "2026-08-13"
    assert entry["hard_deadline_at"] == "2026-08-15"


def test_upcoming_lists_each_task_once():
    import mcp_tools.things_tool as things
    day = things.iso_to_day("2026-08-13")
    with _patch_things({"t1": _payload(tt="both", sr=day, dd=day)}):
        assert len(_store().get_upcoming("2026-08-11")) == 1


def test_upcoming_excludes_overdue():
    import mcp_tools.things_tool as things
    state = {"t1": _payload(tt="late", sr=things.iso_to_day("2026-08-01"))}
    with _patch_things(state):
        assert _store().get_upcoming("2026-08-11") == []


def test_upcoming_includes_today_and_the_horizon_edge():
    import mcp_tools.things_tool as things
    state = {
        "t1": _payload(tt="today", sr=things.iso_to_day("2026-08-11")),
        "t2": _payload(tt="day seven", sr=things.iso_to_day("2026-08-18")),
        "t3": _payload(tt="day eight", sr=things.iso_to_day("2026-08-19")),
    }
    with _patch_things(state):
        titles = [t["title"] for t in _store().get_upcoming("2026-08-11")]
    assert titles == ["today", "day seven"]


def test_upcoming_sorted_soonest_first_with_days_away():
    import mcp_tools.things_tool as things
    state = {
        "t1": _payload(tt="later", sr=things.iso_to_day("2026-08-16")),
        "t2": _payload(tt="sooner", sr=things.iso_to_day("2026-08-12")),
    }
    with _patch_things(state):
        found = _store().get_upcoming("2026-08-11")
    assert [t["title"] for t in found] == ["sooner", "later"]
    assert [t["days_away"] for t in found] == [1, 5]


def test_upcoming_carries_project_and_tags_for_context():
    import mcp_tools.things_tool as things
    state = {
        "p1": _payload(tt="Klaus", tp=1),
        "g1": {"_class": "Tag4", "tt": "Errand"},
        "t1": _payload(tt="task", sr=things.iso_to_day("2026-08-12"),
                       pr=["p1"], tg=["g1"]),
    }
    with _patch_things(state):
        entry = _store().get_upcoming("2026-08-11")[0]
    assert entry["project"] == "Klaus" and entry["tags"] == ["Errand"]


def test_upcoming_window_is_configurable():
    import mcp_tools.things_tool as things
    state = {"t1": _payload(tt="in 10 days", sr=things.iso_to_day("2026-08-21"))}
    with _patch_things(state):
        store = _store()
        assert store.get_upcoming("2026-08-11") == []
        assert len(store.get_upcoming("2026-08-11", days=14)) == 1


def test_upcoming_survives_a_bad_date():
    with _patch_things({"t1": _payload()}):
        assert _store().get_upcoming("not-a-date") == []


def test_today_and_overdue_now_carries_real_tags():
    """Unlike the Firestore-native store, Things has tags to report."""
    import mcp_tools.things_tool as things
    state = {
        "g1": {"_class": "Tag4", "tt": "Errand"},
        "t1": _payload(tt="shop", sr=things.iso_to_day("2026-08-11"), tg=["g1"]),
    }
    with _patch_things(state):
        result = _store().get_today_and_overdue("2026-08-11")
    assert result["today"] == [{"title": "shop", "tags": ["Errand"]}]


# ------------------------------------------------------------------ #
# Read discipline — never raise, degrade to the mirror                #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("failure", [
    ThingsAuthError("bad password"),
    ThingsUnavailableError("network down"),
])
def test_reads_raise_when_things_is_down_instead_of_serving_the_mirror(failure):
    """Firestore is a mirror/outbox and must not become task-read authority."""
    store = _store()
    with _patch_things({"t1": _payload(tt="cached")}):
        store.list()                                   # warm the cache

    store_mod._cache["checked_at"] = 0.0               # force a refresh attempt
    with patch.object(store_mod.things, "fetch_history_key", side_effect=failure):
        with pytest.raises(type(failure)):
            store.list()


def test_reads_raise_when_cold_and_things_is_down():
    store = _store()
    with patch.object(store_mod.things, "fetch_history_key",
                      side_effect=ThingsUnavailableError("down")):
        with pytest.raises(ThingsUnavailableError):
            store.list()
        with pytest.raises(ThingsUnavailableError):
            store.get("t1")
        with pytest.raises(ThingsUnavailableError):
            store.get_summary("2026-08-11")


def test_staleness_clears_after_a_successful_refresh():
    store = _store()
    with patch.object(store_mod.things, "fetch_history_key",
                      side_effect=ThingsUnavailableError("down")):
        with pytest.raises(ThingsUnavailableError):
            store.list()
    assert store_mod._cache["stale_reason"] is not None

    store_mod._cache["checked_at"] = 0.0
    with _patch_things({"t1": _payload()}):
        store.list()
    assert store_mod._cache["stale_reason"] is None


# ------------------------------------------------------------------ #
# Freshness / delta selection                                         #
# ------------------------------------------------------------------ #

def test_head_check_is_throttled():
    """A cheap check, but not on every single read."""
    state = {"t1": _payload()}
    with _patch_things(state) as patched:
        store = _store()
        for _ in range(5):
            store.list()
        assert patched["fetch_history_key"].call_count == 1


def test_unchanged_head_skips_the_delta_pull():
    state = {"t1": _payload()}
    with _patch_things(state, head=1, cursor=1) as patched:
        store = _store()
        store.list()
        assert patched["replay_journal"].call_count == 1   # initial full replay
        store_mod._cache["checked_at"] = 0.0
        store.list()
        assert patched["replay_journal"].call_count == 1, "head unchanged — no pull"


def test_advanced_head_triggers_delta_from_cursor():
    state = {"t1": _payload()}
    with _patch_things(state, head=1, cursor=1) as patched:
        store = _store()
        store.list()
        patched["fetch_history_key"].return_value = {
            "history-key": "hk", "latest-server-index": 9}
        store_mod._cache["checked_at"] = 0.0
        store.list()

    assert patched["replay_journal"].call_count == 2
    assert patched["replay_journal"].call_args.kwargs["start_index"] == 1


# ------------------------------------------------------------------ #
# Sidecar                                                             #
# ------------------------------------------------------------------ #

def test_sidecar_fields_merge_over_things_payload():
    """Things has no priority field; Klaus keeps its planning data alongside."""
    sidecar = {"t1": {"priority": "high", "estimated_minutes": 45}}
    with _patch_things({"t1": _payload(tt="x")}):
        task = _store(sidecar).get("t1")
    assert task["priority"] == "high"
    assert task["estimated_minutes"] == 45


def test_priority_defaults_to_none_without_sidecar():
    with _patch_things({"t1": _payload()}):
        assert _store().get("t1")["priority"] == "none"


def test_create_writes_only_sidecar_fields_to_the_sidecar():
    store = _store()
    store._write_sidecar = MagicMock()
    with _patch_things({}), patch.object(store, "_commit"):
        store.create({"title": "x", "priority": "high", "notes": "body"})
    written = store._write_sidecar.call_args.args[1]
    assert written["priority"] == "high"


# ------------------------------------------------------------------ #
# Write discipline                                                    #
# ------------------------------------------------------------------ #

def test_create_commits_a_create_record():
    store = _store()
    with _patch_things({}), patch.object(store, "_commit") as commit:
        store.create({"title": "new task", "due_date": "2026-08-11"})
    _uuid, record = commit.call_args.args
    assert record["t"] == 0 and record["p"]["tt"] == "new task"


def test_complete_never_spawns_a_recurrence():
    """Things owns recurrence — Klaus creating the next instance would duplicate."""
    store = _store()
    with _patch_things({"t1": _payload()}), patch.object(store, "_commit") as commit:
        assert store.complete("t1") == {"next_id": None}
    record = commit.call_args.args[1]
    assert "rr" not in record["p"] and "rt" not in record["p"]


def test_delete_trashes_rather_than_hard_deleting():
    store = _store()
    with _patch_things({"t1": _payload()}), patch.object(store, "_commit") as commit:
        store.delete("t1")
    record = commit.call_args.args[1]
    assert record["p"]["tr"] is True
    assert record["t"] != 2, "must never issue a journal delete"


def test_update_reschedule_leaves_the_deadline_alone():
    store = _store()
    with _patch_things({"t1": _payload()}), patch.object(store, "_commit") as commit:
        store.update("t1", {"due_date": "2026-09-01"})
    assert "dd" not in commit.call_args.args[1]["p"]


def test_update_sends_only_supplied_fields():
    store = _store()
    with _patch_things({"t1": _payload()}), patch.object(store, "_commit") as commit:
        store.update("t1", {"title": "renamed"})
    sent = commit.call_args.args[1]["p"]
    assert sent["tt"] == "renamed"
    assert "nt" not in sent and "sr" not in sent


def test_sidecar_only_update_makes_no_things_commit():
    store = _store()
    store._write_sidecar = MagicMock()
    with _patch_things({"t1": _payload()}), patch.object(store, "_commit") as commit:
        store.update("t1", {"priority": "low"})
    commit.assert_not_called()


def test_write_failures_re_raise():
    """Reads degrade quietly; writes must not."""
    store = _store()
    with _patch_things({"t1": _payload()}), \
         patch.object(store_mod.things, "commit", side_effect=ThingsUnavailableError("no")):
        with pytest.raises(ThingsUnavailableError):
            store.complete("t1")
