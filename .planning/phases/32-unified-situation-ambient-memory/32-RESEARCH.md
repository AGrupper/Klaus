# Phase 32: Unified Situation (Ambient Memory) - Research

**Researched:** 2026-07-22
**Domain:** Internal codebase integration — ambient retrieval, conversation continuity, cross-store reconciliation, cost-gate invariants, Anthropic prompt-caching architecture
**Confidence:** HIGH (all claims verified against live source with file:line citations, or against official Anthropic/Groq/OpenAI documentation fetched this session)

## Summary

This is not a greenfield integration — it is four new read-only "gathers" wired into an
already-working 3-layer cascade (`core/autonomous.py`) and chat path (`core/main.py`).
Three of the four building blocks the phase needs already exist in some form:
`FirestoreConversationStore.get_recent_window()` (Phase 31), `MemoryStore.recall()`'s
recency-blended scoring (`_blend_recency`, already live), and
`_gather_training_evidence()` (already gathers Garmin/Hevy/training_log ground truth).
The actual net-new work is: (1) a score threshold on top of the existing recall
recency-blend, (2) a `training_reality` reconciliation function that merges four
existing read paths under an evidence-precedence rule, (3) a `current_location`
derivation from data that's already inside the existing `calendar` gather, (4) a Groq
daily-token ledger (new Firestore counter store, modeled directly on
`CostTripwireLogStore`), and (5) a token-budget guard test.

**The single highest-value finding in this research is a correction to the existing
milestone research's mental model of Anthropic prompt caching.** `core/llm_client.py`'s
Anthropic backend currently sends the *entire* rendered `smart_system` string as **one**
`system` content block with a single `cache_control` marker on it (verified,
`core/llm_client.py:232-244`). Anthropic's cache lookup is prefix-hashed **per marked
block**, not per character position within a block — placing `{current_time}` "at the
tail of the string" (the existing comment at `core/main.py:548` claims this "preserves
the cache prefix") has **no caching effect at all**, because there is only one block and
its hash covers the block's entire content. Every chat turn where the per-minute
`{current_time}` differs from the previous turn's rendering is a **full cache miss** on
BRAIN-02's own caching feature — confirmed against the official Anthropic prompt-caching
docs this session. Phase 32 is about to add three more per-turn/per-tick volatile blocks
(`{things_you_remember}`, `{training_reality}`, the continuity tail) into that same
single string, which will not make the existing problem worse (it's already
effectively-always-a-miss) but it IS the exact moment to fix it, since "guided by the
1h-TTL decision" is precisely the 30.5 discretion item this phase's own CONTEXT.md flags
as unresolved ("placeholder positions ... MUST sit AFTER the stable cached prefix").
**The fix is structural, not positional**: `LLMClient.chat()`'s `system` parameter must
be split into two actual content blocks — a cached stable block and an uncached volatile
block — not achieved by string concatenation order. See Architecture Pattern 5 below.

**Primary recommendation:** Build all four gathers as sibling `_gather_*` functions
following the exact sentinel-on-failure shape already used by the other 14 (context-only
in `_is_empty_signals`, never raise); model the Groq ledger on `CostTripwireLogStore`;
fix the cache-block split as part of wiring the new prompt blocks in; use the officially
open-sourced `o200k_harmony` tiktoken encoding (the actual gpt-oss-120b tokenizer) for
the budget-guard test rather than a char-count estimate.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01: Evidence wins.** When the 4 sources disagree about whether/when a
  session happened, precedence is **Garmin/Hevy actual-activity evidence → your
  own `training_log` self-report → calendar/planned-split (intent only)**. A
  logged run satisfies the day's planned slot even at a different time of day.
  Rationale: matches how Amit actually trains — the sensor data is ground truth
  for "did it happen."
- **D-02: Same-day + type matching.** A real activity satisfies a planned slot
  when it is the **right modality (run/lift) on the planned day** — do NOT demand
  the pace/distance/duration match the prescription. A run is a run: mark the slot
  done, coach on quality separately. A completed-but-imperfect session is "done"
  and **never re-asked about** (the SC-4 invariant). Quality/intensity commentary
  is a separate concern from slot-satisfaction.
- The reconciled window is **context-only**: it must NOT be added to
  `_is_empty_signals` (mirrors the existing training_status/acwr/standing_directives
  precedent — a single reconciliation fact must never wake the free tier).
- **D-03: Auto-block AND manual `recall` coexist.** The auto-injected "Things you
  remember" block gives ambient background every chat turn (best-effort, short
  timeout, k≈5 on the live message); the manual `recall` tool stays for deep,
  targeted mid-conversation lookups on a topic not in the current message. Two
  different needs — keep both. `recall` prompt guidance stays as-is.
- **D-04: Contradicted memories are flagged in the nightly, Amit confirms delete.**
  Reflection surfaces a memory contradicted by newer facts as a woven nightly note
  ("I still have you down as marathon-training — drop that?"); Klaus deletes ONLY
  on Amit's confirmation. This honors "deliberate-only forgetting, no auto-decay"
  (MEM-03) — the flag is a suggestion, Amit pulls the trigger. `forget_memory`
  (Pinecone delete by id) is the deliberate path, callable by Amit ("forget that")
  and executed on confirmation of a nightly flag. Reflection never auto-deletes.
- **D-05: Continuity = rehydrate the tail as history + a time-gap boundary marker.**
  After a 6h+ idle gap into a fresh/empty session, prepend the recent conversation
  tail as real message history (natural continuity — no amnesia), but insert a
  synthetic boundary marker at the seam (e.g. "[~8h elapsed since the messages
  above — a new session begins here]") so the brain reads it as memory of a prior
  thread and does NOT re-act on the last stale message as if it were just said.
  This is the both-worlds answer. Best-effort; a failed tail read yields no block,
  never blocks the turn.
- **D-06: Default home silently; ASK when ambiguous.** With no active travel
  signal, assume Tel Aviv and say nothing (the 99% case; the bug being fixed is
  Paris-getting-TLV-weather, not TLV-getting-uncertainty). Travel overrides only
  when a calendar travel event or a standing directive positively places Amit
  elsewhere. When signals **conflict or a trip window is unclear**, Klaus asks
  before serving weather/travel for a possibly-wrong location — reuse Phase 31's
  "still in France, Sir?" nightly-ask pattern rather than inventing a new prompt
  surface. Weather (`fetch_weather`, currently hardcoded default "Tel Aviv") and
  travel-time (`routes_tool`) both consume the derived `current_location`.
- The location gather is **context-only** — deriving a location must never wake
  the free tier.
- **D-07: Warn at 80% (160K of 200K TPD).** Heartbeat flags when the day's Groq
  usage crosses ~80% of the cap — early enough to react before ticks fail, not so
  early it cries wolf on a busy day. Also alert when `tick_fallback` purposes
  spike (per MEM-06).
- **D-08: At the cap, fall to the Gemini tick-brain fallback.** When the daily
  Groq budget is exhausted, route tick-brain reasoning to the existing
  `TICK_BRAIN_FALLBACK` (Gemini) for the rest of the day — ticks keep judging,
  just not free. The ledger + the 80% heartbeat warning make the (small) cost
  visible. This reuses the existing fallback path rather than silencing Klaus.
- The ledger is a **local Firestore counter** (Groq exposes no daily-remaining
  header) incremented per tick-brain call, reset daily.
- **Non-negotiable:** All four new gathers (`conversation_tail`, `standing_directives`
  [already], `training_reality`, `location`) are context-only in `_is_empty_signals`. A
  token-budget guard test asserts the MAXIMAL rendered triage prompt + `max_tokens`
  fits Groq's verified per-request ceiling (8K TPM for gpt-oss-120b). This test is
  a hard requirement of the phase, not optional.

### Claude's Discretion

- Auto-recall relevance/score threshold and recency-weighting formula (REQUIREMENTS
  says score-thresholded + recency-weighted, k≈5 — pick the concrete numbers).
- Exact rendering/labels of the "Things you remember" block and the
  `training_reality` block in chat vs triage vs paid-compose prompts (windows
  differ per MEM-04; keep the triage version within the char cap).
- Boundary-marker wording for D-05 continuity.
- Ledger schema (counter doc shape, reset mechanism, per-purpose breakdown) and
  the exact heartbeat alert phrasing.
- How `current_location` derivation reads calendar travel events (what shape marks
  a "travel event") and how it composes with a standing directive's location text.
- Placeholder positions for the new blocks in `smart_agent.md` — MUST sit AFTER
  the stable cached prefix (30.5 prompt-caching landmine: volatile content before
  the cache breakpoint silently kills cache reads).

