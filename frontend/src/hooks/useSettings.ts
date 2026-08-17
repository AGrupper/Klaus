/**
 * useSettings — account-wide Hub settings with live theme application.
 *
 * On every successful load, applyAppearance() pushes accent/flame/font into
 * the CSS custom properties, so the theme follows the account across devices.
 * useUpdateSettings PATCHes a section whole (the sheet always sends full
 * state) with an optimistic cache update — the sheet already previews live
 * via applyAppearance, so the network write is fire-and-confirm.
 */
import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchSettings, patchSettings, type HubSettings } from '../api/settings'
import { applyAppearance, defaultAppearance } from '../tokens'

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
  return useMutation({
    mutationFn: patchSettings,
    onMutate: async (patch) => {
      const previous = queryClient.getQueryData<HubSettings>(['settings'])
      if (previous) {
        queryClient.setQueryData<HubSettings>(['settings'], { ...previous, ...patch })
      }
      return { previous }
    },
    onError: (_err, _patch, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['settings'], context.previous)
        applyAppearance(context.previous.appearance)
      }
    },
    onSuccess: (settings) => {
      queryClient.setQueryData(['settings'], settings)
    },
  })
}
