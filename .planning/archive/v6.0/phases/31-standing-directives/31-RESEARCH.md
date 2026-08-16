# Phase 31: Standing Directives - Research

**Researched:** 2026-07-19
**Domain:** Durable user-preference capture + injection across every reasoning surface of an
existing deployed personal agent (Klaus / Cloud Run / Firestore), plus a conversation-window
primitive and a reflection-driven self-directive learning loop.
**Confidence:** HIGH

## Summary

This phase is not exploratory — the architecture, pitfalls, and locked user decisions already
fully specify the shape of the work. `.planning/research/ARCHITECTURE.md` §2 gives file:line-level
integration points for a new `StandingDirectiveStore` modeled directly on the existing
`FollowupStore` (`memory/firestore_db.py:1569-1751`), a shared `render_standing_directives_block()`
formatter consumed by five call sites, and a `get_recent_window()` addition to
`FirestoreConversationStore` that must land in this phase (not Phase 32) because
`core/reflection.py`'s learning-loop fix needs it immediately — the current `_gather_day` reads
`conv_store.get(user_id)` (reflection.py:159), which returns the *active 6-hour session window*
and is empty at nightly-review time on most nights. `.planning/research/PITFALLS.md` names the two
genuinely hard judgment problems this phase must get right: coarse-topic-match veto
over-suppression (Pitfall 5) and casual venting captured as a permanent directive (Pitfall 6) —
both are mitigated by locked decisions already made in `31-CONTEXT.md` (D-01 liberal capture with
ack-as-correction-surface; D-15 topic-scoped veto with a nightly clarification queue instead of a
blanket gate).

The store, tools, and prompt wiring are mechanical and well-precedented by five existing sibling
patterns in this codebase (`FollowupStore`, `_READ_CACHE`, `SMART_AGENT_DIRECT_TOOLS`, the
`_format_now_block` render-once-reuse pattern, and the `send_and_inject`/`OutreachLogStore`
write-after-send discipline). The genuinely novel piece — and the correct focus of implementation
risk — is the reflection learning loop (DIR-06/07): pairing `OutreachLogStore` entries against
`get_recent_window()` conversation content to classify Amit's reaction (replied / ignored /
pushback) and proposing `origin="klaus_self"` directives, activated immediately per D-09, with no
comparable production reference system to copy from.

**Primary recommendation:** Build `StandingDirectiveStore` exactly on the `FollowupStore` template
(never-raise reads, re-raise writes, uuid4 doc ids, `_READ_CACHE`-backed `list_active()`), land
`get_recent_window()` on `FirestoreConversationStore` first (it is a dependency of the reflection
fix), then wire the shared formatter into the five call sites in the order: chat (`render_smart_system`)
→ triage (`autonomous_triage.md` Step-0) → Layer-2 compose → follow-up compose → interim legacy-cron
injection (nightly/morning). Do the reflection learning-loop rewrite last, since it is the piece with
no existing pattern to lean on.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Directive capture (verbatim store + ack) | API/Backend (`core/tools.py` brain-direct handler) | Database (`StandingDirectiveStore`) | Capture is a tool call triggered by brain judgment; persistence is Firestore |
| Directive injection into chat | Backend (`core/main.py::render_smart_system`) | Database (cached read) | Prompt-template substitution, same tier as `{training_profile}` |
| Directive injection into tick triage (Step-0 veto) | Backend (`core/autonomous.py::_build_triage_prompt` + `prompts/autonomous_triage.md`) | — | Free-tier Groq judgment layer, not a UI concern |
| Directive injection into Layer-2/follow-up compose | Backend (`core/autonomous.py::_compose_layer2` / `_compose_followup_layer2`) | — | Synthetic chat-turn compose, same tier as chat |
| Directive injection into legacy nightly/morning crons (interim) | Backend (`core/nightly_review.py::_gather_tomorrow`, `core/morning_briefing.py::_gather_data`) | — | Throwaway until Phase 33's cascade unifies these paths |
| List/cancel directives from chat | Backend (brain-direct tool) | Database (store read/write) | No UI surface this phase (Hub is v6.1 VIS-01, deferred) |
| Persona-conflict flag + resolution | Backend (prompt-level judgment in `smart_agent.md` capture rule) | Database (`superseded_by` write) | One-exchange resolution at capture time, not a separate flow |
| Nightly conversation-window read (`get_recent_window`) | Database (`FirestoreConversationStore`) | Backend (`core/reflection.py` consumer) | New store method; consumed by the reflection cron |
| Reflection learning loop (reaction pairing, self-directive proposal) | Backend (`core/reflection.py` + `prompts/reflection.md`) | Database (`OutreachLogStore` read, `StandingDirectiveStore` write) | Nightly cron judgment, not a request-time concern |

## User Constraints

<user_constraints>

### Locked Decisions (from CONTEXT.md — copied verbatim)

