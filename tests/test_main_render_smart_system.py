"""Tests for AgentOrchestrator.render_smart_system — Phase 18-06 Task 0.

The render method is a pure refactor extraction from handle_message. It
substitutes the 4 standard placeholders {self_md}, {self_state},
{journal_digest}, {today_date} into a smart-system template.

It is invoked by:
  - handle_message (per-message chat path) — extracted from inline render
  - core/autonomous.py:_compose_layer2 (per-tick autonomous path) — Plan 18-06

Plan 32-02: render_smart_system now returns a (stable, volatile) tuple
split at the existing CURRENT TIME heading in prompts/smart_agent.md, so
the Anthropic backend can cache the stable prefix as a real second content
block. Tests that only care about substituted CONTENT (not the split point
itself) use the `_rendered()` helper below, which concatenates the tuple
back into one string — every synthetic template in this file lacks the
CURRENT TIME heading, so `_rendered()` is equivalent to the pre-32-02
plain-string return for all of them (volatile is always "").

Test strategy
-------------
Firestore + google.* are mocked at the sys.modules level using the same
_install_firestore_mock() pattern from tests/test_reflection.py so that
core.main can be imported with no real Google API libraries installed.
"""
from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def _safe_mock_module(name: str) -> None:
    if name in sys.modules:
        return
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent in sys.modules and isinstance(sys.modules[parent], MagicMock):
            sys.modules[name] = MagicMock()
            return
    try:
        __import__(name)
    except ImportError:
        sys.modules[name] = MagicMock()


def _install_firestore_mock() -> None:
    """Install mock google.cloud.firestore + auth stubs into sys.modules."""
    if "google.cloud.firestore" not in sys.modules:
        import types
        try:
            import google
        except ImportError:
            google = types.ModuleType("google")
            sys.modules["google"] = google

        try:
            import google.cloud
            google_cloud_mod = sys.modules["google.cloud"]
        except ImportError:
            google_cloud_mod = types.ModuleType("google.cloud")
            sys.modules["google.cloud"] = google_cloud_mod
            if not hasattr(google, "cloud"):
                setattr(google, "cloud", google_cloud_mod)

        firestore_mock = MagicMock()

        class _Increment:
            def __init__(self, value):
                self.value = value
            def __repr__(self):
                return f"Increment({self.value!r})"

        firestore_mock.Increment = _Increment
        firestore_mock.SERVER_TIMESTAMP = object()
        firestore_mock.ArrayUnion = MagicMock()

        sys.modules["google.cloud.firestore"] = firestore_mock
        google_cloud_mod.firestore = firestore_mock
        if not hasattr(google, "cloud"):
            google.cloud = google_cloud_mod


        _safe_mock_module("google.api_core")
        _safe_mock_module("google.api_core.exceptions")
        _safe_mock_module("google.cloud.firestore_v1")
        _safe_mock_module("google.cloud.firestore_v1.base_query")

    # Unconditionally install auth + googleapiclient stubs so core/auth_google,
    # core/tools (imported transitively by core.main) load cleanly without the
    # real Google libraries.
    _safe_mock_module("google.auth")
    _safe_mock_module("google.auth.exceptions")
    _safe_mock_module("google.auth.transport")
    _safe_mock_module("google.auth.transport.requests")
    _safe_mock_module("google.oauth2")
    _safe_mock_module("google.oauth2.credentials")
    _safe_mock_module("google.oauth2.service_account")
    _safe_mock_module("google_auth_oauthlib")
    _safe_mock_module("google_auth_oauthlib.flow")
    _safe_mock_module("googleapiclient")
    _safe_mock_module("googleapiclient.errors")
    _safe_mock_module("googleapiclient.discovery")

    _safe_mock_module("dotenv")


_install_firestore_mock()


# ---------------------------------------------------------------------------
# Orchestrator factory
# ---------------------------------------------------------------------------

def _make_orchestrator(
    *,
    self_md: str = "SELF.MD-CONTENT",
    coaching_guide_content: str = "COACHING-GUIDE-SLIM",  # Phase 22 addition
    self_state_store=None,
    journal_store=None,
):
    """Construct an AgentOrchestrator with all heavy dependencies stubbed.

    The orchestrator is NOT initialised via __init__ (which would talk to
    LLM backends and Firestore). Instead, we manually attach the four
    attributes that render_smart_system reads.
    """
    from core.main import AgentOrchestrator
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._self_md_content = self_md
    orchestrator._coaching_guide_content = coaching_guide_content  # Phase 22
    orchestrator._self_state_store = self_state_store
    orchestrator._journal_store = journal_store
    orchestrator._smart_prompt_template = (
        "SMART_PROMPT\n{self_md}\n---\n{self_state}\n---\n"
        "{journal_digest}\n---\n{today_date}\nEND"
    )
    return orchestrator