### Deferred Ideas (OUT OF SCOPE)

- Routing occasions (nightly/morning/weekly) through the shared cascade so
  `training_reality` and the tails drive proactive judgment — that's Phase 33
  (Occasion Cascade), which explicitly depends on this phase's context-only
  invariant + Groq ledger being safe first.
- Mechanically updating the training source of truth from calendar workout actions
  or chat-reported changes — Phase 34 (Write-Backs). This phase only READS/reconciles.
- A Hub surface for browsing/forgetting memories — not in scope; deliberate
  `forget_memory` is chat/nightly-driven for now.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEM-01 | Auto-inject relevant Pinecone memories every chat turn (score-thresholded, recency-weighted, k≈5), best-effort/timeout | `_blend_recency` recency-weighting **already implemented** (`memory/pinecone_db.py:32-50`); only a score threshold is net-new (see Pattern 2). Timeout/isolation pattern in Pitfall 7 below and existing `_gather_*` sentinel convention. |
| MEM-02 | Fresh/empty session → prepend recent conversation tail (no amnesia after 6h+ idle) | `get_recent_window()` already exists (`firestore_conversation.py:205-248`); D-05 boundary-marker design in Pattern 3. |
| MEM-03 | `forget_memory` tool (Pinecone delete by id); reflection flags contradicted memories; deliberate-only, no auto-decay | Tool registration 3-site pattern verified live (`core/tools.py:40-42`, `433/463`, `3117-3118`); Pinecone delete-by-id is a stock `index.delete(ids=[...])` call (Don't Hand-Roll). |
| MEM-04 | Cascade sees conversation tail (24h/≤15msgs/240-char triage vs 48h/≤40msgs paid) + reconciled `training_reality` (planned vs log vs Hevy/Garmin vs calendar, today-3d..tomorrow), done-is-never-re-asked | Char cap (240) + window sizes already specified in `.planning/research/ARCHITECTURE.md:255`; reconciliation algorithm designed in Pattern 4 from verified store shapes (`TrainingLogStore`, `StrengthSessionStore`, `RunDetailStore`, `_planned_workouts_for`). |
| MEM-05 | All 4 new gathers context-only in `_is_empty_signals`; token-budget guard test against verified Groq per-request ceiling | `_is_empty_signals` pattern verified live (`core/autonomous.py:175-227`); Groq ceiling verified 8K TPM via official Groq docs; budget-test design in Validation Architecture below. |
| MEM-06 | Local Groq daily token ledger (Firestore counter, no vendor header); heartbeat alert at 80%/spike | Modeled on `CostTripwireLogStore` (`firestore_db.py:2223-2272`) and `increment_fallback_counter` (`firestore_db.py:146-157`); see Pattern 6. |
| MEM-07 | `current_location` derived from calendar travel events + standing directives; weather/travel-time consume it | `calendar` gather already includes `location` per event (`mcp_tools/calendar_tool.py:132`, consumed via `_gather_calendar`); hardcoded call sites identified (`nightly_review.py:201`, `morning_briefing.py:272`); heuristic designed in Pattern 5. |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Ambient auto-recall (MEM-01) | API/Backend (`core/main.py::handle_message`, pre-`_run_smart_loop`) | Database (Pinecone query) | Chat-critical-path, in-process; no browser/CDN tier exists in this single-service architecture |
| Conversation-tail continuity (MEM-02) | API/Backend (`core/main.py::handle_message`) | Database (Firestore `get_recent_window`) | Same process, same request |
| `forget_memory` tool + contradiction flag (MEM-03) | API/Backend (brain-direct tool + `core/reflection.py`) | Database (Pinecone delete-by-id) | Tool dispatch is backend-owned; no UI surface this phase |
| `training_reality` reconciliation (MEM-04) | API/Backend (`core/training_checkin.py`, pure function) | Database (Firestore reads: TrainingLogStore/StrengthSessionStore/RunDetailStore; Google Calendar API) | Pure aggregation function, no I/O of its own — callers inject already-fetched data |
| Context-only gather + budget guard (MEM-05) | API/Backend (`core/autonomous.py`) | — | Cost-gating logic is entirely server-side; no client involvement |
| Groq token ledger (MEM-06) | API/Backend (`core/tick_brain.py` write, `core/heartbeat.py` read) | Database (new Firestore counter store) | Same pattern as every other usage counter in this codebase |
| `current_location` derivation (MEM-07) | API/Backend (`core/autonomous.py` gather, pure function) | Database (Google Calendar API via existing `calendar` gather) | Deterministic string output consumed by `mcp_tools/weather_tool.py` / `routes_tool.py` call sites in `nightly_review.py`/`morning_briefing.py` |

There is no browser/CDN tier in this phase — Klaus is a single Cloud Run FastAPI
service; all four capabilities are backend-only. The map exists here to confirm that
correctly, since a plan that put ambient recall behind an API sub-route (rather than
inline in `handle_message`) would introduce an unneeded network hop this phase does not
need.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pinecone` | already `>=5.0` in `requirements.txt` | Vector recall (already used) | No change needed — `MemoryStore.recall`/`.upsert` unchanged |
| `google-cloud-firestore` | already `>=2.18` | New `GroqTokenLedgerStore` collection, `training_reality` reads | No change needed — same client pattern as every other store |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tiktoken` | `0.13.0` (latest, [VERIFIED: npm... wait PyPI registry — see provenance note] `pip index versions tiktoken` → `0.13.0`) | Token-count the maximal rendered triage prompt against Groq's `o200k_harmony`-tokenized 8K-TPM ceiling | Only for the MEM-05 budget-guard test (and optionally a `scripts/measure_groq_tokens.py` sibling to the existing `scripts/measure_prompt_tokens.py`). NOT used for Anthropic-side counting — BRAIN-06 already established that Sonnet-5 uses a different tokenizer family and must use the real `count_tokens` API, not `tiktoken`. That constraint does not apply here: Groq's `openai/gpt-oss-120b` genuinely IS tokenized with `o200k_harmony`, which OpenAI open-sourced as a `tiktoken` encoding — this is the correct, not-approximate, tool for THIS specific model. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `tiktoken` exact count | char-count heuristic (e.g. chars/3.5) | Faster, zero new dependency, but the research notes existing headroom is already thin (~0.3K tokens estimated after Phase 32's additions per `.planning/research/PITFALLS.md:244`) — an approximation with meaningful per-direction error risk either false-passes or false-fails the guard test right at the margin that matters. Prefer the exact tokenizer since it exists and is free (MIT-licensed, no network call). |
| A dedicated `GroqTokenLedgerStore` | Deriving Groq daily usage from `LLMUsageStore`'s existing per-purpose counters | `LLMUsageStore.record()` stores `total_in_tokens`/`total_out_tokens` **only as day-wide totals across ALL purposes** (smart+worker+tick+tick_autonomous+fallbacks all summed into one field) — verified at `firestore_db.py:549-556`. There is no `{purpose}_in_tokens`/`{purpose}_out_tokens` per-purpose breakdown today, only `{purpose}_calls` and `{purpose}_cost_usd`. Deriving Groq-only token usage from `LLMUsageStore` would require adding per-purpose token fields to that store (a defensible alternative — see Open Questions) OR building a dedicated ledger scoped to exactly the two Groq-billed purposes (`tick`, `tick_autonomous`) that increments only from `TickBrain.think()`'s primary (non-fallback) path. The dedicated-ledger approach is recommended: smaller blast radius, no risk of double-counting fallback-purpose tokens (which bill Gemini, not Groq) against the Groq 200K/day cap. |

**Installation:**
```bash
pip install tiktoken==0.13.0
```
Add to `requirements.txt` under a new `# --- Groq token-budget measurement (Phase 32) ---` comment block, sibling to the existing SDK section.

**Version verification:** `pip index versions tiktoken` → `0.13.0` (latest), confirmed
live this session. `o200k_harmony` encoding support landed in tiktoken's open-source
release alongside the gpt-oss model family (OpenAI's official gpt-oss model card and
the `openai/gpt-oss-120b` Hugging Face repo both reference the tokenizer as
`o200k_harmony`, "open sourced in the tiktoken library") — verify
`tiktoken.get_encoding("o200k_harmony")` loads without error in the target Python 3.11/3.13
environment before relying on it in CI (some tiktoken versions require an explicit
`tiktoken_ext` registration or a first-run download of the merge-ranks file; confirm
whether this needs network access at test time or ships vendored — if it needs to
download and CI has no network egress to `openaipublic.blob.core.windows.net`, fall back
to `cl100k_base` as a documented over-estimate, or cache the encoding file in the repo).

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|--------------|-----------|-------------|
| `tiktoken` | PyPI | ~3 years (since GPT-4 era, 2023) | Very high (tens of millions/month; core OpenAI tokenizer library) | `github.com/openai/tiktoken` | `[OK]` (verified this session via `slopcheck install tiktoken`) | Approved |

**Packages removed due to slopcheck `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** none.

`tiktoken` is tagged `[ASSUMED]` for package-name provenance purposes per the
provenance rule (the name came from training knowledge + WebSearch corroboration of the
`o200k_harmony` encoding, not from Context7/official-docs-first discovery) even though
slopcheck independently confirmed `[OK]` on the real PyPI registry. The planner should
gate the `pip install tiktoken` step behind a lightweight `checkpoint:human-verify` (or
simply have the executing agent re-run `pip index versions tiktoken` immediately before
install) rather than treating this as fully verified, per the package-name provenance
rule — registry existence does not by itself confer `[VERIFIED]` status.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
                         │  Chat turn (core/main.py::handle_message)│
                         └───────────────┬───────────────────────────┘
                                         │
                    ┌────────────────────┼─────────────────────────┐
                    ▼                    ▼                         ▼
        ┌───────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
        │ Ambient auto-recall│  │ Session-tail prepend  │  │ render_smart_    │
        │ (NEW, best-effort, │  │ (NEW, get_recent_     │  │ system()          │
        │  timeout-guarded)  │  │  window, D-05 marker)  │  │  — STABLE block   │
        │  MemoryStore.recall│  │ FirestoreConversation  │  │  (cached) THEN    │
        │  + score threshold │  │  Store.get_recent_     │  │  VOLATILE block   │
        └─────────┬──────────┘  │  window(hours=6)       │  │  (uncached, NEW   │
                  │             └───────────┬─────────────┘  │  split — see      │
                  │                         │                │  Pattern 5)       │
                  └────────────┬────────────┘                └────────┬──────────┘
                               ▼                                      ▼
                    ┌───────────────────────────────────────────────────────┐
                    │        _run_smart_loop() → Anthropic chat()            │
                    │  system=[{stable, cache_control}, {volatile}]  NEW shape│
                    └───────────────────────────────────────────────────────┘

                         ┌─────────────────────────────────────────┐
                         │  Tick (core/autonomous.py::run_autonomous│
                         │  _tick, unchanged entry, */20 7-21)      │
                         └───────────────┬───────────────────────────┘
                                         ▼
                    ┌───────────────────────────────────────────────────────┐
                    │  Layer 0 — gather_situation() ThreadPoolExecutor        │
                    │   existing 14 sources  +  NEW: conversation_tail,       │
                    │   training_reality, location   (standing_directives     │
                    │   already landed Phase 31)                              │
                    │   ALL new gathers: sentinel-on-failure, NEVER checked   │
                    │   in _is_empty_signals (context-only, MEM-05)           │
                    └───────────────┬───────────────────────────────────────┘
                                    ▼
                    ┌───────────────────────────────────────────────────────┐
                    │  _is_empty_signals() — UNCHANGED trigger set            │
                    │  (ticktick_overdue, due_followups, calendar gap/       │
                    │   overload, meals, hours_since_contact≥8h,             │
                    │   habit_pending, recovery.flags)                        │
                    └───────────────┬───────────────────────────────────────┘
                                    ▼ (if not empty)
                    ┌───────────────────────────────────────────────────────┐
                    │  Layer 1 — TickBrain.think() [Groq openai/gpt-oss-120b] │
                    │   triage_system (12,109 chars) + rendered snapshot      │
                    │   NEW: conversation_tail (24h/≤15msg/240-char cap)      │
                    │   NEW: training_reality (tight render)                  │
                    │   → increments NEW GroqTokenLedgerStore                 │
                    │   BUDGET GUARD: system+user+max_tokens(2048) ≤ 8000 TPM │
                    └───────────────┬───────────────────────────────────────┘
                                    ▼ (if should_act)
                    ┌───────────────────────────────────────────────────────┐
                    │  Layer 2 — _compose_layer2() [claude-sonnet-5]          │
                    │   training_reality: WIDER render (48h/≤40msg)           │
                    └───────────────────────────────────────────────────────┘

                         ┌─────────────────────────────────────────┐
                         │  Heartbeat (hourly)                       │
                         │   NEW: read GroqTokenLedgerStore.today()  │
                         │   alert at ≥160,000/200,000 (80%) OR      │
                         │   tick_fallback-purpose spike (MEM-06)    │
                         └─────────────────────────────────────────┘
```

### Recommended Project Structure

No new top-level modules. New code lands inside existing files:

```
core/
├── autonomous.py         # +_gather_conversation_tail, +_gather_training_reality,
│                          #  +_gather_location (sibling _gather_* functions);
│                          #  jobs dict + _build_triage_prompt gain 2 new keys
├── training_checkin.py    # +planned_sessions_for(date_iso) — MOVED from
│                          #  nightly_review.py::_planned_workouts_for (import-
│                          #  cycle constraint, see Pattern 4)
├── main.py                # handle_message: +ambient recall pre-loop, +tail
│                          #  prepend; render_smart_system(): SPLIT return into
│                          #  (stable, volatile) — see Pattern 5
├── tick_brain.py           # think(): +GroqTokenLedgerStore.increment() on the
│                          #  PRIMARY (Groq) success path only
├── heartbeat.py            # +check_groq_budget() sibling to check_daily_spend()
└── llm_client.py            # _AnthropicBackend.chat(): system param accepts
                            #  str | tuple[str, str]; only first element cached

memory/
├── pinecone_db.py          # recall(): +score threshold param/constant
└── firestore_db.py         # +GroqTokenLedgerStore (new class, ~30 lines,
                            #  modeled on CostTripwireLogStore)

mcp_tools/
├── memory.py               # +forget_memory handler (thin wrapper, mirrors
│                          #  remember/recall shape)
└── weather_tool.py / routes_tool.py  # unchanged signatures — callers
                            #  (nightly_review.py, morning_briefing.py) pass
                            #  the derived current_location string instead of
                            #  the "Tel Aviv" / hardcoded literal

prompts/
├── smart_agent.md           # +{things_you_remember}, continuity-tail marker
│                          #  text — placed in the render_smart_system VOLATILE
│                          #  half, never inside the cached stable half
└── autonomous_triage.md     # +{conversation_tail}, +{training_reality} render
                            #  slots (within the existing char-cap discipline)

tests/
├── test_autonomous.py       # +context-only invariant tests for all 4 gathers
├── test_tick_brain.py       # +GroqTokenLedgerStore increment test
└── test_token_budget.py     # NEW — the MEM-05 guard test (see Validation
                            #  Architecture)
```

### Pattern 1: Sentinel-on-failure gather isolation (existing, reuse verbatim)

**What:** Every `_gather_*` function in `core/autonomous.py` owns its own
try/except and returns a typed sentinel (`[]`/`0`/`""`/`{}`/`None`) on failure —
never raises. `gather_situation` fans them out via
`ThreadPoolExecutor(max_workers=8)`.
**When to use:** All 3 remaining new gathers (`conversation_tail`,
`training_reality`, `location`) — `standing_directives` already shipped in Phase 31
following this exact shape (`core/autonomous.py:338-355`).
**Example (verified live, this is the pattern to clone):**
```python
# Source: core/autonomous.py:338-355 (Phase 31, standing_directives — the
# newest gather, structurally identical to what Phase 32 needs to add)
def _gather_standing_directives(project_id: str, database: str) -> list:
    try:
        from memory.firestore_db import StandingDirectiveStore
        sds = StandingDirectiveStore(project_id=project_id, database=database)
        return sds.list_active()
    except Exception:
        logger.warning("autonomous: standing_directives gather failed", exc_info=True)
        return []
```
Then registered in `gather_situation`'s `jobs` dict (`core/autonomous.py:642-646`)
and deliberately **NOT** referenced in `_is_empty_signals` — the comment block at
`core/autonomous.py:220-226` is the exact wording pattern the new gathers'
context-only comments should mirror.

### Pattern 2: Auto-recall score threshold (new — the actual MEM-01 gap)

`memory/pinecone_db.py::MemoryStore.recall` (lines 129-168) **already implements**
recency-weighted ranking: `_blend_recency` scales cosine similarity by a bounded
exponential age decay (90-day half-life, capped at 30% influence — lines 32-62),
over-fetches `top_k=max(20, k*2)` candidates, re-sorts by blended score, and returns
the top `k`. This satisfies "recency-weighted, k≈5" already, with zero new code.

**What's missing:** there is currently no score floor — `recall()` always returns up
to `k` results even when the best match is a poor semantic fit (e.g. score 0.15),
which is exactly the auto-inject failure mode Pitfall 8 (below) warns about: a weak,
barely-relevant memory surfacing every turn as if it were solid ground.

**Recommendation (Claude's discretion, tag as `[ASSUMED]` — needs live tuning):**
Add a `min_score: float = 0.5` parameter to `recall()` (or a new
`recall_ambient(user_id, query, k=5, min_score=0.5)` wrapper used only by the
auto-inject path, leaving the existing tool-facing `recall()` unthresholded so a
deliberate `recall` call from the model can still see a marginal match if it chose to
search). Filter the **blended** score (post-recency-decay), not raw cosine, since
that's the score already exposed to callers. `0.5` is a reasonable starting point for
Gemini `gemini-embedding-2` cosine similarity on short personal-fact text (empirically,
well-matched short facts on this embedding family commonly land 0.55-0.85; near-random
matches sit under 0.3-0.4) but this number is NOT verified against Klaus's actual
production embedding distribution — flag as a tuning target, and consider logging
the raw (score, was_injected) pair for the first 1-2 weeks of live auto-recall so the
threshold can be re-tuned from real data rather than an estimate.

**Auto-recall must be timeout-guarded and off any blocking path** (Pitfall 7): wrap the
embed + Pinecone query in `asyncio.wait_for(..., timeout=2.5)` (or run via
`run_in_executor` if the embedding SDK call is synchronous — the Gemini SDK's `embed_content`
is a blocking call, matching the known "Gemini SDK sync-call quirk" already documented
in the codebase's own memory notes), and always fall back to an empty block on any
exception or timeout — never let it raise into `handle_message`.

### Pattern 3: Continuity tail + D-05 boundary marker (MEM-02)

`FirestoreConversationStore.get_recent_window(user_id, hours=24, max_messages=60)`
(`firestore_conversation.py:205-248`, landed Phase 31) already returns the message
array windowed by per-message `ts`, tolerating legacy messages without `ts` (kept by
array position). For MEM-02, call it with `hours=6` (matching `SESSION_TIMEOUT_HOURS`,
the same constant `get()` uses to decide a session has gone idle — `firestore_conversation.py:135`)
whenever `get(user_id)` returns an empty list AND the raw stored `messages` array is
non-empty (i.e. there IS a prior session, it's just idle-expired). Prepend those
messages as real `{"role": ..., "content": ...}` history, then insert one synthetic
system-flavored marker message at the seam:

```python
# Illustrative — not verified against a specific file since this code doesn't exist yet.
# Compute elapsed time from the last message's `ts` vs now (fall back to a generic
# phrase if `ts` is absent on the legacy tail).
gap_marker = {
    "role": "user",
    "content": f"[~{elapsed_hours:.0f}h elapsed since the messages above — "
                f"a new conversation begins here.]",
}
```
Use `role: "user"` (not a bespoke `system` block mid-conversation — Anthropic's
message format only supports `user`/`assistant` roles in the `messages` array; a
system-flavored aside has to be phrased as if Amit or the environment said it, or
rendered as an `assistant`-voiced framing) — this mirrors how the rest of this
codebase injects synthetic context (`core/autonomous.py::_compose_layer2` builds a
synthetic `{"role": "user", "content": ...}` turn for the exact same structural
reason). Keep this **best-effort**: a failed `get_recent_window` call must yield "no
tail, no marker" (fall through to today's existing amnesiac-but-safe behavior), never
raise into `handle_message`.

### Pattern 4: `training_reality` reconciliation (MEM-04)

Four existing, verified data shapes feed the reconciliation, each already read
somewhere in the codebase today:

1. **Planned (intent, weakest precedence)** — `core/nightly_review.py::_planned_workouts_for(date_iso)`
   (lines 130-162, VERIFIED) reads `UserProfileStore.load()["weekly_split"]`, keyed by
   weekday name (NOT by calendar date — it's a recurring weekly template, not a
   per-date store), and returns `{"weekday", "am": {...}, "pm": {...}}` where each slot
   dict has `label`/`modality`/`priority`. Per the architecture research
   (`ARCHITECTURE.md:224-240`), this function must be **moved** into
   `core/training_checkin.py` as `planned_sessions_for(date_iso)` — `nightly_review.py`
   then re-imports it, never the reverse, preserving the acyclic import direction
   `autonomous.py → training_checkin.py ← nightly_review.py / morning_briefing.py`
   that already holds for `compute_recovery_concern` (imported by both composer files
   from `training_checkin`, confirmed at `core/training_checkin.py:147`). **Do not**
   let `core/autonomous.py` import `core/nightly_review.py` directly — this is an
   explicit locked project decision (`.planning/STATE.md` §Decisions: "`core/autonomous.py`
   must never import `core/nightly_review.py`").
2. **Calendar (intent, may override the template)** — the existing `calendar` gather
   (`_gather_calendar`, `core/autonomous.py:240-255`) already returns today's events
   including a `location` field (via `GoogleCalendarManager.list_events`,
   `mcp_tools/calendar_tool.py:67-136`) — reuse this list rather than adding a second
   calendar API call; filter for events whose `summary`/`calendar` marks them as
   Training-calendar workouts if that distinction matters for the reconciliation
   (the existing `list_training_events` method, `calendar_tool.py:316-387`, already
   strips `Get Ready:`/`Travel:` buffer blocks and is the cleaner source if a
   Training-calendar-scoped view is preferred over the primary-calendar `calendar`
   gather).
3. **Self-report** — `TrainingLogStore.get_by_date(date_iso)` / `.get_range(start, end)`
   (`firestore_db.py:1172-1223`, VERIFIED) — rows carry `type`, `planned`, `completed`,
   `skipped_reason`, `source` (`garmin`/`telegram`/`manual_chat`).
4. **Hard evidence (strongest precedence)** — `_gather_training_evidence`
   (`core/autonomous.py:504-579`, VERIFIED, ALREADY EXISTS) already compacts
   `StrengthSessionStore.get_range` (Hevy) and `RunDetailStore.get_range` (Garmin) plus
   `TrainingLogStore.get_by_date` into `{training_log_today, strength_today, runs_today}`
   for a single date. **Reuse this function directly** rather than re-deriving evidence
   shape — it already does 2/3 of the hard work for a single day; MEM-04 just needs to
   call it across the `today-3d .. tomorrow` window (loop over dates, or extend it to
   accept a range) and merge with (1) and (2) above.

**Reconciliation algorithm (new — this phase's actual design work):**
```python
# Illustrative shape — new function, core/training_checkin.py
def build_training_reality(dates: list[str]) -> dict[str, dict]:
    """Per-date: {"planned": {...from planned_sessions_for...},
                  "calendar": [...matching Training-calendar events...],
                  "evidence": {...from _gather_training_evidence-shaped read...},
                  "slots": {"am": "done"|"missed"|"skipped:<reason>"|"planned",
                            "pm": "..."}}
    Precedence per slot (D-01): evidence (Hevy/Garmin) > self-report
    (TrainingLogStore.completed) > calendar intent > weekly_split intent.
    Matching (D-02): same calendar date + modality match only — no
    pace/distance/duration comparison. Once evidence or a completed
    self-report exists for a slot's modality on that date, status is
    terminal ("done") — never re-derived as "missed" on a later read
    (this is what makes SC-4's "never re-asked" invariant hold: the
    STATUS is idempotent per date+slot once evidence lands, so a later
    tick reading the same date sees "done" again, not a fresh "missed").
    """
```
Render TWO variants from the same underlying dict (per MEM-04's differing windows):
- **Triage (tight):** today + tomorrow only, `slots` status strings only (no raw
  evidence detail) — stays within the 240-char-per-message-equivalent discipline
  the rest of the triage prompt already follows.
- **Paid compose (wide):** full `today-3d..tomorrow` window with evidence detail
  (session titles, volumes, pace) for actual coaching quality — this is the version
  `prompts/autonomous.md`'s Layer-2 compose and (later, Phase 34) the weekly review
  consume.

### Pattern 5: Prompt-cache block split (the 30.5 landmine, corrected)

**Verified current behavior:** `core/llm_client.py:238-244` builds
`kwargs["system"] = [{"type": "text", "text": system, "cache_control": {...}}]` — ONE
dict, where `system` is main.py's fully-rendered single string (stable persona +
`{self_state}`/`{journal_digest}`/`{training_profile}`/`{standing_directives}` +
`{today_date}`/`{current_time}`, all concatenated). Per Anthropic's official
prompt-caching documentation (fetched this session): *"cache writes happen only at
your breakpoint... the hash is cumulative, covering everything up to and including the
breakpoint [so] changing any block at or before the breakpoint produces a different
hash on the next request... there is no partial cache hit."* With only one block
marked, **the entire block's content must be byte-identical to a previously cached
version for any cache read to occur.** Since `{current_time}` (formatted per-minute,
`core/main.py:1155`) sits inside that same single block, nearly every chat turn that
lands in a different clock-minute than the immediately preceding one is a **full cache
write with zero read**, regardless of where `{current_time}` is positioned in the
string. The existing code comment ("dynamic — per-minute; templates place it at the
tail to preserve the cache prefix", `core/main.py:548`) reflects a mental model —
ordering-within-a-string preserves caching — that does not hold once the *entire*
system prompt is emitted as a single cached block. The existing `.planning/research/PITFALLS.md`
Pitfall 4 makes the same ordering-based claim ("volatile content placed before the
stable prefix... turns every call into a fresh cache write"); this research refines
that finding: **position doesn't matter at all while there is only one block** — the
fix requires an actual second content block.

**Recommended fix (in scope for this phase, since it's a direct prerequisite for
correctly placing the 3 new volatile blocks MEM-01/02/04 add):**
1. Change `render_smart_system()` to return `(stable: str, volatile: str)` instead of
   one combined string — `stable` = everything that changes at most once/day
   (`{coaching_guide}`, `{self_md}`, `{self_state}`, `{journal_digest}`,
   `{training_profile}`, `{standing_directives}` — these already only change on a
   reflection/directive write, not per-turn — plus the entire hardcoded persona body up
   to, but not including, the `CURRENT TIME` section); `volatile` = `{today_date}` +
   `{current_time}` + the 3 new blocks this phase adds
   (`{things_you_remember}`, the continuity-tail marker, `{training_reality}` if/when
   chat surfaces it).
2. Change `LLMClient.chat()`'s `system` parameter to accept `str | tuple[str, str]`.
   In `_AnthropicBackend.chat()`, when given a tuple, emit **two** blocks: the first
   with `cache_control`, the second without. When given a plain `str` (existing
   callers — worker agent, tick-brain, cost-tripwire compose — none of which need
   caching), preserve today's single-block behavior unchanged (full backward
   compatibility, zero risk to non-Anthropic-caching call sites). Gemini/OpenAI
   backends simply join the tuple with `"\n\n"` (no native `cache_control` concept
   in this codebase's abstraction) — but only `_AnthropicBackend.chat()` needs any code
   change at all.
3. Every call site that currently does `system=smart_system` (a single string) needs
   updating to pass the tuple through unchanged to `chat()` — `handle_message` and
   `core/autonomous.py::_compose_layer2`/`_compose_followup_layer2` are the only three
   call sites (verified: `render_smart_system` has exactly these three callers).

**Net effect:** self_state/journal_digest/standing_directives/training_profile (which
genuinely only change ~once/day per the codebase's own docstring at
`firestore_db.py:52-58`) become part of a STABLE, cacheable block for the whole day
(refreshing the 1h TTL on every hit), and only the truly per-request content
(`current_time`, the new ambient/tail blocks) sits in the always-fresh suffix. This is
a real, measurable fix to the cache-hit-rate BRAIN-02 already claims to have shipped —
worth flagging to the planner as a finding that may warrant its own explicit
verification task (check `LLMUsageStore.summary_for_date()`'s `total_cache_read_tokens`
before/after this change on a live day) even though it's technically closing out
unfinished business from Phase 30.5, not new Phase 32 scope per se.

**This does NOT affect the triage/compose Groq or tick-brain paths** — Groq's
OpenAI-compatible API has no equivalent explicit `cache_control` mechanism in this
codebase's usage, so the budget-guard test (Pattern 1/6, Validation Architecture) is
an entirely separate concern from this caching fix.

### Pattern 6: Groq daily token ledger (MEM-06)

Model directly on `CostTripwireLogStore` (`firestore_db.py:2223-2272`, VERIFIED) —
same date-keyed-document shape, same never-raise-on-read / re-raise-on-write
discipline:

```python
# Illustrative — new class, memory/firestore_db.py, sibling to CostTripwireLogStore
class GroqTokenLedgerStore:
    """Collection: groq_token_ledger. Doc ID: YYYY-MM-DD (one doc/day).

    Incremented once per successful PRIMARY (Groq) TickBrain.think() call —
    NOT on fallback calls (those bill Gemini, not the Groq TPD cap). Uses
    firestore.Increment for concurrency-safety, same as LLMUsageStore.record().
    """
    _COLLECTION = "groq_token_ledger"

    def increment(self, purpose: str, in_tokens: int, out_tokens: int) -> None:
        # date-keyed doc; total_tokens + {purpose}_tokens both firestore.Increment
        # purpose in {"tick", "tick_autonomous"} only — never *_fallback purposes.
        ...

    def today(self) -> dict:
        # {} on error/absent — never raises (read discipline).
        ...
```
Increment inside `TickBrain.think()` (`core/tick_brain.py:186-196`) immediately after
the **primary** `self._client.chat(...)` call succeeds (the `try` block that currently
only logs on `LLMError`) — read `response["usage"]["in_tokens"]`/`["out_tokens"]` from
the unified response envelope (already returned by every backend, per
`core/llm_client.py`'s documented envelope shape) and pass them to the ledger. Do
**not** increment on the fallback path (`self._fallback_client.chat(...)`, line
211-216) — that path already bills Gemini and is tracked by the existing
`LLMUsageStore` under the `*_fallback` purpose suffix (per D-06/D-08, a fallback spike
is itself a heartbeat-alertable signal via the **existing** `LLMUsageStore` per-purpose
call counters — `tick_fallback_calls`/`tick_autonomous_fallback_calls` — no new store
needed for the spike-alert half of MEM-06, only for the raw-token-cap half).

Heartbeat (`core/heartbeat.py`, sibling to `check_daily_spend()` at line 819) reads
`GroqTokenLedgerStore().today()["total_tokens"]`, computes the fraction against `200000`,
and fires a Klaus-composed (or plain-text-fallback, mirroring `_spend_plain_text_fallback`)
alert once per day when crossing 0.8 — reuse the exact per-date suppression pattern
`CostTripwireLogStore`/`OutreachLogStore` already establish (a boolean "already alerted
today" doc check) so the 80% alert doesn't refire on every hourly heartbeat tick once
tripped.

**Reset mechanism:** none needed — a new date-keyed document is the reset (matches
`LLMUsageStore`/`CostTripwireLogStore`/`increment_fallback_counter`'s existing
"today's doc ID is the date string" convention throughout this codebase).

### Pattern 7: `current_location` derivation (MEM-07)

The `calendar` gather (`_gather_calendar`, `core/autonomous.py:240-255`) already
returns each event's `location` field (verified present in
`GoogleCalendarManager.list_events`'s per-event dict, `calendar_tool.py:125-134` — but
**absent** from `list_all_events`'s merged dict, `calendar_tool.py:293-303`; if the
location gather widens beyond primary-calendar events later, that gap needs closing
first). No new Calendar API call is needed for the common case — reuse `situation["calendar"]`.

**Heuristic (Claude's discretion — this is inherently fuzzy, tag `[ASSUMED]`):**
```
1. Home default: "Tel Aviv" (matches fetch_weather's existing default arg,
   mcp_tools/weather_tool.py:19).
2. Calendar signal: scan today's `calendar` events for a non-empty `location`
   field whose value does not obviously indicate home (simplest check: doesn't
   contain "Tel Aviv" — a deliberately conservative heuristic that under-detects
   travel rather than over-detects it, consistent with D-06's "silent home is
   the 99% case" framing). If found, that location string IS the candidate.
3. Standing-directive signal: scan active directives' `text`/`condition_text`
   (StandingDirectiveStore already exposes both as free text, no structured
   location field exists — verified firestore_db.py:1844-1853) for an explicit
   place-name pattern, e.g. a directive containing "while I'm in <X>" or
   "back from <X>" (the same phrasing Amit already used in the DIR-02/DIR-05
   example fixtures). A conservative regex against a small closed vocabulary
   is safer than an open-ended parse — genuinely ambiguous free text should
   fall to step 4, not a guessed extraction.
4. Ambiguity handling (D-06): if calendar and directive signals disagree, OR a
   travel-indicating event/directive exists but its END is unclear (no explicit
   return-date event, no directive expires_at/condition_text resolution), do
   NOT guess — suppress the location-dependent output for that day and queue a
   nightly-ask ("still in France, Sir?"), reusing Phase 31's nightly-ask
   mechanism verbatim rather than building a second confirmation surface.
```
Both consuming call sites are hardcoded today and verified:
`core/nightly_review.py:201` (`fetch_weather("Tel Aviv")`) and
`core/morning_briefing.py:272` (same literal) — both need to accept and pass through
the derived `current_location` string instead. `mcp_tools/routes_tool.py::get_travel_time`
already takes `origin`/`destination` as plain strings with no hardcoded default,
so it needs no signature change — only its caller needs the derived value.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Recency-weighted memory scoring | A new decay function | `memory/pinecone_db.py::_blend_recency` (already exists, already tuned: 90-day half-life, 30%-max influence) | It's already built and already what MEM-01 asks for — the only gap is a score floor, not the weighting itself |
| Pinecone delete-by-id (`forget_memory`) | A custom soft-delete/tombstone scheme | `index.delete(ids=[vector_id])` (stock Pinecone SDK call, same client `MemoryStore._get_index()` already constructs) | Pinecone natively supports hard delete by ID; no need for a tombstone field or a filtered-query workaround |
| Groq token counting for the budget-guard test | A hand-rolled BPE approximation or a naive chars/4 heuristic | `tiktoken.get_encoding("o200k_harmony")` — the actual, officially open-sourced gpt-oss tokenizer | This is the one case in the codebase where an approximation is NOT necessary — the real tokenizer is free, MIT-licensed, and already what Groq uses server-side for this exact model |
| Training-reality precedence merge | A generic "confidence scoring" system across sources | The explicit D-01/D-02 precedence rule (evidence > self-report > intent, same-day + modality match only) | The user has already made this a locked decision with concrete, non-probabilistic rules — building a fuzzier scoring system would be both unnecessary and would violate the "never re-asked" (SC-4) determinism the locked rule guarantees |
| Groq per-request admission control | A retry-with-backoff wrapper around 413s | The token-budget guard test (compile-time/CI check against the true ceiling) | The known 2026-06-12 incident (`max_tokens=4096` → 413 → silent reroute to metered Gemini) was already caused by exactly this class of bug; a retry loop treats the symptom, the guard test prevents the cause |

**Key insight:** almost everything MEM-01 through MEM-07 needs already exists in
`memory/pinecone_db.py`, `memory/firestore_conversation.py`, and
`core/autonomous.py`'s existing `_gather_training_evidence`. The actual net-new
logical work this phase does is narrow: one score threshold, one reconciliation
merge function, one location heuristic, one counter store, and one guard test. Most
of the "don't hand-roll" risk in this phase is building something that already
exists elsewhere in the repo, not reaching for an external dependency that shouldn't
be reached for.

## Runtime State Inventory

Not applicable — this is a greenfield-within-existing-architecture phase (new
gathers/tools/stores), not a rename/refactor/migration. Skipped per the research
protocol's trigger condition.

## Common Pitfalls

### Pitfall 1: Believing string-ordering achieves prompt-cache block separation

**What goes wrong:** A plan that says "put the new volatile blocks after
`{standing_directives}` in the template" (as the current CONTEXT.md's discretion item
literally phrases it) ships without any caching benefit, because `render_smart_system`
still returns ONE string and `LLMClient.chat()` still wraps it in ONE `cache_control`
block.
**Why it happens:** The existing code already has a comment claiming this
ordering-based approach works (`core/main.py:548`), and the existing milestone
research (`PITFALLS.md` Pitfall 4) repeats the same mental model — it's an easy trap
to inherit without re-verifying against the actual Anthropic caching mechanics.
**How to avoid:** Implement Pattern 5 above (an actual second content block, not a
string-ordering convention). Add a test asserting the STABLE half of
`render_smart_system`'s output is byte-identical across two calls one minute apart
(with only `self_state`/`journal_digest`/etc. held constant) while the VOLATILE half
differs — this is the "lightweight assertion" the existing `PITFALLS.md` Pitfall 4
already recommends, but it only proves the fix if the underlying call is actually
split into two blocks.
**Warning signs:** `cache_read_input_tokens` in `LLMUsageStore` stays near 0 across
consecutive same-day chat turns even after this phase ships.

### Pitfall 2: Token-budget guard test built on an estimate instead of the real tokenizer

**What goes wrong:** A char-count heuristic (chars/4) either over- or under-estimates
badly enough at the margin (research estimates as little as ~300 tokens of headroom
remain after this phase's additions, per `.planning/research/PITFALLS.md:244`) that the
guard test either false-passes (ships an oversized prompt that 413s in production,
recreating the exact 2026-06-12 incident class via prompt bloat instead of a request-shape
bug) or false-fails (blocks a plan that would have actually fit).
**Why it happens:** `tiktoken` isn't already a project dependency and reaching for a
"good enough" char heuristic is the path of least resistance.
**How to avoid:** Use `tiktoken.get_encoding("o200k_harmony")` — verified this session
as the actual gpt-oss-120b tokenizer, officially open-sourced by OpenAI specifically for
this model family. See Standard Stack / Validation Architecture.
**Warning signs:** The guard test passes in CI but production logs show `tick_fallback`
purpose calls climbing (a live 413-triggered reroute) shortly after this phase deploys.

### Pitfall 3: New gathers reachable from `_is_empty_signals` by accident

**What goes wrong:** Any of the 3 new gathers (`conversation_tail`, `training_reality`,
`location`) gets referenced — even indirectly, e.g. inside a helper `_is_empty_signals`
calls — in the empty-gate logic, which would make "any chat in the last 24h" (nearly
always true) flip every one of the 43 daily ticks to non-empty, defeating the entire
free-tier cost gate.
**Why it happens:** It's tempting to think "if there's a conversation to continue,
that IS worth a tick" — a reasonable-sounding but explicitly-rejected design (per
D-01/the locked decisions: the reconciled window and conversation tail are
context-only, full stop).
**How to avoid:** Add each new gather key to `_is_empty_signals`'s docstring exclusion
list (mirroring the existing `training_status`/`acwr`/`standing_directives` comments,
`core/autonomous.py:192-226`) with an explicit one-line rationale, and add a dedicated
test per gather asserting `_is_empty_signals({..., "conversation_tail": <non-trivial
value>}) is True` when no OTHER trigger is present.
**Warning signs:** `TickLogStore` shows a sharp rise in daily tick-brain call volume
immediately after this phase deploys, with no corresponding rise in genuinely
actionable outreach.

### Pitfall 4: Ambient recall blocking the chat critical path

**What goes wrong:** The embedding call (Gemini SDK, synchronous per this codebase's
own documented SDK quirk) or the Pinecone query hangs or degrades, and because it's
now on EVERY chat turn (not a weekly cron, per the known 2026-06-24 weekly-review
500 incident's blast radius), a single degraded call now stalls every conversation.
**Why it happens:** "Best-effort, timeout-guarded" is easy to state as an intent and
easy to under-implement — the happy path (recall succeeds fast) ships without ever
exercising the timeout/failure branch.
**How to avoid:** Wrap in an explicit timeout (2-3s) with a guaranteed empty-block
fallback on ANY exception, and add a test that forces the recall call to hang/raise and
asserts `handle_message` still completes within the normal latency budget.
**Warning signs:** Chat reply latency develops a new bimodal distribution (fast when
recall hits, slow when it times out).

### Pitfall 5: Ambient memory surfaces a stale/contradicted fact with no correction path shipped

**What goes wrong:** Auto-injection ships without the D-04 contradiction-flag +
`forget_memory` hygiene half landing in the SAME phase — a wrong fact (an old goal, an
outdated plan) gets re-surfaced every turn with nothing correcting it, since ambient
injection (unlike a deliberate `recall` call) has no natural "one bad turn and it's
over" boundary.
**Why it happens:** Retrieval is the fun/visible half to build; hygiene (contradiction
detection in `core/reflection.py`, the `forget_memory` tool) is easy to defer as a
"nice to have."
**How to avoid:** Ship both in this phase, per the locked decisions (D-04 is not
optional). Build at least one deliberate stale-fact fixture (a fact stated, then
contradicted in a later message) and assert reflection's nightly digest surfaces it.
**Warning signs:** `forget_memory` has zero invocations weeks after ship.

## Code Examples

### Existing recency-weighted recall (reuse as-is)
```python
# Source: memory/pinecone_db.py:32-62 (verified live)
def _blend_recency(cosine: float, ts: str | None) -> float:
    if not ts:
        return cosine
    try:
        age_days = (
            datetime.now(tz=timezone.utc) - datetime.fromisoformat(ts)
        ).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return cosine
    age_days = max(0.0, age_days)
    decay = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)   # 90 days
    return cosine * ((1.0 - _RECENCY_WEIGHT) + _RECENCY_WEIGHT * decay)  # weight=0.3
```

### Existing training-evidence compaction (reuse for training_reality)
```python
# Source: core/autonomous.py:504-579 (verified live, single-date shape —
# MEM-04 needs this looped/extended across today-3d..tomorrow)
def _gather_training_evidence(now, project_id, database) -> dict:
    ...
    return {
        "training_log_today": training_log_today,   # planned/completed/skipped rows
        "strength_today": strength_today,             # Hevy sessions (compacted)
        "runs_today": runs_today,                      # Garmin runs (compacted)
    }
```

### Existing counter-store pattern to clone for the Groq ledger
```python
# Source: memory/firestore_db.py:2223-2272 (CostTripwireLogStore, verified live)
class CostTripwireLogStore:
    _COLLECTION = "cost_tripwire_log"
    def already_fired(self, date_str: str) -> bool:
        try:
            return bool(self._col.document(date_str).get().exists)
        except Exception:
            logger.warning(...); return False
    def mark_fired(self, date_str: str, summary: dict) -> None:
        try:
            self._col.document(date_str).set({"date": date_str,
                "fired_at": firestore.SERVER_TIMESTAMP, **summary})
        except Exception:
            logger.error(...); raise
```

### Tiktoken usage for the Groq budget-guard test
```python
# Illustrative — new test, tests/test_token_budget.py
import tiktoken

def _count_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("o200k_harmony")  # the real gpt-oss-120b tokenizer
    return len(enc.encode(text))

def test_maximal_triage_prompt_fits_groq_budget():
    triage_system = _load_prompt("prompts/autonomous_triage.md")
    maximal_situation = _build_maximal_fixture_situation()  # every gather populated,
                                                             # conversation_tail at its
                                                             # 15-msg/240-char cap,
                                                             # training_reality fully
                                                             # populated for 5 days
    user_msg = _build_triage_prompt(maximal_situation, triage_system)
    total = _count_tokens(triage_system) + _count_tokens(user_msg) + TICK_BRAIN_MAX_TOKENS
    # Groq's verified per-request ceiling for openai/gpt-oss-120b (Free tier): 8,000 TPM
    assert total <= 8000, f"triage prompt+completion budget {total} exceeds Groq's 8K TPM ceiling"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `qwen/qwen3-32b` tick-brain model | `openai/gpt-oss-120b` | Pre-milestone, 2026-07-16 (Groq hard-decommissioned qwen3-32b with limited notice) | Same 8K TPM/200K TPD free-tier shape carried over; `<think>` tag stripping in `_parse_response` kept defensively even though gpt-oss doesn't emit it, in case of a future model swap |
| String-ordering as a caching strategy | Explicit multi-block `system` with per-block `cache_control` | Not yet changed in this codebase — this research recommends changing it in this phase | Currently 0% effective; the fix genuinely activates BRAIN-02's caching for the first time in practice |

**Deprecated/outdated:** the `core/main.py:548` code comment's stated rationale
("templates place it at the tail to preserve the cache prefix") should be corrected or
removed once Pattern 5 ships, since it will otherwise mislead future maintainers into
re-adding volatile content to the wrong (single, stable) block.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Auto-recall score threshold of `0.5` on the blended (recency-weighted) score is a reasonable starting cutoff for Gemini `gemini-embedding-2` cosine similarity on short personal facts | Pattern 2 | Too high → auto-recall rarely fires, feels like it "doesn't work"; too low → weak/irrelevant memories surface every turn (Pitfall 5's poisoning risk). Needs live tuning against real query/score pairs in the first 1-2 weeks. |
| A2 | Calendar-signal heuristic for "travel event" (`location` field present and doesn't contain "Tel Aviv") is sufficient to detect the common travel case | Pattern 7 | Under-detects trips where the calendar event has no `location` field set at all (Amit would need to rely on the standing-directive signal or the nightly-ask fallback in that case) — acceptable per D-06's "silent home is the 99% case, ask when ambiguous" framing, but worth confirming with Amit whether he reliably sets event locations when traveling. |
| A3 | A simple closed-vocabulary regex ("while I'm in X", "back from X") is sufficient to extract a place name from standing-directive free text | Pattern 7 | A directive phrased differently (e.g. "I'm away until Friday" with no place name) would need to fall through to the ambiguity/ask path rather than silently doing nothing — the design already routes non-matches to D-06's ask-when-ambiguous path, so the risk is bounded, not silent-wrong. |
| A4 | `tiktoken`'s `o200k_harmony` encoding is loadable in this project's Python 3.11/3.13 environment without requiring network egress at test/CI time | Standard Stack, Pitfall 2 | If the encoding's merge-ranks file requires a first-run download from an OpenAI-hosted URL and CI has no egress, the guard test would need a vendored/cached copy of the encoding file, or fall back to `cl100k_base` as a documented (slightly less accurate but same-family BPE) over-estimate. Verify this in a Wave 0 spike before relying on it. |
| A5 | Groq's "8K TPM" per-request admission control rejects a single oversized request outright (413) rather than only accumulating toward a rolling 60s window | Validation Architecture | This is inferred from the codebase's own documented 2026-06-12 incident (`max_tokens=4096` caused 413s), not from official Groq documentation (which does not describe the exact admission-control mechanism per this session's fetch). If wrong, the guard test's "≤8000 tokens per single request" framing is still a safe, conservative check (it can only be MORE conservative than the true behavior, never less), so the risk is low. |

## Open Questions

1. **Should `LLMUsageStore` gain per-purpose token fields instead of a dedicated Groq ledger?**
   - What we know: `LLMUsageStore.record()` already tracks `{purpose}_calls` and
     `{purpose}_cost_usd` per purpose, but `total_in_tokens`/`total_out_tokens` are
     day-wide sums across ALL purposes, not per-purpose.
   - What's unclear: whether extending `LLMUsageStore` with `{purpose}_in_tokens`/
     `{purpose}_out_tokens` (a small, generically useful schema addition) is preferred
     over a Groq-specific dedicated store, from a "one usage store to rule them all"
     maintainability standpoint.
   - Recommendation: build the dedicated `GroqTokenLedgerStore` (Pattern 6) for this
     phase — it's smaller-blast-radius and ships faster — but flag the `LLMUsageStore`
     schema-extension alternative as a Phase 35 (Hardening) housekeeping candidate if
     Amit wants a single source of truth for all token accounting later.

2. **Does `training_reality`'s triage rendering need per-slot detail, or just a status summary?**
   - What we know: the char-cap discipline (240 chars/message-equivalent) is locked for
     the conversation tail; MEM-04 doesn't specify an equivalent cap for `training_reality`'s
     triage rendering.
   - What's unclear: whether triage needs to see WHY a slot is "done" (e.g. "5km run
     logged via Garmin") or just the terminal status ("done"/"missed"/"planned").
   - Recommendation: keep the triage rendering to terminal status strings only (no
     evidence detail) — the triage layer's job (per `autonomous_triage.md`'s own
     "Training evidence (context, not a trigger)" section) is to know NOT to ask about
     something already resolved, which a status string alone accomplishes; save the
     rich detail for the paid compose layer where coaching quality matters.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `tiktoken` | MEM-05 budget-guard test | ✗ (not yet in `requirements.txt`) | `0.13.0` on PyPI (verified via `pip index versions tiktoken`) | `cl100k_base` encoding (same library, already-bundled, less-accurate-but-safe over-estimate) if `o200k_harmony` can't load offline |
| Groq API (`TICK_BRAIN_API_KEY`) | Tick-brain (already live) | ✓ (already deployed and in use) | `openai/gpt-oss-120b` | `TICK_BRAIN_FALLBACK_*` (Gemini) — already wired (Phase 30.5) |
| `google-cloud-firestore` | New `GroqTokenLedgerStore` | ✓ (already a dependency, `>=2.18`) | in use | — |
| `pinecone` | `forget_memory`, score-threshold recall | ✓ (already a dependency, `>=5.0`) | in use | — |

**Missing dependencies with no fallback:** none — `tiktoken` has a same-library fallback encoding.
**Missing dependencies with fallback:** `tiktoken`'s `o200k_harmony` encoding (fallback: `cl100k_base`, same package).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest>=8.0` (already the project standard) |
| Config file | `pytest.ini` (`testpaths = tests`, `python_files = test_*.py`) |
| Quick run command | `pytest tests/test_autonomous.py -x` (targeted, per-file — full-suite segfaults in one process per the documented grpc/protobuf Python 3.13 GC issue; **always verify per-file**, never `pytest tests/` in one process) |
| Full suite command | Run each `tests/test_*.py` file as a separate `pytest` invocation (93 files as of this research); the ~1775+ backend-test baseline (per `.planning/STATE.md`) must hold across all files |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|---------------------|-------------|
| MEM-01 | Auto-recall injects a "Things you remember" block, best-effort/timeout, never blocks the turn | unit + forced-failure | `pytest tests/test_main.py -k ambient_recall -x` | ❌ Wave 0 |
| MEM-01 | Score threshold filters weak matches from the ambient block | unit | `pytest tests/test_pinecone_db.py -k score_threshold -x` (or wherever `MemoryStore` tests live — verify exact filename first) | ❌ Wave 0 |
| MEM-02 | Fresh/empty session (6h+ idle) prepends tail + boundary marker | unit | `pytest tests/test_main.py -k continuity_tail -x` | ❌ Wave 0 |
| MEM-03 | `forget_memory` deletes by id; contradiction flag surfaces in nightly digest, never auto-deletes | unit | `pytest tests/test_tools.py -k forget_memory -x` + `pytest tests/test_reflection.py -k contradiction -x` | ❌ Wave 0 |
| MEM-04 | `training_reality` reconciliation: evidence > self-report > intent, same-day+modality match, terminal "done" never re-flagged as missed | unit (stale-fact-style fixture: same date+slot re-read after evidence lands) | `pytest tests/test_training_checkin.py -k training_reality -x` | ❌ Wave 0 |
| MEM-05 | All 4 new gathers are context-only in `_is_empty_signals` | unit, one assertion per gather | `pytest tests/test_autonomous.py -k is_empty_signals -x` | ❌ Wave 0 (extend existing file) |
| MEM-05 | Token-budget guard: maximal rendered triage prompt + `max_tokens` fits Groq's verified 8K TPM ceiling | unit (deterministic, no network call — pure tokenizer count) | `pytest tests/test_token_budget.py -x` | ❌ Wave 0 (new file) |
| MEM-06 | Groq ledger increments on primary (not fallback) calls; heartbeat alerts at 80% once/day | unit | `pytest tests/test_tick_brain.py -k ledger -x` + `pytest tests/test_heartbeat.py -k groq_budget -x` | ❌ Wave 0 |
| MEM-07 | `current_location` derivation: home-default silent, travel-signal override, ambiguity → ask (never guesses) | unit, 3+ fixture cases (home/travel/ambiguous) | `pytest tests/test_autonomous.py -k current_location -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** targeted `pytest tests/test_<touched_file>.py -x`
- **Per wave merge:** run every `tests/test_*.py` file individually (per-file, never combined — segfault risk) and confirm the full count still matches or exceeds the pre-phase baseline
- **Phase gate:** full per-file suite green, plus a live/staging exercise of the budget-guard test's fixture data against a real `TickBrain.think()` call if feasible (not just the offline tokenizer count) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_token_budget.py` — new file, covers MEM-05's budget-guard test (Pattern/Code Example above)
- [ ] `tests/test_training_checkin.py` — likely doesn't exist yet for `planned_sessions_for`/`build_training_reality`; verify actual filename via `ls tests/ | grep training`
- [ ] Confirm exact existing test filenames before writing new test cases (`test_main.py`, `test_pinecone_db.py`, `test_reflection.py`, `test_heartbeat.py` — verify each exists and its current test-function naming convention with a quick `grep -l` pass at plan time, since this research did not exhaustively enumerate every test file)
- [ ] `pip install tiktoken==0.13.0` added to `requirements.txt` and to the CI/test environment before `test_token_budget.py` can run

*(Framework install: none needed — pytest already fully set up.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | No new auth surface this phase |
| V3 Session Management | No | Conversation-tail reuse of existing session/timeout mechanics only |
| V4 Access Control | No | Single-user system (Amit only); `$eq` user_id filter on all Pinecone queries already enforced (`pinecone_db.py:155`) |
| V5 Input Validation | Yes (light) | `forget_memory`'s `vector_id` input should be validated as a string matching Pinecone's ID format before calling `index.delete` — a malformed id should fail cleanly, not raise an unhandled exception into the tool-dispatch layer |
| V6 Cryptography | No | No new crypto surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-------------------|
| Ambient memory poisoning (OWASP ASI06 — auto-injected context treated as verified truth, self-reinforcing via top-k similarity) | Tampering (of the agent's own belief state, not an external attacker) | Ship `forget_memory` + reflection contradiction-flagging in the SAME phase as auto-recall (Pitfall 5); score-threshold weak matches out (Pattern 2); recency-weight facts with a natural shelf life more aggressively |
| Standing-directive text injected via a non-Amit channel misread as a location signal (e.g. a Notion page or Gmail body containing "while I'm in Paris" gets misattributed) | Spoofing | Not a new risk introduced by this phase specifically — the existing `smart_agent.md` SECURITY CONSTRAINT already scopes directive capture to "live conversational turns from Amit" only (verified, `prompts/smart_agent.md:373`); the location-derivation heuristic in Pattern 7 reads ONLY from `StandingDirectiveStore` (already-captured, already-scoped directives), not raw tool output, so it inherits that existing protection rather than needing a new one |
| A degraded/slow Pinecone or Gemini-embedding call stalling the chat critical path (availability, not confidentiality/integrity) | Denial of Service (self-inflicted, not adversarial) | Timeout-guard + best-effort empty-fallback, per Pitfall 4 |

## Sources

### Primary (HIGH confidence)
- Live codebase inspection (this session): `core/autonomous.py`, `core/tick_brain.py`,
  `core/llm_client.py`, `core/main.py`, `memory/firestore_db.py`,
  `memory/firestore_conversation.py`, `memory/pinecone_db.py`, `mcp_tools/memory.py`,
  `mcp_tools/weather_tool.py`, `mcp_tools/routes_tool.py`, `mcp_tools/calendar_tool.py`,
  `core/training_checkin.py`, `core/nightly_review.py`, `core/heartbeat.py`,
  `prompts/smart_agent.md`, `prompts/autonomous_triage.md` — all file:line citations
  above are from direct reads this session.
- [Prompt caching — Claude Platform Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — fetched and quoted this session; confirms per-block cumulative-hash caching, no partial-block cache hits, and the correct breakpoint-placement pattern.
- [Rate Limits — GroqDocs](https://console.groq.com/docs/rate-limits) — fetched this session; confirms `openai/gpt-oss-120b` Free tier: 30 RPM / 1K RPD / 8K TPM / 200K TPD.
- `pip index versions tiktoken` (run this session) → `0.13.0` latest.
- `slopcheck install tiktoken` (run this session) → `[OK]`.

### Secondary (MEDIUM confidence)
- [gpt-oss-120b & gpt-oss-20b Model Card (OpenAI, arXiv)](https://arxiv.org/html/2508.10925v1) and [gpt-oss-120b Hugging Face discussion](https://huggingface.co/openai/gpt-oss-120b/discussions/39) — corroborate `o200k_harmony` as the model's tokenizer, open-sourced via `tiktoken`.
- `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md`,
  `.planning/research/SUMMARY.md` (this milestone's Phase 3/32 sections) — treated as
  primary planning input per the canonical-refs instruction, cross-checked against live
  code where cited; one claim (Pitfall 4's ordering-based caching model) was refined
  by this session's direct verification against the official Anthropic docs.

### Tertiary (LOW confidence)
- WebSearch synthesis of Groq free-tier limits from third-party trackers
  (CloudZero, TokenMix, Grizzly Peak) — used only as corroboration; the GroqDocs
  primary fetch is the source of record for the actual numbers used in this document.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — only one new dependency (`tiktoken`), verified against the registry and against the model card confirming its tokenizer identity
- Architecture: HIGH — every integration point verified against live source with file:line citations; the cache-block-split finding is independently corroborated by official Anthropic documentation fetched this session
- Pitfalls: HIGH — grounded in this codebase's own documented incident history (2026-06-12 Groq 413 incident, 2026-06-24 weekly-review 500 incident) plus the milestone's own prior research

**Research date:** 2026-07-22
**Valid until:** 30 days for the codebase-integration findings (stable, internal); the
Groq rate-limit numbers should be re-verified if Groq changes its free-tier terms before
implementation (Groq's own history of decommissioning `qwen3-32b` with limited notice is
a documented precedent for this ecosystem moving faster than typical API stability
norms) — treat the 8K TPM / 200K TPD numbers as valid for 7-14 days, not 30.
