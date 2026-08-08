"""Compact life snapshot contract shared by MCP and the Hub."""
from __future__ import annotations

import asyncio
import json


def test_snapshot_uses_normalized_today_state_and_provider_neutral_context():
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

    snapshot = asyncio.run(
        build_life_snapshot(
            today_loader=today_loader,
            dispatcher=dispatcher,
            directives_loader=lambda: [{"id": "d1", "text": "No morning noise"}],
            reviews_loader=lambda day: {"morning": {"target_date": day}},
        )
    )

    assert snapshot["schema_version"] == "klaus.life-snapshot.v1"
    assert snapshot["today"]["calendar"]["timed"][0]["id"] == "e1"
    assert snapshot["tasks"][0]["id"] == "t1"
    assert snapshot["habits_pending"][0]["id"] == "h1"
    assert snapshot["memory"]["authoritative_store"] == "pinecone"
    assert snapshot["directives"][0]["id"] == "d1"
