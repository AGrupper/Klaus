# Groq Tick-Efficiency — Design Spec

**Date:** 2026-07-27
**Status:** approved design → ready for implementation plan
**Owner:** Amit / Klaus
**Scope:** Levers 1 + 2 (build now). Lever 3 (adaptive controller) documented as a deferred fast-follow.

## Problem

Klaus's tick-brain (`openai/gpt-oss-120b` on Groq's free tier) is the always-on, $0 reasoning
layer that gates the paid brain. Two production incidents exposed that the free tier is being
defeated:

1. **Daily-cap exhaustion (2026-07-22, evening).** Genuine Groq 200K-tokens/DAY cap hit
   (`429 rate_limit_exceeded ... TPD Limit 200000`). Fallback to metered Gemini is *designed*
   behavior (D-08) — correct, but it means the back half of the day runs metered.

2. **Per-request TPM breach (2026-07-27, all morning) — the urgent one.** Every autonomous tick
   is rejected with `413 Request too large ... tokens per minute (TPM): Limit 8000, Requested
   ~8,100–8,180`. Groq's free tier enforces an **8,000-tokens-per-request** ceiling (billed as
   TPM; at our ≤1-call/min cadence a single request alone blows it). Production requests land at
   ~8,150 — **~150 over, on every tick** — so the autonomous path is **100% bypassed** and all
   its reasoning runs on metered Gemini. Confirmed via `llm_usage/2026-07-27`:
   `tick_calls: 1` (one heartbeat call succeeded), `tick_autonomous_fallback_calls: 18`.

**Root cause of #2:** Phase 32 (plan 32-07) added `conversation_tail` + `training_reality` to the
triage prompt, pushing `input` from ~4,400 to ~6,100 tokens. With `max_tokens=2048`, Groq's
`Requested = input + max_tokens` ≈ 8,150 > 8,000. The MEM-05 token-budget guard measured its
"maximal" fixture at 7,730 and passed — the fixture **under-sized real production by ~350 tokens**,
giving false confidence. So the guard is itself defective.

**Cost reality:** the metered fallback is ~$0.10/day (~$3/month). This work is therefore driven by
**correctness** (keep the free reasoning tier actually usable, durable through Phase 33's added
tick traffic), not by the dollar amount.

## Goal

Keep every tick-brain request safely under Groq's 8,000-tokens/request ceiling **and** keep daily
consumption comfortably under the 200K/day cap — durably, with **zero loss to Klaus's judgment
quality**. Target per-request budget **≤ 7,200 tokens** (real margin below 8,000). Target daily
consumption **≤ ~130K** (≥35% headroom under 200K, absorbs Phase 33).

## Non-goals

- The adaptive budget controller (Lever 3) — designed here, built later.
- Reducing the *paid* brain's cost (that's the Phase 30.5 cost-tripwire's domain).
- Changing what signals Klaus reasons over (we change *rendering density*, never remove a trigger).

## Binding constraints (invariants this design must not break)

- **Per-request:** `input_tokens + max_tokens < 8,000` for every tick-brain Groq call. Design
  target ≤ 7,200.
- **Per-minute (TPM nuance):** the 8,000 limit is billed per *minute* across *all* requests, not
  strictly per request. Today's 413s are each a single oversized request (provable, dominant
  problem), but the autonomous tick (`*/20`) and the hourly heartbeat both fire at `:00`, so two
  tick-brain calls can land in the same minute and *sum* against 8,000. Lever 1 (smaller requests)
  + Lever 2 (skip-gate reduces call volume, so fewer collisions) mitigate this; a residual
  same-minute collision of two near-maximal requests could still 413. **Mitigation if it shows up
  post-fix:** stagger the heartbeat's tick-brain pass off the `:00` boundary, or serialize via the
  Lever-3 controller. Tracked as a post-deploy watch item, not built now.
- **Per-day:** sum of successful Groq `in+out` tokens < 200,000. Design target ≤ ~130K.
- **Context-only invariant (MEM-05):** none of the ambient signals may flip an empty tick to
  non-empty. The change-detection gate (Lever 2) must not resurrect a signal as a trigger.
- **Fail-open:** every new store read/lookup degrades to "proceed with the normal call" on error;
  nothing new may block or crash a tick.
- **Judgment parity:** a tick that *would* have spoken must still speak. No change may convert a
  real should_act into false silence (this rules out blind `max_tokens` truncation).

