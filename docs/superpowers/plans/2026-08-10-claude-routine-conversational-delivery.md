# Claude Routine Conversational Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every successful morning, nightly, and weekly Claude Routine review fully readable in its Claude Routine session and in the authenticated Klaus Hub, route review notifications to the exact Hub review, and provide a safe one-click return to the originating Claude session for follow-up.

**Architecture:** Preserve Klaus as the single canonical review store and Claude Routine sessions as the per-review conversational surface. Capture the validated Claude session URL returned by Anthropic, persist it as navigation metadata beside the canonical review, expose authenticated list/detail review reads, route Web Push to same-origin review detail pages, and require each routine skill to render the exact published review as its final assistant response. Keep publication, push, and authority semantics one-shot and unchanged.

**Tech Stack:** Python 3.13, FastAPI, Firestore, MCP Python SDK, pytest, React 19, TypeScript 6, React Router 7, TanStack Query 5, Vitest, Vite PWA/Workbox, Claude Remote Routines, Google Cloud Run.

## Global Constraints

- Follow the approved design in `docs/superpowers/specs/2026-08-10-claude-routine-conversational-delivery-design.md`.
- Klaus Firestore/Postgres/Pinecone state remains authoritative; a Claude URL is navigation metadata only.
- Preserve exactly one initial `publish_review`, one canonical review record, and one initial user-visible push. Late upgrades remain silent.
- Never expose `remote_trigger_result`, API-trigger bearer tokens, OAuth tokens, connector credentials, or arbitrary external URLs to the browser.
- Review APIs remain protected by `require_hub_session`; review text is rendered as plain data, never executable HTML.
- Preserve the routine connector's existing `klaus.routine` authority and lack of `klaus.approve`.
- Keep `KLAUS_ROUTINE_MORNING_CUTOVER=false` and `KLAUS_ROUTINE_WEEKLY_CUTOVER=false`. Temporarily pause nightly only for the coordinated 7.1.0 skill/backend rollout, then restore `KLAUS_ROUTINE_NIGHTLY_CUTOVER=true` after shadow UAT.
- Preserve `.claude/scheduled_tasks.lock` and the untracked `AGENTS.md`; never stage either file.
- Use `apply_patch` for source edits. Do not use destructive git commands.
- Every implementation task starts RED, reaches GREEN, and receives its own focused commit.

---

### Task 1: Capture and persist safe Claude Routine session metadata

**Files:**
- Create: `core/review_delivery.py`
- Create: `tests/test_review_delivery.py`
- Modify: `core/subscription_routines.py:17-222`
- Modify: `memory/firestore_db.py:5143-5199`
- Modify: `interfaces/mcp_runtime.py:224-315`
- Modify: `tests/test_subscription_routines.py:1-242`
- Modify: `tests/test_firestore_db.py:1350-1375`
- Modify: `tests/test_mcp_runtime.py:203-end`

**Interfaces:**
- Produces: `normalise_claude_session_url(value: object) -> str | None`
- Produces: `routine_review_path(routine: str, target_date: str) -> str`
- Produces: `routine_review_title(routine: str) -> str`
- Extends: `RoutineReviewStore.publish` with optional keyword `claude_session_url: str | None = None`
- Adds top-level safe `claude_session_url` to `RoutineRunStore` transition metadata when Anthropic returns one
- Persists only the normalized URL on the canonical review

- [ ] **Step 1: Write failing URL and path policy tests**

Create `tests/test_review_delivery.py`:

```python
import pytest

from core.review_delivery import (
    normalise_claude_session_url,
    routine_review_path,
    routine_review_title,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://claude.ai/code/session_01ABC-def?trigger=trig_private",
            "https://claude.ai/code/session_01ABC-def",
        ),
        (
            "https://www.claude.ai/epitaxy/session_01XYZ_9?trigger=trig_private",
            "https://claude.ai/epitaxy/session_01XYZ_9",
        ),
    ],
)
def test_normalise_claude_session_url_accepts_known_session_forms(raw, expected):
    assert normalise_claude_session_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://claude.ai/code/session_01ABC",
        "https://evil.example/code/session_01ABC",
        "https://claude.ai.evil.example/code/session_01ABC",
        "https://user:pass@claude.ai/code/session_01ABC",
        "https://claude.ai/chat/ordinary-chat",
        "//claude.ai/code/session_01ABC",
        "https://claude.ai/code/session_01ABC/extra",
        "https://claude.ai/code/session_01ABC\nhttps://evil.example",
        None,
        42,
    ],
)
def test_normalise_claude_session_url_rejects_unsafe_values(raw):
    assert normalise_claude_session_url(raw) is None


def test_routine_review_path_is_deterministic_and_strict():
    assert routine_review_path("nightly", "2026-08-10") == (
        "/klaus/reviews/nightly/2026-08-10"
    )
    with pytest.raises(ValueError, match="unsupported routine"):
        routine_review_path("adhoc", "2026-08-10")
    with pytest.raises(ValueError, match="ISO date"):
        routine_review_path("morning", "2026-02-30")


def test_routine_review_title_is_user_visible_and_strict():
    assert routine_review_title("morning") == "Klaus Morning Review"
    assert routine_review_title("nightly") == "Klaus Nightly Review"
    assert routine_review_title("weekly") == "Klaus Weekly Review"
    with pytest.raises(ValueError, match="unsupported routine"):
        routine_review_title("adhoc")
```

