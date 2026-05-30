"""HealthKit Nutrition tool — Lifesum-on-iOS-sourced meal sync.

Pipeline (Path B, live-UAT revised 2026-05-30):
    Lifesum (iOS) → Apple HealthKit → iOS Shortcut (Personal Automation
    on Lifesum close) → POST /cron/healthkit-sync → HealthKitPayload
    Pydantic parse (FLAT per-quantity samples) →
    _aggregate_quantity_samples() group-by (start_date, food_item) +
    sum same-quantity-type duplicates → _normalize_healthkit_sample() →
    MealStore.upsert() (idempotent on source_id).

The source_id `healthkit:{HKObject.UUID}` is the integrity anchor.
Re-syncs (e.g. the 23:55 24h catch-up automation) collapse to the same
Firestore doc via MealStore's merge=True semantics.

Wave 0 (Plan 01) found that the iOS Shortcut "Get Details → Source" action
returns the source-app NAME ("Lifesum") rather than the HKObject UUID. When
``uuid`` is empty OR matches a known source-name, the normalizer falls back
to a deterministic synthetic key
``healthkit:{start_date_iso}:{food_item}:{calories_int}`` so every distinct
meal still gets a unique source_id. ``food_item`` is part of the key because
the aggregator separates meals by ``(start_date, food_item)`` — omitting it
would silently collapse two distinct foods logged at the same timestamp with
equal integer calories into one Firestore doc (CR-01).

Path B (live UAT, 2026-05-30) found that Lifesum writes ONE HKQuantitySample
per macro PER FOOD ITEM (a meal with 3 foods = 3 Energy + 3 Protein + 3
Carbs + 3 Fat + 3 Fiber samples). iOS Shortcuts cannot read the
HKCorrelation parent UUID via the `Find Health Samples` action, so the
bundling into per-meal records MUST happen server-side. The wire format is
therefore FLAT — one ``HealthKitQuantitySample`` per row — and
``_aggregate_quantity_samples`` groups by ``(start_date.isoformat(), food_item)``
and sums same-quantity-type values within each group.

Output dict shape is the SAME 9 keys as mcp_tools.google_fit_tool._normalize_point
(source_id, timestamp, meal_type, calories, protein_g, carbs_g, fat_g,
food_item, source) with ``meal_type`` as **int 1..4** (parity with google_fit's
int enum; see RESEARCH.md Q8).

PHASE 19.1 — HEALTHKIT-01, HEALTHKIT-02, HEALTHKIT-03 (and Plan 05 Path B).
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

    Per-meal errors inside ingest_payload are logged + skipped (Pattern C)
    so one malformed meal does not drop the batch — this exception is for
    "no bridge at all" failure modes (heartbeat staleness catches via
    _CRON_MAX_STALENESS_HOURS['healthkit-sync'] = 48 in Plan 04).
    """


# ------------------------------------------------------------------ #
# Pydantic models — FLAT wire format (Path B)                        #
# ------------------------------------------------------------------ #

class HealthKitQuantitySample(BaseModel):
    """Single HKQuantitySample as emitted by an iOS Shortcut.

    Lifesum writes one of these per (food_item × macro_type). Server groups
    by (start_date, food_item) to reconstruct per-meal records — see
    :func:`_aggregate_quantity_samples`.

    Wire-format example (one of ~5 rows per meal)::

        {
            "uuid": "Lifesum",
            "start_date": "2026-05-29T20:00:00GMT+3",
            "quantity_type": "DietaryEnergyConsumed_kcal",
            "value": 324.0,
            "metadata": {},
            "food_item": null
        }
    """

    # ``uuid`` becomes part of the Firestore document ID on the primary path
    # (``healthkit:{uuid}``). Firestore IDs cannot contain '/', cannot be
    # '.'/'..', cannot match ``__.*__`` and are capped at 1500 bytes. Bound
    # the length here as defense-in-depth (the route is authenticated); '/' is
    # additionally stripped in _compute_source_id so a bad value can never
    # change the document path (WR-01).
    uuid: str = Field(max_length=1024)
    start_date: datetime
    quantity_type: str
    value: float
    metadata: dict[str, Any] = Field(default_factory=dict)
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

    @field_validator("start_date", mode="after")
    @classmethod
    def _ensure_aware(cls, v: datetime) -> datetime:
        """Attach Asia/Jerusalem to any naive datetime at parse time (WR-02).

        The GMT-offset coercer only rewrites a trailing ``GMT+N`` suffix and
        passes everything else through, so an ISO string with no offset parses
        to a NAIVE datetime. Downstream, ``_infer_meal_type`` calls
        ``astimezone(_TZ)`` (which on a naive value assumes the system-local tz
        — UTC on Cloud Run, mis-bucketing meals near band edges), and the
        synthetic source_id embeds ``isoformat()`` (so a naive vs. aware variant
        of the same instant yields different keys, breaking idempotency between
        the 2h-close push and the 23:55 catch-up). The codebase intends
        Asia/Jerusalem semantics throughout, so normalize naive → aware here.
        """
        return v.replace(tzinfo=_TZ) if v.tzinfo is None else v

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_stringy_numeric(cls, v: Any) -> Any:
        """iOS Shortcuts often emits numeric Health-sample values as strings
        (RESEARCH.md Q1). Float-coerce string inputs; raises ValueError via
        Pydantic if the string is not parseable.

        Unlike the legacy bundled samples_by_type validator (which silently
        dropped non-coercible entries), Path B's one-sample-per-row shape
        means a garbage value can be properly reported per-row — the
        per-meal try/except in ingest_payload still keeps a bad row from
        dropping the entire batch.
        """
        if isinstance(v, str):
            return float(v)
        return v