def _rendered(orch, template: str) -> str:
    """Call render_smart_system and concatenate the (stable, volatile) tuple
    back into one string (Plan 32-02). Every synthetic template in this file
    lacks the CURRENT TIME heading, so volatile is always "" here — this is
    equivalent to the pre-32-02 plain-string return for content assertions
    that don't care about the split point itself."""
    stable, volatile = orch.render_smart_system(template)
    return stable + volatile


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_render_substitutes_self_md():
    """{self_md} is replaced with the orchestrator's _self_md_content."""
    orch = _make_orchestrator(self_md="Klaus-identity-block")
    out = _rendered(orch, "Header\n{self_md}\nFooter")
    assert "Klaus-identity-block" in out
    assert "{self_md}" not in out


def test_render_self_state_none_substitutes_empty_string():
    """When _self_state_store is None, {self_state} -> '' (not literal placeholder)."""
    orch = _make_orchestrator(self_state_store=None)
    out = _rendered(orch, "A\n{self_state}\nB")
    assert "{self_state}" not in out
    # The placeholder line collapsed to an empty replacement, not the literal token.
    assert "A\n\nB" in out


def test_render_journal_none_substitutes_empty_string():
    """When _journal_store is None, {journal_digest} -> '' (not literal placeholder)."""
    orch = _make_orchestrator(journal_store=None)
    out = _rendered(orch, "X\n{journal_digest}\nY")
    assert "{journal_digest}" not in out
    assert "X\n\nY" in out


def test_render_today_date_substituted():
    """{today_date} is replaced with the result of _today_israel()."""
    orch = _make_orchestrator()
    with patch("core.main._today_israel", return_value="Saturday, May 23, 2026"):
        out = _rendered(orch, "Date: {today_date}")
    assert "Saturday, May 23, 2026" in out
    assert "{today_date}" not in out


def test_render_current_time_substituted():
    """{current_time} is replaced with the result of _current_time_israel()."""
    orch = _make_orchestrator()
    with patch("core.main._current_time_israel", return_value="14:20"):
        out = _rendered(orch, "Now: {current_time}")
    assert "14:20" in out
    assert "{current_time}" not in out


def test_render_no_unresolved_placeholders():
    """After rendering, none of the placeholder tokens remain in the output."""
    orch = _make_orchestrator()
    template = (
        "{self_md}\n{self_state}\n{journal_digest}\n{today_date}\n{current_time}\n"
        "{self_md}\n{today_date}"  # repeated tokens still replaced
    )
    out = _rendered(orch, template)
    for token in ("{self_md}", "{self_state}", "{journal_digest}", "{today_date}",
                  "{current_time}"):
        assert token not in out, f"placeholder {token} survived render"


def test_render_self_state_populated_block():
    """When _self_state_store returns non-empty state, the rendered block lists fields."""
    fake_store = MagicMock()
    fake_store.get.return_value = {
        "current_focus": "phase 18 wave 2",
        "mood": "focused",
        "updated_at": "ignored",
        "bootstrapped_at": "ignored",
        "empty_field": "",  # blank values are filtered out per D-05
    }
    orch = _make_orchestrator(self_state_store=fake_store)
    out = _rendered(orch, "{self_state}")
    assert "current_focus: phase 18 wave 2" in out
    assert "mood: focused" in out
    # Bookkeeping fields are filtered
    assert "updated_at" not in out
    assert "bootstrapped_at" not in out
    # Empty field omitted (D-05)
    assert "empty_field" not in out
    assert "**Self-state:**" in out


def test_render_journal_digest_populated_block():
    """When _journal_store has recent entries, render includes a digest block."""
    fake_store = MagicMock()
    fake_store.get_recent.return_value = [
        {
            "date": "2026-05-21",
            "mood": "focused",
            "summary": "shipped plan 05",
            "highlights": ["green tests"],
        },
        {
            "date": "2026-05-20",
            "mood": "ok",
            "summary": "wave 1 wrap",
            "highlights": [],
        },
    ]
    orch = _make_orchestrator(journal_store=fake_store)
    out = _rendered(orch, "{journal_digest}")
    assert "**Recent journal:**" in out
    assert "2026-05-21" in out
    assert "shipped plan 05" in out
    assert "green tests" in out  # highlight line included
    assert "2026-05-20" in out


