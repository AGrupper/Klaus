# Phase 24: Strict Coaching Integration + Nutrition Accountability — Pattern Map

**Mapped:** 2026-06-06
**Files analyzed:** 12 (8 modified, 1 new class in existing file, 4 prompts)
**Analogs found:** 12 / 12

---

## Line Number Drift Check

RESEARCH.md cited line numbers were verified against live code. All confirmed accurate:
- `OutreachLogStore` class: line 1291 (CONFIRMED — exact)
- `MealStore.get_day`: line 641 (CONFIRMED — exact)
- `TrainingLogStore.log_session`: line 797 (CONFIRMED — exact)
- `TrainingLogStore` class: line 766 (CONFIRMED — exact)
- `_jsonsafe_doc`: line 735 (CONFIRMED — exact)
- `_silent_garmin_sync`: line 446 (CONFIRMED — exact)
- `handle_rpe_callback`: line 666 (CONFIRMED — exact)
- `_slot_for`: line 425 (CONFIRMED — exact)
- `attach_note`: line 851 (CONFIRMED — exact)
- `MAX_TOOL_ITERATIONS = 8`: line 44 (CONFIRMED — exact)
- Smart-loop fallback text: lines 665–668 (CONFIRMED — exact)
- `_handle_read_coaching_guide`: line 1500 (CONFIRMED — exact; fuzzy loop lines 1531–1541)
- `proactive_alerts._already_sent`: line 197 (CONFIRMED — the call, not the def; def is line 297)
- `proactive_alerts.run_proactive_alerts`: line 151 (CONFIRMED — exact)
- `_compose_alert`: line 484 (CONFIRMED — exact)
- `morning_briefing._gather_data`: line 174 (CONFIRMED — exact)
- `morning_briefing._compose_briefing`: line 308 (CONFIRMED — exact)
- `weekly_training_review._gather_week_data`: line 42 (CONFIRMED — exact)
- `weekly_training_review._compose_review`: line 227 (CONFIRMED — exact)

**DRIFT DETECTED (minor):**
- RESEARCH.md says `run_proactive_alerts` structure "lines 151–290". Actual send + `_mark_processed` is at line 288–290. Structure confirmed; line range accurate.
- RESEARCH.md says "ACWR fetch… ~line 197". The `_already_sent()` CHECK is at line 197 (the call `if _already_sent(target_date):`). The function definition is at line 297. RESEARCH.md references the call site correctly.
- RESEARCH.md Finding 6: "runs BEFORE `_already_sent` gate". CONFIRMED: `run_training_checkin` called at lines 163–168, BEFORE `if _already_sent(target_date)` at line 197.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `memory/firestore_db.py` → `CoachingTopicStore` (NEW class) | store | event-driven | `OutreachLogStore` (line 1291) | exact |
| `memory/firestore_db.py` → `TrainingLogStore.log_session` (MODIFY) | store | CRUD | self — existing `log_session` pattern (line 797) | self-analog |
| `core/training_checkin.py` → `derive_session_quality` (NEW pure fn) | utility | transform | `_slot_for` (line 425) — same pure-fn-no-I/O pattern | role-match |
| `core/training_checkin.py` → `_silent_garmin_sync` (MODIFY) | service | event-driven | self — existing `_silent_garmin_sync` (line 446) | self-analog |
| `core/training_checkin.py` → `handle_rpe_callback` (MODIFY) | controller | request-response | self — existing `handle_rpe_callback` (line 666) | self-analog |
| `core/proactive_alerts.py` → `_gather_nutrition_data` (NEW fn) | service | CRUD | `morning_briefing._gather_data` (line 174) | role-match |
| `core/proactive_alerts.py` → `run_proactive_alerts` (MODIFY) | controller | request-response | self — existing `run_proactive_alerts` (line 151) | self-analog |
| `core/morning_briefing.py` → `_gather_data` (MODIFY) | service | CRUD | self — existing `_gather_data` (line 174) | self-analog |
| `core/weekly_training_review.py` → `_gather_week_data` (MODIFY) | service | CRUD | self — existing `_gather_week_data` (line 42) | self-analog |
| `core/main.py` → `_run_smart_loop` (MODIFY) | controller | request-response | self — existing `_run_smart_loop` (line 488+) | self-analog |
| `core/tools.py` → `_handle_read_coaching_guide` (MODIFY) | utility | request-response | self — existing `_handle_read_coaching_guide` (line 1500) | self-analog |
| `prompts/*.md` (4 prompt files, MODIFY) | config | — | existing prompt structure in each file | self-analog |

---

## Pattern Assignments

---

