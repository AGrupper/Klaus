# Phase 29: Web Push & Transition - Pattern Map

**Mapped:** 2026-07-02
**Files analyzed:** 20 (new + modified, backend + frontend + tests)
**Analogs found:** 20 / 20

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `memory/firestore_db.py` — `PushSubscriptionStore` (NEW class) | model/store | CRUD | `memory/firestore_db.py::RunDetailStore` (lines 1226-1334) | exact (upsert/delete/get/list, `_jsonsafe_doc` reads, re-raise-on-write) |
| `memory/firestore_db.py` — `HubSettingsStore` (NEW class) | model/store | CRUD (single doc) | `memory/firestore_db.py::HeartbeatConfigStore` (lines 287-320) | exact (single settings doc, `get()`-with-defaults + `set()`-merge) |
| `core/push_sender.py` (NEW) | service | request-response (sync HTTP fan-out) | `core/auth_google.py::SecretManagerTokenStorage` (lines 106-175) for key load; `core/heartbeat.py::check_tokens` (lines 203-222) for the try/except-per-item shape | role-match (no prior "sync external POST fan-out" module exists) |
| `core/scheduled_message.py` — extend `send_and_inject` | service | event-driven (fan-out on send) | itself (`core/scheduled_message.py`, whole file, 71 lines) | exact (extend in place) |
| `interfaces/web_server.py` — `/api/push/*`, `/api/settings` (NEW routes) | route | request-response | `interfaces/web_server.py::api_today` (1415-1478) for GET-with-executor shape; `interfaces/web_server.py::api_chat_send` (1554-1617) for POST-with-validation shape | exact |
| `interfaces/web_server.py` — push hook in `/internal/process-hub-message` | route (internal) | event-driven | `interfaces/web_server.py::internal_process_hub_message` (1668-1721) | exact (extend in place) |
| `interfaces/_router.py` — push after `reply_text` | controller (telegram handler) | event-driven | `interfaces/_router.py` lines 330-362 (existing `handle_message` → `reply_text` block) | exact (extend in place) |
| `core/tools.py` — `toggle_telegram_mirror`, `get_push_health` (NEW schemas + handlers) | controller (tool dispatch) | request-response | `core/tools.py::get_self_status` schema (769-783) + `_handle_get_self_status` (1788-1827) + `_HANDLERS`/`SMART_AGENT_DIRECT_TOOLS` registration (40-78, 2606, 2679) | exact |
| `core/heartbeat.py` — `_check_push_health()` (NEW checker) | service (checker) | batch | `core/heartbeat.py::check_tokens` (203-222) + `_collect_signals` (621-634) | exact |
| `frontend/vite.config.ts` — `generateSW` → `injectManifest` | config | build-time transform | itself (`frontend/vite.config.ts`, whole file, 69 lines) | exact (modify in place) |
| `frontend/src/sw.ts` (NEW) | service (worker) | event-driven | none in-repo (first custom SW); modeled directly on `vite.config.ts`'s existing `workbox` block + RESEARCH.md Pattern 4 | no in-repo analog — RESEARCH.md Pattern 4 is the source |
| `frontend/src/hooks/usePush.ts` (NEW) | hook | request-response + browser API | `frontend/src/hooks/useInstallBanner.ts` (whole file, 78 lines) | role-match (feature-detect + localStorage-gated browser capability hook) |
| `frontend/src/hooks/useAppBadge.ts` (NEW) | hook | event-driven (reconcile on state change) | `frontend/src/hooks/useUnread.ts` (whole file, 47 lines) | exact (same counter it mirrors) |
| `frontend/src/components/settings/SettingsPage.tsx` (NEW) | component (page) | request-response | `frontend/src/components/tasks/TasksPage.tsx` pattern (page composing hook + shared components) — not read in full, referenced via `App.tsx` `TasksPage` wiring (59-61) | role-match |
| `frontend/src/components/shared/PushEnableBanner.tsx` (NEW) | component | event-driven (user gesture) | `frontend/src/components/shared/InstallBanner.tsx` (whole file, 161 lines) + `useInstallBanner.ts` | exact |
| `frontend/src/App.tsx` — `/settings` route | route (frontend) | request-response | `frontend/src/App.tsx` (whole file, 164 lines) — existing `TasksPage`/`HabitsPage` route wiring | exact (extend in place) |
| `frontend/src/components/layout/Sidebar.tsx` — nav entry | component | — | `frontend/src/components/layout/Sidebar.tsx` lines 1-55 (`NAV_ITEMS`) | exact (extend in place) |
| `tests/test_push_subscription_store.py` (NEW) | test | CRUD | `tests/fakes.py` (`FakeCollection`/`FakeQuery`/`make_snap`, whole file) + existing store test files (e.g. `tests/test_firestore_db.py` patterns via `RunDetailStore`) | exact |
| `tests/test_push_api.py` (NEW) | test | request-response | `tests/test_hub_chat.py` (`_stub_web_server_imports`, `_ENV`, `dependency_overrides`, lines 1-80) | exact |
| `tests/test_push_sender.py` (NEW) | test | request-response (mocked HTTP) | `tests/fakes.py` + `unittest.mock.patch` idioms used across `tests/test_heartbeat.py`/`tests/test_hub_chat.py` | role-match |

