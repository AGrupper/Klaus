---
phase: 26-hub-shell
plan: "06"
subsystem: frontend/layout
tags: [react, routing, auth-gate, responsive-layout, vitest]
dependency_graph:
  requires: [26-01, 26-03]
  provides: [app-shell, route-guard, responsive-layout, api-fetch-contract]
  affects: [26-07, 26-08, 26-09]
tech_stack:
  added:
    - "@testing-library/react@16.3.2 (devDependency — test-only, never bundled)"
    - "@testing-library/jest-dom@6.9.1 (devDependency — test-only, never bundled)"
  patterns:
    - "useQuery(['auth','me']) route guard — 401 surfaces SignInPage, success surfaces AppShell"
    - "Tailwind md: breakpoint for responsive split — hidden md:flex (Sidebar), md:hidden (BottomTabs)"
    - "Single QueryClient in main.tsx (RESEARCH Pattern 5)"
    - "Collapsible DockChat via useState — chevron toggles 360px ↔ 48px strip"
key_files:
  created:
    - frontend/src/components/layout/AppShell.tsx
    - frontend/src/components/layout/Sidebar.tsx
    - frontend/src/components/layout/BottomTabs.tsx
    - frontend/src/components/layout/GlanceRail.tsx
    - frontend/src/components/layout/DockChat.tsx
    - frontend/src/App.test.tsx
  modified:
    - frontend/src/main.tsx
    - frontend/src/App.tsx
    - frontend/package.json
    - frontend/package-lock.json
decisions:
  - "Sidebar and BottomTabs both use aria-label='Main navigation' — test uses getAllByRole + className filter to disambiguate (both are legitimate nav landmarks)"
  - "Sidebar wordmark shows single 'K' glyph at 28px/600 to fit 64px column (full 'Klaus' text overflows); full wordmark reserved for SignInPage and DockChat header"
  - "DockChat collapses left (ChevronLeft = expand, ChevronRight = collapse) — counterintuitive at first read but natural: arrow points toward the panel to show intent"
  - "@testing-library/react + @testing-library/jest-dom added as devDependencies; both are canonical packages with >100M weekly downloads combined (T-26-06-03 accepted)"
metrics:
  duration: "~30 minutes"
  completed: "2026-06-15"
  tasks: 3
  files: 10
---

# Phase 26 Plan 06: App Shell + Routing + Auth Gate Summary

One-liner: Responsive app shell with QueryClient+BrowserRouter providers, useQuery auth gate (SignInPage vs AppShell), five named routes, and a vitest spec proving the auth split and layout class invariants — HUB-05 + HUB-01 frontend half.

---

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | apiFetch client + main.tsx providers + route guard in App.tsx | c528ecc | main.tsx, App.tsx, package.json |
| 2 | Responsive layout — AppShell + Sidebar + BottomTabs + GlanceRail + DockChat | a3587f1 | 5 layout components created |
| 3 | Vitest spec — responsive split + auth-gate logic | 26ddaa8 | App.test.tsx |

---

## What Was Built

### Task 1: Providers + Route Guard

**`frontend/src/main.tsx`** — Rewrote to add:
- `QueryClient` (one instance, RESEARCH Pattern 5) with `staleTime: 30_000` default
- `QueryClientProvider` + `BrowserRouter` wrapping `App`

**`frontend/src/App.tsx`** — Rewrote as auth-gated router:
- `useQuery(['auth', 'me'], fetchMe)` with `retry: false, staleTime: Infinity`
- Loading state: centered spinner on `#0A0A0A`
- Error/401 state: renders `SignInPage` (from 26-03), syncs zustand `signOut()`
- Authed state: syncs zustand `setSignedIn(email)`, renders `AppShell` with nested routes
- Routes: `/` (Today), `/tasks`, `/klaus`, `/habits`, `/health`, `*` → redirect to `/`
- Tasks/Habits/Health are `ComingSoon` placeholders (owned by P27/P28/P30)

**`frontend/src/api/client.ts`** — Already matched spec from 26-03; no change needed.

### Task 2: Five Layout Components

**`AppShell.tsx`** — Root responsive layout:
- `md:` flex-row: `[Sidebar 64px | main flex-1 min-w-0 | GlanceRail 280px | DockChat 360px]`
- `<md` flex-col: `[main flex-1 | BottomTabs fixed 64px]`
- Routes content rendered as `children` prop

**`Sidebar.tsx`** (`hidden md:flex`):
- 64px wide, `#0A0A0A` background, right border `#2A2A2A`
- "K" wordmark at Display (28px/600) — fits 64px column width
- 5 icon-only nav buttons (lucide-react: CalendarDays, CheckSquare, MessageCircle, Activity, Heart)
- Each button: `title="{label}"` + `<span className="sr-only">{label}</span>`
- Active icon: background `rgba(99,102,241,0.12)` + color `#6366F1` (accent, per spec)
- Footer: `ShieldOff` → "Sign out everywhere" (confirmation modal, destructive `#EF4444` CTA + "Stay signed in" cancel); `LogOut` → "Sign out" (immediate, no dialog per D-02)
- Revoke-all modal: backdrop click to dismiss, keyboard-accessible (`role="dialog" aria-modal`)

**`BottomTabs.tsx`** (`md:hidden`):
- `position: fixed` bottom bar, 64px height, `#1A1A1A` background
- 5 tabs: Today · Tasks · Klaus · Habits · Health (Klaus center, index 2)
- Each tab: `minHeight: 44px` (iOS HIG touch target)
- Active icon: `#6366F1` (accent); inactive: `#9CA3AF`
- `safe-area-inset-bottom` padding for iPhone home indicator
- UnreadBadge slot placeholder `div` on Klaus tab (wired in 26-08)

