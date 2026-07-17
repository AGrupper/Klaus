# Stack Research

**Domain:** Klaus v6.0 "Klaus Becomes an Agent" — brain migration to `claude-sonnet-5` (Anthropic) with prompt caching, standing-directives/ambient-memory Firestore stores, occasion-tagged judgment cascade. Groq `openai/gpt-oss-120b` tick-brain already shipped pre-milestone (commit `b784a1d`).
**Researched:** 2026-07-17
**Confidence:** HIGH (all Anthropic facts verified against `platform.claude.com` official docs published for the Sonnet 5 launch; Groq limits verified against `console.groq.com/docs/rate-limits` + the model card, cross-checked against an independent third-party tracker)

## Executive Context

This is a subsequent-milestone research pass. It supersedes the v5.0 `STACK.md` that previously lived at this path (that research — React/Vite/Tailwind PWA stack — is validated, shipped, and out of scope for v6.0; see `.planning/PROJECT.md` for what's already live). This file covers only the NEW stack surface for v6.0: the Anthropic SDK/API behavior needed for the `claude-sonnet-5` brain migration, confirmation of already-shipped Groq tick-brain limits, and confirmation that no new libraries are needed for the standing-directives/ambient-memory/occasion-cascade features.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `anthropic` (Python SDK) | **`>=0.99,<1.0`** (current PyPI latest verified: **0.117.0**, 2026-07-17) | Brain backend for `_AnthropicBackend` in `core/llm_client.py` | `requirements.txt` currently pins `anthropic>=0.40`. That floor predates `output_config.effort` (added ~0.75) and the current `thinking: {"type": "adaptive"}` shape. 0.40 would *technically* still send raw JSON kwargs through and probably work (the SDK is a thin wrapper over `**kwargs`), but pin the floor to a version that ships typed `OutputConfigParam`/`ThinkingConfigAdaptiveParam` so tooling/typing doesn't silently drift. No breaking changes for existing `messages.create()` call shape — this is additive. |
| `claude-sonnet-5` (API model ID) | launch model, GA | Smart-agent brain model string (`SMART_AGENT_MODEL`) | Per official "What's new" page: **1M token context window is the only variant** (no smaller-context SKU), 128K max output tokens, same tool-use/platform feature set as Sonnet 4.6 except Priority Tier (not available on Sonnet 5). Pricing $3/$15 per MTok in/out standard, **introductory $2/$10 through 2026-08-31** — Klaus's cost metering will see effective per-token cost drop then rise back on that date; `core/pricing.py` should carry a dated note, not just today's number. |
| Prompt caching (`cache_control: {"type": "ephemeral"}`) | Native SDK support since anthropic-sdk-python 0.40+ | Caches the stable prefix (system prompt + SELF.md + directives + tool schemas) across brain calls | This is the actual cost lever for the milestone. Minimum cacheable prefix for Sonnet 5 is **1,024 tokens** (same as Sonnet 4.6/Opus 4.8) — Klaus's `smart_agent.md` + SELF.md + directives block is already well over that. Cache writes cost **1.25× base input** (5-min TTL, default) or **2× base input** (1h TTL, explicit `"ttl": "1h"`); cache reads cost **0.1× base input**. Given Klaus's turn cadence (autonomous tick every 20 min plus interactive chat), the default **5-minute TTL is the wrong choice** — most gaps between brain calls exceed 5 minutes, so the default would almost never hit and every call would pay the 1.25× write premium with no offsetting reads. Use the **1-hour TTL** (`"ttl": "1h"`) on the system-prompt cache block. |

### Groq Tick-Brain (already shipped — verification only, no new work)

| Item | Verified Value | Source confidence |
|------|----------------|--------------------|
| Free-tier limits for `openai/gpt-oss-120b` | **30 RPM · 1,000 RPD · 8,000 TPM · 200,000 TPD** | HIGH — matches exactly what `core/tick_brain.py`'s docstring and `CLAUDE.md` already state (8K TPM/request, 200K tokens/day). Confirmed against `console.groq.com/docs/rate-limits` directly, cross-checked by an independent tracker (grizzlypeaksoftware) — no drift since the qwen3→gpt-oss-120b migration. |
| Rate-limit response headers | `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`, `x-ratelimit-reset-requests` (RPD), `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-tokens` (**TPM only**), `retry-after` (only present on 429) | HIGH — from official Groq rate-limits doc. **Important for the Phase 32 "Groq daily token ledger":** Groq's headers report **per-minute** token state, not per-day. There is no `x-ratelimit-remaining-tokens-day`-style header. A daily 200K-token ledger cannot be read off response headers alone — it must be tracked locally (a Firestore counter incremented from each call's `usage.prompt_tokens + usage.completion_tokens`, reset on day rollover), same pattern as every other Klaus store. This is a **build-it-yourself requirement**, not a "read Groq's header" requirement — flag this for the requirements doc so Phase 32 doesn't assume the header exists. |
| Context window / max output | 131,072 tokens context, 65,536 max output | HIGH — Groq model card. Confirms `TICK_BRAIN_MAX_TOKENS` (default 2048 in code) has enormous headroom vs. the model's real ceiling; the binding constraint is Groq's free-tier **8K TPM per-request** cap, already handled correctly in the existing code (`TICK_BRAIN_MAX_TOKENS` kept small to leave input headroom). |
| Deprecation risk | None found for `openai/gpt-oss-120b` as of research date | MEDIUM — absence of a deprecation notice isn't proof of permanence (Groq gave qwen3-32b a hard decommission on 2026-07-17 with limited notice per `CLAUDE.md`). Keep `TICK_BRAIN_FALLBACK_*` (Gemini) wired and tested — this is already the plan for Phase 30.5. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| *(none new)* | — | Standing directives store, ambient-memory auto-recall, occasion cascade | All three new-feature areas are Firestore-store-pattern + existing-client work: `StandingDirectiveStore` follows the exact shape of `TaskStore`/`HabitStore`/`CoachingTopicStore` (already in `memory/firestore_db.py`), ambient auto-recall calls the existing `MemoryStore.recall()` in `memory/pinecone_db.py` (already does Gemini-embedding cosine search), and the occasion cascade reuses the existing 3-layer gather→triage→compose plumbing in `core/autonomous.py`. No new SDK, no new vector store, no new queue library is needed. |
| `google-genai` | already `>=1.0` | Embeddings (`gemini-embedding-2`) stay on AI Studio for ambient-memory recall | Unaffected by the brain migration — embeddings are a separate call path from the brain/tick-brain chat calls and are NOT part of this SDK change. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Anthropic **token counting endpoint** (`client.messages.count_tokens(...)`, part of the SDK ≥0.40) | Re-measure `smart_agent.md` + SELF.md against the **new Sonnet 5 tokenizer** before finalizing prompt-slimming targets | Official docs: Sonnet 5's new tokenizer produces **~30% more tokens for the same text** than Sonnet 4.6/Gemini. The milestone's stated "~4.5K tokens off every call" slimming target for `smart_agent.md` was presumably sized against the *old* (Gemini) token count — re-run token counting against the actual Sonnet 5 tokenizer before treating that number as a phase acceptance criterion. Don't estimate from character count or from Gemini's `count_tokens`. |