## Pattern Assignments

### `memory/firestore_db.py` — `PushSubscriptionStore` (NEW)

**Analog:** `memory/firestore_db.py::RunDetailStore` (lines 1226-1334) — same shape needed: `upsert` (idempotent, doc-id keyed, re-raise on failure), `delete` (re-raise), `get`/`list_all` (never raise, `_jsonsafe_doc`).

**Class skeleton to copy verbatim (lines 1226-1301, adapt doc-id + fields):**
```python
class RunDetailStore:
    _COLLECTION = "run_details"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def upsert(self, run: dict) -> None:
        activity_id = run.get("activity_id")
        if not activity_id or activity_id == "None":
            raise ValueError("RunDetailStore.upsert requires an activity_id")
        try:
            self._col.document(str(activity_id)).set(
                {**run, "source": "garmin", "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except Exception:
            logger.error("RunDetailStore.upsert(%r) failed", activity_id, exc_info=True)
            raise

    def delete(self, activity_id: str) -> None:
        try:
            self._col.document(str(activity_id)).delete()
        except Exception:
            logger.error("RunDetailStore.delete(%r) failed", activity_id, exc_info=True)
            raise

    def get_run(self, activity_id: str) -> dict | None:
        try:
            snap = self._col.document(str(activity_id)).get()
            if not snap.exists:
                return None
            return _jsonsafe_doc(snap.to_dict() or {})
        except Exception:
            logger.warning("RunDetailStore.get_run(%r) failed", activity_id, exc_info=True)
            return None
```
**Adaptation for `PushSubscriptionStore` (per RESEARCH.md Pattern 2):**
- Doc id = `sha256(endpoint).hexdigest()[:32]` (endpoint itself is too long/unsafe as a doc id — no existing precedent for hashed ids; this is new but the *shape* of `upsert(dict)` keyed on a derived id matches `RunDetailStore.upsert` keyed on `run["activity_id"]`).
- Add `list_all()` — copy `get_range`'s never-raise + `_jsonsafe_doc`-list shape (lines 1303-1318) but without date filters: `[_jsonsafe_doc(snap.to_dict() or {}) for snap in self._col.stream()]`.
- Add `record_success(endpoint)` / `record_failure(endpoint, error)` — small merge writes, model on `IncidentStore.record_open`'s `doc_ref.set(payload, merge=True)` pattern (`memory/firestore_db.py:353-380`).

**Error-handling convention (house rule, applies to all new stores):** reads never raise (return `None`/`[]` on exception, `logger.warning`); writes re-raise after `logger.error` so callers know a sync did not land.

---

### `memory/firestore_db.py` — `HubSettingsStore` (NEW)

**Analog:** `memory/firestore_db.py::HeartbeatConfigStore` (lines 287-320) — exact shape: single doc at `collection='config'`, defaults merged on read, `set()` merges a patch.

**Full analog to copy verbatim (rename doc/collection, add fields):**
```python
class HeartbeatConfigStore:
    _COLLECTION = "config"
    _DOCUMENT = "heartbeat"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._doc_ref = self._client.collection(self._COLLECTION).document(self._DOCUMENT)

    def get(self) -> dict:
        try:
            snap = self._doc_ref.get()
            stored = snap.to_dict() or {} if snap.exists else {}
        except GoogleAPICallError:
            logger.warning("HeartbeatConfigStore.get() failed — using defaults")
            stored = {}
        return {**_HEARTBEAT_CONFIG_DEFAULTS, **stored}

    def set(self, patch: dict) -> None:
        try:
            self._doc_ref.set(
                {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
                merge=True,
            )
        except GoogleAPICallError:
            logger.error("HeartbeatConfigStore.set() failed")
            raise
```
For `HubSettingsStore`: `_COLLECTION = "config"`, `_DOCUMENT = "hub_settings"`, defaults dict `{"telegram_mirror_enabled": True, "push_enabled_at": None, "chat_visible_until": None}` (per RESEARCH.md Pattern 2). `get()` return value MUST pass through `_jsonsafe_doc` wherever it feeds `json.dumps` (e.g. the `/api/settings` route and `get_push_health` tool) — see `_jsonsafe_doc` at lines 885-913.

