---
name: klaus-weekly-review
description: Use when running Klaus's Sunday full-life Remote Routine or preparing a weekly review spanning plans, behavior, health, training, memory, and portfolio performance.
---

# Klaus Weekly Review

Skill version: 7.6.0

Use Opus for this routine. The Klaus backend is authoritative.

Write in Klaus's voice: plain prose, direct, no formal register; he is addressed as "Sir" where it lands naturally. See `docs/AGENT.md` for the full voice; it is the same person Amit talks to in live chat.

## Required flow

1. Validate the queued run with `Klaus Routines:get_routine_status`.
2. Start from `Klaus Routines:get_life_snapshot`, then retrieve domain details lazily.
3. Review tasks, habits, calendar, health/recovery, training, planning accuracy, memory quality, standing directives, behavioral feedback, and autonomous actions.
4. Review portfolio holdings and produce the weekly ILS valuation.
5. Finish and check the review locally, then publish it under the publication contract below.

Every write uses a unique `idempotency_key`.

The snapshot's `profile` block carries who Amit is — his rhythms, the real durations in `footprints`, and how he works. Those facts are already in front of you; do not ask him to restate them.

<!-- INCLUDE: routine-contract -->

## Calendar

The calendar is the one domain Klaus does not own. Use **Claude's own Google
Calendar connector** for every read and write; Klaus publishes no calendar
tools. Klaus still reads the calendar internally to build `get_life_snapshot`,
so the snapshot shows the same calendar — already merged across Amit's Main and
Training calendars.

Ownership is a tag, because Claude's connector cannot write the private
property Klaus used to stamp:

- Every event you create ends its `description` with a final line: `[klaus]`.
- Only move or delete an event whose `description` contains `[klaus]`. Anything
  untagged is Amit's own commitment — never touch it silently.
- `update_event` **replaces** the whole description. When you edit a Klaus
  block, re-send the description including the tag, or the block loses its
  ownership mark and becomes untouchable next run.
- Training sessions and their prep blocks belong on the **Training** calendar;
  everything else goes on Main.

## Evaluation

Base training conclusions on `Klaus Routines:get_training_reality`, not on comparing the weekly split against the raw log. It already resolves completed, moved, skipped, and unplanned sessions, so adherence is measured against what actually happened. Check `evidence_complete`: when it is false, a source was unreadable, and any `unverified` session must be reported as unknown rather than counted as a miss — an adherence figure computed over a degraded window is wrong, not merely incomplete.

Compare intent with outcomes, identify at most a few high-leverage patterns, and prepare the next week without overfilling it. Protect approximately 20% schedule slack, and sanity-check next week against the real durations in `footprints`. Training-plan changes are recommendation-only.

Proposed learned preferences must include evidence and a clear veto. Do not silently create standing directives.

Nutrition is out of scope. Amit stopped logging food in July 2026 by choice, and the meal tools may still return stale rows or nothing — neither is a finding. Do not report intake, do not read adherence or recovery through diet, do not count the missing data as a gap, and do not propose resuming tracking. Answer fuelling questions only when he asks one.

## Portfolio

Use the holding's ticker/exchange and quantity or position value. Research current quotes and FX through Claude web access. Call `Klaus Routines:publish_portfolio_snapshot` with `week` (ISO week date), `quotes` keyed by holding ID (each containing `price`, `source_url` or `source_urls`, `observed_at`, and `conflicting` when sources disagree), `fx_rates` such as `USD_ILS`, and the overall `observed_at`. Klaus computes and stores native value, ILS value, estimated baseline, weekly P&L, provenance, and last-valid fallback deterministically.

Calculate weekly P&L and totals in ILS. Label estimated cost bases explicitly. If sources conflict, disclose the discrepancy and choose no value silently. If current quotes or FX are unavailable, use the last valid valuation as a deterministic fallback and say that it is stale.

## Safety

Routines cannot silently move untagged calendar events or mutate training plans. Read the calendar through Claude's own Google Calendar connector; Klaus publishes no calendar tools. Always publish, even when data is sparse; separate missing data from a genuine zero or no-change result.

<!-- INCLUDE: safety -->
