# Phase 33: Occasion Cascade - Pattern Map

**Mapped:** 2026-07-29
**Files analyzed:** 14 (modified) + 5 (new)
**Analogs found:** 19 / 19

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `core/autonomous.py` (`run_autonomous_tick` → gains `occasion` param / `_run_cascade` helper) | service (orchestrator) | event-driven (3-layer cascade) | itself — `run_autonomous_tick` (lines 1761-1929) is both the thing being generalized and its own best analog | exact (self-generalization) |
| `core/autonomous.py::_compose_layer2` / `_compose_followup_layer2` | service (compose helper) | request-response (LLM call) | itself (lines 1380-1560) — the follow-up compose sibling is the analog for a third "occasion compose" variant | exact |
| `core/nightly_review.py::run_nightly` (rerouted through cascade) | controller/service (occasion entry point) | event-driven → request-response | itself (lines 376-411) — keep gather/state, replace `_compose_nightly` call | exact (in-place rewire) |
| `core/morning_briefing.py` (new `run_morning_briefing_triggered`, `handle_tick`/state-machine deleted) | controller/service (occasion entry point) | event-driven → request-response | `core/nightly_review.py::run_nightly` (push-triggered, dedup-via-state-doc shape) | exact — nightly is the better template than morning's own legacy polling shape |
| `core/weekly_training_review.py::run_weekly_review` (rerouted through cascade, never self-skips) | controller/service (occasion entry point) | event-driven → request-response | `core/nightly_review.py::run_nightly` for the cascade call shape; itself for gather/`run_in_executor` pattern (lines 548-617) | exact |
| `core/task_dispatch.py::enqueue_occasion` (new) | service (Cloud Tasks dispatch) | event-driven → async dispatch | `core/task_dispatch.py::enqueue_hub_message` (lines 106-179) | exact |
| `interfaces/web_server.py::POST /trigger/morning` (new) | route/controller | request-response (bearer-auth trigger) | `interfaces/web_server.py::trigger_nightly` + `_verify_trigger_request` (lines 432-558) | exact |
| `interfaces/web_server.py::_verify_morning_trigger_request` (new) | middleware (auth) | request-response | `interfaces/web_server.py::_verify_trigger_request` (lines 432-473) | exact |
| `interfaces/web_server.py::POST /internal/process-occasion` (new) | route/controller (Cloud Tasks target) | event-driven (OIDC-gated internal endpoint) | `interfaces/web_server.py::/internal/process-hub-message` (lines 2586-2620ish) and `/internal/process-update` | exact |
| `interfaces/web_server.py::trigger_nightly` (D-32 fix: BackgroundTasks → Cloud Tasks) | route/controller | request-response → async dispatch | `interfaces/web_server.py::api_chat_send` (lines 2262-2352) — the proven "enqueue, ACK 202/200, never BackgroundTasks" shape | exact |
| `core/tools.py` (new `get_recent_decisions` schema + handler + dispatch entry) | tool/utility (brain-direct read tool) | CRUD (read) | `core/tools.py::forget_memory` schema (lines 497-522) + `_handle_get_training_history` (lines 2735-2744) for the `days`-parameter read-tool shape | exact |
| `memory/firestore_db.py::ActionLogStore` (new, D-25 action-audit store) | model/store (Firestore) | CRUD (append + range-read) | `memory/firestore_db.py::OutreachLogStore` (lines 2108-2221) — date-keyed doc + `ArrayUnion` append pattern | exact |
| `memory/firestore_db.py` (morning/nightly/weekly occasion state docs — `status` enum extended with `skipped_by_judgment`) | model/store (Firestore) | CRUD | `core/nightly_review.py::_get_state`/`_set_state` (lines 60-80) — the existing date-keyed `merge=True` state-doc pattern (no store class; direct collection access) | exact |
| `core/heartbeat.py` (4 new D-28 anomaly checks) | service (monitoring) | batch (hourly scan) | `core/heartbeat.py::check_cron_health` (lines 142-213) and `_check_push_health` (lines 261-338) — `Signal` construction + fingerprint/severity/remediation shape | exact |
| `core/tick_brain.py` / `prompts/autonomous_triage.md` (D-01/D-02 occasion guidance) | prompt/config | request-response | itself — `TickBrain.think()` (lines 189-290+) contract unchanged; only the rendered prompt content grows | exact (no code change, prompt-only) |
| `prompts/autonomous.md` (D-16/D-17 fold-in, D-23/D-24 write-and-disclose) | prompt/config | request-response | itself — shared Layer-2 compose prompt | exact |
| `prompts/nightly_occasion.md`, `prompts/morning_occasion.md`, `prompts/weekly_occasion.md` (new, D-35) | prompt/config | request-response | `prompts/autonomous_triage.md` / `prompts/autonomous.md` for tone/register; no existing "few-lines identity" prompt precedent | role-match (new pattern, small) |
| `.env`/`deploy.yml` (`OCCASION_CASCADE`, `MORNING_TRIGGER_TOKEN`) | config | — | `interfaces/web_server.py::_verify_trigger_request`'s `CRON_DEV_BYPASS` env-flag convention | exact |
| `tests/test_autonomous.py` (occasion bypass/topic-key tests) | test | unit | itself — existing `test_run_autonomous_tick_*` fixtures (lines 598-880) | exact |
| `tests/test_nightly_review.py` / `tests/test_morning_briefing.py` / `tests/test_weekly_training_review.py` / `tests/test_heartbeat.py` / `tests/test_tools.py` / `tests/test_task_dispatch.py` (new tests) | test | unit | `tests/test_nightly_review.py::test_trigger_nightly_*` (lines 415-522) for route/auth tests; `tests/test_autonomous.py` fixtures for cascade tests | exact |

## Pattern Assignments

