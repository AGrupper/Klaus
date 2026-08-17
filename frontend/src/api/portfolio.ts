/**
 * portfolio.ts — weekly IBI valuation glance (off-by-default Home module).
 *
 * GET /api/portfolio → holdings + weekly ILS snapshots. The Home card only
 * needs the two most recent snapshots for total + week-over-week change.
 */
import { apiFetch } from './client'

export interface PortfolioSnapshot {
  total_ils?: number
  captured_at?: string
  [key: string]: unknown
}

export interface PortfolioData {
  holdings: Array<Record<string, unknown>>
  snapshots: PortfolioSnapshot[]
  last_valid_valuation: PortfolioSnapshot | null
}

export async function fetchPortfolio(): Promise<PortfolioData> {
  return apiFetch<PortfolioData>('/api/portfolio?snapshot_limit=2')
}