- [ ] **Step 2: Run the helper tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_review_delivery.py -q
```

Expected: FAIL during collection because `core.review_delivery` does not exist.

- [ ] **Step 3: Implement strict normalization and deterministic Hub paths**

Create `core/review_delivery.py` with these contracts:

```python
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit


ROUTINE_NAMES = frozenset({"morning", "nightly", "weekly"})
_SESSION_PATH = re.compile(r"^/(?:code|epitaxy)/session_[A-Za-z0-9_-]+$")


def normalise_claude_session_url(value: object) -> str | None:
    if not isinstance(value, str) or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname not in {"claude.ai", "www.claude.ai"}:
        return None
    if parsed.username or parsed.password or port not in {None, 443}:
        return None
    path = parsed.path.rstrip("/")
    if not _SESSION_PATH.fullmatch(path):
        return None
    return urlunsplit(("https", "claude.ai", path, "", ""))


def routine_review_path(routine: str, target_date: str) -> str:
    if routine not in ROUTINE_NAMES:
        raise ValueError(f"unsupported routine: {routine}")
    try:
        parsed_date = date.fromisoformat(target_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("target_date must be an ISO date") from exc
    canonical = parsed_date.isoformat()
    if canonical != target_date:
        raise ValueError("target_date must be an ISO date")
    return f"/klaus/reviews/{routine}/{canonical}"


def routine_review_title(routine: str) -> str:
    if routine not in ROUTINE_NAMES:
        raise ValueError(f"unsupported routine: {routine}")
    return f"Klaus {routine.title()} Review"
```

Queries and fragments are intentionally stripped. They are not required to reopen the session and may contain provider correlation data that the Hub does not need.

- [ ] **Step 4: Add failing trigger and persistence tests**

Extend `tests/test_subscription_routines.py` so `test_trigger_persists_pending_before_remote_fire_and_schedules_timeout` returns both documented response fields:

```python
return {
    "accepted": True,
    "claude_code_session_id": "session_01ABC",
    "claude_code_session_url": (
        "https://claude.ai/epitaxy/session_01ABC?trigger=trig_private"
    ),
}
```

Then assert:

```python
stored = runs.get(result["correlation_id"])
assert stored["claude_session_url"] == "https://claude.ai/epitaxy/session_01ABC"
```

Add a second test returning `https://evil.example/session_01ABC` and assert the run has no `claude_session_url` while remaining `running`.

Extend the Firestore publisher test:

```python
published = reviews.publish(
    routine="morning",
    target_date="2026-08-08",
    correlation_id="routine-4",
    status="published_claude",
    text="Good morning, Sir.",
    structured={"priorities": ["Deep work"]},
    claude_session_url="https://claude.ai/code/session_01ABC",
)
assert published["claude_session_url"] == "https://claude.ai/code/session_01ABC"
assert stored["claude_session_url"] == "https://claude.ai/code/session_01ABC"
```

Also retain one legacy call with no URL and assert it still publishes.

Add a valid `publish_review` handler test whose fake run contains a safe top-level URL. Assert `RoutineReviewStore.publish` receives exactly the normalized `claude_session_url`. Add a hostile URL case and assert publication still succeeds without that keyword.

- [ ] **Step 5: Run the metadata tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_subscription_routines.py \
  tests/test_firestore_db.py::TestRoutineRunStore::test_review_publisher_extends_existing_collection_with_common_schema \
  tests/test_mcp_runtime.py -q
```

Expected: FAIL because the run/review schema and publication handler do not yet carry safe session metadata.

- [ ] **Step 6: Persist only normalized session metadata**

In `SubscriptionRoutineCoordinator.start`, normalize `remote_result.get("claude_code_session_url")` and include it as a top-level transition field only when valid:

```python
remote_result = self._remote_fire(payload)
transition_fields = {
    "fallback_scheduled": True,
    "remote_trigger_result": remote_result,
}
session_url = normalise_claude_session_url(
    remote_result.get("claude_code_session_url")
    if isinstance(remote_result, dict)
    else None
)
if session_url:
    transition_fields["claude_session_url"] = session_url
self._runs.transition(correlation_id, "running", **transition_fields)
```

Extend `RoutineReviewStore.publish` with an optional keyword. Revalidate it defensively; add it to `record` only when valid so legacy documents do not gain a meaningless `null` field.

In `interfaces.mcp_runtime.publish_review`, read the top-level `current["claude_session_url"]`, revalidate it, and pass the safe value to `RoutineReviewStore.publish`. If the current field is absent, inspect only `current["remote_trigger_result"]["claude_code_session_url"]` for migration compatibility. Never pass the raw trigger response.

In `publish_timeout_fallback`, persist the same safe top-level run URL with the fallback review when it exists.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_review_delivery.py \
  tests/test_subscription_routines.py \
  tests/test_firestore_db.py \
  tests/test_mcp_runtime.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add \
  core/review_delivery.py \
  core/subscription_routines.py \
  memory/firestore_db.py \
  interfaces/mcp_runtime.py \
  tests/test_review_delivery.py \
  tests/test_subscription_routines.py \
  tests/test_firestore_db.py \
  tests/test_mcp_runtime.py
git commit -m "feat: persist Claude routine session links"
```

---

### Task 2: Expose authenticated review inbox and detail reads

**Files:**
- Modify: `interfaces/web_server.py:4204-4220`
- Create: `tests/test_review_api.py`

**Interfaces:**
- Preserves: `GET /api/reviews?limit=20` with a `reviews` array envelope
- Adds: `GET /api/reviews/{routine}/{target_date}` with one `review` object envelope
- Adds browser-safe migration recovery from a correlated `RoutineRunStore`
- Returns 404 for a missing review and 422 for an unsupported routine or invalid ISO date

- [ ] **Step 1: Write failing authenticated API tests**

Create `tests/test_review_api.py` using the same import-stubbing pattern as `tests/test_web_server.py::_stub_web_server_imports`. Override `require_hub_session` only inside the test fixture, and monkeypatch `memory.firestore_db.RoutineReviewStore` plus `RoutineRunStore` with in-memory fakes.

The fixture's canonical records are:

```python
REVIEWS = {
    ("nightly", "2026-08-10"): {
        "review_id": "nightly:2026-08-10",
        "correlation_id": "corr-nightly",
        "routine": "nightly",
        "target_date": "2026-08-10",
        "routine_status": "published_claude",
        "review_text": "Nightly review, Sir.\nRecovery was good.",
        "action_ids": ["task-1"],
        "partial_actions": [{"tool": "task_edit", "error": "conflict"}],
        "published_at": "2026-08-10T22:15:00+00:00",
    },
    ("morning", "2026-08-10"): {
        "review_id": "morning:2026-08-10",
        "correlation_id": "corr-morning",
        "routine": "morning",
        "target_date": "2026-08-10",
        "routine_status": "published_fallback",
        "review_text": "Morning fallback, Sir.",
        "action_ids": [],
        "partial_actions": [],
        "published_at": "2026-08-10T07:30:00+00:00",
    },
}
```

Write seven named tests: `test_review_list_returns_newest_reviews_and_safe_session_links`, `test_review_detail_returns_full_canonical_review`, `test_review_detail_recovers_safe_link_from_correlated_legacy_run`, `test_review_detail_omits_hostile_provider_url`, `test_review_detail_returns_404_when_missing`, `test_review_detail_rejects_unknown_routine_and_invalid_date`, and `test_review_routes_require_hub_auth`.

The legacy run fixture must place the session URL in `remote_trigger_result` and verify the response exposes only normalized `claude_session_url`, never `remote_trigger_result`.

- [ ] **Step 2: Run the API tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_review_api.py -q
```

Expected: FAIL because the detail route and migration-safe enrichment do not exist.

- [ ] **Step 3: Add one private response sanitizer and both reads**

In `interfaces/web_server.py`, add a synchronous helper used inside the executor:

```python
def _review_for_client(review: dict, runs) -> dict:
    from core.review_delivery import normalise_claude_session_url

    result = dict(review)
    session_url = normalise_claude_session_url(result.get("claude_session_url"))
    if not session_url and result.get("correlation_id"):
        run = runs.get(str(result["correlation_id"])) or {}
        session_url = normalise_claude_session_url(run.get("claude_session_url"))
        if not session_url:
            remote = run.get("remote_trigger_result")
            session_url = normalise_claude_session_url(
                remote.get("claude_code_session_url")
                if isinstance(remote, dict)
                else None
            )
    result.pop("claude_session_url", None)
    if session_url:
        result["claude_session_url"] = session_url
    return result
```

For `GET /api/reviews`, instantiate both stores and sanitize every returned review before `_jsonsafe_doc`. Keep the current limit behavior and envelope.

Add the detail route with `routine: Literal["morning", "nightly", "weekly"]`, canonical `date.fromisoformat` validation, and `HTTPException(status_code=404)` when `RoutineReviewStore.get` returns `None`. Return `{"review": _jsonsafe_doc(review)}` after applying `_review_for_client`.

- [ ] **Step 4: Run API and neighboring server tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_review_api.py \
  tests/test_web_server.py \
  tests/test_hub_auth.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add interfaces/web_server.py tests/test_review_api.py
git commit -m "feat: expose authenticated routine reviews"
```

---

### Task 3: Route review pushes to safe Hub detail pages

**Files:**
- Modify: `core/push_sender.py:69-end`
- Modify: `core/subscription_routines.py:28-222`
- Modify: `interfaces/mcp_runtime.py:224-315`
- Modify: `tests/test_push_sender.py:86-150`
- Modify: `tests/test_subscription_routines.py:139-195`
- Modify: `tests/test_mcp_runtime.py:203-end`
- Modify: `frontend/src/sw.ts:130-end`
- Modify: `frontend/src/sw.test.ts:1-end`

**Interfaces:**
- Extends: `send_push_to_all(text: str, message_class: str = "default", destination: str = "/", title: str = "Klaus") -> dict`
- Extends coordinator dependency: `push_sender: Callable[[str, str, str, str], dict]`
- Review publications pass `/klaus/reviews/{routine}/{target_date}`
- Review publications use `Klaus Morning Review`, `Klaus Nightly Review`, or `Klaus Weekly Review` as the notification title
- Non-review callers retain `/`
- Service worker honors only safe same-origin absolute paths

- [ ] **Step 1: Write failing backend destination tests**

Add to `tests/test_push_sender.py`:

```python
def test_payload_uses_explicit_safe_same_origin_destination():
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(store)
    with p1, p2, p3 as mock_webpush:
        push_sender.send_push_to_all(
            "Nightly review",
            "briefing",
            "/klaus/reviews/nightly/2026-08-10",
            "Klaus Nightly Review",
        )
    payload = json.loads(mock_webpush.call_args.kwargs["data"])
    assert payload["title"] == "Klaus Nightly Review"
    assert payload["url"] == "/klaus/reviews/nightly/2026-08-10"


@pytest.mark.parametrize(
    "unsafe",
    [
        "https://evil.example/phish",
        "//evil.example/phish",
        "/\\evil.example/phish",
        "/klaus\n/evil",
        "klaus/reviews/nightly/2026-08-10",
    ],
)
def test_payload_falls_back_to_root_for_unsafe_destination(unsafe):
    store = _FakeSubscriptionStore([_sub(1)])
    p1, p2, p3 = _patched(store)
    with p1, p2, p3 as mock_webpush:
        push_sender.send_push_to_all("Review", "briefing", unsafe, "Klaus Nightly Review")
    payload = json.loads(mock_webpush.call_args.kwargs["data"])
    assert payload["url"] == "/"
```

Update coordinator and MCP publication spies to accept four arguments. Assert both initial Claude publication and timeout fallback call:

```python
(text, "briefing", "/klaus/reviews/nightly/2026-08-10", "Klaus Nightly Review")
```

Retain the late-upgrade assertion that no push occurs.

- [ ] **Step 2: Run backend destination tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_push_sender.py \
  tests/test_subscription_routines.py \
  tests/test_mcp_runtime.py -q
```

Expected: FAIL because `send_push_to_all` accepts no destination and review callers pass only two arguments.

- [ ] **Step 3: Implement defense-in-depth same-origin path validation**

Add a private `_safe_destination(value: object) -> str` in `core/push_sender.py`. It returns `/` unless the value is a string that begins with exactly one `/`, contains no backslash or ASCII control character, and parses with no scheme or network location. Put the sanitized value in the push payload.

Use `routine_review_path` and `routine_review_title` in `interfaces.mcp_runtime.publish_review` and `SubscriptionRoutineCoordinator.publish_timeout_fallback`. Keep the default destination `/` and title `Klaus` so all non-review notifications remain unchanged.

- [ ] **Step 4: Write failing service-worker navigation tests**

Extend `frontend/src/sw.test.ts` so `notificationclick` supplies `notification.data.url`. Add a focused-client case using `/klaus/reviews/nightly/2026-08-10` and assert `postMessage({ type: 'NAVIGATE', path: reviewPath })`; a table-driven hostile-input case using `https://evil.example/phish`, `//evil.example/phish`, `/\\evil.example/phish`, and a path containing a newline, each asserting navigation to `/`; and a no-client case asserting `openWindow(reviewPath)`.

- [ ] **Step 5: Run the service-worker test and verify RED**

Run:

```bash
npm --prefix frontend test -- --run src/sw.test.ts
```

Expected: FAIL because `notificationclick` is hard-coded to `/`.

- [ ] **Step 6: Honor the validated notification destination**

Add `safeNotificationPath(value: unknown): string` in `frontend/src/sw.ts` with the same rules as the backend. In `notificationclick`, read `event.notification.data?.url`, sanitize it, and use that path for both `client.postMessage` and `clients.openWindow`.

Keep the existing order: close notification, register the whole async operation with `waitUntil`, focus an existing window before posting navigation, and open one window only when none exists.

- [ ] **Step 7: Run backend and service-worker tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_push_sender.py \
  tests/test_subscription_routines.py \
  tests/test_mcp_runtime.py -q
npm --prefix frontend test -- --run src/sw.test.ts
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add \
  core/push_sender.py \
  core/subscription_routines.py \
  interfaces/mcp_runtime.py \
  tests/test_push_sender.py \
  tests/test_subscription_routines.py \
  tests/test_mcp_runtime.py \
  frontend/src/sw.ts \
  frontend/src/sw.test.ts
git commit -m "feat: route routine pushes to review details"
```

---

### Task 4: Build the Klaus review inbox and full-detail UI

**Files:**
- Create: `frontend/src/api/reviews.ts`
- Create: `frontend/src/components/claude/ReviewInbox.tsx`
- Create: `frontend/src/components/claude/ReviewInbox.test.tsx`
- Create: `frontend/src/components/claude/ReviewDetailPage.tsx`
- Create: `frontend/src/components/claude/ReviewDetailPage.test.tsx`
- Modify: `frontend/src/components/claude/AskClaudePage.tsx:1-end`
- Modify: `frontend/src/components/claude/AskClaudePage.test.tsx:1-end`
- Modify: `frontend/src/App.tsx:1-180`
- Modify: `frontend/src/App.test.tsx:1-end`

**Interfaces:**
- Produces: `fetchReviews(limit?: number) -> Promise<{reviews: RoutineReview[]}>`
- Produces: `fetchReview(routine: RoutineName, targetDate: string) -> Promise<{review: RoutineReview}>`
- `/klaus` preserves the existing Claude Project launcher and adds recent review cards
- `/klaus/reviews/:routine/:targetDate` renders the complete canonical review
- `Continue in Claude` appears only when the backend returns `claude_session_url`

- [ ] **Step 1: Add the typed reviews client**

Create `frontend/src/api/reviews.ts`:

```typescript
import { apiFetch } from './client'

export type RoutineName = 'morning' | 'nightly' | 'weekly'

export interface RoutineReview {
  review_id: string
  correlation_id: string
  routine: RoutineName
  target_date: string
  routine_status: 'published_claude' | 'published_fallback' | 'late_upgraded'
  provider: 'claude_subscription' | 'deterministic'
  review_text: string
  structured: Record<string, unknown>
  action_ids: string[]
  partial_actions: Array<Record<string, unknown>>
  published_at: string
  claude_session_url?: string
}

export function fetchReviews(limit = 20) {
  return apiFetch<{ reviews: RoutineReview[] }>(`/api/reviews?limit=${limit}`)
}

export function fetchReview(routine: RoutineName, targetDate: string) {
  return apiFetch<{ review: RoutineReview }>(
    `/api/reviews/${routine}/${targetDate}`,
  )
}
```

- [ ] **Step 2: Write failing inbox component tests**

Mock `fetchReviews` and create five named cases: mixed routine cards newest-first with preview/status; nested review links; action and partial-action indicators; the empty state; and the recoverable loading failure.

Use a newline-containing review and assert the card preview is truncated without mutating the API object. The link must be `/klaus/reviews/nightly/2026-08-10`.

- [ ] **Step 3: Run the inbox tests and verify RED**

Run:

```bash
npm --prefix frontend test -- --run src/components/claude/ReviewInbox.test.tsx
```

Expected: FAIL because `ReviewInbox` does not exist.

- [ ] **Step 4: Implement the review inbox**

Use TanStack Query with `queryKey: ['reviews', 'recent']`. Render semantic links using React Router `Link`, not click-only cards. Show:

- routine label and target date;
- `routine_status` rendered as Claude, fallback, or late upgrade;
- a plain-text preview from `review_text`;
- counts for `action_ids` and `partial_actions` when nonzero;
- explicit loading, empty, and retryable error states.

Place `<ReviewInbox />` below the existing Claude connection section in `AskClaudePage`. Keep the Project launch button unchanged.

Update `AskClaudePage.test.tsx` to mock `fetchReviews` to `{reviews: []}` by default and add one assertion that the launcher and review inbox coexist.

- [ ] **Step 5: Write failing detail and route tests**

Mock `fetchReview` and create five named cases: exact full text including line breaks; action IDs and partial-action disclosures; `Continue in Claude` only with a session URL; the explicit unavailable state for fallback reviews; and loading/recoverable error states.

In `App.test.tsx`, mock both reviews API functions and start the router at `/klaus/reviews/nightly/2026-08-10`. Assert the detail heading renders and that the Claude bottom/side navigation item remains active because both navigation components already use prefix matching for `/klaus`.

- [ ] **Step 6: Run detail/route tests and verify RED**

Run:

```bash
npm --prefix frontend test -- --run \
  src/components/claude/ReviewDetailPage.test.tsx \
  src/App.test.tsx
```

Expected: FAIL because the detail component and nested route do not exist.

- [ ] **Step 7: Implement the full review detail page and nested route**

Use `useParams()` to read `routine` and `targetDate`, reject unexpected routine values in the component before calling the API, and query with `queryKey: ['reviews', routine, targetDate]`.

Render `review_text` in a normal text element with `whiteSpace: 'pre-wrap'`. Do not use `dangerouslySetInnerHTML`. Render each `action_id` as text and each partial-action object with `JSON.stringify(item, null, 2)` inside a `<pre>` so disclosures are complete and inert.

Render the Claude action only for a backend-supplied URL:

```tsx
<a
  href={review.claude_session_url}
  target="_blank"
  rel="noopener noreferrer"
>
  Continue in Claude
</a>
```

Otherwise render `Claude session unavailable for this review.`

Add the route before the plain `/klaus` route:

```tsx
<Route
  path="/klaus/reviews/:routine/:targetDate"
  element={<ReviewDetailPage />}
/>
<Route path="/klaus" element={<KlausPage />} />
```

- [ ] **Step 8: Run the complete frontend feature suite and build**

Run:

```bash
npm --prefix frontend test -- --run \
  src/components/claude/AskClaudePage.test.tsx \
  src/components/claude/ReviewInbox.test.tsx \
  src/components/claude/ReviewDetailPage.test.tsx \
  src/App.test.tsx \
  src/sw.test.ts
npm --prefix frontend run build
```

Expected: all tests pass and TypeScript/Vite build succeeds.

- [ ] **Step 9: Commit Task 4**

```bash
git add \
  frontend/src/api/reviews.ts \
  frontend/src/components/claude/ReviewInbox.tsx \
  frontend/src/components/claude/ReviewInbox.test.tsx \
  frontend/src/components/claude/ReviewDetailPage.tsx \
  frontend/src/components/claude/ReviewDetailPage.test.tsx \
  frontend/src/components/claude/AskClaudePage.tsx \
  frontend/src/components/claude/AskClaudePage.test.tsx \
  frontend/src/App.tsx \
  frontend/src/App.test.tsx
git commit -m "feat: add routine review inbox and details"
```

---

### Task 5: Make the exact final Claude response a versioned skill contract

**Files:**
- Modify: `claude/skills/klaus-live-agent/SKILL.md`
- Modify: `claude/skills/klaus-live-agent/VERSION`
- Modify: `claude/skills/klaus-morning-review/SKILL.md`
- Modify: `claude/skills/klaus-morning-review/VERSION`
- Modify: `claude/skills/klaus-nightly-review/SKILL.md`
- Modify: `claude/skills/klaus-nightly-review/VERSION`
- Modify: `claude/skills/klaus-weekly-review/SKILL.md`
- Modify: `claude/skills/klaus-weekly-review/VERSION`
- Modify: `claude/evals/skill-evals.json`
- Modify: `claude/dist/manifest.json`
- Replace: `claude/dist/klaus-live-agent-7.0.0.zip` with `claude/dist/klaus-live-agent-7.1.0.zip`
- Replace: `claude/dist/klaus-morning-review-7.0.0.zip` with `claude/dist/klaus-morning-review-7.1.0.zip`
- Replace: `claude/dist/klaus-nightly-review-7.0.0.zip` with `claude/dist/klaus-nightly-review-7.1.0.zip`
- Replace: `claude/dist/klaus-weekly-review-7.0.0.zip` with `claude/dist/klaus-weekly-review-7.1.0.zip`
- Modify: `interfaces/mcp_server.py:23,457,498,509`
- Modify: `core/subscription_routines.py:105-119`
- Modify: `core/self_manifest.py:420-432`
- Modify: `docs/CLAUDE_FIRST_USE.md:28-80`
- Modify: `tests/test_claude_skills.py:1-end`

**Interfaces:**
- Bumps the lockstep Klaus skill/MCP version from `7.0.0` to `7.1.0`
- Requires the exact published review text as the final Routine session response
- Preserves one-shot publication and forbids a second push
- Packages deterministic upload ZIPs

- [ ] **Step 1: Write failing contract/version tests**

Add to `tests/test_claude_skills.py`:

```python
def test_routine_skills_render_exact_published_text_after_success():
    for name in (
        "klaus-morning-review",
        "klaus-nightly-review",
        "klaus-weekly-review",
    ):
        text = (ROOT / "claude" / "skills" / name / "SKILL.md").read_text().lower()
        assert "exact published review text" in text
        assert "final assistant response" in text
        assert "do not replace it with an acknowledgement" in text
        assert "do not call `publish_review` again" in text
        assert "if `publish_review` fails" in text


def test_skill_version_is_7_1_0_everywhere():
    from interfaces.mcp_server import EXPECTED_SKILL_VERSION

    assert EXPECTED_SKILL_VERSION == "7.1.0"
    assert '"skill_version": "7.1.0"' in (
        ROOT / "core" / "subscription_routines.py"
    ).read_text()
    assert "Expected Claude skill version: `7.1.0`" in (
        ROOT / "core" / "self_manifest.py"
    ).read_text()
```

- [ ] **Step 2: Run the skill tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_claude_skills.py -q
```

Expected: FAIL because the final-response language is absent and all versions remain 7.0.0.

- [ ] **Step 3: Add the final-response contract to all three routine skills**

Add this section after each publication contract, with routine-appropriate nouns only where needed:

```markdown
## Final routine response

After `publish_review` returns success, use the exact published review text as the
body of the final assistant response. Do not replace it with an acknowledgement,
short summary, or “published successfully” message. You may append one short
sentence saying that Amit can continue the conversation in this Routine session.

Rendering the already-published text is not another write: do not call
`publish_review` again and do not request or send another push. If
`publish_review` fails, report the failure honestly and do not describe the
unpublished review as canonical.
```

Add `"Renders the exact published review text as the final assistant response"` to every morning/nightly/weekly case in `claude/evals/skill-evals.json` so the eval fixtures cover the new contract under each pressure case.

- [ ] **Step 4: Bump all lockstep version surfaces to 7.1.0**

Update all four skill `VERSION` files and `Skill version:` lines. Update the live-agent staleness warning, `EXPECTED_SKILL_VERSION`, both MCP server version strings, the subscription trigger payload, `core/self_manifest.py`, and the operator checklist.

All four skills must move together because `tests/test_claude_skills.py` and the MCP metadata intentionally expose one capability version.

- [ ] **Step 5: Rebuild deterministic ZIP artifacts**

Run:

```bash
.venv/bin/python scripts/package_claude_skills.py
.venv/bin/python scripts/package_claude_skills.py --check
```

Expected:

```text
Built 4 Claude skill ZIPs in /Users/amitgrupper/Desktop/Klaus/claude/dist
Claude skill artifacts match canonical sources.
```

- [ ] **Step 6: Run skill, MCP metadata, and manifest tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_claude_skills.py \
  tests/test_mcp_server.py \
  tests/test_self_manifest.py \
  tests/test_subscription_routines.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

```bash
git add \
  claude/skills \
  claude/evals/skill-evals.json \
  claude/dist \
  interfaces/mcp_server.py \
  core/subscription_routines.py \
  core/self_manifest.py \
  docs/CLAUDE_FIRST_USE.md \
  tests/test_claude_skills.py
git commit -m "feat: make routine reviews conversational"
```

---

### Task 6: Document and automate the coordinated rollout guard

**Files:**
- Modify: `docs/DEPLOYMENT.md`
- Modify: `.github/workflows/deploy.yml:90-105` only during the rollout window, then restore nightly to `true` after UAT
- Create: `tests/test_conversational_review_rollout.py`

**Interfaces:**
- Prevents a live 7.0.0 Routine instruction from receiving a 7.1.0 trigger payload
- Preserves independent morning/nightly/weekly cutovers
- Defines the saved Claude Routine instruction addendum and production UAT

- [ ] **Step 1: Write a failing deploy/runbook guard test**

Create `tests/test_conversational_review_rollout.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_runbook_documents_atomic_skill_rollout():
    text = (ROOT / "docs" / "DEPLOYMENT.md").read_text()
    for phrase in (
        "Claude skill 7.1.0 coordinated rollout",
        "KLAUS_ROUTINE_NIGHTLY_CUTOVER=false",
        "Upload all four 7.1.0 ZIP files",
        "Edit all three saved Remote Routine instructions",
        "exact published review text",
        "KLAUS_ROUTINE_NIGHTLY_CUTOVER=true",
    ):
        assert phrase in text


def test_production_cutovers_remain_independent():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "KLAUS_ROUTINE_MORNING_CUTOVER=false" in workflow
    assert "KLAUS_ROUTINE_WEEKLY_CUTOVER=false" in workflow
```

- [ ] **Step 2: Run the rollout guard and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_conversational_review_rollout.py -q
```

Expected: FAIL because the coordinated 7.1.0 rollout procedure is not documented.

- [ ] **Step 3: Add the exact operator runbook**

Add `Claude skill 7.1.0 coordinated rollout` to `docs/DEPLOYMENT.md` with this sequence:

1. Perform Tasks 1-5 and the full verification in Task 7 before any deployment.
2. Set the deploy workflow's nightly cutover to `false`; morning and weekly remain `false`.
3. Deploy and confirm `/health` before touching Claude configuration.
4. Upload all four 7.1.0 ZIP files in Claude Customize → Skills.
5. Edit all three saved Remote Routine instructions so `skill_version is 7.1.0` and append: `After the single successful publish_review call, return the exact published review text as the final assistant response. Do not publish or push again.`
6. Confirm each Routine still has only the Klaus Routines connector and remains API-triggered/manual-only.
7. Run morning, nightly, and weekly shadow UAT.
8. Restore only `KLAUS_ROUTINE_NIGHTLY_CUTOVER=true`; leave morning and weekly `false`.
9. Run one nightly live UAT and confirm no duplicate review, push, journal, or self-state write.

- [ ] **Step 4: Run the rollout guard and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_conversational_review_rollout.py -q
```

Expected: both tests pass.

- [ ] **Step 5: Commit the runbook and guard**

```bash
git add docs/DEPLOYMENT.md tests/test_conversational_review_rollout.py
git commit -m "docs: add coordinated routine skill rollout"
```

Do not change `.github/workflows/deploy.yml` in this commit. The temporary `nightly=false` and final `nightly=true` edits are production operations performed in Task 8, each with explicit user approval.

---

### Task 7: Run complete local verification and review the implementation

**Files:**
- Verify only; fix failures in the task that owns the affected file and rerun that task's tests before continuing

- [ ] **Step 1: Run the focused backend suite**

```bash
.venv/bin/python -m pytest \
  tests/test_review_delivery.py \
  tests/test_review_api.py \
  tests/test_subscription_routines.py \
  tests/test_mcp_runtime.py \
  tests/test_mcp_server.py \
  tests/test_push_sender.py \
  tests/test_firestore_db.py \
  tests/test_claude_skills.py \
  tests/test_conversational_review_rollout.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run the complete frontend suite and production build**

```bash
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

Expected: every Vitest test passes; TypeScript and Vite build successfully.

- [ ] **Step 3: Run the full offline Python regression suite**

```bash
.venv/bin/python -m pytest tests \
  --ignore=tests/test_token_budget.py \
  --ignore=tests/memory/test_pinecone_embed.py -q
```

Expected: zero failures. The two excluded suites are environment/network-specific and must be run separately only in their configured environments.

- [ ] **Step 4: Verify generated artifacts and diff hygiene**

```bash
.venv/bin/python scripts/package_claude_skills.py --check
git diff --check
git status --short
```

Expected: ZIPs match, `git diff --check` exits 0, and status contains only intentional task files plus the preserved user-owned `.claude/scheduled_tasks.lock` and `AGENTS.md` entries.

- [ ] **Step 5: Request code review**

Use `superpowers:requesting-code-review` against the complete implementation. Review especially:

- URL allowlisting and query/credential stripping;
- absence of raw provider response fields in APIs;
- one-shot publication/push behavior under fallback and late upgrade;
- auth on both review endpoints;
- inert rendering of review content;
- service-worker external-navigation rejection;
- version consistency and safe rollout order.

Address findings with `superpowers:receiving-code-review`, rerun the relevant RED/GREEN tests, then repeat Steps 1-4.

---

### Task 8: Perform coordinated Claude configuration, shadow UAT, and nightly restoration

**Files:**
- Temporarily modify, then restore: `.github/workflows/deploy.yml`
- No other source changes unless UAT reveals a defect

**External systems:**
- GitHub Actions deploy workflow
- Google Cloud Run `klaus-agent` in `me-west1`
- Claude Customize → Skills
- Claude Code morning/nightly/weekly Remote Routine settings
- Authenticated Klaus Hub

- [ ] **Step 1: Get explicit approval for production writes**

Present the verified commits, exact temporary cutover change, Claude UI edits, and rollback. Do not push, deploy, upload skills, or edit saved Routines without approval.

- [ ] **Step 2: Temporarily pause nightly in the canonical deploy workflow**

Change only:

```text
KLAUS_ROUTINE_NIGHTLY_CUTOVER=true
```

to:

```text
KLAUS_ROUTINE_NIGHTLY_CUTOVER=false
```

Keep morning/weekly false. Commit:

```bash
git add .github/workflows/deploy.yml
git commit -m "ops: pause nightly for skill upgrade"
```

- [ ] **Step 3: Push and verify the paused deployment**

```bash
git push origin main
```

Wait for `.github/workflows/deploy.yml`, then verify:

```bash
curl --fail --silent --show-error \
  https://klaus-agent-y2abtypx4q-zf.a.run.app/health
gcloud run services describe klaus-agent \
  --project klaus-agent \
  --region me-west1 \
  --format='value(spec.template.spec.containers[0].env)'
```

Expected: health succeeds; morning/nightly/weekly cutovers are all false; expected skill metadata is 7.1.0.

- [ ] **Step 4: Upload and align Claude configuration**

Upload these four exact artifacts:

```text
claude/dist/klaus-live-agent-7.1.0.zip
claude/dist/klaus-morning-review-7.1.0.zip
claude/dist/klaus-nightly-review-7.1.0.zip
claude/dist/klaus-weekly-review-7.1.0.zip
```

Edit each saved Remote Routine instruction:

- morning: verify `routine is morning` and `skill_version is 7.1.0`;
- nightly: verify `routine is nightly` and `skill_version is 7.1.0`;
- weekly: verify `routine is weekly` and `skill_version is 7.1.0`;
- all three: append `After the single successful publish_review call, return the exact published review text as the final assistant response. Do not publish or push again.`

Do not add Interactive connector access to these Routine sessions.

- [ ] **Step 5: Run one shadow UAT per routine**

From an authenticated Klaus Hub browser console, run one at a time:

```javascript
fetch('/api/routines/morning/shadow', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({target_date: new Date().toISOString().slice(0, 10)}),
}).then(async response => ({status: response.status, body: await response.json()})).then(console.log)
```

Repeat with `/api/routines/nightly/shadow` and `/api/routines/weekly/shadow`.

For each, verify in Claude that the final assistant response contains the full review text, not an acknowledgement. Verify in Klaus run state that `shadow_review` exists and no review record, push, journal, or self-state write occurred.

- [ ] **Step 6: Restore nightly only**

Change `.github/workflows/deploy.yml` back to:

```text
KLAUS_ROUTINE_MORNING_CUTOVER=false
KLAUS_ROUTINE_NIGHTLY_CUTOVER=true
KLAUS_ROUTINE_WEEKLY_CUTOVER=false
```

Commit and push:

```bash
git add .github/workflows/deploy.yml
git commit -m "ops: restore nightly Claude cutover"
git push origin main
```

- [ ] **Step 7: Run one live nightly UAT**

Trigger the existing nightly path once. Confirm:

1. Claude's final Routine response contains the exact canonical review text.
2. Klaus stores one `nightly_reviews/{target_date}` record.
3. Klaus sends one initial push.
4. Tapping the push opens `/klaus/reviews/nightly/{target_date}`.
5. The Hub shows the full review plus action and partial-action disclosures.
6. `Continue in Claude` opens the exact originating Routine session.
7. A read-only follow-up succeeds in that session.
8. A reversible task/calendar follow-up uses the Routine connector normally.
9. A prepared high-risk action cannot be approved there and directs Amit to the regular Klaus Project.
10. No duplicate review, push, journal, self-state, or behavioral-feedback write appears.

- [ ] **Step 8: Verify rollback readiness**

If any correctness criterion fails, set `KLAUS_ROUTINE_NIGHTLY_CUTOVER=false` in the workflow and redeploy. The deterministic fallback, stored Hub review, and legacy runtime remain available; morning and weekly were never enabled.

---

## Completion Criteria

- The exact canonical review is visible in the Claude Routine session and the Klaus Hub.
- Review list/detail APIs expose only safe, authenticated data.
- A notification tap reaches the correct same-origin review detail route.
- A valid review links explicitly to the exact safe Claude session; fallback/historical reviews remain readable without a link.
- The final Routine response is enforced by 7.1.0 skills and saved Routine instructions.
- Initial publication/push remains one-shot and late upgrades remain silent.
- Routine authority is unchanged and no unsupported existing-Project-chat insertion is introduced.
- Morning and weekly remain off; nightly is restored only after shadow UAT passes.
- Focused backend, complete frontend, full offline Python, packaging, build, and diff-hygiene checks are green.
