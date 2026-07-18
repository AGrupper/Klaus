# Phase 31: Standing Directives - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-18
**Phase:** 31-standing-directives
**Areas discussed:** Capture judgment, Expiry mechanics, Self-directive lifecycle, Veto scope + list/cancel, Nightly directive traffic, Reaction-pairing semantics, Legacy-cron veto power

---

## Capture judgment

| Option | Description | Selected |
|--------|-------------|----------|
| Liberal + visible ack | Capture whenever it plausibly reads as a lasting wish; the one-line ack is the correction surface | ✓ |
| Judgment-gated | Only capture on durability signals ("always", "from now on", repeated complaint) | |
| Capture but ask when ambiguous | Clear cases silent, ambiguous get a one-line question | |

**User's choice:** Liberal + visible ack

| Option | Description | Selected |
|--------|-------------|----------|
| Reflection prune-flag | Nightly loop sanity-checks directives against the 24h window, flags stale/contradicted ones | ✓ |
| Periodic list digest | Active-directive list appended every N days | |
| No guard — trust list/cancel | Klaus never volunteers; stale directives discovered by their effects | |

**User's choice:** Reflection prune-flag

| Option | Description | Selected |
|--------|-------------|----------|
| Current restatement | Store the present message verbatim; earlier missed statement stays lost | ✓ |
| Dig up the original | Search history/Pinecone for the earlier statement | |
| You decide | Claude's judgment during planning | |

**User's choice:** Current restatement

| Option | Description | Selected |
|--------|-------------|----------|
| Echo + expiry read-back | One line restating the wish AND understood duration | ✓ |
| Minimal ack | Just "Noted, Sir" | |
| Ack + directive count | Echo plus active-directive count | |

**User's choice:** Echo + expiry read-back

---

## Expiry mechanics

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid: date or judged condition | Explicit timeframes → hard expires_at; event conditions → text judged by nightly reflection | ✓ |
| Always judgment-evaluated | Every end condition is text re-evaluated by the model | |
| Always resolve to a date | Convert every condition to a concrete date, asking when needed | |

**User's choice:** Hybrid: date or judged condition

| Option | Description | Selected |
|--------|-------------|----------|
| Almost never | Ask only on unpindownable bounded intent ("for a while") | |
| Ask on any event condition | Ask for a date backstop on event conditions | |
| Ask on any missing condition | No condition stated → ask whether permanent | ✓ (first pass) |
| Capture first, ask in the ack | Store immediately as indefinite; ack appends a soft duration question | ✓ (confirmed reconciliation) |
| Block on the answer | Ask before storing, wait for reply | |
| Revert to DIR-02 as written | Silently indefinite | |

**User's choice:** First picked "Ask on any missing condition"; on the follow-up (flagged as cutting against DIR-02's letter) confirmed **Capture first, ask in the ack** — storage semantics stay DIR-02-compliant, the ack invites a duration.

| Option | Description | Selected |
|--------|-------------|----------|
| Note it in the nightly | Expiry mentioned once in the nightly message | ✓ |
| Silent resumption | Behavior resumes unannounced | |
| Immediate ping | Dedicated proactive message at expiry | |

**User's choice:** Note it in the nightly

| Option | Description | Selected |
|--------|-------------|----------|
| Stay active, ask if prolonged | Uncertain → in force; ask in nightly if uncertainty persists past plausible window | ✓ |
| Stay active, never ask | Active until cancelled | |
| Expire on best guess | Expire when condition probably ended | |

**User's choice:** Stay active, ask if prolonged

---

## Self-directive lifecycle

| Option | Description | Selected |
|--------|-------------|----------|
| Active on proposal, veto cancels | Effective immediately; nightly announces with one-line veto | ✓ |
| Pending until you approve | Inactive until explicit okay | |
| Active after 1 quiet day | Grace window before activation | |

**User's choice:** Active on proposal, veto cancels

| Option | Description | Selected |
|--------|-------------|----------|
| Repeated pattern | Same reaction more than once before proposing | |
| Single strong signal | One clear pushback is enough | ✓ |
| Conservative: explicit only | Only directly-stated missed preferences | |

**User's choice:** Single strong signal — user explicitly chose adaptation speed over the repeated-pattern guard.

| Option | Description | Selected |
|--------|-------------|----------|
| Veto = durable anti-lesson | Kept as vetoed; never re-proposed; veto is training signal | ✓ |
| Veto = just cancel | Nothing stops re-proposal | |
| Veto + cooldown | Blocked N weeks, then eligible | |

**User's choice:** Veto = durable anti-lesson

| Option | Description | Selected |
|--------|-------------|----------|
| One per night | Single most-supported proposal per nightly | |
| Up to 2-3 | Small cap | |
| No cap | Everything qualifying proposed and activated | ✓ |