class TestPhase19TrainingProfile:
    """PROMPT-01 — render_smart_system substitutes {training_profile}."""

    def test_training_profile_substituted(self):
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = MagicMock()
        orch._user_profile_store.load.return_value = {
            "athletic_goals": ["5k under 20:00"],
            "schema_version": 1,
        }
        result = _rendered(orch, "PRE {training_profile} POST")
        assert "PRE" in result and "POST" in result
        # Phase 21 Plan 04: header changed from "Training profile:" to coaching-reference header
        assert "**Coaching reference — Amit's training plan:**" in result
        assert "athletic_goals" in result
        assert "5k under 20:00" in result

    def test_training_profile_empty_renders_empty(self):
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = MagicMock()
        orch._user_profile_store.load.return_value = {}
        result = _rendered(orch, "X{training_profile}Y")
        assert result.startswith("X") and result.endswith("Y")
        assert "{training_profile}" not in result  # literal placeholder GONE
        assert "Training profile" not in result

    def test_training_profile_omits_meta_keys(self):
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = MagicMock()
        orch._user_profile_store.load.return_value = {
            "athletic_goals": [],  # empty list → omitted
            "schema_version": 1,    # meta → filtered
            "bootstrapped_at": "ts",
            "updated_at": "ts",
        }
        result = _rendered(orch, "X{training_profile}Y")
        assert "schema_version" not in result
        assert "bootstrapped_at" not in result
        assert "updated_at" not in result
        # athletic_goals=[] is empty → filtered too
        assert "Training profile" not in result

    def test_user_profile_store_none_renders_empty(self):
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = None
        result = _rendered(orch, "X{training_profile}Y")
        assert result == "XY"


