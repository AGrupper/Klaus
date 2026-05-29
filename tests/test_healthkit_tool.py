"""Tests for mcp_tools/healthkit_tool.py — HealthKit nutrition normalizer.

PHASE 19.1 Plan 02 — HEALTHKIT-01, HEALTHKIT-02, HEALTHKIT-03:
- HealthKitPayload / HealthKitSample Pydantic models — wire-format parse + DoS cap
- _hour_bucket(hour) — hour-of-day → int meal_type (1..4)
- _infer_meal_type(sample) — metadata override → hour-bucket fallback
- _normalize_healthkit_sample(sample) — 9-key dict mirroring google_fit shape
- ingest_payload(payload_dict, store) — per-sample try/except + idempotent upsert

The 9-key parity contract with mcp_tools.google_fit_tool._normalize_point is
enforced explicitly (Q8 from RESEARCH.md — meal_type MUST be int).

Wave 0 (Plan 01) on-device findings drive several tests below:
- uuid arrives as the literal string "Lifesum" (HKObject UUID not exposed via
  iOS Shortcut "Get Details → Source"); normalizer must fall back to a
  deterministic synthetic source_id when uuid is empty / a known source-name.
- start_date arrives with a non-ISO-8601 "GMT+N" suffix; Pydantic must coerce.
- samples_by_type may contain extra unknown keys (e.g. DietaryFiber_g); the
  normalizer silently ignores them via .get(..., 0).
"""
from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from mcp_tools.healthkit_tool import (
    HealthKitPayload,
    HealthKitSample,
    _hour_bucket,
    _infer_meal_type,
    _normalize_healthkit_sample,
    ingest_payload,
)


_TZ = ZoneInfo("Asia/Jerusalem")


# ------------------------------------------------------------------ #
# Helper: build a canonical HealthKitSample                          #
# ------------------------------------------------------------------ #

def _make_sample(
    *,
    uuid: str = "ABC-123",
    hour: int = 13,
    minute: int = 42,
    samples_by_type: dict | None = None,
    metadata: dict | None = None,
    food_item: str | None = "Greek salad",
) -> HealthKitSample:
    return HealthKitSample(
        uuid=uuid,
        start_date=datetime(2026, 5, 28, hour, minute, tzinfo=_TZ),
        samples_by_type=samples_by_type
        or {
            "DietaryEnergyConsumed_kcal": 547.0,
            "DietaryProtein_g": 35.2,
            "DietaryCarbohydrates_g": 62.1,
            "DietaryFatTotal_g": 18.4,
        },
        metadata=metadata or {},
        food_item=food_item,
    )


# ------------------------------------------------------------------ #
# _normalize_healthkit_sample — 9-key shape parity                   #
# ------------------------------------------------------------------ #

def test_normalize_shape_matches_google_fit():
    """The output dict carries the same 9 keys as google_fit_tool._normalize_point."""
    sample = _make_sample()
    result = _normalize_healthkit_sample(sample)
    assert set(result.keys()) == {
        "source_id",
        "timestamp",
        "meal_type",
        "calories",
        "protein_g",
        "carbs_g",
        "fat_g",
        "food_item",
        "source",
    }
    assert result["source"] == "healthkit"
    assert result["calories"] == 547.0
    assert result["protein_g"] == 35.2
    assert result["carbs_g"] == 62.1
    assert result["fat_g"] == 18.4
    assert result["food_item"] == "Greek salad"


def test_meal_type_is_int_not_string():
    """RESEARCH.md Q8 contract: meal_type is int 1..4 in every code path."""
    sample = _make_sample()
    result = _normalize_healthkit_sample(sample)
    assert isinstance(result["meal_type"], int)
    assert 1 <= result["meal_type"] <= 4


def test_normalize_ignores_unknown_macro_keys():
    """Wave 0 finding: real-device fixture has DietaryFiber_g — normalizer silently ignores."""
    sample = _make_sample(
        samples_by_type={
            "DietaryEnergyConsumed_kcal": 1038.0,
            "DietaryProtein_g": 70.0,
            "DietaryCarbohydrates_g": 109.0,
            "DietaryFatTotal_g": 38.0,
            "DietaryFiber_g": 5.6,  # extra key — must NOT raise
        }
    )
    result = _normalize_healthkit_sample(sample)
    assert result["calories"] == 1038.0
    assert result["fat_g"] == 38.0


def test_normalize_missing_macro_keys_defaults_to_zero():
    """Missing macros use 0 default per CONTEXT.md <specifics>."""
    sample = _make_sample(samples_by_type={"DietaryEnergyConsumed_kcal": 100.0})
    result = _normalize_healthkit_sample(sample)
    assert result["calories"] == 100.0
    assert result["protein_g"] == 0
    assert result["carbs_g"] == 0
    assert result["fat_g"] == 0


# ------------------------------------------------------------------ #
# _hour_bucket                                                       #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("hour", list(range(0, 24)))
def test_hour_bucket_returns_int(hour: int):
    """Hour bucket returns int 1..4 for any hour-of-day."""
    bucket = _hour_bucket(hour)
    assert isinstance(bucket, int)
    assert bucket in {1, 2, 3, 4}


