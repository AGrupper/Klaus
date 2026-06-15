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
 */
import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { BottomTabs } from './BottomTabs'
import { GlanceRail } from './GlanceRail'
import { DockChat } from './DockChat'
import { OfflineIndicator } from '../shared/OfflineIndicator'
import { InstallBanner } from '../shared/InstallBanner'

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
      style={{ minHeight: '100dvh', backgroundColor: '#0A0A0A' }}
    >
      {/* Fixed offline indicator — appears at the top of the viewport when offline (HUB-03) */}
      <OfflineIndicator />

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
        className="flex-1 min-w-0 overflow-y-auto"
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
    </div>
  )
}
