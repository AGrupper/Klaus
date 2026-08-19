---
sketch: 001
name: coach-note-quote
question: "How should the coach's note read as a quote block directly under Talk to Klaus?"
winner: null
tags: [hub, today, typography, coach-note]
---

# Sketch 001: Coach Note as a Quote Block

## Design Question
Today the coach note is a grey paragraph tacked under the **bottom** of the Today
timeline (`frontend/src/components/home/HomePage.tsx:419`) — the last thing in the
section, styled like a caption. Moving it to the top, directly under **Talk to Klaus**,
makes it the first thing read. What quote treatment carries that weight without turning
into a fifth card?

## How to View
```
open .planning/sketches/001-coach-note-quote/index.html
```

## Variants
- **A: Hairline rule** — a 3px accent rule, no container; the note is an aside on the page.
- **B: Quote card** — the app's own grouped-card idiom with an attribution row. Path of least resistance: it is a `<Group>`.
- **C: Attached to CTA** — squared into the bottom of the Talk-to-Klaus button and tinted with the accent, so button + note read as one object: Klaus speaking.
- **D: Pull quote** — editorial. Display type, oversized quote mark, no container; the loudest thing under the button.

## What to Look For
- **Weight against the CTA.** Talk to Klaus is a solid midnight slab. A and D sit quietly
  beside it; B adds a second card; C merges with it. Which balance is right?
- **Card count.** Today already stacks Timeline + Stats + Corner. B adds a fifth surface;
  A and D add none.
- **Long note.** The note is capped at 280 characters (`_COACH_NOTE_MAX_LEN`, `core/hub/today.py:372`).
  Flip to "At the 280 cap" — D's display type gets tall fast; A stays compact.
- **The empty state.** Before the morning briefing writes it, `coach_note` is null and the
  page renders *nothing*. Each variant shows a proposed D-06 placeholder — or we keep
  rendering nothing and let the page start at Today.
- **Timestamp.** The note is written once in the morning and never recomposed, so it must
  stay stamped. Compare "Klaus · 07:42" (A), the header row (B), small-caps (D).
- **Accent swap.** Customize can set the accent to Black / Deep teal / Forest — use the
  toolbar to check C's tint still reads at each.
