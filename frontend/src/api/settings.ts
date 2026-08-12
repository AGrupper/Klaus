/**
 * settings.ts — Klaus Hub settings API client (PUSH-03/D-09).
 *
 * Backend endpoint: GET /api/settings -> HubSettings (jsonsafe).
 */
import { apiFetch } from './client'

/** Hub settings document shape returned by GET /api/settings. */
export interface HubSettings {
  /** ISO timestamp of the first successful push subscribe, or null (D-14). */
  push_enabled_at: string | null
  [key: string]: unknown
}

/** Fetch the current hub settings. */
export async function fetchSettings(): Promise<HubSettings> {
  return apiFetch<HubSettings>('/api/settings')
}