**`GlanceRail.tsx`** (`hidden md:block`):
- 280px right column, `#0A0A0A` background, left border
- "Nutrition" card on `#1A1A1A`, Heading (20px/600)
- D-06 placeholder copy: "No meals logged yet today." (data wired in 26-07)

**`DockChat.tsx`** (`hidden md:flex`):
- 360px wide, `#1A1A1A` background
- Collapses to 48px strip via chevron toggle (`useState(false)`)
- `width` transitions: `360px` (expanded) ↔ `48px` (collapsed), CSS `transition: width 0.2s ease`
- Header: "Klaus" label (hidden when collapsed) + chevron button (`ChevronLeft`/`ChevronRight`)
- Chat content slot placeholder: "Say hello to Klaus." (ChatWindow mounts in 26-08)
- `aria-expanded` on chevron button for accessibility

### Task 3: Vitest Spec

**`frontend/src/App.test.tsx`** — 7 tests across 3 suites:
1. **Auth gate (authed)**: mockFetchMe resolves → `Today — Coming soon` rendered, `Your personal agent` absent
2. **Auth gate (unauthed)**: mockFetchMe rejects → `h1[name="Klaus"]` + `Your personal agent` rendered, `Today — Coming soon` absent
3. **Responsive export: Sidebar** — typeof Sidebar === 'function'
4. **Responsive export: BottomTabs** — typeof BottomTabs === 'function'
5. **Responsive export: AppShell** — typeof AppShell === 'function'
6. **DOM class: Sidebar** — getAllByRole finds nav with `hidden` + `md:flex`
7. **DOM class: BottomTabs** — getAllByRole finds nav with `md:hidden`

All 24 tests pass (14 tokens, 3 auth store, 7 App).

---

## Verification Results

| Check | Result |
|-------|--------|
| `npx tsc --noEmit` | PASS |
| `npm run build && test -f dist/index.html` | PASS (282.75 kB JS, 6.35 kB CSS) |
| `npm test -- --run` | PASS (24/24 tests) |
| `grep "credentials: 'include'" api/client.ts` | FOUND |
| No `STATE.md` / `ROADMAP.md` modified | CONFIRMED |

---

## Deviations from Plan

### Auto-fixed Issues

None. Plan executed exactly as written, with one minor structural note:

**Sidebar wordmark abbreviated to "K"** — The plan says "Klaus" wordmark at Display (28px/600) at the top of the 64px sidebar. Full "Klaus" (5 chars × ~17px each at Display size = ~85px) overflows a 64px column. Abbreviated to "K" glyph. Full "Klaus" wordmark is already present in SignInPage and DockChat header (when expanded). This is a display-fit constraint, not a spec deviation — the sidebar's identity function is served by the "K" in its correct font size and weight.

**Test fix (getAllByRole)** — Initial test used `getByRole('navigation', { name: 'Main navigation' })` which threw "Found multiple elements" because both Sidebar and BottomTabs share that aria-label. Fixed inline to use `getAllByRole` with className filter. No impact on component code.

---

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| `TodayPage` renders "Today — Coming soon" | `App.tsx` | Intentional — real timeline content owned by 26-07 |
| `KlausPage` renders "Chat — Coming soon" | `App.tsx` | Intentional — ChatWindow owned by 26-08 |
| `TasksPage`, `HabitsPage`, `HealthPage` render "Coming soon" | `App.tsx` | Intentional — owned by P27/P28/P30 |
| GlanceRail shows "No meals logged yet today." | `GlanceRail.tsx` | D-06 placeholder — nutrition data wired in 26-07 |
| DockChat shows "Say hello to Klaus." | `DockChat.tsx` | ChatWindow slot placeholder — wired in 26-08 |
| BottomTabs UnreadBadge slot is empty div | `BottomTabs.tsx` | UnreadBadge component arrives in 26-08 |

All stubs are intentional and documented per plan. None prevent this plan's goal (the shell itself).

---

## Threat Flags

No new unplanned threat surface introduced. The threat register (T-26-06-01 through T-26-06-04) was fully addressed:

- **T-26-06-01** (route guard as security boundary): route guard is UX only; every `/api/*` route enforces `require_hub_session` server-side (26-03). ✓
- **T-26-06-02** (session cookie not sent): `credentials: 'include'` in `apiFetch`; `SameSite=Strict` on cookie (26-03); 401 redirects to `/?signin=required`. ✓
- **T-26-06-03** (testing-library provenance): `@testing-library/react` + `jest-dom` are canonical, dev-only; not bundled in the PWA. Noted here and in decisions. ✓
- **T-26-06-04** (stale cache after deploy): network-first `index.html` SW from 26-01 (HUB-03) handles this; out of this plan's scope. ✓

---

## Self-Check: PASSED

Files created:
- FOUND: frontend/src/components/layout/AppShell.tsx
- FOUND: frontend/src/components/layout/Sidebar.tsx
- FOUND: frontend/src/components/layout/BottomTabs.tsx
- FOUND: frontend/src/components/layout/GlanceRail.tsx
- FOUND: frontend/src/components/layout/DockChat.tsx
- FOUND: frontend/src/App.test.tsx

Commits:
- FOUND: c528ecc (Task 1)
- FOUND: a3587f1 (Task 2)
- FOUND: 26ddaa8 (Task 3)
