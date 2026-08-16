"""The training plan and the reference documents Klaus reasons from.

`update_plan` is an alias of `update_training_profile`: same handler,
separate schema, because Claude reaches for both names.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os

from core.tools.registry import tool

logger = logging.getLogger(__name__)


@tool({
        "name": "get_training_profile",
        "description": (
            "Read Amit's stored training profile (athletic_goals, training_constraints, "
            "recovery_preferences). call this when you need to know "
            "Amit's coaching context before answering or planning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    })
def _handle_get_training_profile() -> str:
    """PROFILE-04 return the user training profile dict as JSON.

    Uses _jsonsafe_doc to ISO-convert any DatetimeWithNanoseconds values
    (e.g. updated_at, bootstrapped_at) before json.dumps so this handler
    never raises a TypeError on a real Firestore doc.  T-21-04 mitigation.
    """
    from memory.firestore_db import UserProfileStore, _jsonsafe_doc
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    return json.dumps(_jsonsafe_doc(store.load()))


@tool({
        "name": "read_coaching_guide",
        "description": (
            "Read a deep section of the coaching knowledge guide. "
            "Call when Amit asks 'why?' about a training concept, or when the slim "
            "core digest (already in your system prompt) is not detailed enough. "
            "Returns the full section text for the requested topic. "
            "Do NOT call for routine coaching messages — the slim core covers those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Section to retrieve. Use one of: 'interference-effect', "
                        "'block-periodization', 'threshold-runs', 'top-set-strength', "
                        "'calisthenics-progressions', 'intervals-vo2max', "
                        "'peri-workout-fueling', 'protein-timing', "
                        "'carb-periodization', 'supplements'. "
                        "Free-text also accepted — nearest section slug is matched."
                    ),
                },
            },
            "required": ["topic"],
        },
    })
def _handle_read_coaching_guide(topic: str) -> str:
    """COACH-01 return the coaching guide section for the requested topic.

    Reads docs/COACHING_GUIDE.md, finds the <!-- SECTION: {slug} --> anchor,
    and returns the section text as JSON. Fuzzy fallback on partial word match.

    T-22-04 mitigation: topic is normalized to a slug and used ONLY inside a regex
    against authored <!-- SECTION: slug --> anchors in a hardcoded file path. It is
    NEVER concatenated into a filesystem path. '..' / '/' / absolute paths fail to
    match a slug and return error JSON — they cannot escape to the filesystem.
    """
    from core import doc_sections

    content = doc_sections.read_document("COACHING_GUIDE.md")
    if content is None:
        return json.dumps({"error": "COACHING_GUIDE.md not found"})

    section = doc_sections.find_section(content, topic)
    if section is None:
        return json.dumps({"error": f"Section '{topic}' not found in COACHING_GUIDE.md"})

    return json.dumps({"topic": doc_sections.slugify(topic), "content": section})


@tool({
        "name": "read_user_profile",
        "description": (
            "Read one section of Amit's durable profile verbatim from docs/USER.md. "
            "The whole profile is already included in every get_life_snapshot, so call "
            "this only when you need a section word-for-word — for example to quote a "
            "scheduling rule back while explaining a decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Section to retrieve. One of: 'identity', 'rhythms', "
                        "'footprints', 'working-style', 'scheduling-rules'. "
                        "Free-text also accepted — nearest section slug is matched."
                    ),
                },
            },
            "required": ["section"],
        },
    })
def _handle_read_user_profile(section: str) -> str:
    """Return one section of Amit's profile from docs/USER.md.

    The whole profile already ships in every get_life_snapshot, so this is for
    the narrower case where Claude wants one section verbatim — for example to
    quote a scheduling rule back while explaining a decision.

    Args:
        section: Section slug, e.g. "footprints". Matched against authored
            anchors only, never used as a path (see doc_sections).

    Returns:
        str: JSON with "section" and "content", or "error" when not found.
    """
    from core import user_profile

    body = user_profile.section(section)
    if body is None:
        available = ", ".join(user_profile.load_sections()) or "none"
        return json.dumps(
            {"error": f"Section '{section}' not found in USER.md. Available: {available}"}
        )

    from core import doc_sections

    return json.dumps({"section": doc_sections.slugify(section), "content": body})


@tool({
        "name": "update_training_profile",
        "description": (
            "Merge new fields into Amit's stored training profile. "
            "Record the change and tell him you did; only ask first if the new value is "
            "genuinely ambiguous. Recognized top-level keys: "
            "athletic_goals (list), training_constraints (list), recovery_preferences (object), "
            "dated_goals (list), weekly_split (object), nutrition_targets (object), "
            "supplement_schedule (list), fueling_timeline (list), plan_start_date (string)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": (
                        "Dict of fields to merge into users/amit. Top-level keys: "
                        "athletic_goals, training_constraints, recovery_preferences, "
                        "dated_goals, weekly_split, nutrition_targets, "
                        "supplement_schedule, fueling_timeline, plan_start_date."
                    ),
                },
            },
            "required": ["patch"],
        },
    })
def _handle_update_training_profile(patch: dict) -> str:
    """PROFILE-04 merge a patch into users/amit profile."""
    from memory.firestore_db import UserProfileStore
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    try:
        store.update(patch)
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@tool({
        "name": "update_plan",
        "description": (
            "Update Amit's living training plan (goals, weekly split, nutrition targets, "
            "dates). Record the change and tell him; only ask first if the "
            "value is genuinely ambiguous. "
            "Same structured keys as update_training_profile: "
            "dated_goals (list), weekly_split (object), nutrition_targets (object), "
            "supplement_schedule (list), fueling_timeline (list), plan_start_date (string), "
            "athletic_goals (list), training_constraints (list), recovery_preferences (object)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": (
                        "Dict of fields to merge into users/amit. Top-level keys: "
                        "dated_goals, weekly_split, nutrition_targets, "
                        "supplement_schedule, fueling_timeline, plan_start_date, "
                        "athletic_goals, training_constraints, recovery_preferences."
                    ),
                },
            },
            "required": ["patch"],
        },
    })
def _handle_update_plan(**kwargs) -> str:
    """Alias of update_training_profile — same write, different name."""
    return _handle_update_training_profile(**kwargs)
