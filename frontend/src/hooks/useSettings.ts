/**
 * useSettings — account-wide Hub settings with live theme application.
 *
 * On every successful load, applyAppearance() pushes accent/flame/font into
 * the CSS custom properties, so the theme follows the account across devices.
 *
 * Write path (fixed after Amit's 2026-08-17 UAT: "I choose a colour, exit,
 * and it kept the one I picked earlier"). A native colour input emits a
 * change per drag frame, so the old code fired a PATCH per event and the
 * responses raced — an early value could land last and win. Now:
 *   - the CSS variables update instantly (preview never lags the finger),
 *   - the network write is debounced to the last value,
 *   - each write carries a sequence number and a stale response is ignored,
 *     so the newest choice always wins the cache.
 */
import { useCallback, useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchSettings, patchSettings, type HubSettings } from '../api/settings'
import { applyAppearance, defaultAppearance } from '../tokens'

/** Trailing debounce for appearance writes — long enough to swallow a drag. */
const WRITE_DEBOUNCE_MS = 350

export const defaultHomeSections = {
  leaveby: true,
  stats: true,
  corner: true,
  portfolio: false,
}

export function useSettings() {
  const query = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
    staleTime: 5 * 60_000,
  })

  const appearance = query.data?.appearance ?? defaultAppearance
  const homeSections = query.data?.home_sections ?? defaultHomeSections

  // Apply the account theme whenever it (re)loads.
  useEffect(() => {
    if (query.data?.appearance) {
      applyAppearance(query.data.appearance)
    }
  }, [query.data?.appearance])

  return { ...query, appearance, homeSections }
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  // Monotonic id per issued write; responses older than `latest` are dropped.
  const issued = useRef(0)
  const latest = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const queued = useRef<Partial<Pick<HubSettings, 'appearance' | 'home_sections'>> | null>(null)

  const mutation = useMutation({
    mutationFn: async (patch: Partial<Pick<HubSettings, 'appearance' | 'home_sections'>>) => {
      const sequence = ++issued.current
      const settings = await patchSettings(patch)
      return { settings, sequence }
    },
    onSuccess: ({ settings, sequence }) => {
      if (sequence < latest.current) return // a newer write already landed
      latest.current = sequence
      queryClient.setQueryData(['settings'], settings)
    },
    onError: () => {
      // Re-read the server's truth rather than guessing which write survived.
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  const flush = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
    const patch = queued.current
    queued.current = null
    if (patch) mutation.mutate(patch)
  }, [mutation])

  /**
   * Update the local cache immediately, then write once the value settles.
   * Callers that also want a live CSS preview call applyAppearance themselves
   * (the sheet does) — this keeps the query cache and the network in step.
   */
  const save = useCallback(
    (patch: Partial<Pick<HubSettings, 'appearance' | 'home_sections'>>) => {
      const previous = queryClient.getQueryData<HubSettings>(['settings'])
      if (previous) {
        queryClient.setQueryData<HubSettings>(['settings'], { ...previous, ...patch })
      }
      queued.current = { ...(queued.current ?? {}), ...patch }
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(flush, WRITE_DEBOUNCE_MS)
    },
    [flush, queryClient],
  )

  // Never lose a pending write because the sheet closed or the app unmounted.
  useEffect(() => () => {
    if (timer.current) {
      clearTimeout(timer.current)
      const patch = queued.current
      queued.current = null
      if (patch) mutation.mutate(patch)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { save, flush, isPending: mutation.isPending }
}
