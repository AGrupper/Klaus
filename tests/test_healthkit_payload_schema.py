"""Schema-lock harness for the iOS Shortcut → /cron/healthkit-sync wire format.

Locks the JSON shape captured from a real iPhone device into a regression-proof
test. Drift on either side — Shortcut changes its emitted shape, or Plan 02's
Pydantic model diverges from what the device actually sends — breaks loudly.

Pattern lineage: mirrors tests/test_evals.py:23-60 (Pitfall-6 schema lock from
Phase 18-04). The fixture itself was captured from a real iOS Shortcut POST to
webhook.site on 2026-05-29; do NOT replace it with a hand-written one.
"""
from __future__ import annotations

import json

import pytest

_FIXTURE_PATH = "tests/fixtures/healthkit_payload_sample.json"
_REQUIRED_TOP_KEYS = {"samples"}
_REQUIRED_SAMPLE_KEYS = {"uuid", "start_date", "samples_by_type"}


def _load() -> dict:
    with open(_FIXTURE_PATH) as f:
        return json.load(f)


def _sample_ids() -> list[str]:
    return [str(s.get("uuid", ""))[:8] or f"idx-{i}" for i, s in enumerate(_load()["samples"])]


class TestHealthKitFixtureSchema:
    """Validates tests/fixtures/healthkit_payload_sample.json against the locked shape."""

    def test_fixture_exists_and_loads_as_json(self):
        data = _load()
        assert isinstance(data, dict)

    def test_fixture_has_required_top_keys(self):
        missing = _REQUIRED_TOP_KEYS - _load().keys()
        assert not missing, f"missing top-level keys: {missing}"

    def test_samples_is_non_empty_list(self):
        samples = _load()["samples"]
        assert isinstance(samples, list)
        assert len(samples) > 0

    @pytest.mark.parametrize("idx", range(len(_load()["samples"])), ids=_sample_ids())
    def test_each_sample_has_required_keys(self, idx):
        sample = _load()["samples"][idx]
        missing = _REQUIRED_SAMPLE_KEYS - sample.keys()
        assert not missing, f"sample {idx}: missing keys {missing}"

    def test_fixture_loads_via_pydantic_model(self):
        """Turns GREEN once Plan 19.1-02 lands HealthKitPayload."""
        pytest.importorskip("mcp_tools.healthkit_tool")
        from mcp_tools.healthkit_tool import HealthKitPayload  # type: ignore[import-not-found]

        HealthKitPayload.model_validate(_load())
