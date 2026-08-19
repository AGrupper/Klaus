/**
 * useSettings write-path tests — the colour-picker race Amit hit in UAT
 * ("I choose a colour, exit, and it keeps the one I picked earlier").
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as settingsApi from '../api/settings'
import { useUpdateSettings } from './useSettings'

let queryClient: QueryClient

function wrapper({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: queryClient }, children)
}

const APPEARANCE = { accent: '#1C2540', flame: '#B02A2A', font: 'default' as const }

function settingsWith(accent: string): settingsApi.HubSettings {
  return {
    push_enabled_at: null,
    appearance: { ...APPEARANCE, accent },
    home_sections: { leaveby: true, stats: true, corner: true, portfolio: false },
    bell_last_seen: null,
    bell_read_ids: [],
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useUpdateSettings', () => {
  it('debounces a drag into a single write carrying the final value', async () => {
    const patchSpy = vi
      .spyOn(settingsApi, 'patchSettings')
      .mockImplementation(async (patch) => settingsWith(
        (patch.appearance?.accent as string) ?? '#1C2540',
      ))

    const { result } = renderHook(() => useUpdateSettings(), { wrapper })

    // Simulate the colour picker firing on every drag frame.
    act(() => {
      result.current.save({ appearance: { ...APPEARANCE, accent: '#111111' } })
      result.current.save({ appearance: { ...APPEARANCE, accent: '#222222' } })
      result.current.save({ appearance: { ...APPEARANCE, accent: '#333333' } })
    })
    expect(patchSpy).not.toHaveBeenCalled()

    await act(async () => {
      vi.advanceTimersByTime(400)
    })

    expect(patchSpy).toHaveBeenCalledTimes(1)
    expect(patchSpy.mock.calls[0][0].appearance?.accent).toBe('#333333')
  })

  it('flush() commits immediately, so closing the sheet cannot lose a value', async () => {
    const patchSpy = vi
      .spyOn(settingsApi, 'patchSettings')
      .mockResolvedValue(settingsWith('#444444'))

    const { result } = renderHook(() => useUpdateSettings(), { wrapper })

    act(() => {
      result.current.save({ appearance: { ...APPEARANCE, accent: '#444444' } })
    })
    await act(async () => {
      result.current.flush()
    })

    expect(patchSpy).toHaveBeenCalledTimes(1)
    expect(patchSpy.mock.calls[0][0].appearance?.accent).toBe('#444444')
  })

  it('ignores a stale response so the newest choice wins the cache', async () => {
    // The old bug: an earlier (slow) write could resolve last and overwrite a
    // newer colour. Here request #1 is held open while request #2 completes.
    let resolveSlow: ((value: settingsApi.HubSettings) => void) = () => {}
    vi.spyOn(settingsApi, 'patchSettings')
      .mockImplementationOnce(
        () => new Promise<settingsApi.HubSettings>((resolve) => {
          resolveSlow = resolve
        }),
      )
      .mockImplementationOnce(async () => settingsWith('#BBBBBB'))

    const { result } = renderHook(() => useUpdateSettings(), { wrapper })

    act(() => {
      result.current.save({ appearance: { ...APPEARANCE, accent: '#AAAAAA' } })
      result.current.flush()
    })
    act(() => {
      result.current.save({ appearance: { ...APPEARANCE, accent: '#BBBBBB' } })
    })
    await act(async () => {
      result.current.flush()
      await Promise.resolve()
    })

    // The newer write has landed in the cache.
    expect(
      queryClient.getQueryData<settingsApi.HubSettings>(['settings'])?.appearance.accent,
    ).toBe('#BBBBBB')

    // Now the stale first response arrives — it must NOT clobber the cache.
    await act(async () => {
      resolveSlow(settingsWith('#AAAAAA'))
      await Promise.resolve()
    })

    expect(
      queryClient.getQueryData<settingsApi.HubSettings>(['settings'])?.appearance.accent,
    ).toBe('#BBBBBB')
  })
})