## Installation

```bash
# Bump the floor; no new packages required for v6.0 core stack work
pip install -U "anthropic>=0.99,<1.0"

# requirements.txt diff
- anthropic>=0.40                    # Likely main "Smart" agent (Claude)
+ anthropic>=0.99,<1.0                # claude-sonnet-5 brain: output_config.effort + adaptive thinking typed support (0.117.0 latest verified 2026-07-17)
```

No `npm install` — this milestone touches only the Python backend (`core/`, `memory/`, `mcp_tools/`); the React/Vite Hub frontend (`frontend/`) is untouched by v6.0's target features.

## Critical Integration Points into `core/llm_client.py` / `core/pricing.py`

These are not "new libraries" but are **mandatory code changes** driven by verified Sonnet 5 API behavior — surfacing them here because they directly gate Phase 30.5 requirements:

1. **Sampling parameters now hard-reject on Sonnet 5.** `temperature`, `top_p`, `top_k` set to any *non-default* value return an **HTTP 400**, not a warning — verified on the official migration page, explicitly called out as "new for Sonnet-class models" (previously only Opus 4.7+). Audit confirmed: no current call site passes `temperature` through the Anthropic backend today (only `core/tick_brain.py` sets `temperature`, and it targets the OpenAI/Groq backend, not Anthropic) — so today's code is **safe as-is**, but this must become a documented invariant so nobody adds a `temperature=` kwarg to a future Anthropic-backend call without checking the model first.