### `core/autonomous.py` — `occasion` param / shared cascade helper (service, event-driven)

**Analog:** `run_autonomous_tick` itself (lines 1761-1929), `_compose_layer2` (1380-1467), `_compose_followup_layer2` (1469+)

**Full pipeline to generalize** (verbatim, current tick-only shape):
```python
async def run_autonomous_tick(bot, now: datetime | None = None) -> dict:
    if now is None:
        now = datetime.now(_TZ)
    situation = gather_situation(now)
    decision: dict = {"skipped": False, "sent": False, "trail": []}

    # Layer 0 gate (D-11 / SC-3) — empty signals = quiet tick, never call LLM.
    if situation.get("empty"):
        decision["skipped"] = "empty"
        decision["trail"].append("layer0_empty_signals")
        await _write_tick_log(now, situation, decision)
        return decision
    ...
    # Layer 0.5 — change-detection gate (MEM-05 efficiency).
    try:
        _sig_store = _tick_signature_store()
        _signature = _compute_signal_signature(situation)
        _last_signature = _sig_store.get()
        if _last_signature is not None and _signature == _last_signature:
            decision["trail"].append("signals_unchanged_since_last_tick")
            await _write_tick_log(now, situation, decision)
            return decision
        _sig_store.set(_signature)
    except Exception:
        logger.warning("autonomous: change-detection gate errored; proceeding", exc_info=True)

    # Layer 1 — triage.
    try:
        from core.tick_brain import TickBrain
        tb = TickBrain()
        triage_system = _load_prompt("prompts/autonomous_triage.md")
        triage_user_msg = _build_triage_prompt(situation, triage_system)
        verdict = tb.think(triage_user_msg, system_override=triage_system)
    except Exception:
        ...
    decision["trail"].append({"layer1": verdict})
    if not verdict.get("should_act"):
        decision["trail"].append("layer1_no_act")
        await _write_tick_log(now, situation, decision)
        return decision

    # Layer 2 — compose. draft/triage_reason/topic_key extracted from verdict.
    ...
    try:
        final_text = await _asyncio.get_running_loop().run_in_executor(
            None, _compose_layer2, situation, draft, triage_reason,
        )
        if not final_text or any(s in final_text for s in _SMART_LOOP_ERROR_SENTINELS):
            raise RuntimeError(...)
    except Exception as exc:
        logger.warning("autonomous: Layer 2 failed; falling back to draft (D-19): %s", exc)
        final_text = draft
    ...
    from core.scheduled_message import send_and_inject
    try:
        await send_and_inject(bot, final_text, inject_into_conversation=True)
    except Exception:
        decision["trail"].append("send_failed")
        await _write_tick_log(now, situation, decision)
        return decision
    decision["sent"] = True

    # D-10 — write to outreach_log ONLY after the send succeeded.
    try:
        from memory.firestore_db import OutreachLogStore
        ols = OutreachLogStore(project_id=..., database=...)
        ols.append(today_iso, {"topic_key": topic_key, "time": ..., "draft": draft,
                                "final": final_text, "tick_index": ...})
    except Exception:
        logger.warning(..., exc_info=True)

    decision["trail"].append({"shipped": topic_key})
    await _write_tick_log(now, situation, decision)
    return decision
```

**What each occasion module must change when calling into this shared helper:**
1. **Bypass point 1** — `if situation.get("empty")` early-return: skip entirely when `occasion is not None` (Pitfall 2). Occasions still get a "free" Layer-1 triage judgment regardless of signal emptiness.
2. **Bypass point 2** — the `_tick_signature_store()`/`_compute_signal_signature` block (lines 1814-1830): skip entirely when `occasion is not None` (Pitfall 1). An occasion fires on schedule, not on signal novelty.
3. **Layer 1 call unchanged** — same `TickBrain().think(triage_user_msg, system_override=triage_system)` contract; only the *content* of `triage_user_msg` differs (D-02/D-01 occasion guidance rendered into the **user message**, per the Anti-Pattern note in RESEARCH — do not bloat the shared system prompt).
4. **Layer 2 call unchanged in shape** — reuse `_compose_layer2`'s pattern (`_get_orchestrator()._run_smart_loop(...)`, never a fresh `AgentOrchestrator()`), but the synthetic user content must additionally carry: (a) the occasion's own specialized gather data merged in, (b) D-17's full outreach-text fold-in context, (c) D-23/D-24 write-and-disclose framing (lives in `prompts/autonomous.md`, not per-call).
5. **`topic_key`** — deterministic for occasions: `f"nightly:{target_date}"` / `f"morning:{today_iso}"` / `f"weekly:{today_iso}"`, replacing the tick's `verdict.get("topic_key")`/`_synthesize_topic_key` fallback chain (still land in the **same** `OutreachLogStore`, per D-18).
6. **`skipped_by_judgment` vs. `layer1_no_act`** — the existing `decision["trail"].append("layer1_no_act"); return decision` early-return (no send) is *exactly* the D-01/D-02 skip shape already implemented for the tick — occasions reuse this control flow but the *caller* (nightly/morning/weekly module) must translate a `not verdict.get("should_act")` outcome into `status: "skipped_by_judgment"` in its own state doc, and (D-06) source `daily_note` from `verdict.get("draft", "")`.

**Anti-pattern warning (from RESEARCH, load-bearing):** Don't route occasions through `gather_situation()` alone — it is today-scoped. Keep each occasion's specialized gather (`_gather_tomorrow`, `_gather_data`, `_gather_week_data`) and merge its output into the situation dict passed to Layer 1/2, rather than trying to make `gather_situation()` itself tomorrow/week-aware.

---

### `core/nightly_review.py::run_nightly` (controller/service, event-driven → request-response)

**Analog:** itself (full file already read, 442 lines)