**Locked upstream (approved plan + review + research + user decisions — do not re-litigate)**
- `StandingDirectiveStore` modeled on `FollowupStore` (`memory/firestore_db.py:1569`); verbatim text + origin + triggering-context quote; never hard-delete; `superseded_by` chains
- **No automatic TTL / no default expiry** — user decision 2026-07-17 (REQUIREMENTS Out of Scope)
- Step-0 STANDING ORDERS veto sits above all other triage logic; shared `render_standing_directives_block()` formatter consumed by all 5 call sites
- `get_recent_window()` lands THIS phase (reflection's 6h session read is empty most nights — the learning loop needs it immediately)
- Veto must be topic-scoped, not blanket (Pitfall 5): a directive suppresses only what its stated scope plausibly covers; triage reasoning names the directive it applied
- `set_standing_directive` / `list_standing_directives` / `cancel_standing_directive` are brain-direct tools (`SMART_AGENT_DIRECT_TOOLS`)

**Capture judgment**
- D-01: Liberal capture — capture whenever a remark plausibly reads as a lasting wish; no gating question. The visible ack is the correction surface ("I already told you…" is a named trigger).
- D-02: Ack = echo + expiry read-back, in Klaus's voice — one line restating the wish AND the understood duration.
- D-03: For "I already told you…" triggers, store the current restatement verbatim; no history/Pinecone digging for the original.
- D-04: Accumulation guard = reflection prune-flag; nightly sanity-checks active directives against the 24h window and flags stale/contradicted ones in the nightly message. No periodic digest, no auto-decay.

**Expiry mechanics**
- D-05: Hybrid expiry — explicit timeframes parse to a hard `expires_at` at capture; event-based conditions store condition text and nightly reflection judges (vs. calendar + conversation) whether the condition ended.
- D-06: Conditionless captures — capture first, ask in the ack ("Until further notice, or is there an end to this?"). Never block storage on an answer.
- D-07: Expiry (dated or judged) is noted once in the nightly message. No silent resumption, no dedicated ping.
- D-08: When reflection can't tell whether a judged condition ended — stay active (safe default); if uncertainty persists past the plausible window, ask in the nightly. Never expire on a guess.

**Self-directive lifecycle (DIR-06/07)**
- D-09: Self-directives are active on proposal — take effect immediately; nightly announces each with a one-line veto. No pending-approval state.
- D-10: Proposal threshold = single strong signal — one clear pushback/frustration reaction is enough.
- D-11: Ignore = strong signal too — deterministic: no reply from Amit by reflection-window read time. Topic-engaging reply = replied; subject-changing reply = ignored-topic.
- D-12: Ignore-only proposals may go as far as a full stop — no forced softening — form is Klaus's per-case judgment.
- D-13: Veto = durable anti-lesson — vetoed proposals kept (status `vetoed`, never hard-deleted); reflection must not re-propose the same/near-same directive.
- D-14: No cap on proposals per nightly — everything qualifying is proposed and activated the same night.

**Veto scope, conflicts, list/cancel**
- D-15: When triage is genuinely uncertain whether scope covers a candidate outreach — suppress now AND queue a scope-clarification question for the nightly. Triage records which directive it applied and why.
- D-16: Persona conflicts (DIR-05) detected and flagged at capture — capture turn asks "which wins, Sir?" in the same exchange, records the answer as the refined directive with `superseded_by` on the old one.
- D-17: List UX = numbered list in Klaus's voice (text, expiry/condition, origin); cancel by number or NL description, brain resolves it, one-line confirm. No command syntax.
- D-18: List shows active by default; history on ask ("show me everything").

**Nightly directive traffic**
- D-19: Directive items woven into the nightly narrative — no fixed "Directives:" section, no separate message.
- D-20: Heavy nights triaged by Klaus's judgment: activations/expiries always stated; prune-flags/scope-questions may wait a night if the message runs long.

**Legacy-cron veto power (interim, until Phase 33)**
- D-21: Directives have full veto power over legacy crons (morning briefing, weekly review) — nightly is exempt (minimal carve-out: it is the veto/announcement channel).
- D-22: Veto is evaluated by the legacy composer's own compose call — directives block injected with instructions it may output a skip verdict instead of a message. Skips logged distinctly (`skipped_by_directive`).

### Claude's Discretion (from CONTEXT.md)
- `StandingDirectiveStore` schema details (status enum, condition vs date fields, provenance shape) — follow the `FollowupStore` pattern and the decisions above.
- `get_recent_window()` signature/pagination and per-message `ts` handling on `FirestoreConversationStore`.
- Exact Step-0 veto prompt wording (must satisfy D-15 + Pitfall 5 topic-scoping; negative-case fixtures arrive in Phase 35).
- How a directive-skipped legacy morning briefing interacts with the `structured` snapshot / `daily_note` hub contract (not discussed; keep the hub `/api/today` contract unbroken).
- `{standing_directives}` placeholder position in `smart_agent.md` — must sit AFTER the stable cached prefix (30.5 prompt-caching landmine: volatile content before the cache breakpoint silently kills cache reads).
- Veto-phrase recognition in next-morning chat (NL via brain; no rigid syntax).
- Dedup behavior when Amit restates an existing directive (refresh vs duplicate).

### Deferred Ideas (OUT OF SCOPE)
- Hub page for directives (list + cancel buttons) — already tracked as v6.1 VIS-01.
- "Whether a directive-skipped morning briefing still writes its structured snapshot" — flagged during discussion, not decided; Phase 33's OCC-02 makes snapshot-on-send the rule. For Phase 31, Claude's discretion with the hub contract unbroken.

</user_constraints>

## Phase Requirements

<phase_requirements>

| ID | Description | Research Support |
|----|-------------|------------------|
| DIR-01 | Amit states a lasting wish in chat; Klaus stores it verbatim as a standing directive (origin, triggering-context quote) with a one-line ack; "I already told you…" is a named capture trigger | `StandingDirectiveStore.add()` modeled on `FollowupStore.add()` (firestore_db.py:1600); `set_standing_directive` brain-direct tool + `smart_agent.md` capture-rule addition; D-01/D-02/D-03 |
| DIR-02 | Directives with a stated/implied end condition expire on it; otherwise persist until cancelled; Klaus asks "until when?" only when genuinely unsure | Hybrid expiry fields (`expires_at` for dated, `condition_text` for event-based) per D-05/D-06; nightly reflection judges condition-based expiry (D-08) |
| DIR-03 | Active directives injected verbatim into EVERY reasoning path (chat, tick triage Step-0 veto, Layer-2 compose, follow-up compose, interim cron gathers) | `render_standing_directives_block()` shared formatter, 5 call sites per ARCHITECTURE.md §2 data-flow diagram; `_READ_CACHE`-backed store read |
| DIR-04 | Amit can list and cancel standing directives from chat | `list_standing_directives`/`cancel_standing_directive` brain-direct tools, modeled on `list_followups`/`cancel_followup` (tools.py:2043-2079); D-17/D-18 |
| DIR-05 | Persona-conflict flagged, asked once, refined directive recorded with `superseded_by` link | D-16 — resolved in the same capture exchange; `superseded_by` field on the old directive doc |
| DIR-06 | Nightly reflection reads a 24h window via `get_recent_window()` (built this phase) and extracts behavioral feedback pairing each outreach with Amit's reaction | New `FirestoreConversationStore.get_recent_window()` (per-message `ts` in `_txn_append`); `core/reflection.py::_gather_day` replaces its stale `conv_store.get()` read; pairs against `OutreachLogStore.get_today()` entries |
| DIR-07 | Reflection may propose self-directives (`origin="klaus_self"`) surfaced in the nightly message with a one-line veto | D-09..D-14; `prompts/reflection.md` schema extension; woven into nightly narrative per D-19/D-20, not a separate section |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- All GCP/Pinecone resource names must stay lowercase `klaus-*` — the new `standing_directives` Firestore collection name follows this (lowercase, no camelCase).
- `load_dotenv` always with `override=True)` — no local dev script for this phase should regress that.
- The brain (`claude-sonnet-5` after Phase 30.5) never routes through the worker first — directive capture/list/cancel tools MUST be added to `SMART_AGENT_DIRECT_TOOLS`, never left worker-delegated (this is also an explicit CONTEXT.md locked decision).
- `OutreachLogStore.append` is gated on `send_and_inject` success (D-10, project invariant) — the reflection learning loop must read outreach entries as already-delivered-only; it must not itself write anything that violates this pattern for its own proposal-tracking (self-directive activation is immediate per D-09, but this is a *directive* write, not an *outreach* write — the two stores are independent, no conflict).
- Agent turns must run inside a tracked Cloud Tasks request, never a Starlette `BackgroundTask` — not directly touched by this phase (no new HTTP entry points), but any new brain-direct tool call still executes inside the existing `handle_message`/`_run_smart_loop` request path, so this invariant is inherited for free.
- Every LLM client carries an explicit timeout (`LLM_TIMEOUT_SECONDS`) — no new LLM client is introduced this phase; the reflection brain call already has this via the existing `LLMClient` construction in `core/reflection.py::_brain_reflect`.
- New env vars must be added to `deploy.yml`, not just Cloud Run console — Claude's discretion notes state "likely no new env vars this phase, but check." Confirmed by this research: no new env var is required (no new backend/model, no new threshold constant is named in any locked decision).

## Standard Stack

### Core

No new libraries required. This phase is entirely additive Firestore + prompt/tool wiring on
already-integrated SDKs.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `google-cloud-firestore` | `>=2.18` (already in requirements.txt) | `StandingDirectiveStore` persistence | Existing store-per-collection pattern; no migration needed (Firestore is schemaless) |
| `python-dateutil` | `>=2.8.2` (already in requirements.txt) | Parsing explicit directive timeframes ("until March", "next Tuesday") into `expires_at` | Already used identically for `schedule_followup`'s `when` parameter (tools.py:2019-2027) — same NL-datetime parse pattern, reuse it verbatim |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `anthropic` | `>=0.99,<1.0` (Phase 30.5 floor) | Brain-direct tool calls for capture/list/cancel | Already the call path for every other brain-direct tool; no phase-specific change |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Firestore collection-per-store (`standing_directives/{uuid4hex}`) | A single "directives" array field on the existing `UserProfileStore` doc | Rejected — array-field mutation under concurrent writes (capture from chat + reflection learning-loop write) risks lost updates; a dedicated collection with per-doc IDs (matching `FollowupStore`) avoids the whole-document-overwrite race |
| Reflection-computed reaction pairing (this phase) | A dedicated sentiment-classification model call | Rejected — one more LLM call per outreach entry is unnecessary cost; the existing single reflection brain call can receive the outreach log + windowed conversation as structured input and reason about pairing in the same call that already writes the journal |

**Installation:** No new packages. `pip install -r requirements.txt` already covers this phase's needs.

**Version verification:**
```bash
pip show google-cloud-firestore python-dateutil anthropic 2>/dev/null | grep -E "^(Name|Version)"
```
Confirmed already present in `requirements.txt` (read directly, 2026-07-19) at the versions listed above — no bump needed for this phase's scope.

## Package Legitimacy Audit

No external packages are installed in this phase — it is pure Firestore/prompt/tool wiring on
already-vetted dependencies from prior phases. The Package Legitimacy Gate protocol is not
applicable.

**Packages removed due to slopcheck [SLOP] verdict:** none (no new packages)
**Packages flagged as suspicious [SUS]:** none (no new packages)

## Architecture Patterns

### System Architecture Diagram

```
                         Amit (Telegram/Hub chat)
                                  │
                                  ▼
                   core/main.py::AgentOrchestrator.handle_message()
                                  │
                    ┌─────────────┴──────────────┐
                    │                             │
         render_smart_system()          brain judges: is this a
         injects {standing_directives}   lasting-wish capture, a list/
         (chat path, every turn)         cancel request, or a persona-
                    │                    conflict resolution?
                    │                             │
                    │                    ┌────────┼────────┬──────────────┐
                    │                    ▼        ▼        ▼              ▼
                    │           set_standing_  list_    cancel_   (conflict detected:
                    │           directive       standing_ standing_  ask "which wins?"
                    │           (tool call)     directive directive  in same turn)
                    │                    │        │        │              │
                    │                    ▼        ▼        ▼              ▼
                    │           StandingDirectiveStore (Firestore, standing_directives/{uuid})
                    │                    │ (cached via _READ_CACHE, 10-min TTL)
                    │                    ▼
                    │        render_standing_directives_block()  ◄── ONE shared formatter
                    │                    │
        ┌───────────┴────────┬──────────┼───────────────┬─────────────────────┐
        ▼                    ▼          ▼               ▼                     ▼
  render_smart_system   _build_triage  _compose_layer2  _compose_followup   nightly_review.
  (chat, every turn)    _prompt         (Layer 2,        _layer2 (follow-   _gather_tomorrow /
                        (Step-0         on speak)         up compose)        morning_briefing.
                        STANDING                                             _gather_data
                        ORDERS veto,                                         (interim, until
                        autonomous_                                          Phase 33; D-21/22
                        triage.md)                                           veto power)


              Nightly reflection learning loop (separate flow, once/night)
              ─────────────────────────────────────────────────────────────
  core/nightly_review.py::_ensure_reflection(target_date)
              │
              ▼
  core/reflection.py::run_reflection(target_date)
              │
              ├─ get_recent_window(user_id, hours=24) ──► conversation content (NEW)
              ├─ OutreachLogStore.get_today(target_date) ──► what Klaus said + when
              │
              ▼
  pair each outreach entry's "time" against subsequent conversation turns:
    - Amit engages the topic  → "replied"
    - Amit replies, different subject → "ignored-topic"
    - no reply by reflection read-time → "ignored" (D-11: strong signal)
              │
              ▼
  brain reflection call (existing _brain_reflect, extended JSON schema):
    - existing 5 keys (summary/mood/current_focus/recent_context/highlights)
    - NEW: directive_proposals[] (origin="klaus_self", D-09 active immediately)
    - NEW: prune_flags[] (D-04 — stale/contradicted active directives)
    - NEW: expiry_notes[] (D-07 — dated or judged expiries this cycle)
              │
              ▼
  StandingDirectiveStore.add(origin="klaus_self", ...) for each proposal (D-09: active on write)
  StandingDirectiveStore expire/flag calls for judged conditions (D-05/D-08)
              │
              ▼
  woven into nightly narrative (D-19/D-20) — core/nightly_review.py::_compose_nightly
  payload gains a "directive_items" block; NOT a separate message, NOT a fixed section
```

### Recommended Project Structure

No new files/folders — this phase extends existing modules:

```
memory/
├── firestore_db.py          # + StandingDirectiveStore class (sibling of FollowupStore)
└── firestore_conversation.py # + get_recent_window(), per-message ts in _txn_append

core/
├── tools.py                  # + 3 tool schemas, 3 handlers, 3 entries in SMART_AGENT_DIRECT_TOOLS
│                              #   + render_standing_directives_block() shared formatter
├── main.py                   # + {standing_directives} placeholder in render_smart_system
├── autonomous.py             # + _gather_standing_directives job (context-only, NOT a trigger);
│                              #   directives block passed into _build_triage_prompt,
│                              #   _compose_layer2, _compose_followup_layer2
├── nightly_review.py          # + directives block injected into _gather_tomorrow (interim);
│                              #   D-21 veto power in _compose_nightly (nightly EXEMPT per D-21)
├── morning_briefing.py        # + directives block injected into _gather_data (interim);
│                              #   D-22 skip-verdict handling in _compose_briefing / run_morning_briefing
└── reflection.py              # + get_recent_window() read replaces conv_store.get();
                                #   + reaction-pairing, directive-proposal, prune-flag logic

prompts/
├── smart_agent.md             # + capture rule (liberal capture, ack format, persona-conflict ask)
│                              #   + {standing_directives} placeholder after {training_profile}
├── autonomous_triage.md       # + Step-0 STANDING ORDERS veto (topic-scoped, above existing Step 1)
│                              #   + {standing_directives} in the rendered Inputs block
└── reflection.md              # + task description for reaction-pairing + directive proposals;
                                #   + 3 new optional JSON keys in the output schema
```

### Pattern 1: Sentinel-on-failure gather isolation (reused, not invented)

**What:** Every `_gather_*` function in `core/autonomous.py` owns its own try/except and returns a
typed sentinel (`[]`) on failure — `gather_situation` fans them out via `ThreadPoolExecutor` and
`fut.result()` is always safe.
**When to use:** The new `_gather_standing_directives` job added to the `jobs` dict in
`gather_situation` (autonomous.py:588-615) MUST follow this exact shape.
**Example:**
```python
# Source: core/autonomous.py:320-328 (existing sibling — _gather_due_followups)
def _gather_standing_directives(project_id: str, database: str) -> list:
    try:
        from memory.firestore_db import StandingDirectiveStore
        sds = StandingDirectiveStore(project_id=project_id, database=database)
        return sds.list_active()
    except Exception:
        logger.warning("autonomous: standing_directives gather failed", exc_info=True)
        return []
```

### Pattern 2: Render-once via a shared formatter, cache via `_READ_CACHE`

**What:** `render_standing_directives_block()` is called fresh at each of the 5 call sites (text
formatting is cheap), but the underlying Firestore read (`StandingDirectiveStore.list_active()`)
is cached via the existing module-level `_READ_CACHE` (`memory/firestore_db.py:61-86`,
`_cache_get`/`_cache_put`/`_cache_invalidate_prefix`) — this store is read on every chat turn plus
43 ticks/day, so an uncached read here would be the single highest-QPS Firestore path in the app.
**When to use:** Any new context block consumed by more than one LLM surface.
**Example:**
```python
# Source: memory/firestore_db.py:61-86 (existing _READ_CACHE pattern to replicate)
def list_active(self) -> list[dict]:
    key = ("standing_directives", "active")
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        snaps = self._col.where(filter=FieldFilter("status", "==", "active")).stream()
        result = [s.to_dict() for s in snaps]
    except Exception:
        logger.warning("StandingDirectiveStore.list_active failed", exc_info=True)
        return []
    _cache_put(key, result)
    return result
# Any write path (add/cancel/supersede) MUST call
# _cache_invalidate_prefix(("standing_directives",)) so a cross-instance-stale
# read window is bounded, not indefinite.
```

### Pattern 3: Brain-direct tool registration (3-site pattern)

**What:** Every tool the smart brain calls directly (never via `delegate_to_worker`) is registered
in exactly three places: `TOOL_SCHEMAS` (list), `_HANDLERS` (dispatch dict), and
`SMART_AGENT_DIRECT_TOOLS` (frozenset) — `schedule_followup`/`list_followups`/`cancel_followup`
(tools.py:40-52, 826-861, 2852-2854) are the exact sibling to replicate for
`set_standing_directive`/`list_standing_directives`/`cancel_standing_directive`.
**When to use:** All 3 new directive tools.
**Example:**
```python
# Source: core/tools.py:2043-2064 (list_followups handler — replicate shape for list_standing_directives)
def _handle_list_standing_directives(include_history: bool = False) -> str:
    from memory.firestore_db import StandingDirectiveStore
    store = StandingDirectiveStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    items = store.list_all() if include_history else store.list_active()
    return json.dumps([
        {
            "id": d.get("id", ""),
            "text": d.get("text", ""),
            "origin": d.get("origin", ""),
            "expires_at": d.get("expires_at"),
            "condition_text": d.get("condition_text"),
            "status": d.get("status", "active"),
        }
        for d in items
    ])
```

### Pattern 4: Stable-prefix-first prompt ordering (cache discipline)

**What:** `render_smart_system` orders placeholders `{coaching_guide}` → `{self_md}` →
`{self_state}` → `{journal_digest}` → `{training_profile}` → (prose containing `{today_date}`) →
`{current_time}` (main.py:483-491) — stable content first, volatile content last, so Anthropic's
prompt-caching prefix (Phase 30.5) stays a stable byte-for-byte match across turns.
**When to use:** `{standing_directives}` MUST be inserted as a new `.replace()` line immediately
after `{training_profile}` (main.py:489) and before `{today_date}` (main.py:490) — this is
Claude's-discretion in CONTEXT.md but the exact insertion point is now verified against the live
file, not just described.
**Example:**
```python
# Source: core/main.py:483-492 (verified live — insert the new line at the marked point)
return (
    template
    .replace("{coaching_guide}", coaching_guide_content)
    .replace("{self_md}", self._self_md_content)
    .replace("{self_state}", self_state_snippet)
    .replace("{journal_digest}", journal_digest)
    .replace("{training_profile}", training_profile_snippet)
    # INSERT HERE: .replace("{standing_directives}", standing_directives_snippet)
    .replace("{today_date}", today_label)          # dynamic — always last
    .replace("{current_time}", _current_time_israel())
)
```
And in `prompts/smart_agent.md`, the placeholder line goes after line 9 (`{training_profile}`) and
before line 13 (the prose paragraph containing the inline `{today_date}` reference) — verified via
direct grep of the live file.

### Anti-Patterns to Avoid

- **Five independent directive formatters:** Each of the 5 call sites writing its own Firestore
  query + its own string formatting for directives. This codebase already hit this exact failure
  mode once (`_format_now_block`, autonomous.py:669-683, was introduced specifically to fix a
  "one helper, three call sites, no drift" bug). Use one shared formatter, called from every site.
- **Blanket veto instead of topic-scoped veto (Pitfall 5):** Writing the Step-0 STANDING ORDERS
  instruction as "if any active directive exists, suppress" rather than "suppress only topics the
  directive's stated scope plausibly covers." A blanket gate silences unrelated proactive speech
  (supplement nudges, calendar conflicts) for the full duration of an unrelated directive — the
  inverse failure of the bug this milestone is fixing.
- **Default-expiring every directive to "fix" Pitfall 6:** CONTEXT.md's D-01/D-04 explicitly reject
  a bounded default expiry as the venting-mitigation — Amit chose liberal capture + ack-as-correction
  + nightly prune-flag instead. Do not silently reintroduce a default TTL; `.planning/REQUIREMENTS.md`
  lists "Directive default TTL" under Out of Scope as a locked user decision.
- **Treating `standing_directives` as a Layer-0 trigger:** The new `_gather_standing_directives` job
  must NEVER flip `_is_empty_signals` to `False` on its own presence — directives are context for
  triage judgment (the veto), not a reason to wake the free tier. Mirrors the existing
  `training_status`/`acwr` context-only treatment (autonomous.py:192-195).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Directive store CRUD/lifecycle | A bespoke schema from scratch | `FollowupStore`'s exact shape (never-raise reads, re-raise writes, uuid4 doc ids, `status` enum) | Already battle-tested in this codebase for a structurally identical problem (self-managed, lifecycle-bearing Firestore docs read on every tick) |
| Conversation-window truncation/formatting | Three divergent truncation implementations across Phase 31/32 consumers | One `get_recent_window()` method, built once here, reused by Phase 31's reflection fix AND Phase 32's ambient-recall tail-prepend AND Phase 32's `conversation_tail` gather job | ARCHITECTURE.md explicitly calls this out as "a genuine shared dependency" — building it three times risks three divergent truncation/formatting bugs |
| NL date/timeframe parsing for directive expiry | A custom date-phrase parser | `dateutil.parser` (already a dependency, already used identically in `_handle_schedule_followup`, tools.py:2019-2027) | Same problem shape (NL → ISO datetime), already solved, already tested in production |
| Persona-conflict detection | A separate rules engine or classifier | Brain judgment at capture time (D-16) — the capture turn itself asks "which wins, Sir?" | The milestone's own philosophy (judgment over scripts) argues against a deterministic conflict-detection engine; a hand-rolled rules table would need constant maintenance as persona routines evolve |

**Key insight:** Every mechanical piece of this phase (store schema, tool registration, cache
pattern, render-once-reuse) has a live, working sibling elsewhere in this exact codebase. The only
place genuine design judgment is needed is the two hard LLM-judgment problems already named in
PITFALLS.md (veto scoping, venting-vs-directive) and the reflection learning loop's reaction-pairing
logic — everything else should be copy-the-pattern, not invent-a-new-one.

## Common Pitfalls

### Pitfall 1: Directives Veto by Coarse Topic Match, Over-Suppressing Unrelated Proactive Speech

**What goes wrong:** A directive like "stop nagging about training while I'm in France" is meant to
suppress training-scheduling nudges, not every proactive message. If the Step-0 STANDING ORDERS
veto in `autonomous_triage.md` evaluates as "does an active directive exist that's vaguely related"
rather than a topic-scoped check, Klaus can go silent on genuinely unrelated things (supplement
nudge, calendar conflict, health anomaly) for the full directive duration — the inverse of the bug
this milestone fixes, and harder to notice because silence looks like correct judgment.
**Why it happens:** The cheapest implementation of "inject directives, let the model veto" is a
single coarse gate, especially under Groq's tight per-request token budget which pressures the
triage prompt toward terse, blunt instructions.
**How to avoid:** Write the Step-0 veto instruction to require the directive's stated scope to
plausibly cover the specific occasion content, not just co-occur temporally. D-15 (locked): when
genuinely uncertain, suppress now AND queue a scope-clarification question for the nightly — triage
must record which directive it applied and why (feeds Phase 33's `get_recent_decisions`).
**Warning signs:** A multi-day stretch of zero autonomous outreach correlating with an active
directive whose text is topically narrower than the silence suggests; eval fixtures that are
positive-suppression-only with no negative (unrelated-topic → should NOT suppress) cases.
**Phase to address:** Phase 31 (veto instruction design + D-15 scope-uncertainty handling);
negative-case eval fixtures land in Phase 35 per the milestone's own sequencing (HARD-01).

### Pitfall 2: Casual Venting Gets Captured as a Permanent Standing Directive

**What goes wrong:** The capture rule fires on "a lasting wish about Klaus's behavior," including
"I already told you…" Conversational venting ("ugh, don't ask me about running today") is
linguistically identical to a genuine standing order but semantically a one-off mood. Without a
correction surface, one bad-day capture quietly reshapes weeks of proactive behavior (directives
are injected verbatim into every reasoning path).
**Why it happens:** LLM classification of "durable vs. momentary" from a single utterance is
genuinely hard, and optimizing purely for recall (never missing a real directive, since Amit
explicitly complained about *under*-capture in the France case) has no symmetric false-positive cost
built in by default.
**How to avoid:** This is the exact tension CONTEXT.md's D-01/D-02/D-04 already resolved: liberal
capture (favor recall) + a one-line ack that reads as an active correction surface ("Standing
order, Sir: …") + a nightly reflection prune-flag that sanity-checks active directives against the
24h window and flags stale/contradicted ones. Do NOT reintroduce a bounded default expiry as a
mitigation — that was explicitly considered and rejected (REQUIREMENTS.md Out of Scope).
**Warning signs:** Directive store grows a document per emotionally charged message rather than
per deliberate instruction; a directive's triggering-context quote reads like a complaint, not an
instruction.
**Phase to address:** Phase 31 — the ack format IS the mitigation; the reflection prune-flag is the
backstop. Verify via an eval fixture pairing a vent-style message against a genuine-directive
message and asserting the ack correctly reads back what was actually said (so a misread is
correctable on the spot).

### Pitfall 3: `{standing_directives}` Placed Before the Stable Cache Prefix Silently Kills Prompt-Caching

**What goes wrong:** Anthropic's cache breakpoint looks back at the prefix up to the point it's
set; any volatile content placed before the stable prefix (rather than strictly after it, matching
the existing `{today_date}`/`{current_time}` tail-ordering) turns every call into a fresh cache
write with no read — silently paying the 1.25x write premium on every single turn while believing
caching is "on."
**Why it happens:** Each phase ships its own prompt addition in relative isolation; the ordering
discipline established in Phase 30.5 is easy to forget unless explicitly re-checked.
**How to avoid:** `{standing_directives}` goes in the `.replace()` chain AFTER `{training_profile}`
and BEFORE `{today_date}` (verified exact insertion point above, in Pattern 4) — directive content
is semi-volatile (changes when directives are added/cancelled/expired, likely less often than
`{self_state}` but more often than `{self_md}`), so it belongs in the volatile-but-not-daily-clock
zone, same tier as `{journal_digest}`/`{training_profile}`, never before `{self_md}`.
**Warning signs:** `cache_read_input_tokens` (Phase 30.5's new metering field) drops toward 0 after
this phase's deploy.
**Phase to address:** Phase 31 (placement) — verification is possible only after Phase 30.5's
cache-token metering ships; if Phase 30.5 hasn't landed the metering yet when this phase deploys,
note the gap explicitly rather than silently skip the check.

### Pitfall 4: New `standing_directives` Gather Silently Defeats the Free-Tier Cost Gate

**What goes wrong:** If `_gather_standing_directives` (added to `gather_situation`'s `jobs` dict) is
not explicitly excluded from `_is_empty_signals`, its mere presence (any active directive at all)
could flip `empty=False` on every tick for the entire duration any directive is active — spending
Groq (and on Groq degradation, Sonnet) budget on ticks that used to be free no-ops.
**Why it happens:** `_is_empty_signals` (autonomous.py:175-220) requires an explicit per-field
decision; forgetting the exclusion is the default failure mode for any new gather field.
**How to avoid:** Treat `standing_directives` exactly like `training_status`/`acwr`/`training_evidence`
— context-only, never checked in `_is_empty_signals`. Add an explicit code comment at the same
location documenting why (mirrors the existing comment block at autonomous.py:192-220).
**Warning signs:** Autonomous tick frequency/cost increases measurably the moment any directive
becomes active, with no corresponding new genuinely-salient signal.
**Phase to address:** Phase 31 (this gather is added in this phase, so the exclusion must land in
the same change).

### Pitfall 5: Judgment-Learning-Loop Reaction Pairing Overcorrects From a Single Ambiguous Signal

**What goes wrong:** D-10/D-11 (locked) deliberately choose fast adaptation — a single strong
pushback, or even a single ignored outreach, is enough to ground a self-directive proposal. This is
an explicit user choice (Amit wants Klaus to self-correct fast), but it means a delayed reply
misread as "ignored," or one uncharacteristically terse reply misread as "pushback," can swing
behavior visibly the next day.
**Why it happens:** Reaction classification (replied / ignored-topic / ignored) from a single
day's conversation is inherently noisy at n=1.
**How to avoid:** This is a locked user decision, not a bug to defensively soften — the user
explicitly rejected the "weight by volume/consistency over multiple days" guard that a generic
memory-system pattern would suggest. Do NOT quietly reintroduce it. The actual safety net is D-13
(vetoed proposals are a durable anti-lesson, never re-proposed) plus D-17/D-18 (Amit can always
list/cancel). Implement reaction classification exactly as D-11 specifies: no reply by
reflection-window read time = ignored (deterministic), topic-engaging reply = replied,
subject-changing reply = ignored-topic.
**Warning signs:** A pattern of self-directives being proposed then immediately vetoed on the same
topic repeatedly — this would indicate the classification itself is systematically wrong (e.g.
mistaking a delayed-but-genuine reply for "ignored"), which IS worth investigating, distinct from
the accepted fast-adaptation tradeoff itself.
**Phase to address:** Phase 31 (implement per the locked decisions); Phase 35's eval fixtures should
include at least one reaction-pairing fixture per HARD-01's scope, but the negative-guard pattern
itself is explicitly out of scope for this phase.

### Pitfall 6: Reflection's Stale 6-Hour Read Silently Persists If `get_recent_window()` Isn't Actually Wired In

**What goes wrong:** `core/reflection.py::_gather_day` currently calls
`conv_store.get(user_id)` (reflection.py:159), which is `FirestoreConversationStore.get()` — the
ACTIVE session window bounded by `SESSION_TIMEOUT_HOURS` (default 6h). At the nightly reflection
time (22:00 legacy cron, or whenever `_ensure_reflection` fires from `nightly_review.py`), this is
empty on most nights because the last chat activity was hours earlier. If the learning loop is
built on top of this existing call without actually replacing it with `get_recent_window()`, the
entire DIR-06/07 feature silently sees no conversation data, ever — this is a live, already-known
bug (documented in ARCHITECTURE.md as "B3"), not a hypothetical.
**Why it happens:** It's easy to add new reflection logic (reaction pairing) alongside the existing
gather call rather than replacing the specific line that's broken.
**How to avoid:** `_gather_day`'s conversation-gather block (reflection.py:152-161) must call the
NEW `get_recent_window(user_id, hours=24)` method, not `conv_store.get(user_id)`. Verify with a live
test: seed a conversation with `updated_at` >6h in the past, call `_gather_day`, and assert the
conversation list is non-empty (the current behavior would return `[]`).
**Warning signs:** `conversation` in `_gather_day`'s output stays `[]` even on nights with real
daytime chat activity.
**Phase to address:** Phase 31 — this is the single most concrete, already-diagnosed bug this phase
must fix; it is not optional or best-effort.

## Code Examples

### `StandingDirectiveStore` — modeled directly on `FollowupStore`

```python
# Source: memory/firestore_db.py:1569-1638 (FollowupStore.__init__ + .add — direct template)
class StandingDirectiveStore:
    """Persists Amit's lasting behavioral wishes (standing directives).

    Schema (collection: ``standing_directives/{uuid4hex}``):
        id: str                  # doc-id (uuid4 hex)
        text: str                # verbatim captured wish
        origin: str              # 'user_chat' | 'klaus_self' (D-09/D-11)
        context_quote: str        # the triggering exchange, verbatim (DIR-01/D-03)
        created_at: str           # ISO-8601 UTC
        status: str               # 'active' | 'expired' | 'cancelled' | 'superseded' | 'vetoed'
        expires_at: str | None    # ISO-8601 UTC — hard date expiry (D-05, explicit timeframe)
        condition_text: str | None # event-based expiry text (D-05, e.g. "while I'm in France")
        superseded_by: str | None # id of the refined directive that replaced this one (D-16)

    Reads (list_active, list_all) never raise — [] on Firestore error (D-11 tick-cost-gate
    parity with FollowupStore.list_due). Writes (add, cancel, supersede, expire) re-raise
    after logging so the caller decides. NEVER hard-delete — status transitions only.

    Phase 31 — DIR-01..07.
    """
    _COLLECTION = "standing_directives"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)

    def add(
        self, text: str, origin: str = "user_chat",
        context_quote: str = "", expires_at: str | None = None,
        condition_text: str | None = None,
    ) -> dict:
        import uuid
        from datetime import datetime, timezone
        did = uuid.uuid4().hex
        doc = {
            "id": did, "text": text, "origin": origin,
            "context_quote": context_quote,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            "expires_at": expires_at, "condition_text": condition_text,
            "superseded_by": None,
        }
        try:
            self._col.document(did).set(doc)
        except Exception:
            logger.error("StandingDirectiveStore.add failed (text=%r)", text, exc_info=True)
            raise
        _cache_invalidate_prefix(("standing_directives",))
        return doc
```

### Step-0 STANDING ORDERS veto insertion point in `autonomous_triage.md`

```markdown
<!-- Source: prompts/autonomous_triage.md:163-168 (existing "Decision procedure" header — insert
     a new Step 0 immediately above the current "Step 1 — vetoes" block) -->

## Decision procedure (run these checks in order)

Step 0 — standing orders. Before anything else, check the active standing
directives block above. A directive vetoes THIS tick's topic only if its
stated scope plausibly covers what I'm about to raise — co-occurring in time
is not enough. If a directive covers this topic, I do not act on it, and I
record which directive I applied and why in my reasoning. If I am genuinely
unsure whether a directive's scope covers this specific topic, I suppress
for now but flag the ambiguity so tonight's reflection can ask Amit to
clarify the scope.

Step 1 — vetoes. [... existing content unchanged ...]
```

### `render_standing_directives_block()` — shared formatter (chat-facing prose vs. JSON-embeddable)

```python
# Source: pattern mirrors core/autonomous.py:669-683 (_format_now_block — "one helper, three
# call sites, no drift")
def render_standing_directives_block(directives: list[dict], *, style: str = "prose") -> str:
    """One shared formatter for the standing-directives context block.

    style="prose"  — for chat/compose system-prompt injection (bulleted, human-readable).
    style="json"   — for the triage snapshot dict (compact, machine-parseable).
    Callers own their own cached store read; this function only formats.
    """
    if not directives:
        return "" if style == "prose" else "[]"
    if style == "json":
        import json as _json
        return _json.dumps([
            {"text": d.get("text", ""), "origin": d.get("origin", ""),
             "expires_at": d.get("expires_at"), "condition_text": d.get("condition_text")}
            for d in directives
        ], ensure_ascii=False)
    lines = ["**Active standing directives:**"]
    for d in directives:
        line = f"- {d.get('text', '')}"
        if d.get("expires_at"):
            line += f" (until {d['expires_at']})"
        elif d.get("condition_text"):
            line += f" (until: {d['condition_text']})"
        if d.get("origin") == "klaus_self":
            line += " [self-proposed]"
        lines.append(line)
    return "\n".join(lines)
```

### `get_recent_window()` — new method on `FirestoreConversationStore`

```python
# Source: pattern mirrors memory/firestore_conversation.py:146-166 (get_full — builds over the
# existing unbounded-by-timeout read; adds an hours cutoff against the NEW per-message ts field)
def get_recent_window(self, user_id: int, hours: int = 24, max_messages: int = 60) -> list[dict]:
    """Return messages from the last `hours`, ignoring the session-idle timeout.

    Built for the Phase 31 reflection learning-loop fix (the 6h-timeout-bounded
    `get()` is empty at nightly reflection time on most nights). Also the shared
    dependency for Phase 32's ambient-recall tail-prepend and conversation_tail gather.

    Legacy messages without a `ts` field (pre-Phase-31) are tolerated: kept by
    array position (best-effort), not KeyError'd or dropped outright.
    """
    from datetime import datetime, timezone, timedelta
    doc_ref = self._col.document(str(user_id))
    try:
        snapshot = doc_ref.get()
    except GoogleAPICallError:
        logger.warning("FirestoreConversationStore.get_recent_window failed for user_id=%d", user_id)
        return []
    if not snapshot.exists:
        return []
    messages = list((snapshot.to_dict() or {}).get("messages", []))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    windowed = []
    for m in messages:
        ts_raw = m.get("ts")
        if ts_raw is None:
            windowed.append(m)  # legacy message — no ts, keep by position
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
        except (ValueError, TypeError):
            windowed.append(m)
            continue
        if ts >= cutoff:
            windowed.append(m)
    return windowed[-max_messages:]
```

And the `ts` stamping addition in `_txn_append` (firestore_conversation.py:54):
```python
# Source: memory/firestore_conversation.py:54 (existing line — add "ts" field)
messages.append({
    "role": role, "content": content,
    "ts": datetime.now(timezone.utc).isoformat(),  # NEW — per-message timestamp
})
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `core/reflection.py::_gather_day` reads `conv_store.get(user_id)` (6h-timeout-bounded active session) | `get_recent_window(user_id, hours=24)` (timeout-independent 24h window) | This phase (Phase 31) | Fixes a live, already-diagnosed bug (ARCHITECTURE.md "B3") — the learning loop is otherwise structurally blind to the day's conversation |
| No behavioral-preference persistence layer at all — Amit had to hope Klaus "remembered" a stated preference from conversation history alone | `StandingDirectiveStore` — durable, verbatim, injected into every reasoning path | This phase | Directly fixes the milestone's own root-cause example (the France-vacation directive that silently outlived correctly stating it once) |
| Nightly/morning composers have no directive awareness at all | Interim direct injection into `nightly_review._gather_tomorrow` / `morning_briefing._gather_data` with D-21/D-22 veto power | This phase (interim — replaced by Phase 33's unified cascade) | A directive now has real teeth over legacy proactive surfaces immediately, not just chat |

**Deprecated/outdated:**
- The pattern of injecting new always-on prompt content without checking placement against the
  Phase 30.5 cache-prefix ordering — this phase (and every phase through 33) must re-verify cache
  stability, not treat it as a one-time Phase 30.5 concern (PITFALLS.md Pitfall 4).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The reflection cron entry point (`core/reflection.py::run_reflection`) is still invoked exclusively via `core/nightly_review.py::_ensure_reflection`, and the standalone `/cron/reflect` (22:00) route referenced in older docs/CLAUDE.md history is dormant/retired per the "Retired: proactive-alerts (21:30) and reflect (22:00)" note in CLAUDE.md §5 | Common Pitfalls #6, code_context | If a separate `/cron/reflect` route is still live and calling `run_reflection` independently of `_ensure_reflection`, the learning-loop fix needs to land in a single shared code path, not be duplicated — verify the route table in `interfaces/web_server.py` before implementation, not assumed from docs |
| A2 | No new Cloud Scheduler job, env var, or Firestore composite index is required for this phase (directive queries filter on a single `status` field, which Firestore auto-indexes) | Standard Stack, Project Constraints | If `list_active()`'s query ever needs a compound filter (e.g. `status == "active" AND expires_at <= now`) a composite index would be needed — verify the exact query shape chosen during implementation against Firestore's automatic-index rules before assuming none is needed |
| A3 | `prompts/reflection.md`'s existing 5-key JSON contract can be extended with 3 new *optional* keys (`directive_proposals`, `prune_flags`, `expiry_notes`) without breaking `_parse_reflection_json`'s current required-key validation, since that function only enforces `_REQUIRED_STR_KEYS` and passes through anything else via `**data` merge patterns elsewhere in the codebase | Code Examples, Architecture Patterns | If `_parse_reflection_json` is stricter than assumed (e.g. rejects unknown keys, or the current implementation silently drops unlisted keys via an allowlist-only merge), the new keys would need an explicit parse-and-validate addition, not a bolt-on — re-read `_parse_reflection_json` in full before extending its schema |

**If this table is empty:** N/A — see above; both entries are LOW risk (both resolvable by a five-minute grep/read at the start of implementation) and do not block planning.

## Open Questions (RESOLVED)

1. **How does the D-22 "skip verdict instead of a message" get expressed from the legacy composer's LLM call?**
   - What we know: D-22 says "the directives block is injected with instructions that it may output a skip verdict instead of a message. No new LLM call." `_parse_followup_action` in `core/autonomous.py` (lines 799-831) already demonstrates a precedent — a fenced ` ```json {"action": ...} ``` ` block trailing the message body, parsed out before display.
   - What's unclear: Whether `_compose_nightly`/`_compose_briefing` should adopt the identical fenced-JSON-trailer convention (parse a `{"skip": true, "reason": "..."}` block) or a different sentinel (e.g. a fixed leading token like `SKIP:`).
   - Recommendation: Reuse the `_parse_followup_action` fenced-JSON-trailer pattern exactly — it's already proven, already has a test precedent, and keeps the parsing logic consistent across the codebase. The planner should specify the exact sentinel shape as an implementation task, not leave it to per-composer improvisation.
   - RESOLVED: adopted — 31-05 (`_parse_briefing_skip`) and 31-06 reuse the `_parse_followup_action` fenced-JSON-trailer convention with a `{"skip": true, "reason": "..."}` object.

2. **Does the morning-briefing D-22 skip verdict still write the `structured` snapshot / `daily_note` used by the hub's `/api/today` contract?**
   - What we know: CONTEXT.md's `<deferred>` section explicitly flags this as undecided for Phase 31, with Claude's discretion to keep the hub contract unbroken; Phase 33's OCC-02 will make "snapshot-on-send" the formal rule.
   - What's unclear: For this phase specifically, if a directive causes `run_morning_briefing` to skip the send, should `_set_state`'s `structured` write and the `daily_note`/`daily_note_date` write (morning_briefing.py:163-197) still happen?
   - Recommendation: For Phase 31 only, do NOT write `structured`/`daily_note` on a directive-skipped morning briefing — the hub's `/api/today` should fall back to its existing "Coach note coming after your morning briefing" placeholder (referenced in the existing code comment at morning_briefing.py:176) rather than surface stale or misleading structured data from a briefing that didn't actually fire. This keeps the hub contract unbroken (no crash, sensible placeholder) without pre-deciding Phase 33's formal rule.
   - RESOLVED: adopted — 31-05 Task 1 explicitly skips the `structured`/`daily_note` writes on a directive-skipped morning briefing, keeping the hub `/api/today` placeholder fallback.

3. **What exact reflection-window "read time" does D-11's "no reply by reflection-window read time" mean in practice, given the nightly can fire organically (Sleep-Focus trigger, any time) or via the 01:00 backstop?**
   - What we know: `nightly_target_date()` (nightly_review.py:46-48) already handles the wind-down-belongs-to-prior-day logic via a 5-hour shift; `_ensure_reflection` runs whenever the nightly fires, organic or backstop.
   - What's unclear: If Amit's reply to an outreach arrives AFTER the organic Sleep-Focus trigger fires but BEFORE the 01:00 backstop, does that late-but-real reply get correctly classified as "replied" (not "ignored"), or does reflection only ever see the conversation snapshot as of whichever trigger actually ran it?
   - Recommendation: Since `_ensure_reflection` only runs once per `target_date` (idempotent, guarded by journal presence), the reaction-pairing read happens exactly once, at whichever time the nightly actually fires for that date. This is an accepted, inherent limitation of the once-per-night design — a genuinely late reply (after the organic trigger, before backstop) that arrives in the gap is a rare edge case, not worth special-casing. Flag this as a known limitation in the plan rather than building extra machinery to handle it.
   - RESOLVED: adopted — 31-06 Task 1 records the once-per-night read-time limitation as an accepted edge case (no special-casing).

## Environment Availability

Not applicable — this phase has no new external dependencies (no new tools, services, runtimes,
databases, or package managers). All required infrastructure (Firestore, the existing Cloud Run
service, the existing brain/tick-brain LLM clients) is already live and verified by Phase 30.5.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (`pytest.ini`: `testpaths = tests`, `python_files = test_*.py`) |
| Config file | `/Users/amitgrupper/Desktop/Klaus/pytest.ini` |
| Quick run command | `pytest tests/test_firestore_conversation.py tests/test_autonomous.py tests/test_reflection.py -x` |
| Full suite command | `pytest tests/` (segfaults in one process per known grpc/protobuf gotcha — verify per-file; 1775+ passing baseline must hold, per-file verification is the established workaround) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DIR-01 | `set_standing_directive` captures verbatim text + origin + context_quote | unit | `pytest tests/test_tools.py -k standing_directive -x` | ❌ Wave 0 (new store + handler tests) |
| DIR-02 | Directive with explicit timeframe gets `expires_at`; conditionless persists indefinitely | unit | `pytest tests/test_firestore_db.py -k StandingDirectiveStore -x` | ❌ Wave 0 |
| DIR-03 | Directives block appears in all 5 injection sites | integration | `pytest tests/test_main.py tests/test_autonomous.py -k standing_directives -x` | ❌ Wave 0 (extend existing files) |
| DIR-04 | `list_standing_directives`/`cancel_standing_directive` round-trip | unit | `pytest tests/test_tools.py -k standing_directive -x` | ❌ Wave 0 |
| DIR-05 | Persona-conflict capture writes `superseded_by` on the old doc | unit | `pytest tests/test_firestore_db.py -k supersede -x` | ❌ Wave 0 |
| DIR-06 | `get_recent_window()` returns messages from a 24h window regardless of session timeout | unit | `pytest tests/test_firestore_conversation.py -k recent_window -x` | ❌ Wave 0 (extend existing file) |
| DIR-07 | Reflection proposes a self-directive from a single ignored/pushback signal | integration | `pytest tests/test_reflection.py -k directive_proposal -x` | ❌ Wave 0 (extend existing file) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_firestore_db.py tests/test_tools.py tests/test_firestore_conversation.py tests/test_main.py tests/test_autonomous.py tests/test_reflection.py -x` (the 6 files this phase touches)
- **Per wave merge:** Full suite run per-file (per the known segfault workaround) — no single-process `pytest tests/` invocation
- **Phase gate:** Per-file full-suite green before `/gsd:verify-work`; explicitly re-confirm the 1775+ baseline count did not drop

### Wave 0 Gaps
- [ ] `tests/test_firestore_db.py` — needs a `TestStandingDirectiveStore` class (add/list_active/cancel/supersede/expire) — no existing coverage for this store (new in this phase)
- [ ] `tests/test_tools.py` — needs 3 new handler tests (`set_standing_directive`/`list_standing_directives`/`cancel_standing_directive`) — check this file currently exists and its `FollowupStore`-handler test shape to mirror
- [ ] `tests/test_firestore_conversation.py` (92 lines, 3 existing tests) — needs `get_recent_window` coverage: (a) returns messages within 24h ignoring 6h session timeout, (b) tolerates legacy messages without `ts`, (c) respects `max_messages` cap
- [ ] `tests/test_reflection.py` (802 lines, existing) — needs: (a) `_gather_day` now uses `get_recent_window` not `conv_store.get`, (b) reaction-pairing classification (replied/ignored-topic/ignored) against `OutreachLogStore` entries, (c) a self-directive-proposal fixture, (d) a veto-then-no-re-propose fixture (D-13)
- [ ] `tests/test_autonomous.py` (1808 lines, existing) — needs: (a) `_gather_standing_directives` context-only exclusion from `_is_empty_signals`, (b) directives block present in `_build_triage_prompt` snapshot, (c) directives block present in `_compose_layer2`/`_compose_followup_layer2` synthetic content
- [ ] `tests/test_main.py` — needs: `{standing_directives}` placeholder resolution in `render_smart_system`, placed after `{training_profile}` and before `{today_date}` (assert ordering, not just presence, since cache-prefix ordering is load-bearing)
- Framework install: none — pytest + existing monkeypatch/`isolated_modules` fixtures already cover this pattern (see `tests/test_firestore_conversation.py:65` for the existing fixture convention)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-user system, existing Telegram/Hub session auth untouched by this phase |
| V3 Session Management | no | No new session surface |
| V4 Access Control | no | Single-user (Amit-only) system; no multi-tenant concern |
| V5 Input Validation | yes | Directive capture text is free-form user chat content — no injection risk into the store itself (Firestore string field, not executed), but see threat pattern below re: capture-source scoping |
| V6 Cryptography | no | No new secrets/crypto surface this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Indirect prompt injection via non-chat content triggering directive capture — content Klaus reads on Amit's behalf (an email body, a Notion page, an ingested chat log) that contains imperative-sounding text ("always do X") could theoretically be captured as if Amit said it, if the capture rule isn't scoped to genuine live chat turns | Spoofing | Scope `set_standing_directive` capture explicitly to direct conversational turns from Amit (the live `handle_message` chat path), never to tool-read content (Gmail, Notion, ingested chat-log summaries) flowing through the same context window. This is named explicitly in PITFALLS.md's Security Mistakes table — carry it forward as an implementation constraint for the capture rule in `smart_agent.md`. |
| A manipulated/misleading stored directive influencing downstream judgment indefinitely (since directives are injected verbatim into every reasoning path with no re-verification) | Tampering | `superseded_by`/`cancel`/`status` transitions are the only mutation paths (never hard-delete, matching `FollowupStore`'s discipline) — every state change is auditable via Firestore doc history. No confirmation gate is added for `cancel_standing_directive` per D-17 (NL cancel is fine, "cancel by number or description"), consistent with the existing `cancel_followup` idempotent-no-confirmation pattern already in production. |
| Conversation-tail content (the 24h window read by `get_recent_window()`) potentially containing an accidentally-pasted secret, forwarded to the reflection brain call | Information Disclosure | This is a PITFALLS.md-documented residual risk already accepted at the milestone level (conversation tail sent to Groq triage in Phase 32) — Phase 31's `get_recent_window()` usage is reflection-only (Anthropic backend, not Groq), which is a smaller blast radius than the Phase 32 Groq-triage case, but the same secret-denylist discipline used in `self_inspect.py`'s source-reading tools should be considered if this becomes a live concern; not a blocking requirement for this phase. |

## Sources

### Primary (HIGH confidence)
- `.planning/phases/31-standing-directives/31-CONTEXT.md` — locked user decisions (D-01..D-22), canonical refs, code context
- `.planning/research/ARCHITECTURE.md` §2 "Standing directives (Phase 31)" — file:line-verified integration points, build order, data-flow diagrams
- `.planning/research/PITFALLS.md` Pitfalls 5, 6 + cache-prefix-ordering (Pitfall 4) — directly shaped this research's risk framing
- `.planning/research/SUMMARY.md` §Phase 2 (31) — delivery list, sequencing rationale
- `.planning/REQUIREMENTS.md` §Standing Directives — DIR-01..07 verbatim, Out of Scope table
- `.planning/phases/30.5-brain-upgrade-sonnet-5/30.5-CONTEXT.md` — prompt-caching decisions constraining `{standing_directives}` placement
- Direct codebase reads (2026-07-19): `memory/firestore_db.py` (FollowupStore lines 1569-1751, `_READ_CACHE` lines 61-86, OutreachLogStore lines 1754-1866), `memory/firestore_conversation.py` (full file, 230 lines), `core/autonomous.py` (full file, 1259 lines), `core/tools.py` (SMART_AGENT_DIRECT_TOOLS lines 40-82, TOOL_SCHEMAS follow-up section lines 826-861, handlers lines 1998-2079, `_HANDLERS` dispatch lines 2827+), `core/main.py` (render_smart_system lines 304-492), `core/reflection.py` (full file, 539 lines), `core/nightly_review.py` (full file, 417 lines), `core/morning_briefing.py` (targeted reads, lines 1-264, 460-609), `prompts/autonomous_triage.md` (full file), `prompts/smart_agent.md` (grep for placeholder ordering), `prompts/reflection.md` (full file), `pytest.ini`, `requirements.txt`, `evals/tick_brain/README.md`

### Secondary (MEDIUM confidence)
- CLAUDE.md §5 "Live infrastructure" — cron/route status ("Retired: proactive-alerts (21:30) and reflect (22:00) — folded into the nightly review") — cross-checked against `core/nightly_review.py::_ensure_reflection` calling `core/reflection.py::run_reflection` directly, consistent with the CLAUDE.md note, but see Assumption A1 for the residual uncertainty about whether a standalone `/cron/reflect` route still exists in `interfaces/web_server.py` (not directly re-verified in this research pass)

### Tertiary (LOW-MEDIUM confidence, used as directional signal)
- None used — this research relied entirely on primary planning documents and direct codebase inspection; no external web sources were needed since this is a pure codebase-integration question with the design already fully specified by prior discuss-phase/research artifacts.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every dependency already verified present in `requirements.txt` at the required version
- Architecture: HIGH — every integration point verified against live source (file:line citations), not inferred; cross-checked against two independent upstream research documents that already did the file:line verification work
- Pitfalls: HIGH — grounded in the live codebase, the approved milestone plan/review, and CONTEXT.md's own locked decisions that already resolved the two hardest judgment problems
- Reflection learning loop (DIR-06/07) specifically: MEDIUM — the mechanical parts (get_recent_window, OutreachLogStore reads) are HIGH confidence; the exact reaction-classification prompt engineering and self-directive-proposal JSON schema extension are genuinely novel to this codebase with no directly comparable production reference system, so expect iteration during implementation

**Research date:** 2026-07-19
**Valid until:** 30 days (stable codebase-integration research; re-verify file:line citations if Phase 30.5 lands materially different code shape than this research assumed, e.g. if `render_smart_system`'s placeholder chain changes during the brain-migration phase)