2. **Adaptive thinking is ON by default and consumes `max_tokens`.** Requests to `claude-sonnet-5` that omit a `thinking` field run with adaptive thinking (`effort` defaults to `high`), and thinking tokens count against the *same* `max_tokens` ceiling as the visible response. `core/llm_client.py`'s module-level `MAX_TOKENS = 4096` becomes a real truncation risk once the brain model is Sonnet 5 — a `high`/`xhigh`-effort turn can spend most of the 4096-token budget on thinking and return `stop_reason: "max_tokens"` with a truncated/empty visible answer. Two independent levers, pick deliberately per call site (this is a requirements-level decision, not just a code tweak):
   - Raise `MAX_TOKENS` (official guidance: leave real headroom beyond the expected response length at `high`+ effort), **and/or**
   - Pass `thinking: {"type": "disabled"}` explicitly for latency-sensitive/cheap paths (e.g., a quick Telegram acknowledgment) where deep reasoning isn't wanted, and leave thinking on (with `output_config: {"effort": "high"}` or higher) for the occasion-cascade compose step and reflection, where the milestone explicitly wants better judgment.
   - `display: "omitted"` (the Sonnet 5 default) is fine to leave as-is — Klaus doesn't currently surface thinking text to the user, and omitted-display doesn't change billing, only whether the `thinking` field is populated.

3. **System prompt and tools need restructuring to carry `cache_control`.** `_AnthropicBackend.chat()` currently sends `system` as a plain string (`kwargs["system"] = system`). To cache it, `system` must become a list of content blocks: `system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]`. Tool schemas (already Anthropic-native, passed through unchanged today) can carry `cache_control` on the *last* tool definition in the list to cache the whole tool block as a separate breakpoint (max 4 breakpoints per request — system + tools + directives + conversation-tail is a reasonable 3-breakpoint layout, leaving one spare).

4. **`usage` extraction must capture cache fields for truthful metering.** Today `_AnthropicBackend.chat()` only reads `response.usage.input_tokens` / `.output_tokens`. The response also carries `cache_creation_input_tokens` and `cache_read_input_tokens` (plus, for 1h-TTL requests, a nested `cache_creation: {ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}` breakdown). `LLMUsageStore.record()` and `core/pricing.py::compute_cost()` need new parameters/columns for these — a cache-token record that just adds `cache_read_input_tokens` into the existing `in_tokens` bucket at the *full* input price would make Klaus's cost dashboard **overstate** actual spend by up to 10× on cache-hit calls (reads are 0.1× base price), which directly undermines the milestone's "cache-token metering so LLMUsage stays truthful" goal.

5. **New tokenizer changes cost-per-call independent of the caching work.** Because the same text now costs ~30% more input tokens on Sonnet 5 than the same text costs on Gemini 3.5 Flash today, the "daily-spend tripwire in the heartbeat" threshold inherited from Gemini-era spend patterns will read differently on day one — size the tripwire threshold empirically after a few days of live Sonnet 5 usage, not by porting the old Gemini number.

6. **Refusal handling.** Sonnet 5 is "the first Sonnet-tier model with real-time cybersecurity safeguards" — refusals return as a normal HTTP 200 with `stop_reason: "refusal"`, not an exception. `_AnthropicBackend.chat()`'s current `stop_reason` passthrough already handles this correctly as an opaque string (the orchestrator doesn't special-case `stop_reason` values today) — worth a one-line note in the fallback path so a refusal isn't silently retried against Gemini as if it were a transient error.

## Streaming vs. Non-Streaming (Question A, webhook-driven agent)

**Recommendation: stay non-streaming (`client.messages.create()`), do not adopt SSE streaming for this milestone.**