### `memory/firestore_db.py` → NEW `CoachingTopicStore` class

**Analog:** `OutreachLogStore` (lines 1291–1403)

**Why this analog:** Identical structural contract — per-day doc keyed to Asia/Jerusalem date, atomic `ArrayUnion`, "never raises on read / re-raises on write" discipline. The key difference is `CoachingTopicStore` stores `list[str]` topic keys directly (not a `list[dict]` entries), which is REQUIRED by Pitfall 3 (ArrayUnion deep-equality breaks with dict entries containing SERVER_TIMESTAMP).

**Constructor pattern** (OutreachLogStore lines 1319–1328 — copy exactly):
```python
_COLLECTION = "coaching_topics"   # lowercase, no uppercase K — see CLAUDE.md §6

def __init__(self, project_id: str, database: str = "(default)") -> None:
    self._client = _make_firestore_client(project_id, database)
    self._col = self._client.collection(self._COLLECTION)
```

**Docstring pattern with NOTE 2** (OutreachLogStore lines 1291–1317 — the NOTE 2 anti-pattern warning is critical, copy its spirit):
```python
class CoachingTopicStore:
    """Per-day coaching topic gate for cross-cron dedup (Phase 24 — COACH-05).

    Collection: coaching_topics/{YYYY-MM-DD}
    Schema: { "date": str, "topics": list[str], "updated_at": SERVER_TIMESTAMP }

    D-04: daily reset via date-keyed doc (same pattern as OutreachLogStore).
    D-02: has_topic() hard-blocks; add_topic() writes only for proactive crons.
    D-03: reactive chat never calls either method.

    NOTE: store topic keys as a plain list[str]. DO NOT use list[dict] entries
    with embedded timestamps. ArrayUnion compares by deep equality — dicts
    containing SERVER_TIMESTAMP sentinels are NEVER equal (each sentinel is a
    fresh object), which defeats dedup. See OutreachLogStore NOTE 2.

    Reads (has_topic, topics_today) never raise — fail-open (return False / []).
    Writes (add_topic) re-raise after logging — caller decides whether to abort.
    """
```

**Write pattern** (OutreachLogStore.append lines 1355–1366 — mirror with simplified entry):
```python
def add_topic(self, date_str: str, topic_key: str) -> None:
    """Atomic add. Re-raises on write failure. Call AFTER send succeeds (mirrors
    OutreachLogStore.append Phase-18 D-10 invariant)."""
    try:
        self._col.document(date_str).set(
            {
                "date": date_str,
                "topics": firestore.ArrayUnion([topic_key]),  # plain string, NOT dict
                "updated_at": firestore.SERVER_TIMESTAMP,     # doc-level only
            },
            merge=True,
        )
    except Exception:
        logger.error("CoachingTopicStore.add_topic(%r, %r) failed", date_str, topic_key, exc_info=True)
        raise
```

**Read pattern** (OutreachLogStore.get_today lines 1368–1386 — mirror with fail-open bool return):
```python
def has_topic(self, date_str: str, topic_key: str) -> bool:
    """Hard-block check. Never raises — fail-open (returns False on error)."""
    try:
        snap = self._col.document(date_str).get()
        if not snap.exists:
            return False
        topics = (snap.to_dict() or {}).get("topics") or []
        return topic_key in topics
    except Exception:
        logger.warning("CoachingTopicStore.has_topic failed", exc_info=True)
        return False   # fail-open: let the topic fire rather than silently suppress

def topics_today(self, date_str: str) -> list[str]:
    """Return today's raised topic_keys. Never raises."""
    try:
        snap = self._col.document(date_str).get()
        if not snap.exists:
            return []
        return list((snap.to_dict() or {}).get("topics") or [])
    except Exception:
        logger.warning("CoachingTopicStore.topics_today failed", exc_info=True)
        return []
```

**Placement in file:** Insert after `OutreachLogStore` (after line 1403), before `TickLogStore` (line 1406). Follow the existing store ordering pattern in the file.

---

### `memory/firestore_db.py` → `TrainingLogStore.log_session` (MODIFY)

**Analog:** Self — existing `log_session` (lines 797–844)

**Current signature** (lines 797–810):
```python
def log_session(
    self,
    date: str,                              # YYYY-MM-DD
    slot: str,                              # calendar event id or YYYYMMDDHHmm
    session_type: str | None = None,
    planned: bool = False,
    completed: bool = False,
    skipped_reason: str | None = None,
    rpe: int | None = None,
    feel: int | None = None,
    notes: str | None = None,
    source: str = "telegram",
    garmin_activity_id: str | None = None,
) -> None:
```

