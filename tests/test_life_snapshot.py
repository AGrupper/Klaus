"""Compact life snapshot contract shared by MCP and the Hub."""
from __future__ import annotations

import asyncio
import json

import pytest


def _build(**overrides):
    """Run build_life_snapshot with every loader injected."""
    from core.life_snapshot import build_life_snapshot

    async def today_loader():
        return {
            "today": "2026-08-08",
            "calendar": {"timed": [{"id": "e1"}], "all_day": []},
            "garmin": {"sleep_score": 84},
            "weather": {"summary": "Clear"},
            "meals": [],
            "training": {"planned": []},
            "coach_note": "Protect the morning.",
            "nutrition_totals": {"kcal": 0},
        }

    def dispatcher(name, _arguments):
        values = {
            "task_list": [{"id": "t1", "title": "Plan week"}],
            "get_habit_adherence": [{"id": "h1", "title": "Creatine"}],
            "get_self_status": {"daily_note": "steady"},
        }
        return json.dumps(values[name])

    kwargs = {
        "today_loader": today_loader,
        "dispatcher": dispatcher,
        "directives_loader": lambda: [{"id": "d1", "text": "No morning noise"}],
        "reviews_loader": lambda day: {"morning": {"target_date": day}},
    }
    kwargs.update(overrides)
    return asyncio.run(build_life_snapshot(**kwargs))


def test_snapshot_uses_normalized_today_state_and_provider_neutral_context():
    snapshot = _build(profile_loader=lambda: {"source": "docs/USER.md", "sections": {}})

    assert snapshot["schema_version"] == "klaus.life-snapshot.v2"
    assert snapshot["today"]["calendar"]["timed"][0]["id"] == "e1"
    assert snapshot["tasks"][0]["id"] == "t1"
    assert snapshot["habits_pending"][0]["id"] == "h1"
    assert snapshot["memory"]["authoritative_store"] == "pinecone"
    assert snapshot["directives"][0]["id"] == "d1"


def test_memory_block_carries_no_instruction_prose():
    """The snapshot is data. Instructions for Claude belong in the skills.

    A "rule" string telling Claude how to use memory used to ship inside this
    dict, which made a behavioural instruction arrive through a tool response
    where it could be lost or ignored.
    """
    snapshot = _build(profile_loader=lambda: {"source": "docs/USER.md", "sections": {}})

    assert set(snapshot["memory"]) == {"authoritative_store", "conversation_context"}


class TestProfileBlock:
    """Amit's durable profile rides along on every snapshot (docs/USER.md)."""

    def test_profile_is_included_and_sourced(self):
        snapshot = _build()

        assert snapshot["profile"]["source"] == "docs/USER.md"
        sections = snapshot["profile"]["sections"]
        # These are the facts every skill is entitled to assume it already has.
        for expected in ("identity", "rhythms", "footprints", "working-style"):
            assert expected in sections, f"USER.md lost its '{expected}' section"
        assert sections["identity"].strip(), "identity section is empty"

    def test_profile_carries_the_facts_skills_used_to_hoard(self):
        """Guards the regression this whole change exists to prevent.

        Each of these lived in exactly one skill, so the other three did not know
        it. If someone deletes them from USER.md without moving them somewhere
        every surface reads, this fails.
        """
        sections = _build()["profile"]["sections"]
        blob = " ".join(sections.values()).lower()

        assert "3h15m" in blob, "the real gym footprint is missing"
        assert "capture bucket" in blob, "the task-list capture-bucket fact is missing"
        assert "almost no deadlines" in blob, "the deadline-habit fact is missing"
        assert "plans tomorrow every night" in blob, "the nightly-planning fact is missing"

    def test_profile_stays_within_the_every_turn_size_budget(self):
        """USER.md ships on every single turn; it must not balloon unnoticed."""
        from core.user_profile import PROFILE_SIZE_BUDGET_BYTES, profile_block

        size = len(json.dumps(profile_block()))
        assert size <= PROFILE_SIZE_BUDGET_BYTES, (
            f"profile block is {size} bytes, over the {PROFILE_SIZE_BUDGET_BYTES} "
            "byte budget — trim USER.md or raise the budget deliberately"
        )

    def test_missing_user_md_degrades_to_empty_rather_than_failing(self, monkeypatch):
        """A missing profile makes Klaus less informed, never broken."""
        from core import doc_sections, user_profile

        user_profile.reset_cache()
        monkeypatch.setattr(doc_sections, "read_document", lambda _filename: None)
        try:
            assert user_profile.profile_block() == {
                "source": "docs/USER.md",
                "sections": {},
            }
        finally:
            user_profile.reset_cache()


class TestReadUserProfileTool:
    """read_user_profile returns one section verbatim."""

    @pytest.fixture(autouse=True)
    def _clear(self):
        from core import user_profile

        user_profile.reset_cache()
        yield
        user_profile.reset_cache()

    def test_known_section_returns_content(self):
        import core.tools as tools

        parsed = json.loads(tools.dispatch("read_user_profile", {"section": "footprints"}))
        assert "error" not in parsed
        assert parsed["section"] == "footprints"
        assert "3h15m" in parsed["content"]

    def test_free_text_matches_nearest_section(self):
        import core.tools as tools

        parsed = json.loads(tools.dispatch("read_user_profile", {"section": "scheduling"}))
        assert "error" not in parsed
        assert "Training" in parsed["content"]

    def test_path_traversal_is_not_a_lookup(self):
        """The section name is matched against authored anchors, never a path."""
        import core.tools as tools

        parsed = json.loads(
            tools.dispatch("read_user_profile", {"section": "../../etc/passwd"})
        )
        assert "error" in parsed
        assert "content" not in parsed