**Current send/state-write shape to preserve, with two surgical changes:**
```python
async def run_nightly(bot: Bot, target_date: str, *, trigger: str, dedup: bool = True) -> bool:
    if dedup and was_sent(target_date):
        logger.info("nightly_review: already sent for %s — skipping (%s)", target_date, trigger)
        return False

    loop = asyncio.get_running_loop()
    built = await loop.run_in_executor(None, _build_nightly, target_date)   # journal + gather + compose

    from core.scheduled_message import send_and_inject
    await send_and_inject(bot, built["text"], inject_into_conversation=True, message_class="review")

    # Mark sent + persist tomorrow snapshot AFTER the send succeeds (write-after-send).
    _set_state(target_date, {
        "status": "sent", "trigger": trigger,
        "sent_at": datetime.now(_TZ).isoformat(),
        "structured": built["structured"],
    })
    return True
```

**Changes required (D-04, D-05, D-06, D-07, OCC-01, OCC-06 flag):**
- `was_sent(target_date)` must now check `status in {"sent", "skipped_by_judgment"}` for the backstop's terminal semantics (D-04) — but a fresh Sleep-Focus trigger should still treat `skipped_by_judgment` as terminal too (D-12 dedup applies to *any* terminal status, not just `"sent"`).
- `_build_nightly` (`_ensure_reflection` + `_gather_tomorrow` + `_compose_nightly`) — the `_ensure_reflection(target_date)` call (journal write) must run **unconditionally before** the cascade routes to skip-or-send (D-07: "nightly journal is always written"), i.e. keep it exactly where it is today (first line of `_build_nightly`), just make sure the skip branch below still reaches it.
- Replace `_compose_nightly(journal, tomorrow, target_date)` with the shared cascade call (`occasion="nightly"`) behind the `OCCASION_CASCADE` flag (D-30/Pattern 5): `if os.getenv("OCCASION_CASCADE", "false").lower() == "true": <cascade path> else: <existing _compose_nightly path, byte-identical>`.
- **D-05 override of the existing write-after-send ordering**: the `structured` snapshot write currently sits inside the single `_set_state(...)` call **after** `send_and_inject` — this must split into two writes: `structured` written unconditionally (sent OR skipped), `status`/`sent_at`/`trigger` written only on the actual branch taken. Mirror `morning_briefing.py::run_morning_briefing`'s existing `skipped_by_directive` early-return shape (below) for the skip branch.
- `_plain_text_fallback` (SC-1 infra path, lines 319-353) and `_compose_nightly`'s two-tier LLM fallback (primary Sonnet-5 → Gemini fallback → `_plain_text_fallback`, lines 232-316) survive **completely untouched** on the `OCCASION_CASCADE=false` path — this is the A/B's "legacy path stays byte-identical" contract.

---

### `core/morning_briefing.py` — push-triggered replacement (controller/service, event-driven → request-response)

**Analog for the NEW entry point:** `core/nightly_review.py::run_nightly` (dedup-via-state-doc + trigger-string shape), not `morning_briefing.py`'s own `handle_tick`/state machine (being deleted).

**Deleted code (D-09), verbatim for reference — do not resurrect any of this shape:**
```python
# core/morning_briefing.py::handle_tick, lines 58-124 — ENTIRE FUNCTION DELETED
async def handle_tick(bot: Bot) -> None:
    now = datetime.now(_TZ)
    if (now.hour, now.minute) > (10, 15):          # <- the cutoff, DELETED
        return
    state = _get_state(today_iso)
    status = state.get("status", "pending")
    if status in {"sent", "manual"}:
        return
    if status == "pending":
        sleep_data = _fetch_garmin_safe(today_iso)  # <- the Garmin gate, DELETED
        if not sleep_data:
            return
        ...  # sync_detected / retry_count state machine — ALL DELETED
```

**Surviving compose entry point to adapt** (`run_morning_briefing`, lines 130-227) — its skip-vs-send branch shape is the exact template for `skipped_by_judgment`:
```python
async def run_morning_briefing(bot: Bot, today_iso: str, *, dedup: bool = True) -> bool:
    if dedup:
        state = _get_state(today_iso)
        if state.get("status") in {"sent", "manual"}:
            return False
    today_data = _gather_data(today_iso)
    text = _compose_briefing(today_data, today_iso)
    skip, skip_reason, text = _parse_briefing_skip(text)     # <- REPLACED by Layer-1 should_act=False
    if skip:
        logger.info("morning_briefing: skipped_by_directive for %s (%s)", today_iso, skip_reason)
        _set_state(today_iso, {"status": "skipped_by_directive", "skip_reason": skip_reason})
        return True                                          # <- returns BEFORE send + BEFORE structured/daily_note
    from core.scheduled_message import send_and_inject
    await send_and_inject(bot, text, inject_into_conversation=True, message_class="briefing")
    ...
    _set_state(today_iso, {"structured": {...}})              # <- currently send-gated; D-05 makes this unconditional
    ...
    _sss.set({"daily_note": _coach_note_one_line, "daily_note_date": today_iso})  # <- currently send-gated; D-06 sources this from verdict["draft"] on skip
    return False
```