**Change:** Add `quality: str | None = None` parameter after `notes`. The full updated signature:
```python
def log_session(
    self,
    date: str,
    slot: str,
    session_type: str | None = None,
    planned: bool = False,
    completed: bool = False,
    skipped_reason: str | None = None,
    rpe: int | None = None,
    feel: int | None = None,
    notes: str | None = None,
    quality: str | None = None,            # NEW — "strong" | "neutral" | "grind" | None (D-13)
    source: str = "telegram",
    garmin_activity_id: str | None = None,
) -> None:
```

**Payload pattern** (lines 826–841 — add `quality` key after `notes`):
```python
payload = {
    "date": date,
    "slot": slot,
    "type": session_type,
    "planned": planned,
    "completed": completed,
    "skipped_reason": skipped_reason,
    "rpe": rpe,
    "feel": feel,
    "notes": notes,
    "quality": quality,                    # NEW
    "source": source,
    "garmin_activity_id": garmin_activity_id,
    "updated_at": firestore.SERVER_TIMESTAMP,
}
```

`merge=True` at line 841 already handles the "existing entries without quality remain valid" requirement — no change needed there.

**Docstring addition:** Add `quality: "strong" | "neutral" | "grind" | None — D-13 derived field.` after the existing `Pitfall 7` note.

---

### `core/training_checkin.py` → NEW `derive_session_quality` pure function

**Analog:** `_slot_for` (lines 425–439) — same pure-function-no-I/O pattern. Also mirrors the `RECOVERY_THRESHOLDS` dict pattern (lines 65–75) for module-level config constants.

**Module-level constants to add** (mirror `_ACTIVITY_TYPE_MAP` pattern at lines 45–51):
```python
# Garmin Feel scale: 0=Very Weak, 25=Weak, 50=Okay, 75=Strong, 100=Very Strong
# Source: ingest_garmin_zip.py workoutFeel comment; garmin_tool.py directWorkoutFeel
_GARMIN_FEEL_LABELS: dict[int, str] = {
    100: "very_strong", 75: "strong", 50: "okay", 25: "weak", 0: "very_weak"
}

_QUALITY_STRONG_NOTES = ("pb", "pr", "personal record", "felt great", "best ever")
_QUALITY_GRIND_NOTES  = ("terrible", "awful", "cut short", "struggled", "could not")
```

**Function signature and body** (place near `_slot_for` at ~line 440, before `_silent_garmin_sync`):
```python
def derive_session_quality(
    rpe: int | None,
    feel: int | None,       # Garmin raw: 0/25/50/75/100 — Pitfall 4: 0 is valid!
    notes: str | None = None,
) -> str | None:
    """Return "strong" | "neutral" | "grind" | None.

    D-13: derived from Garmin Feel + RPE + notes. No new user input required.

    PITFALL 4: use 'is not None' checks, never truthiness, for feel.
    feel == 0 (Very Weak) is falsy in Python but is a valid Garmin value.
    """
    # Pitfall 4: 'feel is not None' not 'if feel'
    if rpe is None and feel is None:
        return None

    quality: str | None = None

    if feel is not None:
        # Feel takes precedence (Garmin self-eval is more reliable signal)
        if feel >= 75:
            quality = "strong" if (rpe is None or rpe >= 5) else "neutral"
        elif feel == 50:
            quality = "neutral"
        else:  # 0 or 25 — Very Weak or Weak
            quality = "grind"
    else:
        # RPE-only fallback (no Garmin feel available)
        if rpe >= 8:
            quality = "grind"
        elif rpe <= 4:
            quality = "strong"
        else:
            quality = "neutral"

    # Notes override (simple keyword scan — applied last)
    if notes:
        notes_lower = notes.lower()
        if any(k in notes_lower for k in _QUALITY_STRONG_NOTES):
            quality = "strong"
        elif any(k in notes_lower for k in _QUALITY_GRIND_NOTES):
            quality = "grind"

    return quality
```

---

### `core/training_checkin.py` → `_silent_garmin_sync` (MODIFY)

**Analog:** Self — existing `_silent_garmin_sync` (lines 446–480)

**Current `log_session` call** (lines 468–478):
```python
store.log_session(
    date=today_iso,
    slot=activity_id,
    session_type=act.get("type"),
    planned=False,
    completed=True,
    rpe=perceived_exertion,
    feel=act.get("feel"),
    source="garmin",
    garmin_activity_id=activity_id,
)
```

