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
      strategies: 'generateSW',
      workbox: {
        // Precache all build outputs (hashed JS/CSS/HTML/icons)
        globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest}'],
        // index.html: network-first so a new deploy is never blocked by stale cache
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.destination === 'document',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'html-cache',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 5, maxAgeSeconds: 60 * 60 * 24 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          // Hashed assets (JS/CSS bundles) — cache-first, long TTL
          {
            urlPattern: /\/assets\/.+\.(js|css)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'assets-cache',
              expiration: { maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
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
