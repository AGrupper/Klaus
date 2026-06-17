/**
 * Test stub for vite-plugin-pwa's `virtual:pwa-register/react` module.
 *
 * The virtual module only exists when the PWA plugin runs (real builds / dev).
 * vitest has no plugin, so vitest.config.ts aliases the virtual import here.
 * The stub reports "no update needed" so UpdatePrompt renders nothing in tests.
 */
export function useRegisterSW() {
  return {
    needRefresh: [false, () => {}] as [boolean, (value: boolean) => void],
    offlineReady: [false, () => {}] as [boolean, (value: boolean) => void],
    updateServiceWorker: async (_reloadPage?: boolean) => {},
  }
}