class TestPhase21CoachingReferenceRendering:
    """Phase 21 Plan 04 — coaching-reference prose rendering of structured profile fields."""

    def _make_orch_with_profile(self, profile_data: dict):
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = MagicMock()
        orch._user_profile_store.load.return_value = profile_data
        return orch

    def test_coaching_reference_header(self):
        """Structured profile renders with new coaching header, not 'Training profile:'."""
        orch = self._make_orch_with_profile({
            "dated_goals": [
                {"goal_label": "Oct peak", "target_date": "2026-10-01", "metrics": ["100kg bench", "120kg squat"]}
            ],
        })
        result = _rendered(orch, "{training_profile}")
        assert "**Coaching reference — Amit's training plan:**" in result
        assert "**Training profile:**" not in result

    def test_dated_goals_renders_metric_bullets(self):
        """dated_goals renders one bullet per goal including the metric values."""
        orch = self._make_orch_with_profile({
            "dated_goals": [
                {"goal_label": "Oct peak", "target_date": "2026-10-01", "metrics": ["100kg bench", "120kg squat"]},
                {"goal_label": "Nov peak", "target_date": "2026-11-01", "metrics": ["125 push-ups", "35 pull-ups"]},
            ],
        })
        result = _rendered(orch, "{training_profile}")
        assert "100kg bench" in result
        assert "120kg squat" in result
        assert "125 push-ups" in result
        assert "Oct peak" in result
        assert "Nov peak" in result

    def test_dated_goals_renders_dict_metric_values(self):
        """dated_goals.metrics as a dict (the ingest contract) renders names AND
        values — guards against CR-21-01 where dict iteration dropped every target."""
        orch = self._make_orch_with_profile({
            "dated_goals": [
                {
                    "goal_label": "Oct peak",
                    "target_date": "2026-10-31",
                    "metrics": {"bench_press_kg": 100, "half_marathon_time": "1:25:00"},
                },
            ],
        })
        result = _rendered(orch, "{training_profile}")
        # The numeric target value MUST survive into the prompt, not just the key.
        assert "100" in result
        assert "1:25:00" in result
        assert "bench_press_kg" in result

    def test_real_ingest_payload_renders_all_targets(self):
        """Integration guard (WR-21-02): feed the actual build_profile_dict()
        output through the renderer and assert every Tier A target survives.
        This is the cross-plan check that the per-plan fixtures missed."""
        from scripts.ingest_blueprint import build_profile_dict
        orch = self._make_orch_with_profile(build_profile_dict())
        result = _rendered(orch, "{training_profile}")
        # October peak numeric targets from the blueprint.
        assert "100" in result          # bench_press_kg
        assert "120" in result          # squat_kg
        assert "1:25:00" in result      # half_marathon_time
        # November peak targets.
        assert "125" in result          # push_ups
        assert "35" in result           # pull_ups
        # Block anchor must render.
        assert "2026-06-21" in result

    def test_real_template_injects_profile_block_exactly_once(self):
        """Regression guard (WRN-01): render the ACTUAL prompts/smart_agent.md with a
        real seeded profile and assert the coaching-reference block is injected exactly
        once. str.replace hits every occurrence, so a stray literal `{training_profile}`
        in the prose (line 87 before the fix) would duplicate the whole Tier A block and
        corrupt the instructional sentence. No literal placeholders may survive either."""
        from pathlib import Path
        from scripts.ingest_blueprint import build_profile_dict

        template = Path("prompts/smart_agent.md").read_text(encoding="utf-8")
        orch = self._make_orch_with_profile(build_profile_dict())
        orch._coaching_guide_content = "COACHING_GUIDE_SENTINEL"
        result = _rendered(orch, template)

        # The rendered Tier A coaching-reference header must appear exactly once.
        assert result.count("**Coaching reference — Amit's training plan:**") == 1
        # No placeholder may survive the substitution chain.
        assert "{training_profile}" not in result
        assert "{coaching_guide}" not in result
        # The instructional prose that describes the block must stay intact (not get a
        # full profile block spliced into the middle of the sentence).
        assert "The training-profile block injected above" in result

    def test_weekly_split_renders_day_and_modality(self):
        """weekly_split renders a per-day line with label and modality."""
        orch = self._make_orch_with_profile({
            "weekly_split": {
                "Monday": {
                    "am": {"label": "Upper strength", "modality": "lift", "priority": "high"},
                    "pm": {"label": "Easy run", "modality": "run", "priority": "medium"},
                },
                "Tuesday": {
                    "am": {"label": "Rest", "modality": "rest", "priority": "low"},
                    "pm": {"label": "Lower strength", "modality": "lift", "priority": "high"},
                },
            },
        })
        result = _rendered(orch, "{training_profile}")
        assert "Monday" in result
        assert "lift" in result
        assert "run" in result
        assert "Upper strength" in result

    def test_weekly_split_no_attendance_words(self):
        """weekly_split rendered snippet contains NO attendance-tracking words."""
        orch = self._make_orch_with_profile({
            "weekly_split": {
                "Wednesday": {
                    "am": {"label": "Calisthenics", "modality": "calisthenics", "priority": "high"},
                    "pm": {"label": "Rest", "modality": "rest", "priority": "low"},
                },
            },
        })
        result = _rendered(orch, "{training_profile}")
        for forbidden in ("attendance", "completed", "missed"):
            assert forbidden not in result, f"'{forbidden}' should not appear in weekly_split rendering"

    def test_plan_start_date_renders_block_anchor(self):
        """plan_start_date renders as 'Block anchor: YYYY-MM-DD (Block Week 1)'."""
        orch = self._make_orch_with_profile({
            "plan_start_date": "2026-06-21",
        })
        result = _rendered(orch, "{training_profile}")
        assert "Block anchor: 2026-06-21 (Block Week 1)" in result

    def test_nutrition_targets_renders_macros(self):
        """nutrition_targets renders daily macro targets as readable text."""
        orch = self._make_orch_with_profile({
            "nutrition_targets": {
                "protein_g": 150,
                "carbs_g": 350,
                "fueling_slots": ["pre-workout", "post-workout"],
            },
        })
        result = _rendered(orch, "{training_profile}")
        assert "150" in result
        assert "350" in result

    def test_unknown_key_falls_back_to_generic_format(self):
        """An unknown key not in the known-key set renders as '- key: value' (forward-compat)."""
        orch = self._make_orch_with_profile({
            "future_experimental_key": "some value",
        })
        result = _rendered(orch, "{training_profile}")
        assert "- future_experimental_key:" in result
        assert "some value" in result

    def test_meta_keys_still_excluded(self):
        """updated_at/bootstrapped_at/schema_version are never rendered."""
        orch = self._make_orch_with_profile({
            "plan_start_date": "2026-06-21",
            "schema_version": 2,
            "updated_at": "some-timestamp",
            "bootstrapped_at": "some-timestamp",
        })
        result = _rendered(orch, "{training_profile}")
        assert "schema_version" not in result
        assert "updated_at" not in result
        assert "bootstrapped_at" not in result
        # plan_start_date is still rendered
        assert "Block anchor" in result

    def test_empty_profile_still_renders_empty(self):
        """Empty profile after non_empty filter → empty snippet (existing guard preserved)."""
        orch = self._make_orch_with_profile({
            "schema_version": 2,
            "updated_at": "ts",
            "dated_goals": [],
        })
        result = _rendered(orch, "A{training_profile}B")
        assert result == "AB"


def test_handle_message_uses_render_smart_system():
    """Regression: handle_message calls render_smart_system (not the inline render)."""
    import inspect
    from core.main import AgentOrchestrator

    source = inspect.getsource(AgentOrchestrator.handle_message)
    # The new contract: handle_message must call self.render_smart_system.
    assert "self.render_smart_system" in source, (
        "handle_message should delegate render to render_smart_system"
    )
    # The old inline render block (constructing smart_system via 4 .replace calls)
    # must no longer appear in handle_message.
    assert ".replace(\"{self_md}\"" not in source, (
        "handle_message still contains inline render — refactor incomplete"
    )