**New entry point shape** (mirrors `run_nightly`'s trigger-string parameter, D-14's existing "manual" precedent already visible in `_handle_run_morning_briefing` tool handler at `core/tools.py:1891-1911`):
```python
async def run_morning_briefing_triggered(bot: Bot, today_iso: str, *, trigger: str, dedup: bool = True) -> bool:
    # trigger: "focus" | "manual" — mirrors run_nightly's "focus" | "backstop"
    ...
```
- `_get_state`/`_set_state` (lines 36-51) survive **byte-identical** — same `_make_firestore_client` + `collection(_COLLECTION).document(today_iso)` pattern as `nightly_review.py`.
- D-15 widened window: reuse `core.nightly_review._get_state(yesterday_iso)` — already imported into `morning_briefing.py::_gather_data` at line 322 (`from core.nightly_review import _get_state as _nightly_state`) for the existing `since_last_night` delta read; the "did last night's nightly run" check is the same call, just test `bool(nightly.get("status") in {"sent", "skipped_by_judgment"})` instead of just reading `structured`.
- `_fetch_garmin_safe`, `_sync_bodyweight_from_garmin`, `_gather_data` (lines 234-526) all survive **unchanged** — D-11 says "compose without it and name the gap" if Garmin hasn't synced, which `_gather_data`'s existing `data["garmin"] = {"state": 2}` fallback already produces (no gather-code change needed, only removing the `handle_tick` gate that used to wait for `state == 1`).

---

### `core/weekly_training_review.py::run_weekly_review` (controller/service, event-driven → request-response)

**Analog:** `core/nightly_review.py::run_nightly` for the cascade-call shape; itself for the `run_in_executor` blocking-work-offload pattern (D-03: never self-skips).

**Current send shape to preserve (`run_weekly_review`, lines 548-617):**
```python
async def run_weekly_review(bot, today_iso: str) -> None:
    loop = asyncio.get_running_loop()
    week_data = await loop.run_in_executor(None, _gather_week_data, today_iso)
    message = await loop.run_in_executor(None, _compose_review, week_data, today_iso)  # <- REPLACED by cascade call (OCCASION_CASCADE flag)

    skip, skip_reason, message = _parse_review_skip(message)   # <- D-03: occasion cascade must NEVER produce this skip; only the Phase-31 directive veto (Step-0) may skip
    if skip:
        return

    from telegram.error import TimedOut
    from core.scheduled_message import send_and_inject
    try:
        await send_and_inject(bot, message, inject_into_conversation=True, message_class="review")
    except TimedOut:
        await asyncio.sleep(2)
        await send_and_inject(bot, message, inject_into_conversation=True, message_class="review")

    # Post-send topic write — SURVIVES UNCHANGED
    try:
        _topics_included = week_data.get("coaching_topics_included") or []
        if _topics_included:
            from memory.firestore_db import CoachingTopicStore
            _cts = CoachingTopicStore(project_id=..., database=...)
            for _topic in _topics_included:
                _cts.add_topic(today_iso, _topic)
    except Exception:
        logger.warning(..., exc_info=True)
```

**D-03 implementation note:** the shared cascade helper's `if not verdict.get("should_act"): return decision` early-return (the tick's normal skip path) must be **bypassed for `occasion="weekly_review"`** — Layer 1's `should_act` verdict governs shape/emphasis via the draft/reason fields injected into Layer 2's prompt, never the send/no-send decision. Concretely: for the weekly occasion, treat Layer 1 as advisory-only and always proceed to Layer 2 compose + send, UNLESS the Step-0 standing-directive veto fired (Phase 31 invariant, checked upstream of Layer 1 exactly as `_parse_review_skip`'s replacement source — the directive veto, not a `_parse_*_skip` JSON trailer).

**Must survive untouched (Pitfall 9):** `_derive_structural_topics` (lines 362-386) and its call site inside `_gather_week_data` (`data["coaching_topics_included"] = _derive_structural_topics(data)`, line 340) — this is deterministic non-LLM dedup-key derivation, unrelated to the `_compose_review` replacement. Do not delete it alongside `_compose_review`/`_parse_review_skip`.

**`max_tokens=32000` note:** `_compose_review`'s existing brain call sets `max_tokens=32000` (line 472) because Sonnet's internal thinking previously exhausted the default 16K mid-thought (2026-07-19 incident). The new cascade's Layer-2 `_run_smart_loop` call does not currently set a custom `max_tokens` for weekly-scale compose — flag this as a planning risk (the weekly's data volume is the largest compose in the system).

---

### `core/task_dispatch.py::enqueue_occasion` (new, service, event-driven → async dispatch)

**Analog:** `enqueue_hub_message` (lines 106-179), which itself mirrors `enqueue_update` (lines 54-104) exactly.

**Full pattern to copy (only the target-URL and payload shape change):**
```python
def enqueue_occasion(occasion: str, *, trigger: str, target_date: str | None = None) -> bool:
    """Enqueue an occasion compose for full-CPU agent processing.

    Mirrors enqueue_hub_message exactly — same queue, same OIDC token, same
    dispatch deadline — but targets /internal/process-occasion instead of
    /internal/process-hub-message, and carries {occasion, trigger, target_date}.
    """
    queue = os.getenv("CLOUD_TASKS_QUEUE", "")
    if not queue:
        return False
    try:
        project = os.environ["GCP_PROJECT_ID"]
        location = os.getenv("CLOUD_TASKS_LOCATION", "me-central1")
        base_url = os.environ["CLOUD_RUN_URL"]
        sa_email = os.environ["CLOUD_SCHEDULER_SA_EMAIL"]

        client = _get_client()
        parent = client.queue_path(project, location, queue)
        payload: dict = {"occasion": occasion, "trigger": trigger}
        if target_date:
            payload["target_date"] = target_date
        task = {
            "dispatch_deadline": {"seconds": _DISPATCH_DEADLINE_SECONDS},
            "http_request": {
                "http_method": "POST",
                "url": f"{base_url}/internal/process-occasion",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode("utf-8"),
                "oidc_token": {
                    "service_account_email": sa_email,
                    "audience": base_url,
                },
            },
        }
        client.create_task(request={"parent": parent, "task": task})
        return True
    except Exception:
        logger.exception("Cloud Tasks enqueue failed for occasion=%s — caller should surface 503/degrade", occasion)
        return False
```
**Invariant to preserve:** "Never raises — the caller must be able to degrade rather than crash" (both `enqueue_update` and `enqueue_hub_message` return `False` on any failure, never propagate). `enqueue_occasion` must follow the same contract; per D-32's own example code in RESEARCH, the trigger route falls back to `BackgroundTasks` only as a degraded path, not primary.