**Change:** Derive quality BEFORE the `log_session` call and pass it in. Mirror the existing `perceived_exertion` / `feel` extraction pattern:
```python
perceived_exertion = act.get("perceived_exertion")
if perceived_exertion is None:
    continue
_feel = act.get("feel")
# D-13: derive quality here (Pitfall 4: feel=0 is valid — function uses 'is not None')
_quality = derive_session_quality(rpe=perceived_exertion, feel=_feel)
store.log_session(
    date=today_iso,
    slot=activity_id,
    session_type=act.get("type"),
    planned=False,
    completed=True,
    rpe=perceived_exertion,
    feel=_feel,
    quality=_quality,                      # NEW
    source="garmin",
    garmin_activity_id=activity_id,
)
```

**Pitfall 6 guard:** `_silent_garmin_sync` already reads both `perceived_exertion` and `feel` from the activity dict. Quality derivation goes here so Garmin-only sessions get a quality value — not just Telegram-tapped sessions.

---

### `core/training_checkin.py` → `handle_rpe_callback` (MODIFY)

**Analog:** Self — existing `handle_rpe_callback` (lines 666–729)

**Current `log_session` call** (lines 699–708):
```python
tls = TrainingLogStore()
tls.log_session(
    date=event_date,
    slot=session_key.split("_", 1)[1] if "_" in session_key else session_key,
    session_type=session.get("session_type"),
    planned=True,
    completed=True,
    rpe=rpe_value,
    source="telegram",
)
```

