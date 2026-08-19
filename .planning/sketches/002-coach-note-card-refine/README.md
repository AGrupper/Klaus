---
sketch: 002
name: coach-note-card-refine
question: "Within the quote card, how does the note get marked as Klaus's voice?"
winner: "3"
tags: [hub, today, typography, coach-note]
---

# Sketch 002: The Quote Card, Four Ways

## Design Question
Sketch 001 settled the shape: a card, under Talk to Klaus. What it didn't settle is
attribution. A plain white card looks like every other card on Today — nothing says the
words inside it are Klaus talking. Four ways to fix that, same geometry throughout.

## How to View
```
open .planning/sketches/002-coach-note-card-refine/index.html
```

## Variants
- **1: As you saw it** — 001's variant B unchanged, as the control.
- **2: Accent edge** — a 4px midnight edge on the card, attribution dropped to a footer so the note's own words open the card.
- **3: Klaus mark** ★ SELECTED — the pen nib from the Talk to Klaus button reused as a 22px avatar; name left, time right. The card reads as a message from him.
- **4: Tinted** — the card washed in 7% accent with a serif quote-mark watermark. No label; the colour attributes.

## What to Look For
- **Does the label earn its line?** 1 and 3 spend a row on attribution; 2 and 4 don't.
- **Ties to the CTA.** 2 and 3 borrow directly from the Talk to Klaus button (its colour,
  its icon). 4 borrows the hue only. Does that connection read, or just repeat?
- **Accent swap.** Customize can set Black / Deep teal / Forest — 4 depends most on the
  accent staying light enough to tint; check it at each.
- **Empty state.** 3 keeps the avatar and greys it; the others go plain italic.

## Outcome
Shipped 2026-08-19. `CoachNote` in `frontend/src/components/home/HomePage.tsx`, with the
mark itself extracted to `components/shared/KlausMark.tsx` so the button and the note can
never drift apart. Amit added a follow-on: the mark is user-settable in Customize, which
is why it is a component and not two copies of an icon.
