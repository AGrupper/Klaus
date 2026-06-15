import { defineConfig } from 'vitest/config'
import path from 'node:path'

// Separate vitest config (no React plugin) to avoid vite version type conflicts
// between vite@8 (main bundle) and vitest's internal vite copy
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
