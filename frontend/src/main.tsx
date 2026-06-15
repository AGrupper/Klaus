/**
 * main.tsx — Application entry point.
 *
 * Mounts the React tree with:
 *  - QueryClientProvider  (@tanstack/react-query v5) — server state, polling, optimistic mutations
 *  - BrowserRouter        (react-router-dom v7) — client-side routing
 *  - App                  — route guard + layout
 *
 * RESEARCH.md Pattern 5: one QueryClient instance per app, never per component.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000, // 30s default stale time
    },
  },
})

const rootEl = document.getElementById('root')
if (!rootEl) throw new Error('Root element #root not found')

createRoot(rootEl).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
