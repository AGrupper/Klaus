"""Tests for mcp_tools/healthkit_tool.py — HealthKit nutrition normalizer.

PHASE 19.1 Plan 02 — HEALTHKIT-01, HEALTHKIT-02, HEALTHKIT-03; PATH B (live UAT
revision 2026-05-30):

- HealthKitPayload / HealthKitQuantitySample Pydantic models — FLAT wire format
  (one HKQuantitySample per (food_item × macro_type), per CONTEXT.md D-15 v2)
- _aggregate_quantity_samples — group flat samples by (start_date, food_item)
  and sum same-quantity-type values per group → emit per-meal dicts
- _hour_bucket(hour) — hour-of-day → int meal_type (1..4)
- _infer_meal_type(meal_dict) — metadata override → hour-bucket fallback
- _normalize_healthkit_sample(meal_dict) — canonical 9-key MealStore meal shape
- ingest_payload(payload_dict, store) — aggregate → normalize → idempotent upsert,
  with Pattern C per-item try/except so one bad meal doesn't drop the batch.

The 9-key MealStore shape contract is enforced explicitly
(Q8 from RESEARCH.md — meal_type MUST be int).

Wave 0 (Plan 01) on-device findings drive several tests below:
- uuid arrives as the literal string "Lifesum" (HKObject UUID not exposed via
  iOS Shortcut "Get Details → Source"); normalizer must fall back to a
  deterministic synthetic source_id when uuid is empty / a known source-name.
- start_date arrives with a non-ISO-8601 "GMT+N" suffix; Pydantic must coerce.
- samples_by_type may contain extra unknown keys (e.g. DietaryFiber_g); the
  normalizer silently ignores them via .get(..., 0).

Path B addition: live UAT (2026-05-30) revealed that Lifesum writes ONE
HKQuantitySample per macro PER FOOD ITEM. A meal with 3 food items writes
3 Energy samples + 3 Protein samples + … and iOS Shortcuts cannot reach the
HKCorrelation parent UUID to bundle them client-side. The server-side
aggregator groups by (start_date, food_item) and sums same-quantity-type
values inside each group.
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
    HealthKitQuantitySample,
    _aggregate_quantity_samples,
    _hour_bucket,
    _infer_meal_type,
    _normalize_healthkit_sample,
    ingest_payload,
)


_TZ = ZoneInfo("Asia/Jerusalem")


# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #

def _make_meal_dict(
    *,
    uuid: str = "ABC-123",
    hour: int = 13,
    minute: int = 42,
    samples_by_type: dict | None = None,
    metadata: dict | None = None,
    food_item: str | None = "Greek salad",
) -> dict:
    """Build a per-meal dict in the shape emitted by _aggregate_quantity_samples.

    This is what the normalizer consumes — the aggregator's output, NOT a
    Pydantic instance. Mirrors the legacy bundled-shape exactly so the rest
    of the pipeline (normalize → upsert) is unaffected by the contract change.
    """
    return {
        "uuid": uuid,
        "start_date": datetime(2026, 5, 28, hour, minute, tzinfo=_TZ),
        "samples_by_type": samples_by_type
        or {
            "DietaryEnergyConsumed_kcal": 547.0,
            "DietaryProtein_g": 35.2,
            "DietaryCarbohydrates_g": 62.1,
            "DietaryFatTotal_g": 18.4,
        },
        "metadata": metadata or {},
        "food_item": food_item,
    }


def _make_quantity_sample(
    *,
    uuid: str = "Lifesum",
    start_date: datetime | None = None,
    quantity_type: str = "DietaryEnergyConsumed_kcal",
    value: float = 547.0,
    metadata: dict | None = None,
    food_item: str | None = None,
) -> HealthKitQuantitySample:
    """Build a flat HealthKitQuantitySample (Path B wire format)."""
    return HealthKitQuantitySample(
        uuid=uuid,
        start_date=start_date or datetime(2026, 5, 28, 13, 42, tzinfo=_TZ),
        quantity_type=quantity_type,
        value=value,
        metadata=metadata or {},
        food_item=food_item,
    )


# ------------------------------------------------------------------ #
# _normalize_healthkit_sample — 9-key shape parity                   #
# ------------------------------------------------------------------ #

def test_normalize_shape_matches_mealstore_contract():
    """The output dict carries the canonical 9 keys MealStore consumes."""
    meal = _make_meal_dict()
    result = _normalize_healthkit_sample(meal)
    assert set(result.keys()) == {
        "source_id",
        "timestamp",
        "meal_type",
        "calories",
        "protein_g",
        "carbs_g",
        "fat_g",
        "fiber_g",
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
    meal = _make_meal_dict()
    result = _normalize_healthkit_sample(meal)
    assert isinstance(result["meal_type"], int)
    assert 1 <= result["meal_type"] <= 4


def test_normalize_captures_fiber_and_ignores_other_unknown_keys():
    """Phase 19.2: DietaryFiber_g is now threaded to fiber_g; other unknowns ignored."""
    meal = _make_meal_dict(
        samples_by_type={
            "DietaryEnergyConsumed_kcal": 1038.0,
            "DietaryProtein_g": 70.0,
            "DietaryCarbohydrates_g": 109.0,
            "DietaryFatTotal_g": 38.0,
            "DietaryFiber_g": 5.6,       # Phase 19.2 — now captured
            "DietarySugar_g": 12.0,      # still-unknown key — must be ignored
        }
    )
    result = _normalize_healthkit_sample(meal)
    assert result["calories"] == 1038.0
    assert result["fat_g"] == 38.0
    assert result["fiber_g"] == 5.6
    assert "DietarySugar_g" not in result  # genuinely unknown key dropped


def test_normalize_missing_macro_keys_defaults_to_zero():
    """Missing macros (incl. fiber) use 0 default per CONTEXT.md <specifics>."""
    meal = _make_meal_dict(samples_by_type={"DietaryEnergyConsumed_kcal": 100.0})
    result = _normalize_healthkit_sample(meal)
    assert result["calories"] == 100.0
    assert result["protein_g"] == 0
    assert result["carbs_g"] == 0
    assert result["fat_g"] == 0
    assert result["fiber_g"] == 0


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
    meal = _make_meal_dict(
        hour=8,
        metadata={"HKMetadataKeyMealTime": 3},
    )
    result = _normalize_healthkit_sample(meal)
    assert result["meal_type"] == 3


def test_metadata_unknown_value_falls_back_to_bucket():
    """An unparseable metadata value falls back to hour bucket."""
    meal = _make_meal_dict(
        hour=8,
        metadata={"HKMetadataKeyMealTime": "weird"},
    )
    result = _normalize_healthkit_sample(meal)
    assert result["meal_type"] == 1  # 8h → breakfast


def test_metadata_string_breakfast_maps_to_one():
    """String-form 'Breakfast' is recognised + mapped to int 1."""
    meal = _make_meal_dict(
        hour=15,
        metadata={"HKMetadataKeyMealTime": "Breakfast"},
    )
    result = _normalize_healthkit_sample(meal)
    assert result["meal_type"] == 1


def test_metadata_absent_uses_hour_bucket():
    """Wave 0 confirmed Lifesum does NOT write metadata — hour-bucket is the primary path."""
    meal = _make_meal_dict(hour=13, metadata={})
    result = _normalize_healthkit_sample(meal)
    assert result["meal_type"] == 2  # 13h → lunch


# ------------------------------------------------------------------ #
# Flat wire format — Pydantic model + validators                      #
# ------------------------------------------------------------------ #

def test_flat_payload_parses_canonical_shape():
    """A flat payload with the 4 required fields parses cleanly."""
    payload = {
        "samples": [
            {
                "uuid": "FLAT-1",
                "start_date": "2026-05-28T13:42:00+03:00",
                "quantity_type": "DietaryEnergyConsumed_kcal",
                "value": 547.0,
            }
        ]
    }
    parsed = HealthKitPayload.model_validate(payload)
    assert len(parsed.samples) == 1
    s = parsed.samples[0]
    assert s.quantity_type == "DietaryEnergyConsumed_kcal"
    assert s.value == 547.0
    assert s.metadata == {}
    assert s.food_item is None


def test_flat_payload_string_value_coerces_to_float():
    """iOS Shortcuts often emits numerics as strings — value field_validator coerces."""
    payload = {
        "samples": [
            {
                "uuid": "STR-NUM",
                "start_date": "2026-05-28T13:42:00+03:00",
                "quantity_type": "DietaryProtein_g",
                "value": "35.2",
            }
        ]
    }
    parsed = HealthKitPayload.model_validate(payload)
    s = parsed.samples[0]
    assert isinstance(s.value, float)
    assert s.value == 35.2


def test_flat_payload_non_coercible_value_raises():
    """A garbage value field raises ValidationError (whereas in the legacy
    bundled shape an unparseable inner-dict entry was silently dropped). With
    one-sample-per-value the per-sample try/except in ingest_payload catches it
    so the batch isn't dropped — but the model itself rejects the row."""
    payload = {
        "samples": [
            {
                "uuid": "BAD-NUM",
                "start_date": "2026-05-28T13:42:00+03:00",
                "quantity_type": "DietaryProtein_g",
                "value": "garbage",
            }
        ]
    }
    with pytest.raises(ValidationError):
        HealthKitPayload.model_validate(payload)


