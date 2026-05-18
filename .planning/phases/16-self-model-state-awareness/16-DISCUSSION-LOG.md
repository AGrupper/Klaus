# Phase 16: Self-Model & State Awareness - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-18
**Phase:** 16-self-model-state-awareness
**Areas discussed:** Manifest refresh workflow, SELF.md injection scope, Message count sourcing, Identity summary bootstrap

---

## Manifest Refresh Workflow

| Option | Description | Selected |
|--------|-------------|----------|
| Manual script at deploy time | `python core/self_manifest.py` run after adding capabilities; heartbeat flags stale | |
| CI step on every deploy | `cloudbuild.yaml` runs `generate_manifest()` before deploying | ✓ |
| Heartbeat re-generates when stale | `check_code()` both detects AND re-generates | |

**User's choice:** "Whatever you think is best regardless of the amount of work it takes now" (delegated to Claude)
**Notes:** Claude selected CI step — most robust, SELF.md always reflects deployed version, no CI-to-Firestore coupling required.

---

## SELF.md Injection Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Full file content | Full SELF.md injected into smart_system; stable → prompt cache benefit | ✓ |
| First section only (capability summary) | Condensed header only; requires disciplined authoring | |
| Claude decides format and size | Standard Claude's Discretion | |

**User's choice:** Full file content
**Notes:** Stable content injected into smart_system only (not worker). Benefits from Gemini prompt cache after first call.

---

## Message Count Sourcing

| Option | Description | Selected |
|--------|-------------|----------|
| Proxy via LLM usage records | Count `LLMUsageStore` rows for today where `purpose='smart_agent'` | ✓ |
| New Firestore counter in handle_message | Increment daily counter doc on every call; precise but adds write latency | |
| Omit message count in Phase 16 | Skip it; add in Phase 17 when JournalStore exists | |

**User's choice:** "Why do we need message count?" (questioned necessity)
**Notes:** Claude explained it's in MODEL-05 for self-awareness ("have you been busy today?"). Since the proxy approach is zero infrastructure overhead, it was included. User accepted this reasoning.

---

## Identity Summary Bootstrap

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcode short description in generate_manifest() | Fixed string seeded at first init | |
| Leave blank until Phase 17 | Empty until reflection runs | |
| Generate from SELF.md intro section | SELF.md intro paragraph copied to SelfStateStore | ✓ |

**User's choice:** "Whatever you think is best regardless of the amount of work it takes now" (delegated to Claude)
**Notes:** Claude selected option 3 (generate from SELF.md intro). Single source of truth: `generate_manifest()` writes SELF.md intro, `SelfStateStore.bootstrap_if_empty()` seeds Firestore on first startup. No CI-to-Firestore coupling — seeding happens at Cloud Run boot, not build time.

---

## Claude's Discretion

- SELF.md file structure and section layout
- SHA/hash embedding format
- Exact injection placement in smart_system template
- SelfStateStore.get() graceful fallback when Firestore unavailable
- get_self_status uptime definition (container start time)

## Deferred Ideas

None.
