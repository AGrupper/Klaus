"""HealthKit Nutrition tool — Lifesum-on-iOS-sourced meal sync.

Pipeline:
    Lifesum (iOS) → Apple HealthKit → iOS Shortcut (Personal Automation
    on Lifesum close) → POST /cron/healthkit-sync → HealthKitPayload
    Pydantic parse → _normalize_healthkit_sample() → MealStore.upsert()
    (idempotent on source_id).

The source_id `healthkit:{HKObject.UUID}` is the integrity anchor.
Re-syncs (e.g. the 23:55 24h catch-up automation) collapse to the same
Firestore doc via MealStore's merge=True semantics.

Wave 0 (Plan 01) found that the iOS Shortcut "Get Details → Source" action
returns the source-app NAME ("Lifesum") rather than the HKObject UUID. When
``uuid`` is empty OR matches a known source-name, the normalizer falls back
to a deterministic synthetic key ``healthkit:{start_date_iso}:{calories_int}``
so every distinct meal still gets a unique source_id.

Output dict shape is the SAME 9 keys as mcp_tools.google_fit_tool._normalize_point
(source_id, timestamp, meal_type, calories, protein_g, carbs_g, fat_g,
food_item, source) with ``meal_type`` as **int 1..4** (parity with google_fit's
int enum; see RESEARCH.md Q8).

PHASE 19.1 — HEALTHKIT-01, HEALTHKIT-02, HEALTHKIT-03.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

# Lifesum's [ASSUMED] metadata key for meal-type override; falls back to bucket
# if the key is absent or the value is unparseable. Wave 0 confirmed Lifesum
# does NOT write this key — hour-bucket is the primary code path.
_META_MEAL_TIME_KEY = "HKMetadataKeyMealTime"

# iOS Shortcut "Get Details → Source" returns the literal app NAME (e.g.
# "Lifesum") instead of the HKObject UUID. Treat these as "no UUID" and use
# the synthetic source_id fallback. Add more app-names as the bridge expands.
_KNOWN_SOURCE_NAMES = {"Lifesum", "Apple Health", "Health"}

# Matches a trailing "GMT+N" or "GMT-N" (1- or 2-digit) at the end of an
# otherwise-ISO-8601 datetime string. Wave 0 fixture had `GMT+3` which neither
# datetime.fromisoformat nor Pydantic V2's parser accept.
_GMT_OFFSET_RE = re.compile(r"GMT([+-])(\d{1,2})(?::?(\d{2}))?$")


class HealthKitUnavailableError(Exception):
    """Raised when the operator-side bridge is broken.

    Per-sample errors inside ingest_payload are logged + skipped (Pattern C)
    so one malformed sample does not drop the batch — this exception is for
    "no bridge at all" failure modes (heartbeat staleness catches via
    _CRON_MAX_STALENESS_HOURS['healthkit-sync'] = 48 in Plan 04).
    """


# ------------------------------------------------------------------ #
# Pydantic models                                                    #
# ------------------------------------------------------------------ #

class HealthKitSample(BaseModel):
    """One HealthKit dietary sample, as emitted by the iOS Shortcut.

    Field shape locked by tests/fixtures/healthkit_payload_sample.json (Plan 01).
    """

    uuid: str
    start_date: datetime
    samples_by_type: dict[str, float]
    metadata: dict[str, Any] = {}
    food_item: str | None = None

    @field_validator("start_date", mode="before")
    @classmethod
    def _normalize_gmt_offset(cls, v: Any) -> Any:
        """Coerce Wave-0 non-ISO 'GMT+N' suffix to a proper '+0N:00' offset.

        Wave 0 finding: the iOS Shortcut emitted ``2026-05-29T07:30:00GMT+3``
        which Pydantic V2's default datetime parser rejects. This validator
        rewrites the suffix to ``+03:00`` before Pydantic's own parser runs.
        Pass-through for any already-ISO input.
        """
        if not isinstance(v, str):
            return v
        match = _GMT_OFFSET_RE.search(v)
        if not match:
            return v
        sign, hours, mins = match.group(1), int(match.group(2)), match.group(3)
        mins_int = int(mins) if mins else 0
        offset = f"{sign}{hours:02d}:{mins_int:02d}"
        return _GMT_OFFSET_RE.sub(offset, v)

    @field_validator("samples_by_type", mode="before")
    @classmethod
    def _coerce_stringy_numerics(cls, v: Any) -> dict:
        """iOS Shortcuts often emits numeric Health-sample values as strings
        (RESEARCH.md Q1). Walk the dict and float()-coerce; non-coercible
        entries are dropped with a warning so one bad nutrient doesn't drop
        the whole sample."""
        if not isinstance(v, dict):
            return v
        out: dict[str, float] = {}
        for k, val in v.items():
            try:
                out[k] = float(val)
            except (TypeError, ValueError):
                logger.warning(
                    "HealthKit: dropping non-numeric value %r at key %r", val, k
                )
        return out


class HealthKitPayload(BaseModel):
    """Top-level wire format from POST /cron/healthkit-sync."""

    # DoS guard per RESEARCH.md threat model — 200 is well above a real day's
    # meal count (~3-8 entries) but cheap to validate.
    samples: list[HealthKitSample] = Field(max_length=200)


# ------------------------------------------------------------------ #
# Meal-type inference                                                #
# ------------------------------------------------------------------ #

def _hour_bucket(hour: int) -> int:
    """Map an hour-of-day (0-23) to Google-Fit-compatible int meal_type.

    5-10  → 1 (breakfast)
    11-14 → 2 (lunch)
    17-21 → 3 (dinner)
    else  → 4 (snack)
    """
    if 5 <= hour <= 10:
        return 1
    if 11 <= hour <= 14:
        return 2
    if 17 <= hour <= 21:
        return 3
    return 4


def _infer_meal_type(sample: HealthKitSample) -> int:
    """HKMetadataKeyMealTime override if present and parseable; else hour bucket.

    Per RESEARCH.md Q2, HKMetadataKeyMealTime is NOT a documented Apple
    constant; Lifesum's actual key shape is [ASSUMED] until verified. Wave 0
    confirmed Lifesum did not write metadata at all, so the hour-bucket path
    is the primary one in practice.

    Tolerates:
    - int 1..4 used as-is
    - string variants ('Breakfast'/'breakfast' etc.) mapped to int 1..4
    - anything else → hour-bucket fallback
    """
    raw = sample.metadata.get(_META_MEAL_TIME_KEY)
    if isinstance(raw, int) and 1 <= raw <= 4:
        return raw
    if isinstance(raw, str):
        mapping = {"breakfast": 1, "lunch": 2, "dinner": 3, "snack": 4}
        mapped = mapping.get(raw.strip().lower())
        if mapped is not None:
            return mapped
    return _hour_bucket(sample.start_date.astimezone(_TZ).hour)


# ------------------------------------------------------------------ #
# source_id (Wave 0 Lifesum fallback)                                #
# ------------------------------------------------------------------ #

def _compute_source_id(sample: HealthKitSample) -> str:
    """Build the idempotency-anchor source_id for a HealthKit sample.

    Primary path: ``f"healthkit:{sample.uuid}"`` (HEALTHKIT-03, D-12).

    Wave 0 fallback: when ``uuid`` is empty OR is one of the known
    source-app NAMES that the iOS Shortcut emits in place of the real
    HKObject UUID (e.g. ``"Lifesum"``), build a deterministic synthetic
    key ``f"healthkit:{start_date_iso}:{calories_int}"`` so each meal
    still gets a distinct, repeatable source_id (re-syncs collapse to
    the same doc via MealStore's merge=True).
    """
    uuid = (sample.uuid or "").strip()
    if uuid and uuid not in _KNOWN_SOURCE_NAMES:
        return f"healthkit:{sample.uuid}"
    # Fallback: synthesize from start_date + calories. Both are stable per-meal.
    start_iso = sample.start_date.isoformat()
    calories = int(sample.samples_by_type.get("DietaryEnergyConsumed_kcal", 0))
    return f"healthkit:{start_iso}:{calories}"


# ------------------------------------------------------------------ #
# Normalizer                                                         #
# ------------------------------------------------------------------ #

def _normalize_healthkit_sample(sample: HealthKitSample) -> dict:
    """Convert a HealthKitSample into Klaus's canonical meal dict.

    Returns the SAME 9 keys as mcp_tools.google_fit_tool._normalize_point:
    source_id, timestamp, meal_type, calories, protein_g, carbs_g, fat_g,
    food_item, source. ``meal_type`` is **int** 1..4 (parity contract).

    Unknown ``samples_by_type`` keys (e.g. Wave 0's DietaryFiber_g) are
    silently ignored — only the four canonical macros are surfaced.
    """
    return {
        "source_id": _compute_source_id(sample),
        "timestamp": sample.start_date.isoformat(),
        "meal_type": _infer_meal_type(sample),
        "calories": sample.samples_by_type.get("DietaryEnergyConsumed_kcal", 0),
        "protein_g": sample.samples_by_type.get("DietaryProtein_g", 0),
        "carbs_g": sample.samples_by_type.get("DietaryCarbohydrates_g", 0),
        "fat_g": sample.samples_by_type.get("DietaryFatTotal_g", 0),
        "food_item": sample.food_item,
        "source": "healthkit",
    }


# ------------------------------------------------------------------ #
# Ingest glue                                                        #
# ------------------------------------------------------------------ #

def ingest_payload(payload_dict: dict, store) -> dict:
    """Validate payload, normalize each sample, upsert idempotently.

    Returns ``{"upserted_count": N, "errored_count": M}``. Per-sample try/except
    means one malformed sample does NOT drop the rest of the batch (Pattern C
    from Phase 19-04 gather_situation).

    Args:
        payload_dict: Raw JSON dict from the /cron/healthkit-sync POST body.
        store: A MealStore instance — anything with an
            ``upsert(source_id, meal)`` method.

    Raises:
        pydantic.ValidationError: When the top-level payload does not match
            HealthKitPayload (the webhook route translates this into 422).
    """
    payload = HealthKitPayload.model_validate(payload_dict)
    upserted = 0
    errored = 0
    for sample in payload.samples:
        try:
            meal = _normalize_healthkit_sample(sample)
            store.upsert(source_id=meal["source_id"], meal=meal)
            upserted += 1
        except Exception:
            logger.warning(
                "healthkit ingest_payload: sample %s failed; continuing",
                sample.uuid, exc_info=True,
            )
            errored += 1
    logger.info(
        "healthkit_sync.upserted count=%d errored=%d", upserted, errored
    )
    return {"upserted_count": upserted, "errored_count": errored}