---

### `interfaces/web_server.py::POST /trigger/morning` (new, route/controller, request-response)

**Analog:** `_verify_trigger_request` (lines 432-473) + `trigger_nightly` (lines 539-558), with the D-32 BackgroundTasks defect replaced by Cloud Tasks dispatch (mirror `api_chat_send`, lines 2262-2352).

**Auth pattern to mirror exactly** (swap only the env var name and log strings):
```python
async def _verify_trigger_request(request: Request) -> None:
    if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
        logger.info("CRON_DEV_BYPASS=true — skipping nightly-trigger auth")
        return
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Missing or malformed Authorization header"})
    received = auth_header.removeprefix("Bearer ").strip()
    expected = os.environ.get("NIGHTLY_TRIGGER_TOKEN", "")
    if not expected:
        logger.error("NIGHTLY_TRIGGER_TOKEN env unset — refusing all nightly-trigger auth")
        raise HTTPException(status_code=500, detail={"error": "Server misconfigured"})
    if not hmac.compare_digest(received.encode(), expected.encode()):
        client = request.client.host if request.client else "?"
        redacted = received[:4] + "..." + received[-4:] if len(received) >= 8 else "***"
        logger.warning("nightly-trigger auth failed from %s (token_prefix=%s)", client, redacted)
        raise HTTPException(status_code=403, detail={"error": "Invalid token"})
```
→ `_verify_morning_trigger_request` is a byte-for-byte copy with `NIGHTLY_TRIGGER_TOKEN` → `MORNING_TRIGGER_TOKEN` (D-13: **distinct** secret, not shared).

**Current (defective) route — do NOT copy the `background_tasks.add_task` line:**
```python
@app.post("/trigger/nightly")
async def trigger_nightly(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    await _verify_trigger_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    target = nightly_target_date_now()
    background_tasks.add_task(_run_nightly_background, target, "focus")   # <- D-32 DEFECT, being fixed
    return JSONResponse(status_code=202, content={"accepted": True})
```

**D-32-fixed shape to build, mirroring `api_chat_send`'s enqueue-then-202 discipline:**
```python
@app.post("/trigger/morning")
async def trigger_morning(request: Request) -> JSONResponse:
    await _verify_morning_trigger_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    from core.task_dispatch import enqueue_occasion
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    ok = enqueue_occasion("morning", trigger="focus", target_date=today_iso)
    if not ok:
        # graceful degrade — same class as enqueue_hub_message's False path;
        # NEVER background_tasks.add_task here (that is the exact defect D-32 fixes)
        return JSONResponse(status_code=503, content={"accepted": False, "error": "dispatch unavailable"})
    return JSONResponse(status_code=202, content={"accepted": True})
```
`trigger_nightly` gets the identical rewrite (drop the `BackgroundTasks` param, call `enqueue_occasion("nightly", trigger="focus")`).

**New `/internal/process-occasion` target** — mirror `/internal/process-hub-message`'s OIDC-gate + dispatch-to-module shape (`_verify_cron_request`, same as `/internal/process-update`), reading `{occasion, trigger, target_date}` from the Cloud Tasks body and calling the appropriate `core.nightly_review.run_nightly` / `core.morning_briefing.run_morning_briefing_triggered` / `core.weekly_training_review.run_weekly_review`.

---

### `core/tools.py::get_recent_decisions` (new, tool/utility, CRUD read)

**Analog:** `forget_memory` schema shape (lines 497-522) + `_handle_get_training_history`'s `days`-parameter read pattern (lines 2735-2744).

