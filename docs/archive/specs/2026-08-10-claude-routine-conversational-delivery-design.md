# Claude Routine Conversational Delivery

**Status:** Approved in conversation on 2026-08-10

**Scope:** Morning, nightly, and weekly Claude Remote Routines

**Authority:** Klaus remains the canonical review and action store; Claude is the conversational surface.

## Problem

Claude successfully produces and publishes routine reviews, but the current delivery experience is incomplete:

- Klaus Web Push shows only a lock-screen preview.
- Tapping any push is hard-coded to open the Hub Today page.
- The Hub exposes `/api/reviews` but has no review-reading UI.
- `publish_review` pushes directly and does not provide a conversational destination.
- The full Claude Routine session exists, but neither the stored review nor the push gives Amit a reliable path back to it.

As a result, a review can be authoritative and successfully delivered while still being difficult to read and impossible to discuss naturally.

## Product decision

Use the **Claude Routine session as the conversational home for each individual review**, the **Klaus Hub as the durable review archive**, and the **regular Klaus Claude Project as the general-purpose conversation home**.

Do not attempt to inject an unsolicited assistant message into an existing consumer Claude Project chat. The supported Remote Routine API creates a new Claude Code session per trigger and returns that session's URL; it does not expose a supported append-to-existing-Project-chat operation.

Email, Telegram, and other messaging bridges are outside this change. They may be evaluated later, but they do not solve the primary requirement as cleanly: email replies are not connected to Claude, and a Telegram reply would create a second conversational runtime.

## User experience

### Routine completion

After the single successful `publish_review` call, Claude must render the complete canonical review as the final assistant response in that Routine session. A bare acknowledgement such as “published successfully” is not acceptable.

The final response may add one short line explaining that Amit can continue in the session, but it must not summarize away, rewrite, or omit the published `text`. Rendering the text in Claude is not a second publication and must not cause another push.

If publication fails, Claude must report the failure honestly and must not present unpublished content as canonical.

### Klaus notification

The OS notification remains concise because platform payload and display limits apply. It contains the review title and preview, while its destination changes from `/` to the matching authenticated Hub review route:

```text
/klaus/reviews/{routine}/{target_date}
```

All non-review notifications retain their current default destination unless a caller explicitly supplies another safe Hub path.

### Hub review archive

The existing `/klaus` “Ask Claude” surface becomes the review inbox plus Claude launcher. This avoids adding a sixth mobile navigation tab and keeps “review, then discuss with Claude” in one place.

The `/klaus` page shows:

1. the existing Klaus Project launch status and **Open Klaus in Claude** action;
2. recent morning, nightly, and weekly review cards, newest first;
3. routine type, target date, publication status, preview, and action/partial-action indicators;
4. clear loading, empty, and failure states.

Selecting a card opens:

```text
/klaus/reviews/{routine}/{target_date}
```

The detail view shows the complete canonical review text, publication time/status, disclosed actions and partial actions, and a **Continue in Claude** action when a valid Routine session URL exists.

The page must remain useful when no Claude session URL exists: fallback and historical reviews are still fully readable, with an explicit “Claude session unavailable” state rather than a broken link.

### Claude follow-up

**Continue in Claude** opens the exact Claude Code session created for that review. Amit can ask follow-up questions or request ordinary reversible actions in the context of the completed run.

The Routine connector remains intentionally less privileged than the interactive connector. It may perform permitted scheduling/task actions, but it cannot approve high-risk prepared actions. When a follow-up requires interactive approval, Claude must direct Amit to the regular Klaus Project chat.

The regular Klaus Project remains the default location for unrelated or continuing life conversations. Its Interactive connector can retrieve authoritative Klaus state and today's reviews through `get_life_snapshot`.

## Architecture

### Canonical data flow

```text
iOS/Scheduler trigger
  -> Klaus SubscriptionRoutineCoordinator
  -> Claude Routine API /fire
       returns claude_code_session_id + claude_code_session_url
  -> RoutineRunStore.remote_trigger_result
  -> Claude gathers data and calls publish_review exactly once
  -> RoutineReviewStore stores canonical review + safe Claude session URL
  -> Klaus Web Push links to authenticated Hub review detail
  -> Claude renders the same canonical text as its final session response
```

There is one Claude reasoning run, one `publish_review` call, one canonical review record, and one initial user-visible push. The Hub and Claude session are two views of the same review, not separate reviews.

### Session URL handling

`fire_remote_claude_routine` already parses and returns the provider response, and `SubscriptionRoutineCoordinator.start` already records it in `RoutineRunStore.remote_trigger_result`. Publication should extract and persist only a validated session URL.

Validation requirements:

- HTTPS only;
- host exactly `claude.ai` (optionally normalize `www.claude.ai` if returned by Anthropic);
- path restricted to known Claude session forms such as `/code/session_*` or `/epitaxy/session_*`;
- no embedded credentials;
- no caller-controlled fallback URL.

Invalid or missing values are discarded. The review still publishes normally.

`RoutineReviewStore.publish` gains an optional `claude_session_url`. Existing documents and callers remain valid. The review API may recover the URL from the correlated routine run for older records, applying the same validator, but it must never expose the raw provider response or the API-trigger bearer token.

### Review APIs

Keep `GET /api/reviews` for the inbox and add a targeted authenticated read:

