/**
 * HealthPage.tsx — Root /health route component (HLTH-01, HLTH-02, HLTH-03).
 *
 * Renders SubTabs at the top of the standard center column and, below it,
 * exactly one of TrainingHistoryPage / NutritionDetailPage / SleepRecoveryPage
 * based on the active tab (D-01/D-02). Tab switching is pure client state — no
 * route change — and SubTabs owns the localStorage['health-tab'] persistence;
 * HealthPage just consumes the active value via SubTabs' onChange (fired once
 * on mount with the restored/default value, and again on each change). First
 * visit defaults to Training.
 *
 * Layout (D-03): Health renders inside the SAME center column as Today/Tasks —
 * no full-width exception. The 16px content padding matches TasksPage; the
 * app-shell (sidebar + glance rail + docked chat) is untouched.
 */
import { useState } from 'react'
import { SubTabs } from './SubTabs'
import type { HealthTab } from './SubTabs'
import { TrainingHistoryPage } from './training/TrainingHistoryPage'
import { NutritionDetailPage } from './nutrition/NutritionDetailPage'
import { SleepRecoveryPage } from './sleep/SleepRecoveryPage'

export function HealthPage() {
  const [tab, setTab] = useState<HealthTab>('training')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '16px' }}>
      <SubTabs onChange={setTab} />
      {tab === 'training' && <TrainingHistoryPage />}
      {tab === 'nutrition' && <NutritionDetailPage />}
      {tab === 'sleep' && <SleepRecoveryPage />}
    </div>
  )
}