# ---------------------------------------------------------------------------
# Plan 32-02 — render_smart_system returns (stable, volatile); the split
# happens at the existing CURRENT TIME heading in prompts/smart_agent.md so
# the Anthropic cache prefix stops rewriting on every per-minute render.
# ---------------------------------------------------------------------------


class TestPlan3202StableVolatileSplit:

    def test_returns_tuple_of_two_strings(self):
        orch = _make_orchestrator()
        result = orch.render_smart_system("Header\n{self_md}\nFooter")
        assert isinstance(result, tuple)
        assert len(result) == 2
        stable, volatile = result
        assert isinstance(stable, str)
        assert isinstance(volatile, str)

    def test_template_without_current_time_heading_is_entirely_stable(self):
        """A template with no CURRENT TIME seam (e.g. a synthetic test
        template, or real autonomous.md/worker_agent.md which lack the
        heading) degrades to (full_content, '') — the same fallback the
        Anthropic backend relies on to avoid an empty second content block."""
        orch = _make_orchestrator()
        stable, volatile = orch.render_smart_system("Header\n{self_md}\nFooter")
        assert volatile == ""
        assert "Header" in stable and "Footer" in stable

    def test_real_template_splits_at_current_time_heading(self):
        """Rendering the actual prompts/smart_agent.md: {today_date} (line 15)
        stays in the stable half by design; the CURRENT TIME section
        ({current_time}, line 378) is the volatile half."""
        from pathlib import Path
        template = Path("prompts/smart_agent.md").read_text(encoding="utf-8")
        orch = _make_orchestrator()
        with patch("core.main._today_israel", return_value="Saturday, May 23, 2026"), \
             patch("core.main._current_time_israel", return_value="14:20"):
            stable, volatile = orch.render_smart_system(template)
        assert "Saturday, May 23, 2026" in stable
        assert "14:20" not in stable
        assert "CURRENT TIME" in volatile
        assert "14:20" in volatile

    def test_stable_half_byte_identical_across_renders_one_minute_apart(self):
        """Holding stores + today_date constant, two renders ~1 minute apart
        (different current_time) must yield a byte-identical stable half and
        a differing volatile half — the core cache-correctness guarantee."""
        from pathlib import Path
        template = Path("prompts/smart_agent.md").read_text(encoding="utf-8")
        orch = _make_orchestrator()

        with patch("core.main._today_israel", return_value="Saturday, May 23, 2026"), \
             patch("core.main._current_time_israel", return_value="14:20"):
            stable_1, volatile_1 = orch.render_smart_system(template)

        with patch("core.main._today_israel", return_value="Saturday, May 23, 2026"), \
             patch("core.main._current_time_israel", return_value="14:21"):
            stable_2, volatile_2 = orch.render_smart_system(template)

        assert stable_1 == stable_2, "stable half must be byte-identical across per-minute renders"
        assert volatile_1 != volatile_2, "volatile half must change with current_time"

    def test_handle_message_passes_tuple_through_to_run_smart_loop(self):
        """handle_message must pass the (stable, volatile) tuple straight to
        _run_smart_loop's system param — no re-flattening into one string."""
        from core.main import AgentOrchestrator

        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch.smart_agent = MagicMock()
        orch.smart_agent_fallback = None
        orch.worker_agent = MagicMock()
        orch._smart_prompt_template = "smart"
        orch._worker_prompt_template = "worker {today_date}"
        orch._meal_audit_content = ""
        orch.conversation_manager = MagicMock()
        orch.conversation_manager.get.return_value = []
        orch.render_smart_system = MagicMock(return_value=("STABLE-X", "VOLATILE-X"))
        captured = {}

        def _capture(messages, smart_system, worker_system, **kwargs):
            captured["smart_system"] = smart_system
            return "ok"

        orch._run_smart_loop = MagicMock(side_effect=_capture)

        orch.handle_message("hi", user_id=1)

        assert captured["smart_system"] == ("STABLE-X", "VOLATILE-X")

    def test_meal_audit_appended_to_volatile_half_only(self):
        """The chat-path meal_audit append targets the VOLATILE half — the
        stable half must stay untouched so the cache prefix is unaffected."""
        from core.main import AgentOrchestrator

        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch.smart_agent = MagicMock()
        orch.smart_agent_fallback = None
        orch.worker_agent = MagicMock()
        orch._smart_prompt_template = "smart"
        orch._worker_prompt_template = "worker {today_date}"
        orch._meal_audit_content = "MEAL-AUDIT-GUIDANCE"
        orch.conversation_manager = MagicMock()
        orch.conversation_manager.get.return_value = []
        orch.render_smart_system = MagicMock(
            return_value=("STABLE-CONTENT", "VOLATILE-CONTENT")
        )
        captured = {}

        def _capture(messages, smart_system, worker_system, **kwargs):
            captured["smart_system"] = smart_system
            return "ok"

        orch._run_smart_loop = MagicMock(side_effect=_capture)

        orch.handle_message("hi", user_id=1)

        stable, volatile = captured["smart_system"]
        assert stable == "STABLE-CONTENT", "meal_audit must not touch the stable half"
        assert volatile == "VOLATILE-CONTENT\n\nMEAL-AUDIT-GUIDANCE"

    def test_autonomous_compose_sites_never_string_concat_smart_system(self):
        """Source-level guard: neither compose site may treat the
        render_smart_system() result as a plain string (str-concat semantics
        would raise TypeError on a tuple) — both must pass it through as-is."""
        src = open("core/autonomous.py", encoding="utf-8").read()
        assert "smart_system = smart_system +" not in src
        assert "smart_system +=" not in src