```text
GET /api/reviews/{routine}/{target_date}
```

The route accepts only `morning`, `nightly`, or `weekly` and an ISO date. A missing review returns 404. The response is the JSON-safe canonical review plus the validated `claude_session_url` when available.

No review mutation endpoint is introduced.

### Push routing

Extend `send_push_to_all` with an optional destination path that defaults to `/`. Only same-origin absolute paths beginning with `/` are accepted by the push layer; external URLs, protocol-relative URLs, control characters, and malformed paths fall back to `/`.

`publish_review` supplies the deterministic Hub review path. Timeout fallbacks do the same. Late upgrades continue to send no second push.

The service worker must use the payload's validated relative path on notification click instead of always posting `/`. If a Klaus window is already open, focus it and navigate to that path. Otherwise open that same-origin path. It must never navigate a notification directly to an arbitrary external origin.

The Hub detail page performs the explicit external navigation to the validated Claude session URL after a user click.

### Routine instructions and skills

Update the morning, nightly, and weekly routine contracts to require this order:

1. finish and locally validate the complete review;
2. call `publish_review` exactly once;
3. confirm the tool succeeded;
4. render the exact published review text as the final response;
5. do not issue another notification, push, or publication.

Package updated skill ZIPs and keep the saved Claude Routine instructions aligned. Version metadata must be bumped consistently so the capability gate can detect stale uploaded skills.

Claude-native Routine completion notifications are an optional convenience, not a correctness dependency. They are in research preview and not sufficiently documented to serve as the only delivery path. If enabled successfully in Amit's account, they may open the Routine session directly; Klaus Web Push and the Hub archive remain the reliable fallback.

## Failure behavior

| Failure | Required behavior |
|---|---|
| Claude trigger fails | Deterministic fallback publishes; Hub review remains readable; no Claude button |
| Claude callback times out | One fallback review and push; a late Claude result upgrades silently with no second push |
| Missing/invalid Claude session URL | Publish normally; omit the button and show session unavailable |
| Review publication fails | Claude reports failure; no false canonical-success wording |
| Push delivery fails | Review remains stored and visible in the Hub; existing delivery telemetry records failure |
| Hub API unavailable/offline | Show a recoverable error; do not discard or mutate the stored review |
| Claude session later deleted/expired | Hub remains the durable readable record |
| Duplicate trigger/callback | Existing correlation and publication idempotency preserve one canonical review |

## Security and authority

- Klaus Firestore/Postgres/Pinecone state remains authoritative.
- The Claude session URL is navigation metadata, never evidence that publication succeeded.
- Routine sessions retain `klaus.routine` scope and never receive `klaus.approve`.
- Review APIs remain protected by `require_hub_session`.
- No raw provider trigger response, bearer token, OAuth token, or connector credential reaches the browser.
- Notification paths are same-origin allowlisted; Claude navigation occurs only from an explicit Hub link.
- Retrieved review text is rendered as data, not executable HTML.

## Testing

### Backend

- Accept documented/observed Claude session URL forms and reject hostile or malformed URLs.
- Persist a safe session URL with the canonical review without breaking legacy callers.
- Recover a safe URL from the correlated run for an older review when needed.
- Verify review list/detail authentication, routine/date validation, 404 behavior, and JSON safety.
- Verify initial Claude publication and deterministic fallback send the correct Hub review path.
- Verify late upgrade sends no push.
- Verify missing/invalid session metadata does not block publication.

### Frontend and service worker

- Review inbox renders loading, empty, error, fallback, and mixed-routine states.
- Review detail renders full text and disclosures.
- **Continue in Claude** appears only for a validated session URL.
- `/klaus` and nested review routes preserve the existing Claude launcher and mobile navigation behavior.
- Notification click honors safe relative destinations, focuses an existing client when possible, and falls back to `/` for unsafe data.

### Skills and packaging

- Each routine skill explicitly requires the full final response after successful publication.
- Each skill still forbids schema probes and more than one `publish_review` call.
- Skill version and packaged ZIP contents match.

### Production UAT

For each routine, one at a time:

1. run a shadow invocation and inspect the full Claude final response;
2. run a live invocation;
3. confirm one canonical review and one initial push;
4. tap the push and confirm the full Hub review opens;
5. tap **Continue in Claude** and confirm the exact Routine session opens;
6. ask one read-only follow-up and one reversible scheduling/task follow-up;
7. verify the routine cannot approve a prepared high-risk action;
8. confirm no duplicate review, push, journal, or self-state write.

Morning and weekly cutovers remain independent of this feature and must not be enabled merely because the delivery UI ships.

## Out of scope

- Programmatic insertion into an existing Claude Project chat.
- An inbound email-to-Claude bridge.
- A new Telegram-to-Claude bridge.
- Re-enabling the legacy model-backed Hub chat.
- Changing routine reasoning, review content policy, or high-risk action authority.
- Enabling morning or weekly production cutover without their own shadow and live UAT.

## Success criteria

- Every successful live routine has one complete canonical review in Klaus.
- The exact review is readable both in its Claude Routine session and in the Hub.
- A notification tap reliably reaches the full review rather than Today.
- A valid review offers a one-click path to its exact Claude session for follow-up.
- Fallback reviews remain readable even without a Claude session.
- No change introduces duplicate publication, duplicate push, broader routine authority, or unsupported Claude chat injection.