def test_flat_payload_gmt_offset_normalized():
    """The start_date validator accepts the Wave-0 'GMT+N' suffix."""
    p1 = HealthKitPayload.model_validate(
        {"samples": [{
            "uuid": "GMT-A",
            "start_date": "2026-05-29T07:30:00GMT+3",
            "quantity_type": "DietaryEnergyConsumed_kcal",
            "value": 100.0,
        }]}
    )
    p2 = HealthKitPayload.model_validate(
        {"samples": [{
            "uuid": "GMT-B",
            "start_date": "2026-05-29T07:30:00+03:00",
            "quantity_type": "DietaryEnergyConsumed_kcal",
            "value": 100.0,
        }]}
    )
    assert p1.samples[0].start_date == p2.samples[0].start_date


def test_flat_payload_naive_datetime_becomes_jerusalem_aware():
    """WR-02: an ISO start_date with NO offset parses to an Asia/Jerusalem-aware
    datetime (not naive), so meal-type bucketing and the synthetic source_id are
    computed against the intended wall clock and stay idempotent."""
    parsed = HealthKitPayload.model_validate(
        {"samples": [{
            "uuid": "NAIVE-1",
            "start_date": "2026-05-28T13:42:00",
            "quantity_type": "DietaryEnergyConsumed_kcal",
            "value": 100.0,
        }]}
    )
    sd = parsed.samples[0].start_date
    assert sd.tzinfo is not None
    assert sd.utcoffset() == datetime(2026, 5, 28, 13, 42, tzinfo=_TZ).utcoffset()


