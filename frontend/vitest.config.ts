import { defineConfig } from 'vitest/config'
import path from 'node:path'

// Separate vitest config (no React plugin) to avoid vite version type conflicts
// between vite@8 (main bundle) and vitest's internal vite copy
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // vite-plugin-pwa's virtual module only exists with the plugin (real
      // builds/dev). vitest has no plugin, so point it at a stub.
      'virtual:pwa-register/react': path.resolve(
        __dirname,
        './src/test/pwa-register-stub.ts',
      ),
    },
  },
})