---

## Lever 1 — Cheaper calls (per-request cost reduction)

### 1a. Extra-params passthrough — `core/llm_client.py`
Add an optional `extra_params: dict | None = None` to `LLMClient.chat(...)`. On the **OpenAI-compat
backend only**, merge it into the request kwargs (e.g. `reasoning_effort`). Anthropic and Gemini
backends ignore it (documented no-op). This is the single clean seam for Groq-specific knobs; no
existing caller is affected (default `None`).

### 1b. `reasoning_effort=low` on triage — `core/tick_brain.py`
Thread `extra_params={"reasoning_effort": "low"}` on the **primary (Groq) triage path**. The triage
task is "speak or stay silent + one-line reason + <200-char draft" — a judgment, not a derivation —
so a low-effort reasoning trace is sufficient and collapses the dominant completion cost. The Gemini
fallback path does **not** receive it (Gemini ignores the param anyway; kept clean).

### 1c. Right-size `max_tokens` — measured, not guessed
- **Task 1 (measurement):** with 1b in place, make a controlled Groq triage call on a
  representative maximal situation and record actual completion tokens (`out_tokens`,
  `stop_reason`). gpt-oss never succeeds today, so this is the first real number.
- Set `TICK_BRAIN_MAX_TOKENS` default to `p95(out_tokens) + margin` — expected **~768–1024**
  (down from 2048). This is an env-var default in `core/tick_brain.py`; the deployed Cloud Run env
  currently pins `TICK_BRAIN_MAX_TOKENS=2048` and must be updated (or unset to inherit the new
  default) at deploy.
- Because Groq bills the reservation, this directly subtracts ~1,024–1,280 from every request's
  `Requested`. Combined with ~6,100 input that alone lands ~7,100–7,380 < 8,000.
- **Truncation guard:** if `stop_reason == "max_tokens"` on a triage call, log a distinct warning
  (`tick-brain: triage truncated at max_tokens=N`) so under-sizing is visible, not silent.

### 1d. Conditional heavy context — `core/autonomous.py`
Render the Phase-32 heavy blocks only when salient, shrinking `input` on ordinary ticks while
preserving the maximal case for genuinely eventful ones:
- `training_reality`: include only on days with a planned or logged session (else omit — a rest day
  has no training reality to reconcile).
- `conversation_tail`: include only when there is a genuinely recent exchange within the tail
  window (else omit — no continuity to carry).
- The **maximal** (all-present) render must still satisfy the recalibrated guard (≤ 7,200).

### 1e. Recalibrate the MEM-05 token-budget guard — `tests/test_token_budget.py`
- Rebuild the maximal fixture from **real production maxima** (calendar/tasks/meals/recovery/
  directives at their true busy-day sizes — the current fixture was ~350 low).
- Assert `input + TICK_BRAIN_MAX_TOKENS ≤ 7,200` (hard margin below the 8,000 ceiling), not
  `≤ 8,000`. The guard's job is to fail CI *before* a change ships that would 413 in production.
- Keep the o200k_harmony real-tokenizer measurement.

**Lever 1 net:** per-request ~8,150 → ~4,000 (lean tick) / ≤7,200 (maximal tick). Fixes the 413.

---

## Lever 2 — Fewer calls (change-detection skip gate)

### 2a. Signal signature — `core/autonomous.py`
Before the Groq call in `run_autonomous_tick`, compute a **stable signature** over only the
*salient trigger* fields — the exact set `_is_empty_signals` keys on:
`ticktick_overdue`, `due_followups`, calendar gap/overload (derived boolean, not raw events),
`meals_since_last_tick`, `habit_pending`, `recovery.flags`, and the **silence bucket**
(`hours_since_contact >= _SILENCE_TRIGGER_HOURS` as a bool, NOT the raw float — otherwise it
changes every tick and the gate never fires). Volatile noise (exact timestamps, `now_context`
minute) is excluded from the hash. Context-only signals (`conversation_tail`, `training_reality`,
`standing_directives`, `location`) are **excluded** from the signature — consistent with the
MEM-05 invariant (they are not triggers, so a change in them alone must not force a paid re-eval).

### 2b. Last-signature store — `memory/firestore_db.py`
A small record (mirrors `TickLog`): `{signature: str, ts: iso}` per user. Read before the call,
write the new signature after a real call. **Fail-open:** any read/write error → proceed with the
normal call (never skip on uncertainty).