# ---------------------------------------------------------------------------
# Phase 22 Plan 02 — coaching guide slim-core injection (COACH-01)
# ---------------------------------------------------------------------------

def test_render_substitutes_coaching_guide():
    """{coaching_guide} is replaced with the orchestrator's _coaching_guide_content."""
    orch = _make_orchestrator(coaching_guide_content="COACHING-SLIM-BLOCK")
    out = _rendered(orch, "Header\n{coaching_guide}\nFooter")
    assert "COACHING-SLIM-BLOCK" in out
    assert "{coaching_guide}" not in out


def test_render_coaching_guide_empty_no_literal_placeholder():
    """When _coaching_guide_content is '', {coaching_guide} resolves to '' not literal."""
    orch = _make_orchestrator(coaching_guide_content="")
    out = _rendered(orch, "A\n{coaching_guide}\nB")
    assert "{coaching_guide}" not in out


def test_render_no_unresolved_placeholders_includes_coaching_guide():
    """After rendering, {coaching_guide} (plus original 4 tokens) must not survive."""
    orch = _make_orchestrator()
    template = (
        "{coaching_guide}\n{self_md}\n{self_state}\n{journal_digest}\n{today_date}\n"
        "{current_time}\n"
    )
    out = _rendered(orch, template)
    for token in ("{coaching_guide}", "{self_md}", "{self_state}", "{journal_digest}",
                  "{today_date}", "{current_time}"):
        assert token not in out, f"placeholder {token} survived render"


def test_load_coaching_guide_slim_size_guard():
    """_load_coaching_guide_slim against the real COACHING_GUIDE.md is < 350 lines / < 15000 chars.

    This is the Pitfall-2 gate: ensures only the slim-core block (not the full guide)
    is injected into every brain system prompt.
    """
    from core.main import _load_coaching_guide_slim
    result = _load_coaching_guide_slim()
    # Must return non-empty (markers present in docs/COACHING_GUIDE.md)
    assert result != "", "slim core returned empty — SLIM_CORE_START/END markers missing or file absent"
    lines = result.splitlines()
    assert len(lines) < 350, f"slim core too large: {len(lines)} lines (limit 350)"
    assert len(result) < 15_000, f"slim core too large: {len(result)} chars (limit 15000)"


def test_load_coaching_guide_slim_missing_markers(monkeypatch):
    """When SLIM_CORE markers are absent from the guide, loader returns '' with a warning."""
    import core.main as main_module

    # Patch read_text to return content without markers
    _content_no_markers = "# No markers here\nJust plain content.\n"

    class _FakePath:
        def __init__(self, *args, **kwargs):
            import pathlib
            self._inner = pathlib.Path(*args, **kwargs)

        def __truediv__(self, other):
            result = _FakePath.__new__(_FakePath)
            result._inner = self._inner / other
            return result

        def resolve(self):
            result = _FakePath.__new__(_FakePath)
            result._inner = self._inner.resolve()
            return result

        @property
        def parent(self):
            result = _FakePath.__new__(_FakePath)
            result._inner = self._inner.parent
            return result

        @property
        def parts(self):
            return self._inner.parts

        def read_text(self, encoding="utf-8"):
            if "COACHING_GUIDE.md" in str(self._inner):
                return _content_no_markers
            return self._inner.read_text(encoding=encoding)

        def __str__(self):
            return str(self._inner)

    monkeypatch.setattr(main_module, "Path", _FakePath)
    result = main_module._load_coaching_guide_slim()
    assert result == "", f"Expected '' for missing markers, got: {result!r}"