**User's choice:** No cap

---

## Veto scope + list/cancel

| Option | Description | Selected |
|--------|-------------|----------|
| Err toward silence | Ambiguous coverage → suppress | |
| Err toward speaking | Ambiguous coverage → outreach proceeds | |
| Uncertain → ask in nightly | Suppress now, queue a scope-clarification question for the nightly | ✓ |

**User's choice:** Uncertain → ask in nightly

| Option | Description | Selected |
|--------|-------------|----------|
| At capture | Capture turn notices the collision, asks which wins in the same exchange | ✓ |
| At first collision | Flag when a reasoning path actually hits it | |
| In the nightly | Reflection raises conflicts in the nightly | |

**User's choice:** At capture

| Option | Description | Selected |
|--------|-------------|----------|
| Numbered list, NL cancel | Numbered in-voice list; cancel by number or description | ✓ |
| Plain prose list | Conversational, unnumbered | |
| Structured card-style | Formatted block with IDs/dates | |

**User's choice:** Numbered list, NL cancel

| Option | Description | Selected |
|--------|-------------|----------|
| Active by default, history on ask | Default active-only; "show me everything" surfaces expired/vetoed/superseded | ✓ |
| Active + recently ended | Default appends last ~7 days of ended entries | |
| Active only, ever | No chat surface for history | |

**User's choice:** Active by default, history on ask

---

## Nightly directive traffic

| Option | Description | Selected |
|--------|-------------|----------|
| Woven into one narrative | Items handed to the compose as context; no fixed section | ✓ |
| Dedicated section | Consistent "Standing orders" block | |
| Separate message | Housekeeping as its own message | |

**User's choice:** Woven into one narrative

| Option | Description | Selected |
|--------|-------------|----------|
| Klaus's judgment | Activations/expiries always stated; flags/questions may wait a night | ✓ |
| Everything, always | Every item fully stated every night | |
| Hard priority order | Fixed rule with a cut at N items | |

**User's choice:** Klaus's judgment

---

## Reaction-pairing semantics

| Option | Description | Selected |
|--------|-------------|----------|
| No reply by reflection time | Deterministic; topic-engaging reply = replied; subject change = ignored-topic | ✓ |
| Grace window (e.g. 4h) | Exclude late-evening outreaches near reflection time | |
| Judgment call | Reflection decides per-outreach what non-response meant | |

**User's choice:** No reply by reflection time

| Option | Description | Selected |
|--------|-------------|----------|
| Logged data only | Strong signal = explicit words; single ignore never changes policy | |
| Yes, ignore = strong signal | One unanswered nudge can immediately produce an active self-directive | ✓ |
| You decide | Claude designs the taxonomy | |

**User's choice:** Yes, ignore = strong signal

| Option | Description | Selected |
|--------|-------------|----------|
| Soften, don't stop | Ignore-only proposals default to easing off | |
| Full stop allowed | Ignore can propose outright suppression | |
| Bounded trial | Built-in end condition ("for a week") | |

**User's choice:** Free text — "I want to be able to stop it completely, but also, often, it depends on what I ask." Confirmed reading: full stop IS allowed, no forced softening; form is Klaus's per-case judgment from context and what the outreach was; explicit chat asks always override loop inferences.

---

## Legacy-cron veto power

| Option | Description | Selected |
|--------|-------------|----------|
| Full veto, nightly exempt | Directives can skip legacy cron sends; nightly keeps a carve-out as the veto/announcement channel | ✓ |
| Full veto, no exemptions | Any cron including the nightly can be silenced | |
| Shape only until Phase 33 | Tone/content adjustment only; no skips | |

**User's choice:** Full veto, nightly exempt

| Option | Description | Selected |
|--------|-------------|----------|
| The compose call itself | Directives block injected with skip-verdict authority; skip logged as skipped_by_directive | ✓ |
| A pre-send tick-brain check | Free Groq triage before each legacy send | |
| Deterministic scope match | Code-level text matching against cron names | |

**User's choice:** The compose call itself

---

## Claude's Discretion

- `StandingDirectiveStore` schema details (status enum, condition vs date fields, provenance shape)
- `get_recent_window()` signature/pagination + per-message `ts` handling
- Exact Step-0 veto prompt wording (topic-scoped per Pitfall 5)
- Directive-skipped morning briefing vs `structured` snapshot / hub `/api/today` contract
- `{standing_directives}` placeholder position (after the stable cached prefix)
- Veto-phrase recognition in next-morning chat
- Dedup on restatement of an existing directive

## Deferred Ideas

- Hub directives page (list + cancel buttons) — v6.1 VIS-01
- Snapshot-write semantics for directive-skipped briefings — Phase 33 OCC-02 territory; interim at Claude's discretion