class HealthKitPayload(BaseModel):
    """Top-level wire format from POST /cron/healthkit-sync.

    Path B: a flat list of per-quantity samples. The 1000-cap accommodates
    fan-out from multi-item meals (5 macros × N food items × ~5-8 meals/day).
    """

    # DoS guard per RESEARCH.md threat model — 1000 covers ~ 1 day's full
    # fan-out (e.g. 8 meals × 5 macros × 5 food items = 200, with headroom)
    # while staying cheap to validate.
    samples: list[HealthKitQuantitySample] = Field(max_length=1000)


# ------------------------------------------------------------------ #
# Server-side aggregator (Path B)                                    #
# ------------------------------------------------------------------ #

def _aggregate_quantity_samples(
    samples: list[HealthKitQuantitySample],
) -> list[dict]:
    """Group flat per-quantity samples by (start_date, food_item) into per-meal dicts.

    Multiple samples at the same (start_date, food_item) for the same
    ``quantity_type`` are **summed** — handles Lifesum's per-food-item fan-out
    (a meal with 3 chicken pieces may write 3 protein samples at the same
    timestamp under the same food label).

    Returns a list of dicts in the legacy bundled shape
    ``{uuid, start_date, samples_by_type, metadata, food_item}``, ready to be
    consumed by :func:`_normalize_healthkit_sample`. The aggregator output is
    a plain dict (not a Pydantic instance) — the values have already been
    validated by the ``HealthKitQuantitySample`` model on parse, and the
    normalizer just reads dict keys, so the extra Pydantic round-trip would
    cost CPU without buying any safety.

    Grouping key is the ISO string form of ``start_date`` so that the
    aware/naive distinction never silently splits a meal across two groups.
    """
    groups: dict[tuple[str, str | None], dict] = {}
    for s in samples:
        key = (s.start_date.isoformat(), s.food_item)
        g = groups.get(key)
        if g is None:
            g = {
                "uuid": s.uuid,
                "start_date": s.start_date,
                "samples_by_type": {},
                "metadata": dict(s.metadata),
                "food_item": s.food_item,
            }
            groups[key] = g
        # Sum same-quantity-type values within the group (Lifesum fan-out).
        g["samples_by_type"][s.quantity_type] = (
            g["samples_by_type"].get(s.quantity_type, 0.0) + float(s.value)
        )
        # Merge metadata (later samples win on key collision — Lifesum
        # typically writes identical metadata across the fan-out).
        g["metadata"].update(s.metadata)
    return list(groups.values())


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


def _infer_meal_type(meal: dict) -> int:
    """HKMetadataKeyMealTime override if present and parseable; else hour bucket.

    Per RESEARCH.md Q2, HKMetadataKeyMealTime is NOT a documented Apple
    constant; Lifesum's actual key shape is [ASSUMED] until verified. Wave 0
    confirmed Lifesum did not write metadata at all, so the hour-bucket path
    is the primary one in practice.

    Tolerates:
    - int 1..4 used as-is
    - string variants ('Breakfast'/'breakfast' etc.) mapped to int 1..4
    - anything else → hour-bucket fallback

    Args:
        meal: A per-meal dict in the aggregator's output shape
              (``{uuid, start_date, samples_by_type, metadata, food_item}``).
    """
    raw = meal.get("metadata", {}).get(_META_MEAL_TIME_KEY)
    if isinstance(raw, int) and 1 <= raw <= 4:
        return raw
    if isinstance(raw, str):
        mapping = {"breakfast": 1, "lunch": 2, "dinner": 3, "snack": 4}
        mapped = mapping.get(raw.strip().lower())
        if mapped is not None:
            return mapped
    return _hour_bucket(meal["start_date"].astimezone(_TZ).hour)


# ------------------------------------------------------------------ #
# source_id (Wave 0 Lifesum fallback)                                #
# ------------------------------------------------------------------ #