---

### `core/scheduled_message.py` — extend `send_and_inject`

**Analog:** itself. Full current file already read (71 lines) — do not re-read.

**Current signature and body (lines 26-71) — extend, keep backward compatible:**
```python
async def send_and_inject(
    bot: Bot,
    text: str,
    *,
    inject_into_conversation: bool = False,
    reply_markup=None,              # InlineKeyboardMarkup | None (Phase 20)
) -> "telegram.Message":
    user_id = _telegram_user_id()
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)

    if not inject_into_conversation:
        return msg

    try:
        from memory.firestore_conversation import FirestoreConversationStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        collection = os.getenv("FIRESTORE_COLLECTION_CONVERSATIONS", "conversations")
        store = FirestoreConversationStore(project_id=project_id, database=database, collection=collection)
        store.append(user_id, "assistant", text)
        logger.info("scheduled_message: injected into conversation for user_id=%d", user_id)
    except Exception:
        logger.warning(
            "scheduled_message: conversation injection failed — message still sent",
            exc_info=True,
        )
    return msg
```
**New keyword-only params to add (RESEARCH.md Pattern 1, sketch at RESEARCH.md lines 336-354):** `message_class="default"`, `push=True`. Insert D-02 gate + `loop.run_in_executor(None, send_push_to_all, text, message_class)` BEFORE the Telegram send; gate the Telegram send itself on `HubSettingsStore.get()["telegram_mirror_enabled"]` for cron callers (existing lazy-import style at line 59 — follow the same `from memory.firestore_conversation import ...` inline-import convention for the new `from memory.firestore_db import HubSettingsStore` / `PushSubscriptionStore` imports, keeping the module's zero-heavy-import-at-load-time discipline).
**D-10 gate redefinition:** callers (`proactive_alerts.py`, `morning_briefing.py`, etc.) gate `OutreachLogStore.append` on `send_and_inject` success — RESEARCH.md says redefine success as "≥1 channel delivered." Locate those call sites (grep `send_and_inject` across `core/*.py`) and confirm the return-value/exception contract doesn't need to change (a raised exception today means total failure; keep that contract — push failures should NOT raise, only Telegram failures should, mirroring D-04 "messages never lost").

---

### `core/push_sender.py` (NEW)

**No in-repo analog for "sync HTTP fan-out with per-item try/except + cleanup-on-404"** — closest supporting patterns:

**Secret Manager key load** — analog `core/auth_google.py::SecretManagerTokenStorage.load` (lines 134-155):
```python
def load(self) -> str | None:
    from google.cloud import secretmanager
    from google.api_core.exceptions import NotFound
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{self.project_id}/secrets/{self.secret_name}/versions/latest"
    try:
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
    except NotFound:
        logger.info("Secret '%s' has no versions yet", self.secret_name)
        return None
```
Use this exact `access_secret_version(request={"name": ...})` call shape to load `klaus-vapid-private-key`; cache the PEM string in a module-level variable (matches the project's other lazy-singleton patterns, e.g. `_get_orchestrator()` in `core/main.py` per CLAUDE.md §6).

**Per-item try/except-and-classify loop** — analog `core/heartbeat.py::check_tokens` (lines 203-222) for the try/except/Signal-append shape, adapted to a `for sub in store.list_all(): try/except WebPushException` loop exactly as sketched in RESEARCH.md Pattern 5 (lines 542-573) — treat that sketch as load-bearing implementation guidance since no closer in-repo analog exists.

**CLAUDE.md invariants that apply directly:** explicit `timeout=10` on every `webpush()` call (§6 "every LLM/etc client carries an explicit timeout"); lowercase `klaus-vapid-private-key` secret name (§6 GCP naming); fresh `vapid_claims` dict per call (Pitfall 5).

---

### `interfaces/web_server.py` — `/api/push/*` + `/api/settings` (NEW routes)

**Analog for GET-with-executor:** `api_today` (lines 1415-1478) — `loop.run_in_executor` + `_jsonsafe_doc` on the response payload.

**Analog for POST-with-validation:** `api_chat_send` (lines 1554-1617):
```python
@app.post("/api/chat")
async def api_chat_send(
    request: Request,
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    body = await request.json()
    content = body.get("content", "")
    if not content or not content.strip():
        raise HTTPException(status_code=400, detail={"error": "content must be non-empty"})
    if len(content) > _CHAT_CONTENT_MAX_LEN:
        raise HTTPException(status_code=400, detail={"error": "..."})
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, enqueue_hub_message, content, user_id)
    if not ok:
        return JSONResponse(status_code=503, content={"ok": False, "error": "..."})
    return JSONResponse(content={"ok": True})
```
Apply the same shape to `POST /api/push/subscribe` (validate `endpoint.startswith("https://")` + `keys.get("p256dh")`/`keys.get("auth")` present — RESEARCH.md's exact sketch at RESEARCH.md lines 706-730 is ready to use nearly verbatim) and `GET/PATCH /api/settings`.

**Placement:** register BEFORE the SPA mount (explicit Pitfall-1-of-Phase-26 comment already in the file at line 1727 — the same warning applies to the new routes) and use `Depends(require_hub_session)` exactly like every other `/api/*` route — NEVER touch `_verify_cron_request`/OIDC (HUB-04 invariant, used by `/internal/process-hub-message` at line 1688).

---

### `interfaces/web_server.py` — push hook in `/internal/process-hub-message`

**Analog:** itself, `internal_process_hub_message` (lines 1668-1721) — already read in full. The push hook is a small addition after `await asyncio.to_thread(_orchestrator.handle_message, content, user_id)`: fetch the assistant reply (the function currently discards it — needs to either capture the return value or read the last conversation turn) and call the new unified delivery (`send_push_to_all` via `loop.run_in_executor`, plus a mirror-gated Telegram send per D-08, since this path currently has zero Telegram dependency). RESEARCH.md Open Question 2 (lines 792-794) flags exactly this — resolve by having the delivery function construct/reuse a module-level `Bot(token)` lazily rather than threading a `bot` param through this route.

---

### `interfaces/_router.py` — push after `reply_text` (line 362)

**Analog:** itself, the `handle_message` Telegram-turn handler (lines 330-362), already read in full:
```python
orchestrator_response = await asyncio.to_thread(
    self.orchestrator.handle_message,
    message_text,
    telegram_user_id,
    photo_bytes,
    photo_mime_type,
)
...
await update.message.reply_text(orchestrator_response)
```
Add a push call (via `loop.run_in_executor(None, send_push_to_all, orchestrator_response, "chat_reply")`) immediately after `reply_text` succeeds — Telegram send already happened natively via `reply_text`, so no mirror gate applies here (per RESEARCH.md Open Question 1 — D-10's "double-buzz" reasoning covers pushing this path too; D-02 visibility gate doesn't apply since the chat view isn't the source here).

---

### `core/tools.py` — `toggle_telegram_mirror` + `get_push_health` (NEW brain-direct tools)

**Analog:** `get_self_status` — three touch points, all read in full:

**1. Schema registration** (lines 40-78, add to `SMART_AGENT_DIRECT_TOOLS` frozenset):
```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    ...
    "get_self_status",
    ...
})
```
**2. Tool schema block** (pattern at lines 768-783):
```python
{
    "name": "get_self_status",
    "description": (
        "Return Klaus's current operational status: ... "
        "Call this directly — do NOT delegate to the worker. "
        "Use when asked about current status, costs, uptime, or health."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
},
```
Follow this exact "Call this directly — do NOT delegate to the worker" description convention for both new tools; `toggle_telegram_mirror` needs an `enabled: bool` property in `input_schema` (model on any boolean-arg tool, e.g. `input_schema` patterns elsewhere in the file), `get_push_health` takes no args (empty object, like `get_self_status`).

**3. Handler function** (pattern at lines 1788-1827, `_handle_get_self_status`):
```python
def _handle_get_self_status() -> str:
    """Return Klaus's operational status: uptime, message count, costs, heartbeat."""
    result: dict = {}
    try:
        ...
    except Exception as exc:
        result["cost_error"] = str(exc)
    ...
    return json.dumps(result)  # (verify actual return — truncated read; grep confirms json.dumps pattern used elsewhere)
```
`_handle_get_push_health()` should read `PushSubscriptionStore.list_all()` + `HubSettingsStore.get()`, run both through `_jsonsafe_doc`, and `json.dumps` the combined dict. `_handle_toggle_telegram_mirror(enabled: bool)` calls `HubSettingsStore.set({"telegram_mirror_enabled": enabled})` and returns the new state as JSON.

**4. `_HANDLERS` dispatch registration** (pattern at lines 2606-2646, tail of the dict):
```python
"get_self_status":         lambda args: _handle_get_self_status(),
...
"get_habit_adherence":     lambda args: _handle_get_habit_adherence(**args),
}
```
Append `"toggle_telegram_mirror": lambda args: _handle_toggle_telegram_mirror(**args),` and `"get_push_health": lambda args: _handle_get_push_health(),` at the end of this dict, following the existing "# Phase N — ..." comment convention above each addition block.

---

### `core/heartbeat.py` — `_check_push_health()` (NEW checker)

**Analog:** `check_tokens` (lines 203-222), already read in full:
```python
def check_tokens() -> list[Signal]:
    """Token/integration health: Google OAuth refresh probe."""
    signals: list[Signal] = []
    try:
        from core.auth_google import build_auth_manager_from_env
        build_auth_manager_from_env().get_credentials()
    except Exception as exc:
        signals.append(Signal(
            fingerprint="token:google:refresh-failed",
            severity=SEVERITY_CRITICAL, area="token",
            title="Google OAuth refresh failed",
            detail=str(exc)[:200],
            remediation="Re-run the Google OAuth bootstrap; refresh klaus-google-oauth-token.",
        ))
    return signals
```
`Signal` dataclass (lines 38-54) fields: `fingerprint`, `severity`, `area`, `title`, `detail`, `remediation`. New checker `_check_push_health()` builds `Signal`s for the 3 conditions in RESEARCH.md Pattern 9's table (failure-streak, no-subscription, delivery-stale), reading `PushSubscriptionStore` + `HubSettingsStore` (lazy-imported inside the function, matching `check_tokens`' inline `from core.auth_google import ...`).

**Registration point** — `_collect_signals` (lines 621-634):
```python
def _collect_signals(*, tiers: set[str], weekly: bool = False) -> list[Signal]:
    raw: list[Signal] = []
    for checker in (check_cron_health, check_tokens, check_degradation, check_deployment):
        try:
            raw.extend(checker())
        except Exception:
            logger.warning("heartbeat: checker %s crashed", checker.__name__, exc_info=True)
    ...
    return [s for s in raw if s.severity in tiers]
```
Add `_check_push_health` to the checker tuple (or the `weekly`-only `check_code` list, if push-health should run every heartbeat tick rather than weekly — RESEARCH.md implies every tick since D-14 wants self-validation during the mirror week, so add it to the main tuple, not the weekly-only branch).

---

### `frontend/vite.config.ts` — `generateSW` → `injectManifest`

**Analog:** itself, whole file (69 lines), already read in full. Current `workbox` block (lines 20-46) must be DELETED and its two `runtimeCaching` rules replicated verbatim inside `frontend/src/sw.ts` (see next section) — RESEARCH.md Pitfall 2 is explicit that leaving `runtimeCaching` in `vite.config.ts` under `injectManifest` silently no-ops it. Change only `strategies: 'generateSW'` → `strategies: 'injectManifest'`, add `srcDir: 'src'`, `filename: 'sw.ts'`, `injectManifest: { globPatterns: [...] }` (same `globPatterns` value moved from `workbox`). Keep `registerType: 'prompt'` and `injectRegister: false` untouched — verified load-bearing for `UpdatePrompt.tsx`.

---

### `frontend/src/sw.ts` (NEW)

**No in-repo analog** — this is the project's first custom service worker. Build directly from RESEARCH.md Pattern 4's full skeleton (RESEARCH.md lines 447-518), which is itself derived from the current `vite.config.ts` `workbox.runtimeCaching` rules (lines 24-44) being ported verbatim into `registerRoute` calls. Treat the RESEARCH.md skeleton as the canonical source for this file; cross-reference against `vite.config.ts`'s two `runtimeCaching` entries (`html-cache` NetworkFirst 5s timeout; `assets-cache` CacheFirst) to confirm byte-for-byte parity (HUB-03 regression test in RESEARCH.md's Test Map greps `dist/sw.js` for both strings).

---

### `frontend/src/hooks/usePush.ts` (NEW)

**Analog:** `frontend/src/hooks/useInstallBanner.ts` (whole file, 78 lines), already read in full — same shape: feature-detect the browser capability, gate on `localStorage`-persisted state, expose a small `{ ...state, action() }` object:
```typescript
function detectIOS(): boolean {
  if (typeof navigator === 'undefined') return false
  return /iphone|ipad|ipod/i.test(navigator.userAgent)
}
function isDismissed(): boolean {
  try {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem(DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}
export function useInstallBanner(): UseInstallBannerResult {
  const [dismissed, setDismissed] = useState<boolean>(() => isDismissed())
  const isIOS = detectIOS()
  const isStandalone = detectStandalone()
  const showBanner = isIOS && !isStandalone && !dismissed
  const dismiss = useCallback(() => {
    try { localStorage.setItem(DISMISSED_KEY, '1') } catch { /* ignore */ }
    setDismissed(true)
  }, [])
  return { showBanner, dismiss }
}
```
`usePush.ts` follows the same defensive-try/catch-around-browser-API convention plus the subscribe/re-validate flow from RESEARCH.md Pattern 3 (lines 397-413) and Pattern 8 (re-validation, RESEARCH.md lines 607-623).

---

### `frontend/src/hooks/useAppBadge.ts` (NEW)

**Analog:** `frontend/src/hooks/useUnread.ts` (whole file, 47 lines), already read in full — this IS the counter `useAppBadge` mirrors (D-18):
```typescript
export function useUnread(messageCount: number): {
  unreadCount: number
  markAllSeen: () => void
} {
  const lastSeen = parseInt(localStorage.getItem(STORAGE_KEY) ?? '0', 10)
  const unreadCount = Math.max(0, messageCount - lastSeen)
  ...
}
```
`useAppBadge(unreadCount)` takes the `unreadCount` from `useUnread` as an argument and reconciles `navigator.setAppBadge`/`clearAppBadge` + posts `{type:'RESET_BADGE'}` to the SW — RESEARCH.md's Code Examples section (lines 745-755) has the ready-to-use `useEffect` body. Call site: `ChatWindow.tsx`'s existing `useUnread(allMessages.length)` call (line 50) is the anchor — `markAllSeen` (lines 42-44 of `useUnread.ts`) is where the "clear both badges together" (D-18) logic attaches.

---

### `frontend/src/components/shared/PushEnableBanner.tsx` (NEW, D-16)

**Analog:** `frontend/src/components/shared/InstallBanner.tsx` (whole file, 161 lines) + `useInstallBanner.ts`, already read in full — copy the fixed-bottom banner shell (role="complementary", z-40, safe-area padding, dismiss-X button) verbatim, swap copy + the primary button's action from "How to install" expand-toggle to the actual `enablePush()` gesture call (must be a real user-gesture click handler per iOS requirement, RESEARCH.md Pattern 3):
```tsx
export function InstallBanner() {
  const { showBanner, dismiss } = useInstallBanner()
  const [expanded, setExpanded] = useState(false)
  if (!showBanner) return null
  return (
    <div role="complementary" aria-label="..." style={{ position: 'fixed', bottom: 0, ... }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p>...</p>
          <button type="button" onClick={() => setExpanded((p) => !p)} style={{ ... minHeight: '44px' }}>
            How to install
          </button>
        </div>
        <button type="button" aria-label="Dismiss install prompt" onClick={dismiss} style={{ ... minWidth: '44px', minHeight: '44px' }}>
          {/* X icon */}
        </button>
      </div>
    </div>
  )
}
```
Gate rendering on `usePush()`'s "never asked" state (RESEARCH.md Pattern 8's `else: # 'default', never asked` branch) rather than `useInstallBanner`'s iOS/standalone detection.

---

### `frontend/src/components/settings/SettingsPage.tsx` (NEW, D-15)

**Analog:** `App.tsx`'s existing page-component wiring pattern (`TodayPage`/`TasksPage`/`KlausPage`, lines 55-79) — a thin function component wrapping a real content component:
```tsx
function TasksPage() {
  return <TasksPageComponent />
}
```
`SettingsPage.tsx` hosts the enable-push button (from `usePush`) + the mirror toggle (reading/writing `/api/settings` — same `useQuery`/`fetch` idiom as `App.tsx`'s `fetchMe` via `useQuery` at lines 123-128). No deeper page-composition analog was read in full (kept the analog search to 3-5 strong matches per instructions); `TasksPage.tsx` is available for a closer look if the planner wants form-input conventions.

---

### `frontend/src/App.tsx` — `/settings` route

**Analog:** itself, whole file (164 lines), already read in full:
```tsx
<Routes>
  <Route path="/" element={<TodayPage />} />
  <Route path="/tasks" element={<TasksPage />} />
  <Route path="/klaus" element={<KlausPage />} />
  <Route path="/habits" element={<HabitsPage />} />
  <Route path="/health" element={<HealthPage />} />
  <Route path="*" element={<Navigate to="/" replace />} />
</Routes>
```
Add `<Route path="/settings" element={<SettingsPage />} />` following the same import + function-component wrapper pattern as `TasksPage`/`HabitsPage` (lines 59-61, 77-79).

---

### `frontend/src/components/layout/Sidebar.tsx` — nav entry (D-15 discretion)

**Analog:** itself, lines 1-55, already read in full:
```tsx
import { CalendarDays, CheckSquare, MessageCircle, Activity, Heart, LogOut, ShieldOff, X } from 'lucide-react'
const NAV_ITEMS: NavItem[] = [
  { label: 'Today', path: '/', icon: CalendarDays },
  { label: 'Tasks', path: '/tasks', icon: CheckSquare },
  { label: 'Klaus', path: '/klaus', icon: MessageCircle },
  { label: 'Habits', path: '/habits', icon: Activity },
  { label: 'Health', path: '/health', icon: Heart },
]
```
Add `import { Settings } from 'lucide-react'` and append `{ label: 'Settings', path: '/settings', icon: Settings }` to `NAV_ITEMS`. Per RESEARCH.md's Nav-placement note (RESEARCH.md lines 757-758), BottomTabs (phone) has exactly 5 slots already used — do NOT add Settings there; use a gear-icon button in the Today page header instead (UI discretion, D-15).

---

### `tests/test_push_subscription_store.py`, `tests/test_hub_settings_store.py` (NEW)

**Analog:** `tests/fakes.py` (whole file, 193 lines), already read in full — `FakeCollection`/`FakeQuery`/`make_snap`/`FailingCollection` are the standard fixtures for every Firestore store test in this repo:
```python
from tests.fakes import FakeCollection, make_snap, FailingCollection

def test_upsert_creates_doc():
    store = PushSubscriptionStore(project_id="test", database="(default)")
    store._col = FakeCollection([])
    store.upsert({"endpoint": "https://web.push.apple.com/x", "keys": {...}})
    assert store._col.document(...)  # assert on the memoised docref .set call
```
Follow the "never-raise reads / re-raise writes" test-pairing convention: one test per store method exercising both the happy path and the `FailingCollection`-induced failure path.

### `tests/test_push_api.py` (NEW)

**Analog:** `tests/test_hub_chat.py` (lines 1-80+, already read), the standard FastAPI route-test harness:
```python
_ENV = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    "CRON_DEV_BYPASS": "true",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "CLOUD_TASKS_QUEUE": "klaus-updates",
    "CLOUD_TASKS_LOCATION": "me-central1",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
}

def _stub_web_server_imports() -> dict:
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if key == "interfaces.web_server" or key.startswith("interfaces.web_server."):
            del sys.modules[key]
    return stubs

def test_...():
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws
        from fastapi.testclient import TestClient
        with patch.dict(os.environ, _ENV):
            ws.app.dependency_overrides[ws.require_hub_session] = lambda: "amit.grupper@gmail.com"
            client = TestClient(ws.app)
            # POST/GET the new /api/push/* and /api/settings routes
```
Reuse `_ENV` and `_stub_web_server_imports` verbatim (import from the same module or copy the block) for `test_push_api.py`.

### `tests/test_push_sender.py` (NEW)

**Analog:** no direct in-repo analog for "mock an external sync library call" at the unit level — combine `tests/fakes.py`'s `FakeCollection` (for the `PushSubscriptionStore` the sender reads/writes) with `unittest.mock.patch("core.push_sender.webpush", ...)` to simulate success / `WebPushException(404)` / `WebPushException(410)` / generic exception, per RESEARCH.md's Test Map row for PUSH-02 (`pytest tests/test_push_sender.py -x`) and Pattern 5's exact `except WebPushException as ex: status = ex.response.status_code ...` branching (RESEARCH.md lines 563-571) — assert each status maps to the correct store call (`record_success`, `delete`, `record_failure`).

## Shared Patterns

### `_jsonsafe_doc` — every Firestore read that feeds `json.dumps` or a JSON HTTP response
**Source:** `memory/firestore_db.py` lines 885-913
**Apply to:** `PushSubscriptionStore`/`HubSettingsStore` reads, `get_push_health` tool handler, `/api/settings` and `/api/push/*` GET routes.
```python
def _jsonsafe_doc(d: dict) -> dict:
    return {k: _jsonsafe_value(v) for k, v in d.items()}

def _jsonsafe_value(v):
    if isinstance(v, dict):
        return {k: _jsonsafe_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonsafe_value(x) for x in v]
    iso = getattr(v, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return str(v)
    return v
```

### `require_hub_session` — every new `/api/*` route
**Source:** `interfaces/web_server.py` line 41 import, used as `Depends(require_hub_session)` throughout (e.g. lines 1416, 1557, 1622)
**Apply to:** `/api/push/subscribe`, `/api/push/vapid-public-key`, `/api/settings` (GET+PATCH).
```python
async def api_today(_email: str = Depends(require_hub_session)) -> JSONResponse:
```
**Never apply to:** `/internal/process-hub-message` (uses `_verify_cron_request` OIDC instead, line 1688) — HUB-04 invariant, do not weaken.

### `loop.run_in_executor` — every sync Firestore/pywebpush call inside an async route or cron
**Source:** `interfaces/web_server.py` lines 1450-1461 (`api_today`), 1594, 1609 (`api_chat_send`)
**Apply to:** all new `/api/push/*`/`/api/settings` route bodies, `send_push_to_all` call sites inside `send_and_inject`, `_router.py`'s push-after-reply hook, `/internal/process-hub-message`'s push hook.
```python
loop = asyncio.get_running_loop()
ok = await loop.run_in_executor(None, enqueue_hub_message, content, user_id)
```
This is also the direct fix for RESEARCH.md Pitfall 3 (weekly-review-500 class regression) — `pywebpush.webpush()` is synchronous and MUST NOT run inline in an async context.

### Lazy inline imports for Firestore/GCP clients inside functions
**Source:** `core/scheduled_message.py` line 59 (`from memory.firestore_conversation import FirestoreConversationStore`), `core/heartbeat.py` line 639 (`from memory.firestore_db import IncidentStore`), `core/tools.py` line 1812 (`from memory.firestore_db import LLMUsageStore`)
**Apply to:** every new module that touches `PushSubscriptionStore`/`HubSettingsStore` — keeps module import time cheap and avoids import-order issues in tests that stub `sys.modules`.

### Signal/checker registration for heartbeat extensions
**Source:** `core/heartbeat.py` lines 38-54 (`Signal` dataclass) + 621-634 (`_collect_signals`)
**Apply to:** `_check_push_health()` — same `fingerprint`/`severity`/`area`/`title`/`detail`/`remediation` shape, added to the checker tuple in `_collect_signals`.

### Brain-direct tool registration (3-part: frozenset + schema + `_HANDLERS`)
**Source:** `core/tools.py` lines 40-78 (`SMART_AGENT_DIRECT_TOOLS`), 768-783 (schema), 2606-2646 (`_HANDLERS`)
**Apply to:** `toggle_telegram_mirror`, `get_push_health` — all three registration points must be updated together or the tool silently doesn't reach the brain (`get_smart_schemas` filters on `SMART_AGENT_DIRECT_TOOLS` membership, line 2674).

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `frontend/src/sw.ts` | service worker | event-driven | First custom service worker in the repo (currently `generateSW`-only) — build from RESEARCH.md Pattern 4's skeleton, cross-checked against `vite.config.ts`'s existing `workbox.runtimeCaching` config (which it must replicate verbatim per Pitfall 2) |
| `core/push_sender.py` | service | request-response (sync fan-out) | No prior "sync external HTTP POST with per-item classification + cleanup" module; assembled from `SecretManagerTokenStorage` (key load) + RESEARCH.md Pattern 5's full sketch (fan-out loop) |

## Metadata

**Analog search scope:** `memory/firestore_db.py`, `core/scheduled_message.py`, `core/heartbeat.py`, `core/tools.py`, `core/auth_google.py`, `interfaces/web_server.py`, `interfaces/_router.py`, `frontend/vite.config.ts`, `frontend/src/hooks/{useUnread,useInstallBanner}.ts`, `frontend/src/components/{chat/ChatWindow,shared/InstallBanner}.tsx`, `frontend/src/{App,components/layout/Sidebar}.tsx`, `tests/{fakes.py,test_hub_chat.py}`
**Files scanned:** 13 source files fully read (several already in context from the initial required-reading pass), plus targeted `grep`/`wc -l` scans across `memory/firestore_db.py` (3495 lines) and `core/tools.py` (2728 lines) to locate exact line ranges without re-reading whole files
**Pattern extraction date:** 2026-07-02