def test_naive_and_aware_same_instant_yield_same_source_id():
    """WR-02: the naive form and the explicit +03:00 form of the same Jerusalem
    instant must aggregate identically and produce the same source_id, so the
    2h-close push and the 23:55 catch-up push collapse to one Firestore doc."""
    naive = HealthKitPayload.model_validate(
        {"samples": [{"uuid": "Lifesum", "start_date": "2026-05-28T13:42:00",
                      "quantity_type": "DietaryEnergyConsumed_kcal", "value": 100.0,
                      "food_item": "Toast"}]}
    )
    aware = HealthKitPayload.model_validate(
        {"samples": [{"uuid": "Lifesum", "start_date": "2026-05-28T13:42:00+03:00",
                      "quantity_type": "DietaryEnergyConsumed_kcal", "value": 100.0,
                      "food_item": "Toast"}]}
    )
    g_naive = _aggregate_quantity_samples(naive.samples)[0]
    g_aware = _aggregate_quantity_samples(aware.samples)[0]
    assert (
        _normalize_healthkit_sample(g_naive)["source_id"]
        == _normalize_healthkit_sample(g_aware)["source_id"]
    )


def test_flat_payload_caps_samples_at_1000():
    """A meal with 5 food items × 5 macros = 25 samples; 200 was too tight.
    The Path B DoS cap moves to 1000 — still cheap to validate, comfortably
    above any realistic day's fan-out."""
    payload = {
        "samples": [
            {
                "uuid": f"S-{i}",
                "start_date": "2026-05-28T13:42:00+03:00",
                "quantity_type": "DietaryEnergyConsumed_kcal",
                "value": 100.0,
            }
            for i in range(1001)
        ]
    }
    with pytest.raises(ValidationError):
        HealthKitPayload.model_validate(payload)


