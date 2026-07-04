/**
 * settings.ts — Klaus Hub settings API client (PUSH-03/D-09).
 *
 * Backend endpoints (29-06):
 *   GET   /api/settings  -> HubSettings (jsonsafe)
 *   PATCH /api/settings  body { telegram_mirror_enabled: boolean } -> HubSettings
 *
 * Only `telegram_mirror_enabled` is ever sent in the PATCH body — the server
 * ignores any other key (T-29-12), but the client only exposes this one
 * field to keep the Settings page a deliberate skeleton (D-15).
 */
import { apiFetch } from './client'

/** Hub settings document shape returned by GET /api/settings. */
export interface HubSettings {
  telegram_mirror_enabled: boolean
  /** ISO timestamp of the first successful push subscribe, or null (D-14). */
  push_enabled_at: string | null
  [key: string]: unknown
}

/** Fetch the current hub settings. */
export async function fetchSettings(): Promise<HubSettings> {
  return apiFetch<HubSettings>('/api/settings')
}

/** Toggle the Telegram mirror flag. Returns the updated settings document. */
export async function patchSettings(input: { telegram_mirror_enabled: boolean }): Promise<HubSettings> {
  return apiFetch<HubSettings>('/api/settings', {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}
