import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      // Prompt-mode: a new deploy surfaces a "New version available → Refresh"
      // banner (UpdatePrompt.tsx) instead of silently swapping in on some later
      // load. injectRegister:false because UpdatePrompt's useRegisterSW hook
      // owns registration (avoids a double-register with the auto-injected script).
      registerType: 'prompt',
      injectRegister: false,
      // injectManifest: the SW is hand-written (src/sw.ts) so it can carry the
      // push + notificationclick handlers (PUSH-02/04) alongside the same
      // precache + per-route caching behavior the previous auto-generated
      // strategy used to produce.
      // NOTE: per-route caching config in this plugin block is IGNORED under
      // injectManifest — those routes are registered directly in src/sw.ts.
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectManifest: {
        // Precache all build outputs (hashed JS/CSS/HTML/icons) — moved here
        // from the deleted plugin-level workbox config block (same value).
        globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest}'],
      },
      manifest: {
        name: 'Klaus',
        short_name: 'Klaus',
        description: 'Your personal AI agent',
        theme_color: '#000000',
        background_color: '#000000',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      // iOS apple-touch-icon is in index.html head, not in the manifest
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
