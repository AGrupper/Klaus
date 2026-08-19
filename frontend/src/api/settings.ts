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
  /** Legacy read cursor. Read-only now — kept as a floor so upgrading does
   *  not resurrect already-read history. Superseded by `bell_read_ids`. */
  bell_last_seen: string | null
  /** Keys of bell items already read, account-level so reading on the phone
   *  also clears the dot on the Mac. See api/notifications.ts `itemKey`. */
  bell_read_ids: string[]
}

/** The subset of settings the Hub is allowed to write. */
export type SettingsPatch = Partial<
  Pick<HubSettings, 'appearance' | 'home_sections' | 'bell_last_seen' | 'bell_read_ids'>
>

export async function fetchSettings(): Promise<HubSettings> {
  return apiFetch<HubSettings>('/api/settings')
}

export async function patchSettings(
  patch: SettingsPatch,
): Promise<HubSettings> {
  return apiFetch<HubSettings>('/api/settings', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}