def _compute_source_id(meal: dict) -> str:
    """Build the idempotency-anchor source_id for a per-meal dict.

    Primary path: ``f"healthkit:{meal['uuid']}"`` (HEALTHKIT-03, D-12).

    Wave 0 fallback: when ``uuid`` is empty OR is one of the known
    source-app NAMES that the iOS Shortcut emits in place of the real
    HKObject UUID (e.g. ``"Lifesum"``), build a deterministic synthetic
    key ``f"healthkit:{start_date_iso}:{food_item}:{calories_int}"`` so
    each meal still gets a distinct, repeatable source_id (re-syncs
    collapse to the same doc via MealStore's merge=True). ``food_item`` is
    in the key so it matches the aggregator's ``(start_date, food_item)``
    grouping — without it, two distinct foods at the same timestamp with
    equal integer calories collide and one meal is silently lost (CR-01).
    """
    uuid = (meal.get("uuid") or "").strip()
    if uuid and uuid not in _KNOWN_SOURCE_NAMES:
        safe = uuid.replace("/", "_")[:200]
        return f"healthkit:{safe}"
    # Fallback: synthesize from start_date + food_item + calories. The
    # aggregator separates meals by (start_date, food_item) (see
    # _aggregate_quantity_samples), so the synthetic key MUST include
    # food_item too — otherwise two distinct foods logged at the same
    # timestamp with equal integer calories collapse to one Firestore doc
    # and one meal is silently lost (CR-01).
    start_iso = meal["start_date"].isoformat()
    calories = int(meal["samples_by_type"].get("DietaryEnergyConsumed_kcal", 0))
    food_slug = (meal.get("food_item") or "_").replace(":", "_")
    return f"healthkit:{start_iso}:{food_slug}:{calories}"


# ------------------------------------------------------------------ #
# Normalizer                                                         #
# ------------------------------------------------------------------ #

def _normalize_healthkit_sample(meal: dict) -> dict:
    """Convert an aggregated per-meal dict into Klaus's canonical meal shape.

    Returns the SAME 9 keys as mcp_tools.google_fit_tool._normalize_point:
    source_id, timestamp, meal_type, calories, protein_g, carbs_g, fat_g,
    food_item, source. ``meal_type`` is **int** 1..4 (parity contract).

    Unknown ``samples_by_type`` keys (e.g. Wave 0's DietaryFiber_g) are
    silently ignored — only the four canonical macros are surfaced.

    Args:
        meal: A per-meal dict in the aggregator's output shape — see
              :func:`_aggregate_quantity_samples`.
    """
    sbt = meal["samples_by_type"]
    return {
        "source_id": _compute_source_id(meal),
        "timestamp": meal["start_date"].isoformat(),
        "meal_type": _infer_meal_type(meal),
        "calories": sbt.get("DietaryEnergyConsumed_kcal", 0),
        "protein_g": sbt.get("DietaryProtein_g", 0),
        "carbs_g": sbt.get("DietaryCarbohydrates_g", 0),
        "fat_g": sbt.get("DietaryFatTotal_g", 0),
        "food_item": meal.get("food_item"),
        "source": "healthkit",
    }


# ------------------------------------------------------------------ #
# Ingest glue                                                        #
# ------------------------------------------------------------------ #

def ingest_payload(payload_dict: dict, store) -> dict:
    """Validate payload, aggregate flat samples, normalize each meal, upsert.

    Returns ``{"upserted_count": N, "errored_count": M}`` where N + M ≤ number
    of distinct (start_date, food_item) groups in the input — NOT the raw
    input sample count. Per-meal try/except means one malformed meal does NOT
    drop the rest of the batch (Pattern C from Phase 19-04 gather_situation).

    Args:
        payload_dict: Raw JSON dict from the /cron/healthkit-sync POST body.
        store: A MealStore instance — anything with an
            ``upsert(source_id, meal)`` method.

    Raises:
        pydantic.ValidationError: When the top-level payload does not match
            HealthKitPayload (the webhook route translates this into 422).
    """
    payload = HealthKitPayload.model_validate(payload_dict)
    meals = _aggregate_quantity_samples(payload.samples)
    upserted = 0
    errored = 0
    for meal in meals:
        try:
            normalized = _normalize_healthkit_sample(meal)
            store.upsert(source_id=normalized["source_id"], meal=normalized)
            upserted += 1
        except Exception:
            logger.warning(
                "healthkit ingest_payload: meal at %s (food=%r) failed; continuing",
                meal.get("start_date"), meal.get("food_item"),
                exc_info=True,
            )
            errored += 1
    logger.info(
        "healthkit_sync.upserted count=%d errored=%d samples_in=%d meals_out=%d",
        upserted, errored, len(payload.samples), len(meals),
    )
    return {"upserted_count": upserted, "errored_count": errored}