# ------------------------------------------------------------------ #
# _aggregate_quantity_samples — Path B server-side grouping           #
# ------------------------------------------------------------------ #

def test_aggregate_groups_five_macros_at_same_timestamp_into_one_meal():
    """The canonical case: Lifesum writes 5 macros for a single-item meal at
    one start_date → aggregator produces ONE meal dict with all 5 in
    samples_by_type."""
    ts = datetime(2026, 5, 29, 20, 0, tzinfo=_TZ)
    samples = [
        _make_quantity_sample(start_date=ts, quantity_type="DietaryEnergyConsumed_kcal", value=324.0),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryProtein_g", value=5.4),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryCarbohydrates_g", value=43.2),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryFatTotal_g", value=14.4),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryFiber_g", value=2.4),
    ]
    groups = _aggregate_quantity_samples(samples)
    assert len(groups) == 1
    g = groups[0]
    assert g["samples_by_type"]["DietaryEnergyConsumed_kcal"] == 324.0
    assert g["samples_by_type"]["DietaryProtein_g"] == 5.4
    assert g["samples_by_type"]["DietaryCarbohydrates_g"] == 43.2
    assert g["samples_by_type"]["DietaryFatTotal_g"] == 14.4
    assert g["samples_by_type"]["DietaryFiber_g"] == 2.4
    assert g["food_item"] is None
    assert g["start_date"] == ts


def test_aggregate_sums_duplicate_quantity_types_within_group():
    """Lifesum fan-out: a 3-food-item meal with no food_item label writes 3
    Energy samples at the same start_date. Aggregator must SUM them within
    the (start_date, None) group, not just take the last value."""
    ts = datetime(2026, 5, 29, 20, 0, tzinfo=_TZ)
    samples = [
        _make_quantity_sample(start_date=ts, quantity_type="DietaryEnergyConsumed_kcal", value=100.0),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryEnergyConsumed_kcal", value=124.0),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryEnergyConsumed_kcal", value=100.0),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryProtein_g", value=2.0),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryProtein_g", value=1.4),
        _make_quantity_sample(start_date=ts, quantity_type="DietaryProtein_g", value=2.0),
    ]
    groups = _aggregate_quantity_samples(samples)
    assert len(groups) == 1
    g = groups[0]
    assert g["samples_by_type"]["DietaryEnergyConsumed_kcal"] == 324.0
    assert g["samples_by_type"]["DietaryProtein_g"] == 5.4


def test_aggregate_separates_groups_by_start_date():
    """Two meals at different timestamps → two distinct groups."""
    ts_a = datetime(2026, 5, 29, 7, 30, tzinfo=_TZ)
    ts_b = datetime(2026, 5, 29, 20, 0, tzinfo=_TZ)
    samples = [
        _make_quantity_sample(start_date=ts_a, quantity_type="DietaryEnergyConsumed_kcal", value=500.0),
        _make_quantity_sample(start_date=ts_a, quantity_type="DietaryProtein_g", value=20.0),
        _make_quantity_sample(start_date=ts_b, quantity_type="DietaryEnergyConsumed_kcal", value=324.0),
        _make_quantity_sample(start_date=ts_b, quantity_type="DietaryProtein_g", value=5.4),
    ]
    groups = _aggregate_quantity_samples(samples)
    assert len(groups) == 2
    by_start = {g["start_date"]: g for g in groups}
    assert by_start[ts_a]["samples_by_type"]["DietaryEnergyConsumed_kcal"] == 500.0
    assert by_start[ts_b]["samples_by_type"]["DietaryEnergyConsumed_kcal"] == 324.0