def test_load_coaching_guide_slim_file_absent(monkeypatch):
    """When COACHING_GUIDE.md is absent, loader returns '' (no exception raised)."""
    import core.main as main_module

    class _FakePath:
        def __init__(self, *args, **kwargs):
            import pathlib
            self._inner = pathlib.Path(*args, **kwargs)

        def __truediv__(self, other):
            result = _FakePath.__new__(_FakePath)
            result._inner = self._inner / other
            return result

        def resolve(self):
            result = _FakePath.__new__(_FakePath)
            result._inner = self._inner.resolve()
            return result

        @property
        def parent(self):
            result = _FakePath.__new__(_FakePath)
            result._inner = self._inner.parent
            return result

        @property
        def parts(self):
            return self._inner.parts

        def read_text(self, encoding="utf-8"):
            if "COACHING_GUIDE.md" in str(self._inner):
                raise OSError("file not found")
            return self._inner.read_text(encoding=encoding)

        def __str__(self):
            return str(self._inner)

    monkeypatch.setattr(main_module, "Path", _FakePath)
    result = main_module._load_coaching_guide_slim()
    assert result == "", f"Expected '' for missing file, got: {result!r}"


# ---------------------------------------------------------------------------
# Phase 22 Plan 03 — briefing/alert compose-time coaching guide injection
# ---------------------------------------------------------------------------

def test_briefing_no_literal_placeholder():
    """`_compose_briefing` must not leave a literal {coaching_guide} in the system prompt.

    Verifies the PHASE 22 COACH-01 injection: the slim core is substituted at
    compose time via .replace("{coaching_guide}", ...) before the prompt reaches
    the LLM. Pitfall 6 directly addressed.
    """
    import types

    fake_coaching_content = "SLIM-CORE-CONTENT-FOR-TEST"
    fake_orch = types.SimpleNamespace(_coaching_guide_content=fake_coaching_content)

    captured_system_prompts: list[str] = []

    class _FakeLLMClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, messages, system=""):
            captured_system_prompts.append(system)
            return {"text": "Good morning, sir."}

    # Patch at the source module level so the `from core.llm_client import LLMClient`
    # inside _compose_briefing picks up our fake when sys.modules is pre-populated.
    fake_llm_module = MagicMock()
    fake_llm_module.LLMClient = _FakeLLMClient

    import core.morning_briefing as mb_module

    with patch("core.autonomous._get_orchestrator", return_value=fake_orch), \
         patch.dict("sys.modules", {"core.llm_client": fake_llm_module}), \
         patch.dict(os.environ, {
             "SMART_AGENT_BACKEND": "test",
             "SMART_AGENT_MODEL": "test-model",
             "SMART_AGENT_API_KEY": "test-key",
         }):
        mb_module._compose_briefing({}, "2026-06-05")

    assert len(captured_system_prompts) == 1, "LLM was not called exactly once"
    system_prompt = captured_system_prompts[0]

    # Primary assertion: the literal placeholder must be gone.
    assert "{coaching_guide}" not in system_prompt, (
        "Literal {coaching_guide} survived _compose_briefing — inject is broken"
    )
    # Secondary assertion: the slim core content arrived.
    assert fake_coaching_content in system_prompt, (
        "Slim core content missing from briefing system prompt"
    )


def test_alert_no_literal_placeholder():
    """`_compose_alert` must not leave a literal {coaching_guide} in the system prompt.

    Mirror of `test_briefing_no_literal_placeholder` for the evening alert path.
    """
    import types

    fake_coaching_content = "SLIM-CORE-ALERT-TEST"
    fake_orch = types.SimpleNamespace(_coaching_guide_content=fake_coaching_content)

    captured_system_prompts: list[str] = []

    class _FakeLLMClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, messages, system=""):
            captured_system_prompts.append(system)
            return {"text": "Evening alert, sir."}

    fake_llm_module = MagicMock()
    fake_llm_module.LLMClient = _FakeLLMClient

    import core.proactive_alerts as pa_module

    with patch("core.autonomous._get_orchestrator", return_value=fake_orch), \
         patch.dict("sys.modules", {"core.llm_client": fake_llm_module}), \
         patch.dict(os.environ, {
             "SMART_AGENT_BACKEND": "test",
             "SMART_AGENT_MODEL": "test-model",
             "SMART_AGENT_API_KEY": "test-key",
         }):
        pa_module._compose_alert({})

    assert len(captured_system_prompts) == 1, "LLM was not called exactly once"
    system_prompt = captured_system_prompts[0]

    assert "{coaching_guide}" not in system_prompt, (
        "Literal {coaching_guide} survived _compose_alert — inject is broken"
    )
    assert fake_coaching_content in system_prompt, (
        "Slim core content missing from alert system prompt"
    )