### 2c. Gate logic — `core/autonomous.py`
- After the existing `_is_empty_signals` gate (unchanged), if signals are non-empty **and** the
  signature equals the last stored signature → **skip the Groq call, return silence** (trail:
  `signals_unchanged_since_last_tick`). Nothing salient changed, so there is nothing new to judge.
- If the signature differs (or no prior signature) → call Groq as normal, then store the new
  signature.
- A persistent overdue task (non-empty every tick) thus calls Groq **once** when it appears, not
  ~40× across the day. Re-nudge suppression is already handled downstream by
  `OutreachLog`/`CoachingTopicStore`; this gate additionally saves the *reasoning call itself*.

**Lever 2 net:** ~46 → ~30 calls/day on a normal day; near-zero on quiet days.

---

## Combined effect

~30 calls/day × ~4,000 tokens ≈ **~120K/day (~40% under the 200K cap)**, and **every** request
≤ 7,200 < 8,000 → no more 413s, free tier restored, headroom for Phase 33.

## Deferred — Lever 3 (adaptive budget controller)

A controller reads the Groq ledger each tick and spreads the remaining daily budget across the rest
of the 07:00–21:00 window — richer early, leaner (lower `reasoning_effort`/`max_tokens`, more
aggressive skip) as budget depletes — *guaranteeing* free coverage to end-of-day. Not built now:
Levers 1+2 already deliver ~40% headroom, so the guarantee it adds isn't yet needed. Revisit if,
after Phase 33, measured daily consumption trends above ~150K.

## Components & isolation

| Unit | File | Responsibility | Depends on |
|------|------|----------------|------------|
| extra-params passthrough | `core/llm_client.py` | thread backend-specific kwargs | — |
| triage tuning | `core/tick_brain.py` | reasoning_effort=low, sized max_tokens, truncation warn | llm_client |
| conditional context | `core/autonomous.py` | salience-gated heavy-block render | — |
| signature + gate | `core/autonomous.py` | compute signature, skip-if-unchanged | signature store |
| signature store | `memory/firestore_db.py` | persist/read last signature (fail-open) | firestore |
| guard recalibration | `tests/test_token_budget.py` | enforce input+max_tokens ≤ 7,200 on real maxima | tokenizer |

## Error handling

- Groq 413/429 → existing fallback path unchanged (Gemini). This design *prevents* the 413; it does
  not change the fallback contract.
- Signature store errors → proceed with normal call (fail-open).
- `reasoning_effort` unsupported/ignored by fallback backends → no-op by construction.
- `stop_reason == max_tokens` on triage → distinct warning log (visibility), verdict still parsed
  (existing `_parse_response` handles unterminated `<think>`).

## Testing

- `test_llm_client`: `extra_params` merged on openai backend, ignored on anthropic/gemini.
- `test_tick_brain`: reasoning_effort threaded on primary only; sized max_tokens applied;
  truncation warning fires on `stop_reason=max_tokens`.
- `test_autonomous`: signature stability (same situation → same hash; changed trigger flips it;
  silence bucket boundary; context-only fields excluded); skip-gate returns silence on unchanged
  non-empty signals and calls Groq on change; fail-open on store error; conditional-context
  omission on rest day / no recent exchange, inclusion otherwise.
- `test_token_budget`: recalibrated maximal fixture; `input + max_tokens ≤ 7,200`.
- Per-file pytest baseline stays green (full-suite segfaults on Py3.13 — known env quirk).

## Rollout

1. Land + merge; run affected per-file suites green.
2. Deploy (push → CI → Cloud Run) **and** set `TICK_BRAIN_MAX_TOKENS` to the measured value (or
   unset to inherit the new default) — the deploy.yml `--set-env-vars` is the single source of
   truth for Cloud Run env.
3. Verify live: within one tick cycle, `llm_usage` shows `tick_autonomous_calls` incrementing
   (Groq primary succeeding) and the 413 log line gone; ledger daily total tracking normally.

## Open questions (resolve during planning/measurement)

- Exact measured `p95(out_tokens)` for gpt-oss triage at `reasoning_effort=low` → sets the
  `max_tokens` default (task 1).
- Confirm the OpenAI-compat SDK path accepts `reasoning_effort` via the kwargs we pass (Groq
  supports it for gpt-oss; verify the client library forwards it).