def test_aggregate_separates_groups_by_food_item_at_same_timestamp():
    """Two distinct food_item labels at the same timestamp → two groups
    (operator could log e.g. 'Apple' and 'Banana' as snacks at the same minute)."""
    ts = datetime(2026, 5, 29, 15, 0, tzinfo=_TZ)
    samples = [
        _make_quantity_sample(start_date=ts, food_item="Apple", quantity_type="DietaryEnergyConsumed_kcal", value=95.0),
        _make_quantity_sample(start_date=ts, food_item="Apple", quantity_type="DietaryCarbohydrates_g", value=25.0),
        _make_quantity_sample(start_date=ts, food_item="Banana", quantity_type="DietaryEnergyConsumed_kcal", value=105.0),
        _make_quantity_sample(start_date=ts, food_item="Banana", quantity_type="DietaryCarbohydrates_g", value=27.0),
    ]
    groups = _aggregate_quantity_samples(samples)
    assert len(groups) == 2
    by_food = {g["food_item"]: g for g in groups}
    assert by_food["Apple"]["samples_by_type"]["DietaryEnergyConsumed_kcal"] == 95.0
    assert by_food["Banana"]["samples_by_type"]["DietaryEnergyConsumed_kcal"] == 105.0


def test_aggregate_real_fixture_values():
    """End-to-end: the 5-flat-sample fixture (operator's real 20:00 meal)
    aggregates into exactly one meal dict with the operator's true totals."""
    with open("tests/fixtures/healthkit_payload_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    payload = HealthKitPayload.model_validate(data)
    groups = _aggregate_quantity_samples(payload.samples)
    assert len(groups) == 1
    g = groups[0]
    assert g["samples_by_type"]["DietaryEnergyConsumed_kcal"] == 324.0
    assert g["samples_by_type"]["DietaryProtein_g"] == 5.4
    assert g["samples_by_type"]["DietaryCarbohydrates_g"] == 43.2
    assert g["samples_by_type"]["DietaryFatTotal_g"] == 14.4
    assert g["samples_by_type"]["DietaryFiber_g"] == 2.4


# ------------------------------------------------------------------ #
# source_id namespace + Wave 0 Lifesum fallback                       #
# ------------------------------------------------------------------ #

def test_source_id_namespace():
    """source_id is namespaced 'healthkit:{uuid}' and does NOT collide with google_fit."""
    meal = _make_meal_dict(uuid="ABC-123")
    result = _normalize_healthkit_sample(meal)
    assert result["source_id"].startswith("healthkit:")
    assert result["source_id"].endswith("ABC-123")
    assert not result["source_id"].startswith("google_fit:")


def test_source_id_falls_back_when_uuid_is_lifesum():
    """Wave 0 finding: iOS Shortcut 'Get Details → Source' returns the source-app
    name string ('Lifesum'), NOT the HKObject UUID. Without a fallback, every
    sample would collapse to source_id='healthkit:Lifesum' and dedup would break.
    Normalizer synthesizes source_id = 'healthkit:{start_date_iso}:{food_item}'
    (mirrors the aggregator's grouping key). Calories are NOT in the key — see
    test_source_id_stable_across_resync_when_calories_change."""
    meal = _make_meal_dict(
        uuid="Lifesum",
        hour=7,
        minute=30,
        food_item="Oatmeal",
        samples_by_type={
            "DietaryEnergyConsumed_kcal": 1038.0,
            "DietaryProtein_g": 70.0,
            "DietaryCarbohydrates_g": 109.0,
            "DietaryFatTotal_g": 38.0,
        },
    )
    result = _normalize_healthkit_sample(meal)
    assert result["source_id"].startswith("healthkit:")
    assert result["source_id"] != "healthkit:Lifesum"
    assert "Oatmeal" in result["source_id"]
    # calories must NOT appear in the key (the re-sync duplication bug)
    assert "1038" not in result["source_id"]


def test_source_id_stable_across_resync_when_calories_change():
    """2026-06-09 regression guard: the iOS Shortcut re-sends a meal-time on every
    Lifesum close, and its calorie total drifts between syncs (incremental logging,
    edits, rounding). The synthetic source_id must depend ONLY on identity
    (start_date, food_item) — NOT calories — so re-syncs land on the SAME doc and
    overwrite (merge=True) instead of piling up as duplicates that double totals.
    """
    base = dict(uuid="Lifesum", hour=12, minute=0, food_item=None)
    partial = _make_meal_dict(
        **base, samples_by_type={"DietaryEnergyConsumed_kcal": 1177.0,
                                 "DietaryProtein_g": 94.0},
    )
    fuller = _make_meal_dict(
        **base, samples_by_type={"DietaryEnergyConsumed_kcal": 1180.0,
                                 "DietaryProtein_g": 94.0},
    )
    sid_partial = _normalize_healthkit_sample(partial)["source_id"]
    sid_fuller = _normalize_healthkit_sample(fuller)["source_id"]
    assert sid_partial == sid_fuller, (
        "re-sync of the same meal-time with a different calorie total must reuse "
        "the same source_id so it overwrites rather than duplicates"
    )


def test_source_id_fallback_includes_food_item_to_avoid_collision():
    """CR-01 regression: two meals at the SAME start_date with the SAME integer
    calories but DIFFERENT food_item, both reporting uuid='Lifesum', must produce
    TWO distinct source_ids. Before the fix the synthetic key was only
    (start_date, calories), so both collapsed to one Firestore doc and one meal
    was silently lost on upsert (merge=True)."""
    common = {
        "DietaryEnergyConsumed_kcal": 95.0,
        "DietaryCarbohydrates_g": 25.0,
    }
    apple = _make_meal_dict(
        uuid="Lifesum", hour=15, minute=0, food_item="Apple",
        samples_by_type=dict(common),
    )
    banana = _make_meal_dict(
        uuid="Lifesum", hour=15, minute=0, food_item="Banana",
        samples_by_type=dict(common),
    )
    sid_apple = _normalize_healthkit_sample(apple)["source_id"]
    sid_banana = _normalize_healthkit_sample(banana)["source_id"]
    assert sid_apple != sid_banana
    # Both upsert under their own key — no silent merge/loss.
    store = MagicMock()
    store.upsert(source_id=sid_apple, meal=apple)
    store.upsert(source_id=sid_banana, meal=banana)
    assert store.upsert.call_count == 2


def test_source_id_falls_back_when_uuid_empty():
    """Empty uuid → deterministic fallback (Wave 0 operator decision)."""
    meal = _make_meal_dict(uuid="")
    result = _normalize_healthkit_sample(meal)
    assert result["source_id"].startswith("healthkit:")
    assert result["source_id"] != "healthkit:"


def test_source_id_sanitizes_slash_in_primary_uuid():
    """WR-01: a uuid containing '/' must NOT leak into the Firestore document
    path (a '/' would write into an unexpected subcollection). _compute_source_id
    replaces '/' with '_'."""
    meal = _make_meal_dict(uuid="a/b/c")
    result = _normalize_healthkit_sample(meal)
    assert "/" not in result["source_id"]
    assert result["source_id"] == "healthkit:a_b_c"


def test_source_id_strips_whitespace_for_idempotency():
    """WR-01: 'ABC ' and 'ABC' (a trailing-space variant across two pushes) must
    map to the SAME source_id so idempotency is preserved."""
    sid_padded = _normalize_healthkit_sample(_make_meal_dict(uuid="ABC "))["source_id"]
    sid_clean = _normalize_healthkit_sample(_make_meal_dict(uuid="ABC"))["source_id"]
    assert sid_padded == sid_clean == "healthkit:ABC"


def test_uuid_over_max_length_rejected_by_model():
    """WR-01: the Pydantic model bounds uuid length (defense-in-depth against an
    over-long Firestore document ID)."""
    payload = {
        "samples": [
            {
                "uuid": "x" * 2000,
                "start_date": "2026-05-28T13:42:00+03:00",
                "quantity_type": "DietaryEnergyConsumed_kcal",
                "value": 100.0,
            }
        ]
    }
    with pytest.raises(ValidationError):
        HealthKitPayload.model_validate(payload)


# ------------------------------------------------------------------ #
# ingest_payload — Path B end-to-end                                  #
# ------------------------------------------------------------------ #

def test_ingest_payload_aggregates_before_upsert():
    """5 flat samples at the same start_date → ONE upsert call (not 5).
    This is the entire point of Path B."""
    payload = {
        "samples": [
            {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00+03:00",
             "quantity_type": "DietaryEnergyConsumed_kcal", "value": 324.0},
            {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00+03:00",
             "quantity_type": "DietaryProtein_g", "value": 5.4},
            {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00+03:00",
             "quantity_type": "DietaryCarbohydrates_g", "value": 43.2},
            {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00+03:00",
             "quantity_type": "DietaryFatTotal_g", "value": 14.4},
            {"uuid": "Lifesum", "start_date": "2026-05-29T20:00:00+03:00",
             "quantity_type": "DietaryFiber_g", "value": 2.4},
        ]
    }
    store = MagicMock()
    result = ingest_payload(payload, store)
    assert result == {"upserted_count": 1, "errored_count": 0}
    assert store.upsert.call_count == 1
    meal = store.upsert.call_args.kwargs["meal"]
    assert meal["calories"] == 324.0
    assert meal["protein_g"] == 5.4
    assert meal["carbs_g"] == 43.2
    assert meal["fat_g"] == 14.4
    assert meal["source"] == "healthkit"


def test_ingest_payload_per_meal_try_except():
    """Pattern C: one bad meal is logged + skipped; the rest still upsert.
    With the Path B contract the failure unit is the (start_date, food_item)
    GROUP, not the individual flat sample."""
    payload = {
        "samples": [
            # Three distinct meals (different timestamps) — 1 flat sample each
            {"uuid": "Lifesum", "start_date": "2026-05-28T07:00:00+03:00",
             "quantity_type": "DietaryEnergyConsumed_kcal", "value": 100.0},
            {"uuid": "Lifesum", "start_date": "2026-05-28T13:00:00+03:00",
             "quantity_type": "DietaryEnergyConsumed_kcal", "value": 200.0},
            {"uuid": "Lifesum", "start_date": "2026-05-28T19:00:00+03:00",
             "quantity_type": "DietaryEnergyConsumed_kcal", "value": 300.0},
        ]
    }
    store = MagicMock()

    real_normalize = _normalize_healthkit_sample
    call_count = {"n": 0}

    def _flaky_normalize(meal_dict):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated normalize failure")
        return real_normalize(meal_dict)

    with patch(
        "mcp_tools.healthkit_tool._normalize_healthkit_sample",
        side_effect=_flaky_normalize,
    ):
        result = ingest_payload(payload, store)

    assert result == {"upserted_count": 2, "errored_count": 1}
    assert store.upsert.call_count == 2


def test_ingest_payload_real_fixture_smoke():
    """Smoke-test ingest_payload against the real Path B fixture.

    The fixture is 5 flat samples at one start_date → 1 aggregated meal →
    1 upsert call."""
    with open("tests/fixtures/healthkit_payload_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    store = MagicMock()
    result = ingest_payload(data, store)
    assert result["upserted_count"] == 1
    assert store.upsert.call_count == 1


def test_ingest_payload_validation_error_propagates():
    """Malformed payload (e.g. missing 'samples' key) raises ValidationError."""
    store = MagicMock()
    with pytest.raises(ValidationError):
        ingest_payload({"not_samples": []}, store)
    assert store.upsert.call_count == 0


# ------------------------------------------------------------------ #
# reconcile_payload — nightly full-day reconcile                      #
# ------------------------------------------------------------------ #

def _kcal_sample(ts: str, value: float = 300.0, food: str | None = None) -> dict:
    return {"uuid": "Lifesum", "start_date": ts, "food_item": food,
            "quantity_type": "DietaryEnergyConsumed_kcal", "value": value}


def test_reconcile_payload_partitions_by_date():
    """Midnight-spanning 26h payload: target-date meals go through
    store.replace_day (authoritative), other-date meals get plain upserts."""
    from mcp_tools.healthkit_tool import reconcile_payload

    store = MagicMock()
    store.replace_day.return_value = {"upserted": 2, "deleted": 1, "errored": 0}
    payload = {"samples": [
        _kcal_sample("2026-07-08T13:00:00+03:00", 500.0),
        _kcal_sample("2026-07-08T20:00:00+03:00", 700.0),
        _kcal_sample("2026-07-09T00:30:00+03:00", 150.0),  # past midnight
    ]}
    result = reconcile_payload(payload, store, target_date="2026-07-08")

    # replace_day got ONLY the two target-date meals.
    (date_arg, meals_arg), _ = store.replace_day.call_args
    assert date_arg == "2026-07-08"
    assert len(meals_arg) == 2
    assert all(m["timestamp"].startswith("2026-07-08") for m in meals_arg.values())
    # The 00:30 meal was plain-upserted — never routed through replace_day.
    assert store.upsert.call_count == 1
    upsert_meal = store.upsert.call_args.kwargs["meal"]
    assert upsert_meal["timestamp"].startswith("2026-07-09")

    assert result == {
        "date": "2026-07-08", "received": 3, "kept_for_date": 2,
        "upserted": 2, "deleted": 1, "upserted_other_days": 1, "errored": 0,
    }


def test_reconcile_payload_empty_payload_never_deletes():
    """An empty sample list must never wipe the target day."""
    from mcp_tools.healthkit_tool import reconcile_payload

    store = MagicMock()
    store.replace_day.return_value = {"noop": True, "upserted": 0, "deleted": 0}
    result = reconcile_payload({"samples": []}, store, target_date="2026-07-08")
    assert result["deleted"] == 0
    assert result["received"] == 0
    assert store.upsert.call_count == 0


def test_reconcile_payload_naive_datetimes_partition_correctly():
    """Naive rows get Asia/Jerusalem attached at parse time, so the
    timestamp[:10] partition still lands them on the right date."""
    from mcp_tools.healthkit_tool import reconcile_payload

    store = MagicMock()
    store.replace_day.return_value = {"upserted": 1, "deleted": 0, "errored": 0}
    payload = {"samples": [_kcal_sample("2026-07-08T21:00:00", 400.0)]}
    result = reconcile_payload(payload, store, target_date="2026-07-08")
    (_, meals_arg), _ = store.replace_day.call_args
    assert len(meals_arg) == 1
    assert result["kept_for_date"] == 1
    assert result["upserted_other_days"] == 0


def test_reconcile_payload_validation_error_propagates():
    """Malformed payload raises ValidationError — the route turns it into 422."""
    from mcp_tools.healthkit_tool import reconcile_payload

    store = MagicMock()
    with pytest.raises(ValidationError):
        reconcile_payload({"not_samples": []}, store, target_date="2026-07-08")
    store.replace_day.assert_not_called()


def test_reconcile_payload_other_day_upsert_error_isolated():
    """A failing other-day upsert is counted, never raised."""
    from mcp_tools.healthkit_tool import reconcile_payload

    store = MagicMock()
    store.replace_day.return_value = {"upserted": 1, "deleted": 0, "errored": 0}
    store.upsert.side_effect = RuntimeError("boom")
    payload = {"samples": [
        _kcal_sample("2026-07-08T13:00:00+03:00", 500.0),
        _kcal_sample("2026-07-09T00:30:00+03:00", 150.0),
    ]}
    result = reconcile_payload(payload, store, target_date="2026-07-08")
    assert result["upserted_other_days"] == 0
    assert result["errored"] == 1


def test_ingest_payload_upsert_called_with_source_id_kw():
    """ingest_payload calls store.upsert(source_id=..., meal=...) — keyword form."""
    payload = {
        "samples": [
            {
                "uuid": "KW-TEST",
                "start_date": "2026-05-28T13:42:00+03:00",
                "quantity_type": "DietaryEnergyConsumed_kcal",
                "value": 100.0,
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