- Klaus's whole request path is already async-safe for long calls: Telegram gets an instant webhook ACK, and the actual turn runs inside a tracked Cloud Tasks request (`interfaces/web_server.py` → `/internal/process-update`), not a live client connection waiting on tokens. There is no UI consuming token-by-token deltas (Telegram send is one final message; Hub chat polls/fetches, doesn't stream deltas today).
- Anthropic's own guidance is to prefer streaming mainly to avoid network-level idle-connection timeouts on **very long** non-streaming calls (docs: "especially useful for requests with large `max_tokens` values ... SDKs require streaming to avoid HTTP timeouts" for the longest-running cases) and the hard SDK-side non-streaming cap is 10 minutes. Klaus's existing `LLM_TIMEOUT_SECONDS` (default 120s) is already well under that ceiling, and even a `high`/`xhigh`-effort adaptive-thinking turn on Sonnet 5 is expected to complete well inside 120s for Klaus's prompt sizes.
- **However:** once `max_tokens` is raised (per Integration Point #2) to give thinking headroom, re-check that `LLM_TIMEOUT_SECONDS=120` is still comfortably above worst-case `high`-effort latency before shipping Phase 30.5 — if empirical testing shows turns regularly running past ~90s, either raise the timeout or switch specifically the occasion-cascade compose call to the SDK's `client.messages.stream(...)` context manager (which the SDK will happily consume into a single final `Message` for you if you don't need incremental deltas — no architecture change required, just swap the call).

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| 1-hour cache TTL (`"ttl": "1h"`) on system/directives block | Default 5-minute TTL | Only if Klaus's brain call cadence tightens to sub-5-minute intervals across the board (it currently doesn't — interactive chat is bursty, autonomous tick is 20-min spaced) |
| `thinking: {"type": "adaptive"}` with per-call-site `effort` tuning | Leaving `thinking` unset everywhere (accept the `high`-effort default globally) | Only for a first quick-and-dirty migration smoke test — leaving it unset globally will work but burns unnecessary tokens/latency on trivial acknowledgment turns; tune per call site before calling Phase 30.5 done |
| Local Firestore daily-token ledger for Groq TPD tracking | Reading `x-ratelimit-*` headers as the ledger source | Never for the *daily* figure — Groq doesn't expose a daily-remaining header, only per-minute. Headers are still useful as a secondary "did we just get 429'd" signal, but not as the ledger itself |
| Non-streaming Anthropic calls (status quo call shape) | SSE streaming via `client.messages.stream()` | If post-migration latency testing shows `high`/`xhigh`-effort adaptive-thinking calls regularly approaching the 120s timeout, or if a future Hub chat feature wants token-by-token UI |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| Manual extended thinking (`thinking: {"type": "enabled", "budget_tokens": N}`) | **Removed** on `claude-sonnet-5` — returns HTTP 400. This is not a deprecation warning, it's a hard rejection at launch. | `thinking: {"type": "adaptive"}` + `output_config: {"effort": "low"|"medium"|"high"|"xhigh"|"max"}` |
| Passing `temperature`/`top_p`/`top_k` with any non-default value on the Anthropic backend when the model is `claude-sonnet-5` | Hard 400 error, not a soft override | Omit the parameter entirely; steer style/variety via system-prompt instructions instead (this is Anthropic's explicit official recommendation for Sonnet 5) |
| A third-party tokenizer library (e.g. `tiktoken`) to pre-estimate Sonnet 5 prompt sizes for the slimming-pass acceptance criteria | `tiktoken` is OpenAI's tokenizer family and does not model Anthropic's (new, ~30%-larger-per-text) Sonnet 5 tokenizer at all — numbers would be flatly wrong | The Anthropic SDK's built-in `client.messages.count_tokens(...)` endpoint, called against the actual `claude-sonnet-5` model string |
| A new caching library/wrapper (e.g. a Redis or in-process LRU cache in front of the LLM call) to "implement prompt caching" | Prompt caching here is a **server-side Anthropic feature** activated via a request field (`cache_control`), not a client-side caching problem — building a client cache would duplicate/conflict with it and add a new stateful dependency for no benefit | `cache_control: {"type": "ephemeral", "ttl": "1h"}` on the relevant content blocks in the existing request |
| A new pub/sub or rate-limiter package (e.g. `ratelimit`, `slowapi`) for the Groq daily-token ledger | Klaus already has an established Firestore-store pattern (`LLMUsageStore` already meters every call by `purpose`) that can be extended with a per-day Groq token running total — no new infra class needed for a single counter | Extend the existing `LLMUsageStore`/`memory/firestore_db.py` pattern with a same-day aggregate query or a small dedicated `TickBrainDailyUsageStore`, mirroring existing stores |
| Bumping `anthropic` to a `2.x`/major-version-unpinned floor "to be safe" | No 2.x line exists yet at research time (latest is 0.117.0); an unbounded floor risks a future breaking major-version bump silently landing in a Cloud Run redeploy | Pin `anthropic>=0.99,<1.0` — comfortably covers current `output_config`/adaptive-thinking typed support while staying inside the pre-1.0 line Klaus is already on |

## Stack Patterns by Variant

**If the call is interactive chat (Telegram/Hub, user is waiting):**
- Use `thinking: {"type": "disabled"}` or `effort: "low"`/`"medium"` for simple acknowledgments and tool-dispatch turns; reserve `high`+ for genuinely complex reasoning turns
- Because — official Sonnet 5 guidance: at `low`/`medium` effort the model stays literal and scoped (good for predictable turnaround); `high`/`xhigh` adds latency that's wasted on a "did you get my message" reply

**If the call is the occasion-cascade Layer-2 compose (nightly review / morning briefing / autonomous outreach, no one is watching a spinner):**
- Use `thinking: {"type": "adaptive"}` with `effort: "high"` (the Sonnet 5 default) or `"xhigh"` for the judgment-heavy compose step
- Because — this is exactly the "guided by values rather than behavior scripts" judgment work the milestone is about; the extra latency is invisible (fires from a cron/tick, not a live chat wait) and adaptive thinking is what buys the better reasoning

**If the call is the free tick-brain triage (Layer 1, Groq):**
- No change from what's already shipped — `openai/gpt-oss-120b` via the OpenAI-compat backend, `TICK_BRAIN_TEMPERATURE=0.6`, `TICK_BRAIN_MAX_TOKENS=2048`. Sonnet 5's sampling-parameter restriction is Anthropic-backend-only and does not apply to the Groq/OpenAI-compat path.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `anthropic>=0.99,<1.0` | `claude-sonnet-5` API model ID | `output_config.effort` and `thinking.type: "adaptive"` are stable (non-beta) fields on Sonnet 5 per official docs — no `anthropic-beta` header required, unlike some Opus-4.5-era effort features |
| `anthropic>=0.40` (current floor) | `claude-sonnet-5` | Would likely still function (the SDK largely passes typed params through as JSON), but ships without typed `ThinkingConfigAdaptiveParam`/`OutputConfigParam` — bump the floor rather than relying on duck-typed kwargs |
| Sonnet 5 tokenizer | Existing `MAX_TOKENS = 4096` in `core/llm_client.py` | **Incompatible without a code change** — see Integration Point #2. Do not ship the brain migration with the module-level default unchanged. |
| Groq `openai/gpt-oss-120b` free tier | Existing OpenAI-compat backend (`_OpenAIBackend`) | No change required — this path already shipped pre-milestone and needs no SDK bump |

## Sources

- [What's new in Claude Sonnet 5](https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5) — HIGH confidence, official Anthropic docs: sampling-parameter 400 behavior, adaptive-thinking-on-by-default, manual-thinking-removed, new tokenizer (~30% more tokens), 1M context / 128K max output, pricing ($3/$15 standard, $2/$10 intro through 2026-08-31)
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — HIGH confidence, official docs: minimum cacheable prefix per model (1,024 tokens for Sonnet 5), TTL options (5m default / 1h explicit), pricing multipliers (1.25×/2×/0.1× base input), `usage` response fields (`cache_creation_input_tokens`, `cache_read_input_tokens`, `input_tokens`)
- [Adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking) — HIGH confidence, official docs: effort levels (low/medium/high/xhigh/max), thinking-counts-toward-max_tokens, cache-breakpoint interaction with adaptive vs manual mode switching, `display: "omitted"` default on Sonnet 5, billing of thinking tokens regardless of display setting
- [Prompting Claude Sonnet 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5) — HIGH confidence, official docs: effort defaults to `high`, literal instruction-following at low effort, tone/verbosity calibration guidance, streaming/max_tokens headroom warning at high effort
- [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits) — HIGH confidence, official Groq docs: rate-limit header names/units, confirms TPM-only headers (no daily-token header)
- [console.groq.com/docs/model/openai/gpt-oss-120b](https://console.groq.com/docs/model/openai/gpt-oss-120b) — HIGH confidence, official Groq model card: 131,072 token context, 65,536 max output
- PyPI `anthropic` package JSON API (`pypi.org/pypi/anthropic/json`) — HIGH confidence, directly queried: latest version 0.117.0 as of 2026-07-17
- [grizzlypeaksoftware.com — Groq API Free Tier Limits in 2026](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb) — MEDIUM confidence (third-party), used only as cross-check; matches official docs and existing `CLAUDE.md`/`core/tick_brain.py` numbers exactly (30 RPM / 1K RPD / 8K TPM / 200K TPD)
- Codebase read: `core/llm_client.py`, `core/tick_brain.py`, `core/pricing.py`, `requirements.txt` — direct inspection to determine actual current call-site behavior (no existing `temperature` passthrough on the Anthropic backend; `anthropic>=0.40` current floor; no cache_control support today; `usage` extraction currently drops cache fields)

---
*Stack research for: Klaus v6.0 Phase 30.5 (brain migration to `claude-sonnet-5`) + supporting Phase 31/32/33 stores*
*Researched: 2026-07-17*