**Change:** Derive quality from RPE alone (no feel at this point — Garmin hasn't synced yet):
```python
# D-13: provisional quality from RPE alone; _silent_garmin_sync may update
# feel later via merge=True, but quality is not re-derived on that path.
# A subsequent _silent_garmin_sync WILL re-derive quality (Pitfall 6 guard).
_quality = derive_session_quality(rpe=rpe_value, feel=None)
tls.log_session(
    date=event_date,
    slot=session_key.split("_", 1)[1] if "_" in session_key else session_key,
    session_type=session.get("session_type"),
    planned=True,
    completed=True,
    rpe=rpe_value,
    quality=_quality,                      # NEW
    source="telegram",
)
```

**Note:** `attach_note` does NOT need quality derivation — notes arrive after RPE, and the notes-override path is already embedded in `derive_session_quality`. The `_silent_garmin_sync` pass (which always runs at the next 21:30 cron) will produce the final quality value using all available signals.

---

### `core/proactive_alerts.py` → NEW `_gather_nutrition_data` helper + `run_proactive_alerts` integration

**Analog:** `morning_briefing._gather_data` (lines 174–301) — same best-effort gather-each-source-catches-own-errors pattern.

**Gather function pattern** (mirror `_gather_data` block structure):
```python
def _gather_nutrition_data(today_iso: str, garmin_activities: list[dict] | None = None) -> dict:
    """Gather meal totals, fueling-slot miss detection, and anchor times for today.

    Best-effort: each sub-gather is wrapped; failures return {} / [] / None.
    garmin_activities: pass the already-fetched list to avoid a second API call
    (Pitfall 5 / RESEARCH open question 2 — reuse the garmin_data fetched above).

    Returns:
        {
            "meals": list[dict],           # raw from MealStore.get_day
            "macro_totals": dict,          # totals sub-dict from get_day_aggregate
            "macro_gaps": list[dict],      # from _macro_gap_check
            "slot_misses": list[str],      # from _detect_slot_misses
            "am_anchor": str | None,       # ISO datetime of AM run start
            "pm_anchor": str | None,       # ISO datetime of PM lift start
        }
    """
    result: dict = {}

    # Meals (MealStore.get_day — never raises, returns [])
    # Pitfall 7: get_day returns [] not None on empty
    try:
        from memory.firestore_db import MealStore
        ms = MealStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        meals = ms.get_day(today_iso)
        result["meals"] = meals
        agg = ms.get_day_aggregate(today_iso)
        result["macro_totals"] = (agg or {}).get("totals", {})
    except Exception:
        logger.warning("proactive_alerts: nutrition meal fetch failed", exc_info=True)
        result["meals"] = []
        result["macro_totals"] = {}

    # ... anchor resolution, slot miss detection, macro gap check ...
```

**Integration into `run_proactive_alerts`** — insert AFTER step 4 gather and BEFORE `compute_recovery_concern` (which is at ~line 276). Mirror the existing best-effort try/except pattern:

```python
# Phase 24 — NUTR-01/02/03: nutrition + fueling-slot gather
nutrition_data = {}
try:
    nutrition_data = _gather_nutrition_data(today_iso, garmin_activities=...)
    if nutrition_data:
        alerts_context["nutrition"] = nutrition_data
except Exception:
    logger.warning("proactive_alerts: nutrition gather failed", exc_info=True)
    # silent omit — no fabrication (D-13 guardrail)
```

**Dedup gate integration** — pattern to insert between gather and compose (after line 283, before `message = _compose_alert(alerts_context)` at line 285):
```python
# Phase 24 — COACH-05: coaching topic dedup gate
# Filter detected_topics to only un-raised ones before compose context
try:
    from memory.firestore_db import CoachingTopicStore
    _cts = CoachingTopicStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
    )
    _today_il = datetime.now(_TZ).date().isoformat()
    _detected_topics: list[str] = _collect_detected_topics(alerts_context)
    _new_topics = [t for t in _detected_topics if not _cts.has_topic(_today_il, t)]
    alerts_context["coaching_topics_new"] = _new_topics
    alerts_context["coaching_topics_already_raised"] = [
        t for t in _detected_topics if t not in _new_topics
    ]
except Exception:
    logger.warning("proactive_alerts: coaching dedup gate failed", exc_info=True)

message = _compose_alert(alerts_context)

# After successful send: write new topics to CoachingTopicStore
# (mirror OutreachLogStore.append post-send discipline — Phase 18 D-10)
```

**Post-send write pattern** (mirror `_mark_processed` at lines 308–318):
```python
try:
    for _topic in alerts_context.get("coaching_topics_new") or []:
        _cts.add_topic(_today_il, _topic)
except Exception:
    logger.warning("proactive_alerts: coaching topic write failed", exc_info=True)
    # non-fatal — dedup just won't fire for this topic on next cron
```

**`_already_sent` gate position** (lines 197–199 — UNCHANGED, new coaching gate is finer-grained and sits inside the compose path, NOT here):
```python
if _already_sent(target_date):
    logger.info("Proactive alerts: already processed for %s — skipping", target_date)
    return
```

**Existing `_compose_alert` pattern** (lines 484–530 — modify to pass coaching context):
```python
# Current pattern — the alerts_context dict is JSON-dumped as the user message.
# Phase 24 adds keys to alerts_context before this call.
user_message = json.dumps(alerts_context, ensure_ascii=False, indent=2)
```

The existing `{coaching_guide}` injection at lines 495–508 already uses `_get_orchestrator()._coaching_guide_content`. No change to that injection mechanism.

---

### `core/morning_briefing.py` → `_gather_data` (MODIFY)

**Analog:** Self — existing `_gather_data` (lines 174–301)

**Existing gather pattern** (the block gather at lines 273–299 is the closest structural match — copy its best-effort try/except/silent-omit style):
```python
# PHASE 23 — BLOCK-01 example (lines 278–299):
try:
    from memory.firestore_db import BlockStore
    bs = BlockStore(...)
    block = bs.get_current()
    if block:
        week_num = (date.fromisoformat(today_iso) - date.fromisoformat("2026-06-21")).days // 7 + 1
        data["block"] = { ... }
    else:
        ...
except Exception:
    logger.warning("morning_briefing: block state fetch failed", exc_info=True)
```

**New gather blocks to add** (after the existing block gather, before `return data` at line 301):

```python
# PHASE 24 — COACH-05: today's and yesterday's raised coaching topics for dedup + prior-day recap
try:
    from memory.firestore_db import CoachingTopicStore
    _cts = CoachingTopicStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    yesterday_iso = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
    data["coaching_topics_today"] = _cts.topics_today(today_iso)
    data["coaching_topics_yesterday"] = _cts.topics_today(yesterday_iso)
    # D-08: yesterday's topics surfaced so morning briefing can recap unresolved prior-day misses
except Exception:
    logger.warning("morning_briefing: coaching topics fetch failed", exc_info=True)
    data["coaching_topics_today"] = []
    data["coaching_topics_yesterday"] = []
```

**Post-send coaching topic write** — in `run_morning_briefing` (line 122), after `send_and_inject` succeeds (line 140), mirror the post-send discipline:
```python
# PHASE 24 — COACH-05: record any coaching topics included in this briefing
try:
    _topics_included = today_data.get("coaching_topics_included") or []
    if _topics_included:
        from memory.firestore_db import CoachingTopicStore
        _cts = CoachingTopicStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        for _topic in _topics_included:
            _cts.add_topic(today_iso, _topic)
except Exception:
    logger.warning("morning_briefing: coaching topic record failed", exc_info=True)
```

**Integrated block framing (D-18):** The `_compose_briefing` function (lines 308–365) already injects `{coaching_guide}`. The D-18 "one integrated block" is a prompt-level change, not a code change. The gather data already provides all ingredients (`data["block"]`, `data["recovery_concern"]`, `data["calendar"]`). The compose path passes `today_data` as JSON — no structural code change needed, only the prompt update.

---

### `core/weekly_training_review.py` → `_gather_week_data` (MODIFY)

**Analog:** Self — existing `_gather_week_data` (lines 42–224)

**No new gather code needed** (RESEARCH Finding 10 confirmed): The `training_log` entries returned by `store.get_range()` will naturally include the `quality` field once it's been written by `TrainingLogStore.log_session`. `_gather_week_data` already returns the raw list with all fields present (or None). No structural change to the gather needed — the `quality` field is just there.

The `block_benchmarks` from `BenchmarkStore.get_block_benchmarks` (already gathered at lines 200–222) provides the per-facet data. This gather block is already in place.

**What DOES need to change:** The `_compose_review` function (lines 227–296) — add the coaching topic dedup gate check before compose and write after send, following the same pattern as `proactive_alerts` and `morning_briefing`:

```python
# In _compose_review or run_weekly_review, BEFORE compose:
try:
    from memory.firestore_db import CoachingTopicStore
    _cts = CoachingTopicStore(...)
    week_data["coaching_topics_today"] = _cts.topics_today(today_iso)
except Exception:
    logger.warning("weekly_review: coaching topics fetch failed", exc_info=True)
    week_data["coaching_topics_today"] = []
```

**Post-send write** (in `run_weekly_review` at line 299, after `send_and_inject` at line 312):
```python
# Mirror morning_briefing post-send topic write pattern
try:
    _topics_included = week_data.get("coaching_topics_included") or []
    if _topics_included:
        ...  # same CoachingTopicStore.add_topic loop
except Exception:
    logger.warning("weekly_review: coaching topic record failed", exc_info=True)
```

**`_compose_review` prompt system** (lines 242–264 — already follows morning_briefing pattern exactly, including `meal_audit` append):
```python
system_prompt = prompt_path.read_text(encoding="utf-8").replace("{today_date}", today_iso)
meal_audit = meal_audit_path.read_text(encoding="utf-8") if meal_audit_path.exists() else ""
if meal_audit:
    system_prompt = system_prompt + "\n\n" + meal_audit
user_message = json.dumps(week_data, ensure_ascii=False, indent=2, default=str)
```

Note: `weekly_training_review._compose_review` does NOT currently inject `{coaching_guide}` (unlike `_compose_briefing` and `_compose_alert` which do). Phase 24 may want to add the same `_get_orchestrator()._coaching_guide_content` injection here for strict-pushback + per-facet framing. Mirror the pattern from `morning_briefing._compose_briefing` lines 317–328.

---

### `core/main.py` → `_run_smart_loop` (MODIFY)

**Analog:** Self — existing `_run_smart_loop` (lines 488+)

**Current constant** (line 44):
```python
MAX_TOOL_ITERATIONS = 8
```

**Change to:**
```python
MAX_TOOL_ITERATIONS = 12   # raised Phase 24 — data-heavy coaching queries need up to 6 tool calls
```

**Current loop structure** (lines 543–668 — relevant sections):
```python
# Loop entry (line 543):
for iteration in range(MAX_TOOL_ITERATIONS):

# Response text extracted (line 579):
    response_text = response["text"]

# Early exit on no tool calls (lines 582–583):
    if not tool_calls:
        return response_text or ""

# ... tool execution ...

# Loop exhaustion fallback (lines 661–668):
logger.error(
    "Smart loop exceeded MAX_TOOL_ITERATIONS (%d) without a final text response.",
    MAX_TOOL_ITERATIONS,
)
return (
    "Apologies, Sir. This request required more processing steps than expected. "
    "Please rephrase or break it into smaller parts."
)
```

**Change:** Track `last_response_text` across iterations and return it at exhaustion if it's substantive (> 100 chars). Insert tracking variable BEFORE the loop, update it inside the loop after `response_text = response["text"]`, and use it in the fallback:

```python
# Before loop (after line 541 `smart_tools = tool_registry.get_smart_schemas(...)`):
last_response_text = ""   # Phase 24: track last substantive text to suppress double-send

for iteration in range(MAX_TOOL_ITERATIONS):
    # ... existing code ...
    response_text = response["text"]
    if response_text:
        last_response_text = response_text  # Phase 24: update tracker on each text output

    if not tool_calls:
        return response_text or ""
    # ... rest of iteration ...

# At loop exhaustion (replace lines 661–668):
logger.error(
    "Smart loop exceeded MAX_TOOL_ITERATIONS (%d) without a final text response.",
    MAX_TOOL_ITERATIONS,
)
# Phase 24 double-send fix: if the last iteration produced a substantive text
# alongside its tool calls, return it rather than the fallback (SC-1 still
# holds — this text was produced by the brain, not fabricated here).
if last_response_text and len(last_response_text) > 100:
    logger.warning(
        "Smart loop: returning partial response_text (%d chars) to avoid double-send",
        len(last_response_text),
    )
    return last_response_text
return (
    "Apologies, Sir. This request required more processing steps than expected. "
    "Please rephrase or break it into smaller parts."
)
```

**IMPORTANT:** The fallback string at lines 665–668 is referenced by `tests/test_autonomous.py::test_sentinel_substring_matches_main_constant` (CLAUDE.md §6 / line 51–54 of main.py comments). The text must NOT change. The new `last_response_text` return path is a separate early-return BEFORE the sentinel string — the sentinel string is still returned when no substantive text was produced.

---

### `core/tools.py` → `_handle_read_coaching_guide` (MODIFY — WR-02 hardening)

**Analog:** Self — existing fuzzy fallback loop (lines 1531–1541)

**Current fuzzy fallback** (lines 1531–1541 — the bug):
```python
# Fuzzy fallback: first section whose anchor contains any word of the query
for word in slug.split("-"):
    if not word:
        continue
    fallback = _re.compile(
        r"<!-- SECTION: [^>]*" + _re.escape(word) + r"[^>]* -->(.*?)(?=<!-- SECTION:|$)",
        _re.DOTALL | _re.IGNORECASE,
    )
    fm = fallback.search(content)
    if fm:
        return json.dumps({"topic": slug, "content": fm.group(1).strip()})
```

**Bug:** Returns first section matching ANY single word of the slug — e.g. `set` from `top-set-strength` matches any section anchor containing "set". No ambiguity check.

**Replace with (lines 1531–1541 full replacement):**
```python
# Fuzzy fallback: ONLY return if exactly one section matches the word (unambiguous).
# WR-02: short words (< 4 chars) are skipped — they over-match.
# If multiple sections match a word, skip that word (ambiguous) and try the next.
# If no word yields a unique match, return not-found JSON so the brain falls back
# to the slim coaching core (correct behavior for strict-coaching contexts).
for word in slug.split("-"):
    if not word or len(word) < 4:   # skip short words that over-match
        continue
    anchor_pattern = _re.compile(
        r"<!-- SECTION: [^>]*" + _re.escape(word) + r"[^>]* -->",
        _re.IGNORECASE,
    )
    candidate_anchors = anchor_pattern.findall(content)
    if len(candidate_anchors) == 1:
        # Exactly one match — unambiguous
        section_pattern = _re.compile(
            r"<!-- SECTION: [^>]*" + _re.escape(word) + r"[^>]* -->(.*?)(?=<!-- SECTION:|$)",
            _re.DOTALL | _re.IGNORECASE,
        )
        fm = section_pattern.search(content)
        if fm:
            return json.dumps({"topic": slug, "content": fm.group(1).strip()})
    # else: multiple matches or zero — skip this word, try next
```

The final `return json.dumps({"error": f"Section '{topic}' not found in COACHING_GUIDE.md"})` at line 1543 is UNCHANGED — it is the correct not-found response.

**Preserved:** T-22-04 mitigation (line 1506–1509) — slug normalization + regex-only matching — NOT changed. The fix only touches the fallback loop body.

---

### Prompt files (MODIFY — 4 files)

**Pattern:** All four prompt files follow the same structure: read by the LLM composition function, substituted with `{today_date}` (and `{coaching_guide}` where applicable), then passed as `system_prompt` to `LLMClient.chat()`. No structural code changes — pure content additions.

**`prompts/proactive_alert.md`**
- Analog: current file content (Phase 22 coaching integration already in this file per `_compose_alert` lines 495–508)
- Add sections for: strict skip pushback format (D-05 wording, named deficit + directional consequence), nutrition accountability (macro shortfall + fueling-slot miss + supplement rider), dedup semantics ("if coaching_topics_already_raised is non-empty, do not repeat those topics — reference them only if condition has worsened").

**`prompts/morning_briefing.md`**
- Analog: current file content (`{coaching_guide}` injection already in `_compose_briefing` lines 323–328)
- Add: D-18 integrated block instruction (weave named session + recovery state + fueling reminder into ONE block, not three separate labeled sections). Add: prior-day unresolved miss handling using `coaching_topics_yesterday` context.

**`prompts/weekly_training_review.md`**
- Analog: current file content (Phase 23 block/benchmark data already consumed)
- Add: per-facet within-block status framing using `block_benchmarks`; session quality trend framing using `training_log[].quality`; dedup gate semantics for `structural-critique:*` topics.

**`prompts/smart_agent.md`**
- Analog: current file content (renders via `render_smart_system` in main.py)
- Add: strict-pushback format instruction for reactive coaching queries (D-05/D-06/D-07 format — single ranked rec, "your call, Sir", named session + real-unit deficit). Add: reactive chat dedup clarification — "reactive answers are never suppressed by cron topics; you always answer fully."

---

## Shared Patterns

### Best-effort gather block with silent-omit
**Source:** `morning_briefing._gather_data` (lines 178–299) — every source is wrapped in its own try/except; on failure, set the key to `None` or `[]` and log at WARNING. Never crash the cron on a single data source failure.

**Apply to:** `_gather_nutrition_data` (new), all coaching-topic gather blocks in each cron.

```python
try:
    from memory.firestore_db import SomeStore
    store = SomeStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
    )
    data["key"] = store.some_read()
except Exception:
    logger.warning("cron_name: some_source fetch failed", exc_info=True)
    data["key"] = []   # or None — caller must use truthiness / None-check
```

### `_make_firestore_client()` local factory
**Source:** `proactive_alerts.py` lines 80–84, `morning_briefing.py` lines 31–33 — each file defines its own local `_make_firestore_client()` that reads from env vars.

**Apply to:** Any new store instantiation in cron files. Use `os.environ["GCP_PROJECT_ID"]` and `os.getenv("FIRESTORE_DATABASE", "(default)")` — never hardcode.

```python
def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    return _mfc(os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)"))
```

### Asia/Jerusalem date key
**Source:** `proactive_alerts.py` line 164, `morning_briefing.py` line 67.

**Apply to:** Every `CoachingTopicStore.has_topic() / add_topic() / topics_today()` call. Must use Jerusalem-time date, not UTC.

```python
_today_il = datetime.now(_TZ).date().isoformat()
# _TZ = ZoneInfo("Asia/Jerusalem")  # module-level constant in every cron file
```

### `_jsonsafe_doc` for Firestore reads that go through json.dumps
**Source:** `memory/firestore_db.py` line 735, used throughout `TrainingLogStore.get_recent` (line 864), `get_range` (line 912), etc.

**Apply to:** Any new Firestore read whose result is passed to `json.dumps`. The `updated_at: SERVER_TIMESTAMP` field round-trips as `DatetimeWithNanoseconds` and breaks serialization.

### Post-send write discipline (Phase 18 D-10 mirror)
**Source:** `autonomous.py` via `OutreachLogStore.append` contract documented in `CLAUDE.md §6`.

**Apply to:** `CoachingTopicStore.add_topic()` in ALL three crons. Always write coaching topic keys AFTER `send_and_inject` succeeds — never before. A crash between write and send creates a false-positive block.

### LLM composition with `{coaching_guide}` injection
**Source:** `morning_briefing._compose_briefing` lines 317–328; `proactive_alerts._compose_alert` lines 495–508.

**Apply to:** `weekly_training_review._compose_review` — this cron currently does NOT inject `{coaching_guide}` but Phase 24 needs it for per-facet strict coaching context.

```python
try:
    from core.autonomous import _get_orchestrator
    coaching_guide_content = _get_orchestrator()._coaching_guide_content
except Exception:
    logger.warning("weekly_review: coaching guide unavailable — proceeding without it")
    coaching_guide_content = ""
system_prompt = (
    prompt_path.read_text(encoding="utf-8")
    .replace("{coaching_guide}", coaching_guide_content)
    .replace("{today_date}", today_iso)
)
```

### Pure function / no I/O for testability
**Source:** `_slot_for` (line 425), `_evaluate_benchmark_state` (line 92), `_detect_weather_conflicts` (line 325), `_detect_overloaded_day` (line 376).

**Apply to:** `derive_session_quality`, `_macro_gap_check`, `_detect_slot_misses`, `_map_meals_to_slots`, `_resolve_anchor_times`. All new helper functions must be pure (no I/O) so they can be unit tested without Firestore/Garmin mocks.

---

## No Analog Found

All files have close analogs in the codebase. No "no analog" entries.

---

## Metadata

**Analog search scope:** `memory/`, `core/`, `prompts/`
**Files read:** 8 source files (full reads for files ≤ 476 lines; targeted offset/limit reads for larger files)
**Pattern extraction date:** 2026-06-06
**Line number verification:** All RESEARCH.md line numbers confirmed against live code; one minor annotation added (distinction between `_already_sent` call site line 197 vs function definition line 297).