@pytest.mark.parametrize(
    "hour, expected",
    [
        (5, 1), (8, 1), (10, 1),         # breakfast band 5..10
        (11, 2), (13, 2), (14, 2),       # lunch band 11..14
        (15, 4), (16, 4),                # gap → snack
        (17, 3), (19, 3), (21, 3),       # dinner band 17..21
        (22, 4), (0, 4), (4, 4),         # else → snack
    ],
)
def test_hour_bucket_boundary_mapping(hour: int, expected: int):
    """Boundary mapping per CONTEXT.md D-13."""
    assert _hour_bucket(hour) == expected


# ------------------------------------------------------------------ #
# Metadata override + hour-bucket fallback                            #
# ------------------------------------------------------------------ #

def test_metadata_override_takes_precedence():
    """HKMetadataKeyMealTime=3 (dinner) wins over hour=8 (would bucket to breakfast)."""
    sample = _make_sample(
        hour=8,  # would hour-bucket to 1 (breakfast)
        metadata={"HKMetadataKeyMealTime": 3},
    )
    result = _normalize_healthkit_sample(sample)
    assert result["meal_type"] == 3


def test_metadata_unknown_value_falls_back_to_bucket():
    """An unparseable metadata value falls back to hour bucket."""
    sample = _make_sample(
        hour=8,
        metadata={"HKMetadataKeyMealTime": "weird"},
    )
    result = _normalize_healthkit_sample(sample)
    assert result["meal_type"] == 1  # 8h → breakfast


def test_metadata_string_breakfast_maps_to_one():
    """String-form 'Breakfast' is recognised + mapped to int 1."""
    sample = _make_sample(
        hour=15,  # would bucket to snack
        metadata={"HKMetadataKeyMealTime": "Breakfast"},
    )
    result = _normalize_healthkit_sample(sample)
    assert result["meal_type"] == 1


def test_metadata_absent_uses_hour_bucket():
    """Wave 0 confirmed Lifesum does NOT write metadata — hour-bucket is the primary path."""
    sample = _make_sample(hour=13, metadata={})
    result = _normalize_healthkit_sample(sample)
    assert result["meal_type"] == 2  # 13h → lunch


# ------------------------------------------------------------------ #
# String-numeric coercion (Q1 from RESEARCH.md)                       #
# ------------------------------------------------------------------ #

def test_string_numerics_coerce():
    """iOS Shortcuts often emits numerics as strings — field_validator coerces."""
    payload = {
        "samples": [
            {
                "uuid": "STR-NUM",
                "start_date": "2026-05-28T13:42:00+03:00",
                "samples_by_type": {
                    "DietaryEnergyConsumed_kcal": "547",
                    "DietaryProtein_g": "35.2",
                    "DietaryCarbohydrates_g": "62.1",
                    "DietaryFatTotal_g": "18.4",
                },
            }
        ]
    }
    parsed = HealthKitPayload.model_validate(payload)
    sample = parsed.samples[0]
    assert isinstance(sample.samples_by_type["DietaryEnergyConsumed_kcal"], float)
    assert sample.samples_by_type["DietaryEnergyConsumed_kcal"] == 547.0
    result = _normalize_healthkit_sample(sample)
    assert result["calories"] == 547.0
    assert isinstance(result["calories"], float)


def test_string_numerics_drop_non_coercible():
    """Non-coercible values are dropped with a warning, not raised."""
    payload = {
        "samples": [
            {
                "uuid": "PARTIAL",
                "start_date": "2026-05-28T13:42:00+03:00",
                "samples_by_type": {
                    "DietaryEnergyConsumed_kcal": "547",
                    "DietaryProtein_g": "garbage",
                },
            }
        ]
    }
    parsed = HealthKitPayload.model_validate(payload)
    sample = parsed.samples[0]
    assert sample.samples_by_type["DietaryEnergyConsumed_kcal"] == 547.0
    assert "DietaryProtein_g" not in sample.samples_by_type


# ------------------------------------------------------------------ #
# Wave 0 start_date GMT+N parsing                                    #
# ------------------------------------------------------------------ #

def test_start_date_gmt_plus_n_parses():
    """Wave 0: real-device start_date arrives as '2026-05-29T07:30:00GMT+3'.
    Plan 02 must accept that format and a normal ISO 8601 +03:00 form alike."""
    p1 = HealthKitPayload.model_validate(
        {"samples": [{
            "uuid": "GMT-TEST-1",
            "start_date": "2026-05-29T07:30:00GMT+3",
            "samples_by_type": {"DietaryEnergyConsumed_kcal": 100.0},
        }]}
    )
    p2 = HealthKitPayload.model_validate(
        {"samples": [{
            "uuid": "GMT-TEST-2",
            "start_date": "2026-05-29T07:30:00+03:00",
            "samples_by_type": {"DietaryEnergyConsumed_kcal": 100.0},
        }]}
    )
    # Both must parse to the same UTC instant.
    assert p1.samples[0].start_date == p2.samples[0].start_date


