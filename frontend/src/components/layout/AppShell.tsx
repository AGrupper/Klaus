/**
 * AppShell.tsx — Root responsive layout.
 *
 * Desktop (md: >= 768px): horizontal flex row
 *   [Sidebar 64px] | [main flex-1 min-w-0] | [GlanceRail 280px] | [DockChat 360px collapsible→48px]
 *
 * Phone (< md): vertical column
 *   [full-width content area] + [BottomTabs fixed 64px at bottom]
 *
 * Children are rendered inside the main content column via React children prop.
 * The active route content is rendered as children (App.tsx passes <Routes>).
 *
 * Breakpoint: Tailwind md (768px). No intermediate breakpoints.
 *
 * Bounded-height root (UAT gap-closure, 2026-07):
 *   The root was previously `minHeight: 100dvh`. A *min*-height lets the
 *   flex container grow past the viewport to fit its content, which means
 *   `<main>`'s `overflow-y-auto` never becomes the scrolling element for
 *   tall content (e.g. a long chat) — the container itself grows instead
 *   and the document/body scrolls. Downstream, ChatWindow's own message
 *   list relies on `height: 100%` all the way up this chain to become its
 *   own bounded scroll region; with an unbounded ancestor that percentage
 *   chain never resolves, so `scrollHeight` and `clientHeight` stay equal
 *   and the initial-scroll-to-bottom effect's guard never passes (WhatsApp-
 *   style "always open at the latest message" silently failed on phone).
 *   `height: 100dvh` is a definite viewport-relative value (not a
 *   percentage), so it does not depend on html/body/#root having an
 *   explicit height — it bounds the root outright, `<main>` becomes a real
 *   scroll container, and the percentage chain into ChatWindow resolves.
 */
import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { BottomTabs } from './BottomTabs'
import { GlanceRail } from './GlanceRail'
import { DockChat } from './DockChat'
import { OfflineIndicator } from '../shared/OfflineIndicator'
import { InstallBanner } from '../shared/InstallBanner'
import { UpdatePrompt } from '../shared/UpdatePrompt'
import { UndoToast } from '../tasks/UndoToast'

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    /*
     * Outer wrapper: full screen, no scroll on the root element.
     * Desktop: flex row. Phone: flex column.
     */
    <div
      className="flex flex-col md:flex-row"
      style={{ height: '100dvh', backgroundColor: '#0A0A0A' }}
    >
      {/* Fixed offline indicator — appears at the top of the viewport when offline (HUB-03) */}
      <OfflineIndicator />

      {/* "New version available → Refresh" prompt when a new deploy is detected */}
      <UpdatePrompt />

      {/* Fixed iOS install banner — appears at the bottom when on iOS, not standalone, not dismissed (HUB-02 / D-12) */}
      <InstallBanner />

      {/* Desktop only sidebar — 64px wide, full height */}
      <Sidebar />

      {/*
       * Main content area.
       * Desktop: flex-1 with min-w-0 to prevent content overflow past siblings.
       * Phone: flex-1 to fill available height above the bottom tab bar.
       */}
      <main
        className="hub-main flex-1 min-w-0 overflow-y-auto"
        style={{ display: 'flex', flexDirection: 'column' }}
      >
        {children}
      </main>

      {/* Desktop only glance rail — 280px right column */}
      <GlanceRail />

      {/* Desktop only dock chat — 360px collapsible right panel */}
      <DockChat />

      {/* Phone only bottom tab bar — fixed 64px, shown above safe-area inset */}
      <BottomTabs />

      {/*
       * Global undo toast — mounted here (not inside any page) so it survives
       * across routes. Deleting a habit on /habits and completing/deleting a
       * task on /tasks both drive the same zustand undoStore; the toast must
       * exist regardless of the active route (it was previously rendered only
       * inside TasksPage, so habit deletes on /habits produced no toast).
       */}
      <UndoToast />
    </div>
  )
}
