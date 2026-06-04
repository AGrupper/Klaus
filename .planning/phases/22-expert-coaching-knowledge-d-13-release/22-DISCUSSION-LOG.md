# Phase 22: Expert Coaching Knowledge + D-13 Release - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-04
**Phase:** 22-expert-coaching-knowledge-d-13-release
**Areas discussed:** Coaching guide depth, Tier B recency windows, Critique posture (COACH-07), Specificity bar (COACH-02)

---

## Coaching guide depth

### Guide framing
| Option | Description | Selected |
|--------|-------------|----------|
| Applied to your plan | Knowledge written around Amit's sessions/goals/split | ✓ |
| Principles + examples | Durable science with blueprint as worked examples | |
| Pure reference science | Generic knowledge, no personalization | |

### Guide size
| Option | Description | Selected |
|--------|-------------|----------|
| Tight (~300-500) | Dense principles only | |
| Moderate (~600-900) | Balanced | |
| Rich (1000+) | Comprehensive | ✓ (with cost caveat) |

**User's choice:** Rich/comprehensive, BUT made cost-efficient — "make it so not every tool call costs a lot; when I ask something specific on Telegram he only looks for the specific thing and it costs less, with the guide being large and comprehensive."

### Topics
| Option | Selected |
|--------|----------|
| Concurrent training | ✓ |
| Periodization | ✓ |
| Session execution | ✓ |
| Fueling science | ✓ |

### Retrieval mechanism (follow-up — overrides locked full-injection)
| Option | Description | Selected |
|--------|-------------|----------|
| Slim core + lookup tool | ~250-line always-injected core + read_coaching_guide(topic) deep sections on demand | ✓ (implied by user's size answer) |
| Full inject + caching | Whole guide every call, rely on context caching | |
| Pure lookup tool | Nothing injected, always tool-call | |

### Crons
**User's choice:** "I don't really know. I trust you. Just give me the best quality, cost efficiency, and speed... high-quality coaching, but make sure it doesn't cost too much for every coaching call. It can cost more than usual tool calls, but make sure it doesn't cost too much."
**Notes:** Resolved by Claude → crons carry slim core always; may call lookup only-when-needed (weekly review deep, morning briefing/autonomous tick stay cheap).

---

## Tier B recency windows

### Windows
| Option | Description | Selected |
|--------|-------------|----------|
| Use proposed windows | lifts ≤14d, pace ≤7d, nutrition ≤2d, recovery always fresh | ✓ |
| Tighter | lifts ≤7d, pace ≤5d, nutrition ≤1d | |
| Looser | lifts ≤21d, pace ≤14d, nutrition ≤3d | |
| Let me set them | Custom | |

### Just-past-window behavior
| Option | Description | Selected |
|--------|-------------|----------|
| Cite with staleness caveat | Name the number + flag its age | ✓ |
| Refuse, cite target instead | Don't name old number at all | |
| Depends on data type | Per-type mapping | |

**Notes:** Distinct from no-data case (SC-1): no data at all → "I don't have a recent X logged" + target; old data past window → cite-with-caveat.

---

## Critique posture (COACH-07)

### Proactivity
| Option | Description | Selected |
|--------|-------------|----------|
| Volunteer when confident | Unprompted structural critique when knowledge+data clearly show suboptimal | ✓ |
| Only when asked | Never volunteers | |
| Volunteer + dedicated moment | Volunteer + recurring slot (overlaps Phase 24) | |

### Tone
| Option | Description | Selected |
|--------|-------------|----------|
| Blunt expert | Direct, names flaw + fix, minimal hedging | ✓ |
| Diplomatic | Hedged, respectful | |
| Blunt but evidence-first | Verdict after evidence | |

### Boundary
| Option | Description | Selected |
|--------|-------------|----------|
| Recommend, you confirm | update_plan only on explicit yes | ✓ |
| Recommend + offer to log | Proactively offers to update each time | |
| You decide | Claude picks | |

---

## Specificity bar (COACH-02)

### Minimum bar
| Option | Description | Selected |
|--------|-------------|----------|
| Session + load + rationale | Every coaching point names all three | ✓ |
| Session + load (rationale optional) | Terser | |
| Adaptive by context | Full in chat, terse in briefing | |

### Rationale depth
| Option | Description | Selected |
|--------|-------------|----------|
| One-liner default | Single clause; mini-lesson on "why?" (pulls guide lookup) | ✓ |
| Mini-lesson when coaching | 2-3 sentences by default | |
| You decide | Claude picks | |

---

## Claude's Discretion

- Crons lookup-bias resolution (slim core always; deep only-when-needed).
- Slim-core line count + section structure; `read_coaching_guide` tool shape and section keying.
- Upper bound where very old Tier B data degrades to "no recent data."
- Exact prompt wording for the Tier A/B contract, recency thresholds, and staleness-caveat phrasing.
- Whether the rich guide is one anchored file or a small set of section files behind the lookup tool.

## Deferred Ideas

- Data-driven macro-adherence engine + fueling-slot-miss detection → Phase 24 (NUTR).
- Cross-cron coaching-message dedup / repeat-suppression → Phase 24.
- BlockStore/BenchmarkStore, block-state, week-numbers, benchmark triggers → Phase 23.
- Progress projection / pace-to-deadline trend reporting → Phase 25.