# ------------------------------------------------------------------ #
# source_id namespace + Wave 0 Lifesum fallback                       #
# ------------------------------------------------------------------ #

def test_source_id_namespace():
    """source_id is namespaced 'healthkit:{uuid}' and does NOT collide with google_fit."""
    sample = _make_sample(uuid="ABC-123")
    result = _normalize_healthkit_sample(sample)
    assert result["source_id"].startswith("healthkit:")
    assert result["source_id"].endswith("ABC-123")
    assert not result["source_id"].startswith("google_fit:")


def test_source_id_falls_back_when_uuid_is_lifesum():
    """Wave 0 finding: iOS Shortcut 'Get Details → Source' returns the source-app
    name string ('Lifesum'), NOT the HKObject UUID. Without a fallback, every
    sample would collapse to source_id='healthkit:Lifesum' and dedup would break.
    Normalizer must synthesize source_id = 'healthkit:{start_date_iso}:{calories_int}'."""
    sample = _make_sample(
        uuid="Lifesum",
        hour=7,
        minute=30,
        samples_by_type={
            "DietaryEnergyConsumed_kcal": 1038.0,
            "DietaryProtein_g": 70.0,
            "DietaryCarbohydrates_g": 109.0,
            "DietaryFatTotal_g": 38.0,
        },
    )
    result = _normalize_healthkit_sample(sample)
    assert result["source_id"].startswith("healthkit:")
    # The fallback must NOT be the bare "healthkit:Lifesum" (which would collide).
    assert result["source_id"] != "healthkit:Lifesum"
    # Must encode start_date AND calories so each meal is unique.
    assert "1038" in result["source_id"]


def test_source_id_falls_back_when_uuid_empty():
    """Empty uuid → deterministic fallback (Wave 0 operator decision)."""
    sample = _make_sample(uuid="")
    result = _normalize_healthkit_sample(sample)
    assert result["source_id"].startswith("healthkit:")
    assert result["source_id"] != "healthkit:"


# ------------------------------------------------------------------ #
# Pydantic DoS cap                                                   #
# ------------------------------------------------------------------ #

def test_pydantic_caps_samples_at_200():
    """RESEARCH.md threat row: a payload with 201 samples raises ValidationError."""
    payload = {
        "samples": [
            {
                "uuid": f"S-{i}",
                "start_date": "2026-05-28T13:42:00+03:00",
                "samples_by_type": {"DietaryEnergyConsumed_kcal": 100.0},
            }
            for i in range(201)
        ]
    }
    with pytest.raises(ValidationError):
        HealthKitPayload.model_validate(payload)


# ------------------------------------------------------------------ #
# ingest_payload — per-sample try/except + store glue                #
# ------------------------------------------------------------------ #

def test_ingest_payload_per_item_try_except():
    """Pattern C: one bad sample is logged + skipped; the rest still upsert."""
    payload = {
        "samples": [
            {
                "uuid": f"S-{i}",
                "start_date": "2026-05-28T13:42:00+03:00",
                "samples_by_type": {"DietaryEnergyConsumed_kcal": 100.0 * (i + 1)},
            }
            for i in range(3)
        ]
    }
    store = MagicMock()

    real_normalize = _normalize_healthkit_sample
    call_count = {"n": 0}

    def _flaky_normalize(sample):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated normalize failure")
        return real_normalize(sample)

    with patch(
        "mcp_tools.healthkit_tool._normalize_healthkit_sample",
        side_effect=_flaky_normalize,
    ):
        result = ingest_payload(payload, store)

    assert result == {"upserted_count": 2, "errored_count": 1}
    assert store.upsert.call_count == 2


def test_ingest_payload_real_fixture_smoke():
    """Smoke-test ingest_payload against the real Wave 0 fixture."""
    with open("tests/fixtures/healthkit_payload_sample.json") as f:
        data = json.load(f)
    store = MagicMock()
    result = ingest_payload(data, store)
    assert result["upserted_count"] == len(data["samples"])
    assert store.upsert.call_count == len(data["samples"])


def test_ingest_payload_validation_error_propagates():
    """Malformed payload (e.g. missing 'samples' key) raises ValidationError."""
    store = MagicMock()
    with pytest.raises(ValidationError):
        ingest_payload({"not_samples": []}, store)
    assert store.upsert.call_count == 0


def test_ingest_payload_upsert_called_with_source_id_kw():
    """ingest_payload calls store.upsert(source_id=..., meal=...) — keyword form."""
    payload = {
        "samples": [
            {
                "uuid": "KW-TEST",
                "start_date": "2026-05-28T13:42:00+03:00",
                "samples_by_type": {"DietaryEnergyConsumed_kcal": 100.0},
            }
        ]
    }
    store = MagicMock()
    ingest_payload(payload, store)
    call_kwargs = store.upsert.call_args.kwargs
    assert "source_id" in call_kwargs
    assert "meal" in call_kwargs
    assert call_kwargs["source_id"].startswith("healthkit:")
    assert call_kwargs["meal"]["source"] == "healthkit"