class TestStandingDirectivesRendering:
    """Phase 31 Plan 03 — render_smart_system substitutes {standing_directives}
    at the cache-safe position (DIR-03 chat injection site)."""

    def _make_orch(self, active_directives):
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = None
        orch._standing_directive_store = MagicMock()
        orch._standing_directive_store.list_active.return_value = active_directives
        return orch

    def test_non_empty_directives_render_block_content(self):
        orch = self._make_orch([
            {"text": "no training nudges", "origin": "user_chat",
             "expires_at": None, "condition_text": "while I'm in France"},
        ])
        result = _rendered(orch, "PRE {standing_directives} POST")
        assert "PRE" in result and "POST" in result
        assert "**Active standing directives:**" in result
        assert "no training nudges" in result
        assert "(until: while I'm in France)" in result

    def test_empty_directives_resolves_to_nothing(self):
        orch = self._make_orch([])
        result = _rendered(orch, "X{standing_directives}Y")
        assert result == "XY"
        assert "{standing_directives}" not in result

    def test_store_none_renders_empty(self):
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = None
        orch._standing_directive_store = None
        result = _rendered(orch, "X{standing_directives}Y")
        assert result == "XY"

    def test_ordering_after_training_profile_before_today_date(self):
        """Load-bearing cache-prefix ordering (Pitfall 3): directive content
        must appear AFTER the resolved training-profile content and BEFORE
        the resolved {today_date} value — assert index positions."""
        from core.main import AgentOrchestrator
        orch = AgentOrchestrator.__new__(AgentOrchestrator)
        orch._self_md_content = ""
        orch._self_state_store = None
        orch._journal_store = None
        orch._user_profile_store = MagicMock()
        orch._user_profile_store.load.return_value = {
            "athletic_goals": ["5k under 20:00"],
            "schema_version": 1,
        }
        orch._standing_directive_store = MagicMock()
        orch._standing_directive_store.list_active.return_value = [
            {"text": "ordering-marker directive", "origin": "user_chat",
             "expires_at": None, "condition_text": None},
        ]
        result = _rendered(
            orch,
            "{training_profile} ... {standing_directives} ... today is {today_date}",
        )
        training_idx = result.index("5k under 20:00")
        directive_idx = result.index("ordering-marker directive")
        today_idx = result.index("today is")
        assert training_idx < directive_idx < today_idx, (
            f"Expected training({training_idx}) < directive({directive_idx}) < today({today_idx})"
        )


# ---------------------------------------------------------------------------
# Nutrition fueling-coach wiring into the CHAT path
# ---------------------------------------------------------------------------


class TestMealAuditChatWiring:
    """The performance-fueling coach (prompts/meal_audit.md) must be wired into
    the on-demand chat path — previously it loaded only for the crons, which is
    why direct nutrition questions got generic, uncoached answers."""

    def test_main_loads_and_appends_meal_audit_in_chat(self):
        """core/main.py loads meal_audit into _meal_audit_content and appends it
        in the chat path (handle_message)."""
        src = open("core/main.py", encoding="utf-8").read()
        assert "prompts/meal_audit.md" in src, (
            "core/main.py must load prompts/meal_audit.md for the chat coach"
        )
        assert "_meal_audit_content" in src, (
            "core/main.py must store the coach as _meal_audit_content"
        )
        assert "+ self._meal_audit_content" in src, (
            "core/main.py must APPEND _meal_audit_content to the chat smart_system"
        )

    def test_render_smart_system_does_not_append_meal_audit(self):
        """Guard against double-append: meal_audit must be appended in the chat
        path (handle_message), NOT inside render_smart_system — autonomous.py
        calls render_smart_system and appends meal_audit itself."""
        import inspect
        import core.main as main_mod
        render_src = inspect.getsource(main_mod.AgentOrchestrator.render_smart_system)
        assert "meal_audit" not in render_src, (
            "render_smart_system must not append meal_audit — autonomous.py would "
            "then get it twice"
        )

    def test_meal_audit_is_performance_fueling_coach(self):
        """meal_audit.md is the performance-fueling coach: personalized, periodized,
        forward-looking — flags what's worth changing, reinforces what's on track
        only when real (no rigid improve+keep template), not the old non-personalized
        critique."""
        body = open("prompts/meal_audit.md", encoding="utf-8").read()
        assert body.strip(), "prompts/meal_audit.md is empty"
        lowered = body.lower()
        # Must coach toward change and acknowledge on-track without manufacturing it
        assert "worth changing" in lowered or "what to improve" in lowered, (
            "coach must direct what's worth changing against the day's need"
        )
        assert "on track" in lowered or "dialed in" in lowered, (
            "coach must be able to acknowledge an on-track day (but not manufacture it)"
        )
        assert "nutrition_targets" in lowered, "coach must reference the profile anchors"
        # periodization by training load is the core of performance fueling
        assert "carb" in lowered and ("rest day" in lowered or "long-run" in lowered)