**Schema to add to `TOOL_SCHEMAS`** (mirrors `forget_memory`'s description/input_schema shape):
```python
{
    "name": "get_recent_decisions",
    "description": (
        "Look back at recent tick/occasion judgment calls — what Klaus decided, "
        "why, what was sent (or not), and any calendar/task actions taken. "
        "Call this directly — do NOT delegate to the worker. Use when Amit asks "
        "why Klaus did or didn't say something recently, or what he changed on "
        "the calendar."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many days back to look. Default 2.",
            },
        },
        "required": [],
    },
},
```

**Handler pattern** (mirrors `_handle_get_training_history`'s `default=str`-guarded `json.dumps` over a store range-read):
```python
def _handle_get_recent_decisions(days: int = 2) -> str:
    """OCC-07 / D-26: brain-direct read of recent tick/occasion decisions + actions."""
    # V5 input validation (Security Domain): bound days before it drives a range query.
    days = max(1, min(int(days), 30))
    from memory.firestore_db import TickLogStore, ActionLogStore
    tls = TickLogStore(project_id=os.environ["GCP_PROJECT_ID"],
                        database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
    als = ActionLogStore(project_id=os.environ["GCP_PROJECT_ID"],
                          database=os.environ.get("FIRESTORE_DATABASE", "(default)"))
    # ... aggregate ticks_for_date() across `days` dates + als.get_recent(days) ...
    return json.dumps({"decisions": [...], "actions": [...]}, default=str)
```

**Registration** (both required, mirrors `forget_memory`'s three touch-points exactly):
```python
# SMART_AGENT_DIRECT_TOOLS frozenset (line 40-88) — add:
"get_recent_decisions",

# _HANDLERS dict (line 3134-3206) — add:
"get_recent_decisions": lambda args: _handle_get_recent_decisions(**args),
```
`get_smart_schemas()` (lines 3215-3243) requires no change — it already filters `TOOL_SCHEMAS` by `SMART_AGENT_DIRECT_TOOLS` membership.

**D-27 constraint on the read, not the tool contract:** the skip taxonomy this tool surfaces must never be *injected* into a compose prompt proactively (that's a prompt-design constraint on `prompts/autonomous.md`, not on this handler) — the handler itself just returns the data; D-27's "skips never surface unasked" is enforced by never calling this tool from the cascade's own compose step for skip-content, only from a live chat turn when Amit asks.

---

### `memory/firestore_db.py::ActionLogStore` (new, model/store, CRUD)

**Analog:** `OutreachLogStore` (lines 2108-2221) — date-keyed doc + `ArrayUnion` append, **deliberately NOT reusing `OutreachLogStore` itself** (Don't-Hand-Roll table: "mixing send-gated and non-send-gated writes into one collection would blur the write-after-send discipline").

**Pattern to copy (collection name changes; write-after-send discipline is explicitly INVERTED — D-25 requires write-at-action-time, not write-after-send):**
```python
class ActionLogStore:
    """Per-day record of Layer-2 write actions (D-25) — independent of send success.

    Schema (collection: ``action_log/{YYYY-MM-DD}``):
        date: str
        entries: list[dict]   # each = {action, detail, occasion, at, disclosed}
        updated_at: SERVER_TIMESTAMP  # doc-level only, NOT inside entries (NOTE 2 pattern)

    D-25 — written the MOMENT the write happens, decoupled from send success.
    NEVER gate this append on send_and_inject's outcome (unlike OutreachLogStore.append).
    """
    _COLLECTION = "action_log"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def append(self, date_str: str, entry: dict) -> None:
        # IDENTICAL shape to OutreachLogStore.append — ArrayUnion + merge=True,
        # static ISO strings inside entry (NOT firestore.SERVER_TIMESTAMP — see
        # OutreachLogStore's NOTE 2, same ArrayUnion deep-equality trap applies here).
        try:
            self._col.document(date_str).set(
                {"date": date_str, "entries": firestore.ArrayUnion([entry]),
                 "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("ActionLogStore.append(%r) failed", date_str, exc_info=True)
            raise

    def get_recent(self, days: int) -> list[dict]:
        # Range-read pattern mirrors StrengthSessionStore.get_range /
        # TrainingLogStore.get_range (memory/firestore_db.py:1290-1305) — iterate
        # date keys, not a Firestore range query (this store is doc-per-date, not
        # field-indexed), reading each day's `entries` via get_today-style access.
        ...

    def undisclosed(self) -> list[dict]:
        # D-25: entries with disclosed=False — feeds "next occasion sees I already
        # did this but never told him" (the compose prompt reads this, and heartbeat
        # D-28 #4 reads it too).
        ...
```

---

### Occasion state docs — `status` enum extension (model/store, CRUD)

**Analog:** `core/nightly_review.py::_get_state`/`_set_state` (lines 55-80) and `morning_briefing.py::_get_state`/`_set_state` (lines 31-51) — **no store class exists for these**, both use raw `_make_firestore_client(...).collection(_COLLECTION).document(date_str)` with `.set(fields, merge=True)`. This is the pattern to keep — do not introduce a new store class for `nightly_reviews`/`morning_briefings`/`weekly_reviews` docs; only the `status` string enum grows.

```python
def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    return _mfc(os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)"))

def _get_state(target_date: str) -> dict:
    try:
        client = _make_firestore_client()
        snap = client.collection(_COLLECTION).document(target_date).get()
        return (snap.to_dict() or {}) if snap.exists else {}
    except Exception:
        logger.warning(...); return {}

def _set_state(target_date: str, fields: dict) -> None:
    try:
        client = _make_firestore_client()
        client.collection(_COLLECTION).document(target_date).set(fields, merge=True)
    except Exception:
        logger.warning(...)
```
**New `status` values to add:** `"skipped_by_judgment"` (Pattern 2, terminal per D-04), alongside existing `"sent"` / `"skipped_by_directive"` (morning) / (implicit `"sent"`-only for nightly today). Add a `composed_via` field (`"llm"` | `"plain_text_fallback"` | absent-on-skip) per Pitfall 3 so `skipped_by_judgment` is never confusable with the infra-failure path in logs.

**ISO-timestamp-on-read convention (project-wide trap, applies to any new read tool touching these docs):**
```python
# memory/firestore_db.py:1018-1027 — _jsonsafe_doc
def _jsonsafe_doc(d: dict) -> dict:
    """... DatetimeWithNanoseconds breaks json.dumps ... converted to ISO-8601 here."""
    return {k: _jsonsafe_value(v) for k, v in d.items()}

def _jsonsafe_value(v):
    if isinstance(v, dict): return {k: _jsonsafe_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_jsonsafe_value(x) for x in v]
    if isinstance(v, Decimal): return float(v)
    iso = getattr(v, "isoformat", None)
    if callable(iso):
        try: return iso()
        except Exception: ...
```
`get_recent_decisions` and `ActionLogStore`'s reads MUST route through `_jsonsafe_doc` (or an equivalent field-level ISO conversion) before `json.dumps` — this is the exact MealStore/TrainingLogStore bug from project MEMORY.md, and applies identically here since `updated_at`/`captured_at`-style SERVER_TIMESTAMP fields will appear in both new stores.

---

### `core/heartbeat.py` — 4 new D-28 anomaly checks (service, batch)

**Analog:** `check_cron_health` (lines 142-213) for the `Signal`-construction + fingerprint/severity/remediation shape; `_check_push_health` (lines 261-338) for a "read a store, evaluate N conditions, emit Signals" checker with multiple condition blocks — the closest structural match for 4 distinct anomaly classes in one function.

**Signal construction pattern to copy exactly (severity/area/title/detail/remediation, `fingerprint` used for incident dedup):**
```python
signals.append(Signal(
    fingerprint=f"cron:{job_id}:stale",
    severity=SEVERITY_CRITICAL, area="cron",
    title=f"{job_id} has not run in {age_h:.0f}h",
    detail=f"Last run {last.isoformat()}; expected within {max_hours}h.",
    remediation=f"Check the Cloud Scheduler job for {job_id} and Cloud Run logs.",
))
```

**D-28 #1 (errored occasion):** read the occasion's own state doc `composed_via` field (Pitfall 3/8 — `_log_cron_run(..., ok=True)` alone cannot detect this), not the generic `heartbeat_runs` ledger — mirror `_check_push_health`'s "read a dedicated store, not the generic cron ledger" approach.

**D-28 #2 (skip streak):** needs a new helper walking N days of occasion state docs and counting a consecutive `status == "skipped_by_judgment"` run — no existing streak-counter analog in `heartbeat.py` (the closest is `consecutive_failures` on the cron ledger doc, `check_cron_health` lines 204-212, which counts a different thing — infra failures, not judgment skips). Discretion: pick threshold N (RESEARCH flags this as open).

**D-28 #3 (weekly not firing):** extend `_CRON_MAX_STALENESS_HOURS` staleness-check style (lines 108-118, `"weekly-training-review": 170`) — this pattern already exists and should be the analog directly, just re-verify it still applies once the weekly's send path routes through the cascade+flag (D-03: it should never legitimately be silent, so a stale check remains the right shape, unlike nightly/morning where the new `skipped_by_judgment` status must NOT trip a staleness alert).

**D-28 #4 (undisclosed actions pending):** read `ActionLogStore.undisclosed()` (new store above) — closest existing analog is `check_daily_spend`'s pattern of reading a store and emitting a single alert-shaped payload (lines 819-863) rather than a list of `Signal`s; discretion on which shape `get_recent_decisions`' `undisclosed` reads should take here.

**Note on `_CRON_MAX_STALENESS_HOURS["morning-briefing"]` (26h entry, line 109):** once `morning-briefing-tick` retires (D-10/D-31), this entry needs re-pointing at the `/trigger/morning` ledger or removal — Claude's Discretion per RESEARCH Assumption A3, but must not be left dangling (false "stale" alert once the old cron truly stops running).

---

### `OCCASION_CASCADE` feature flag (config, env-driven)

**Analog:** `CRON_DEV_BYPASS` — the only existing env-flag-as-behavior-switch precedent in the codebase (`interfaces/web_server.py::_verify_trigger_request` line 449, `_verify_cron_request` similarly):
```python
if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
    logger.info("CRON_DEV_BYPASS=true — skipping nightly-trigger auth")
    return
```
**Recommended `OCCASION_CASCADE` shape** (D-30: nightly + weekly only, morning has no flag branch):
```python
if os.getenv("OCCASION_CASCADE", "false").lower() == "true":
    # new shared-cascade path (occasion="nightly" | "weekly_review")
    ...
else:
    # existing single-shot _compose_nightly / _compose_review path, UNCHANGED
    ...
```
Must be added to `deploy.yml`'s `--set-env-vars` (per CLAUDE.md invariant: this flag clobbers out-of-band Cloud Run env vars if omitted from the deploy script) alongside `MORNING_TRIGGER_TOKEN`.

---

### Test files — fixtures, Firestore fakes, LLM mocks

**Analog:** `tests/test_autonomous.py` (lines 71-230 for fixture/mock infra; 598-880 for cascade-outcome tests), `tests/test_nightly_review.py` (lines 415-522 for route/auth tests), `tests/test_token_budget.py` (guard-test structure).

**Cascade-outcome test shape to mirror** (`test_run_autonomous_tick_triage_no`, lines 614-629 — the "should_act=False" skip path, directly reusable for `skipped_by_judgment` occasion tests):
```python
def test_run_autonomous_tick_triage_no(mock_bot, fixed_now):
    """Triage returns should_act=False — no Layer-2, no send."""
    sit = _live_situation(fixed_now)
    tb_instance = MagicMock()
    tb_instance.think.return_value = {"should_act": False, "reason": "all quiet"}
    with patch.object(autonomous, "gather_situation", return_value=sit), \
         patch("core.tick_brain.TickBrain", return_value=tb_instance), \
         patch.object(autonomous, "_compose_layer2") as compose, \
         patch("core.scheduled_message.send_and_inject", new=AsyncMock()) as send, \
         patch.object(autonomous, "_write_tick_log", new=AsyncMock()):
        decision = asyncio.run(autonomous.run_autonomous_tick(mock_bot, fixed_now))
    tb_instance.think.assert_called_once()
    compose.assert_not_called()
    send.assert_not_called()
    assert decision["sent"] is False
```

**Route/auth test shape to mirror exactly** (`test_trigger_nightly_rejects_missing_token`/`_bad_token`/`_dev_bypass_acks_and_runs_in_background`, lines 436-499) — reuse `_build_test_client` verbatim for `/trigger/morning`, swap `NIGHTLY_TRIGGER_TOKEN` → `MORNING_TRIGGER_TOKEN`; the `_dev_bypass_acks_and_runs_in_background` test needs updating for D-32 (asserts `enqueue_occasion` was called, not that a `BackgroundTasks`-executed coroutine ran — the `run_mock.assert_awaited_once()` pattern shifts to `enqueue_mock.assert_called_once()`).

**Firestore fake / module-stub pattern:** `_install_firestore_mock()` (test_autonomous.py line 86) and `_build_test_client`'s `sys.modules` stub dict (test_nightly_review.py lines 415-433) — both are the established way to boot `interfaces.web_server`/`core.autonomous` without live GCP creds; reuse for all new test files (`test_morning_briefing.py`, `test_heartbeat.py`, `test_tools.py`, `test_task_dispatch.py`).

**Token-budget guard (mandatory re-run gate, not just a test to write):** `tests/test_token_budget.py::test_maximal_triage_prompt_plus_completion_budget_fits_groq_ceiling` — any edit to `prompts/autonomous_triage.md` (D-02 four-skip-causes, D-01 speak-default-flip) MUST re-run this test before considering the edit done; current margin is 7,146/7,200 tokens (54-token headroom).

---

## Shared Patterns

### Cascade orchestration (Layer 0 → 0.5 gate → Layer 1 → Layer 2 → send → log)
**Source:** `core/autonomous.py::run_autonomous_tick` (lines 1761-1929)
**Apply to:** `core/nightly_review.py`, `core/morning_briefing.py`, `core/weekly_training_review.py` — every occasion module routes through this shared function/helper instead of its own single-shot `LLMClient.chat()` call.

### Write-after-send vs. write-at-action-time (two DIFFERENT invariants, do not conflate)
**Source:** `OutreachLogStore.append` (D-10, gated on `send_and_inject` success) vs. the new `ActionLogStore.append` (D-25, gated on nothing — written the instant a calendar/task write happens)
**Apply to:** any code touching sends (`OutreachLogStore`) vs. any code touching proactive writes (`ActionLogStore`) — never merge these two logs or their gating logic.

### Date-keyed Firestore state doc, `merge=True`, `_get_state`/`_set_state` pair
**Source:** `core/nightly_review.py:55-80`, `core/morning_briefing.py:31-51`
**Apply to:** all three occasion state docs (`nightly_reviews/{date}`, `morning_briefings/{date}`, new `weekly_reviews/{date}` if one doesn't already exist) — same idempotency/dedup contract (D-12).

### Bearer-token trigger auth, refuse-all on unset env, constant-time compare
**Source:** `interfaces/web_server.py::_verify_trigger_request` (lines 432-473)
**Apply to:** the new `_verify_morning_trigger_request`. Never regress to `==` comparison; never fail-open on unset secret.

### Cloud Tasks dispatch — enqueue, never BackgroundTasks for agent-turn work
**Source:** `core/task_dispatch.py::enqueue_update`/`enqueue_hub_message`; `interfaces/web_server.py::api_chat_send` (the caller-side "enqueue, return early, degrade to 503 on enqueue failure" pattern)
**Apply to:** `enqueue_occasion` (new), `trigger_nightly` (fixed), `trigger_morning` (new), and the `/cron/*` occasion routes (D-32's "for consistency" extension).

### `_jsonsafe_doc`/ISO-timestamp-on-read
**Source:** `memory/firestore_db.py:1018-1050`
**Apply to:** `get_recent_decisions` handler, `ActionLogStore` reads, any occasion-state-doc read that flows into `json.dumps` — `DatetimeWithNanoseconds` (SERVER_TIMESTAMP round-trip) breaks `json.dumps` unless coerced first (bit MealStore + TrainingLogStore historically; will bite `action_log`/`nightly_reviews`/`morning_briefings` docs identically since they all use `firestore.SERVER_TIMESTAMP`/`updated_at`).

### `Signal` construction for heartbeat anomaly checks
**Source:** `core/heartbeat.py::check_cron_health` (142-213), `_check_push_health` (261-338)
**Apply to:** all four D-28 anomaly checks — same `fingerprint`/`severity`/`area`/`title`/`detail`/`remediation` shape so existing incident-registration/dedup machinery (`_register_incidents`, `_resolve_absent`) works unmodified.

### Env-flag-as-behavior-switch
**Source:** `CRON_DEV_BYPASS` (`interfaces/web_server.py:449`)
**Apply to:** `OCCASION_CASCADE` (nightly + weekly branch points only, per D-30).

### Tool registration triad (schema + `_HANDLERS` entry + `SMART_AGENT_DIRECT_TOOLS` membership)
**Source:** `forget_memory` (`core/tools.py` lines 40-88, 497-522, 3154)
**Apply to:** `get_recent_decisions`.

### `MAX_TOOL_ITERATIONS` exhaustion handling (D-22 extension point)
**Source:** `core/main.py::_run_smart_loop`, lines 1033-1055 (the existing `last_response_text`-if-substantive fallback)
**Apply to:** insert the new "one more turn, tools stripped" call **before** this existing fallback block, inside the same function — this is shared by every chat turn AND every occasion, not occasion-specific code.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `prompts/nightly_occasion.md` / `morning_occasion.md` / `weekly_occasion.md` (D-35, "identity + standing question, few lines") | prompt/config | request-response | No existing prompt in the repo is this minimal/single-purpose — the smallest existing analogs (`prompts/meal_audit.md`, appended fragments) are still topic-guide-shaped, not identity-framing-shaped. Write from D-35's spec directly; keep to "a few lines each" as locked. |
| The `days`-bounded validation on `get_recent_decisions` (ASVS V5) | utility (input validation) | — | No existing tool handler in `core/tools.py` explicitly clamps a numeric arg range before it drives a Firestore query — most handlers trust the LLM-supplied value. Introduce a simple `max(1, min(days, 30))`-style clamp as new code (Security Domain requirement, not present elsewhere to copy). |

## Metadata

**Analog search scope:** `core/`, `interfaces/`, `memory/`, `prompts/`, `tests/` (full-file reads of `core/autonomous.py`, `core/nightly_review.py`, `core/morning_briefing.py`, `core/weekly_training_review.py`, `core/task_dispatch.py`; targeted reads of `interfaces/web_server.py`, `core/tools.py`, `memory/firestore_db.py`, `core/heartbeat.py`, `core/tick_brain.py`, `core/main.py`, and 3 test files)
**Files scanned:** 14 source files fully or substantially read this session (this agent), building on RESEARCH.md's prior full reads of the same files
**Pattern extraction date:** 2026-07-29
