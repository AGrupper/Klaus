/**
 * settings.ts — Hub settings client (push state + Paper Hub customization).
 *
 * GET  /api/settings              → HubSettings
 * PATCH /api/settings             → HubSettings (sections sent whole)
 *
 * `appearance` and `home_sections` are account-wide: the Customize sheet
 * PATCHes here so iPhone and Mac always match.
 */
import { apiFetch } from './client'
import type { Appearance } from '../tokens'

export interface HomeSections {
  leaveby: boolean
  stats: boolean
  corner: boolean
  portfolio: boolean
}

export interface HubSettings {
  /** ISO timestamp of the first successful push subscribe, or null (D-14). */
  push_enabled_at: string | null
  appearance: Appearance
  home_sections: HomeSections
}

export async function fetchSettings(): Promise<HubSettings> {
  return apiFetch<HubSettings>('/api/settings')
}

export async function patchSettings(
  patch: Partial<Pick<HubSettings, 'appearance' | 'home_sections'>>,
): Promise<HubSettings> {
  return apiFetch<HubSettings>('/api/settings', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}
