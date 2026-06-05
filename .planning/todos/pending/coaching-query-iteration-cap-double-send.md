---
id: coaching-query-iteration-cap-double-send
status: pending
type: bug
priority: medium
created: 2026-06-05
source: phase-22 live verification (22-04 D-13 smoke test)
---

# Data-verification-heavy coaching queries trip the tool-iteration cap and double-send

## Symptom

During Phase 22 live verification (2026-06-05, Cloud Run rev 00085), some coaching
queries returned TWO messages:

1. *"Apologies, Sir. This request required more processing steps than expected.
   Please rephrase or break it into smaller parts."*
2. …immediately followed by the **correct, complete answer**.

Observed on: *"What was my last bench press?"* and *"Review yesterday's nutrition"*.

## Root cause (hypothesis)

The Phase 22 recency-windowed data-presence contract (smart_agent.md) instructs the
brain to verify data presence before answering. For "no recent log" questions this
makes it sweep multiple repositories (Firestore → Notion → Garmin), pushing the smart
loop past its max tool-iteration cap. The orchestrator emits the "more processing
steps" fallback, but the model still completes and a real answer is also sent — a
double-send.

## Why it matters

- UX wrinkle: user sees an error message paired with a correct answer.
- Not a safety failure: the D-13 anti-fabrication gate held in all cases.

## Possible fixes (pick during triage)

1. Raise the smart-loop max tool-iteration cap (verify current value in
   `core/main.py:_run_smart_loop`) — data-presence verification legitimately needs
   more tool calls than the old cap assumed.
2. Suppress the "more processing steps" fallback when a substantive answer was
   produced in the same turn (avoid the double-send).
3. Steer the contract to short-circuit the repository sweep once the first
   authoritative source confirms no log (reduce tool-call depth).

## Acceptance

- A data-verification-heavy query ("what was my last bench press?") returns a single
  correct message, no "more processing steps" fallback.
- Anti-fabrication behavior (SC-1) still holds.
