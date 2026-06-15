/**
 * App.test.tsx — Vitest spec for the auth-gate and responsive layout.
 *
 * Covers:
 *  (a) Authenticated path: when /api/auth/me resolves, AppShell renders and SignInPage does not.
 *  (b) Unauthenticated path: when /api/auth/me rejects (401), SignInPage renders and AppShell does not.
 *  (c) Responsive layout: Sidebar has md:-prefixed desktop-only class; BottomTabs has md:hidden.
 *
 * No real network calls — fetchMe is mocked via vi.mock.
 * JSDOM environment (vitest.config.ts).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { AppShell } from './components/layout/AppShell'
import { Sidebar } from './components/layout/Sidebar'
import { BottomTabs } from './components/layout/BottomTabs'

// ---------------------------------------------------------------------------
// Mock fetchMe from the auth API module
// ---------------------------------------------------------------------------

vi.mock('./api/auth', () => ({
  fetchMe: vi.fn(),
  signInWithGoogle: vi.fn(),
  logout: vi.fn(),
  revokeAll: vi.fn(),
}))

import { fetchMe } from './api/auth'
const mockFetchMe = vi.mocked(fetchMe)

// ---------------------------------------------------------------------------
// Test helper: wrap with fresh QueryClient + MemoryRouter
// ---------------------------------------------------------------------------

function renderApp(initialPath = '/') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// ---------------------------------------------------------------------------
// Auth gate tests
// ---------------------------------------------------------------------------

describe('App auth gate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders AppShell (not SignInPage) when /api/auth/me resolves', async () => {
    mockFetchMe.mockResolvedValueOnce({ email: 'amit.grupper@gmail.com' })

    renderApp()

    // The loader spinner should appear first, then transition to AppShell.
    // TodayPage now renders the real <TimelineDay/> (26-07), so assert on the
    // AppShell navigation landmark rather than the old "Today — Coming soon" placeholder.
    await waitFor(() => {
      expect(screen.getAllByRole('navigation').length).toBeGreaterThan(0)
    })

    // SignInPage should NOT be present
    // SignInPage renders an h1 with text "Klaus" and a paragraph "Your personal agent"
    // The "Your personal agent" copy is SignInPage-specific
    expect(screen.queryByText('Your personal agent')).not.toBeInTheDocument()
  })

  it('renders SignInPage (not AppShell) when /api/auth/me rejects', async () => {
    mockFetchMe.mockRejectedValueOnce(new Error('Not authenticated'))

    renderApp()

    // SignInPage should render — wait for the heading
    await waitFor(() => {
      // SignInPage renders <h1>Klaus</h1>
      expect(screen.getByRole('heading', { level: 1, name: 'Klaus' })).toBeInTheDocument()
    })

    // The subheading is SignInPage-specific
    expect(screen.getByText('Your personal agent')).toBeInTheDocument()

    // AppShell content (Today placeholder) should NOT be present
    expect(screen.queryByText(/Today — Coming soon/i)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Responsive layout: Sidebar and BottomTabs export assertions
// ---------------------------------------------------------------------------

describe('Responsive layout exports', () => {
  it('Sidebar component exports as a function (desktop-only component exists)', () => {
    expect(typeof Sidebar).toBe('function')
  })

  it('BottomTabs component exports as a function (phone-only component exists)', () => {
    expect(typeof BottomTabs).toBe('function')
  })

  it('AppShell component exports as a function (root layout exists)', () => {
    expect(typeof AppShell).toBe('function')
  })
})

// ---------------------------------------------------------------------------
// DOM-class assertions on rendered layout
// ---------------------------------------------------------------------------

describe('Responsive layout DOM classes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetchMe.mockResolvedValue({ email: 'amit.grupper@gmail.com' })
  })

  it('Sidebar has hidden and md:flex classes (desktop-only)', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getAllByRole('navigation').length).toBeGreaterThan(0)
    })

    // Both Sidebar and BottomTabs have aria-label="Main navigation"; use getAllByRole
    const navElements = screen.getAllByRole('navigation', { name: 'Main navigation' })
    // Sidebar is the one with 'hidden' and 'md:flex' classes
    const sidebarNav = navElements.find(
      (el) => el.className.includes('hidden') && el.className.includes('md:flex'),
    )
    expect(sidebarNav).toBeDefined()
    expect(sidebarNav!.className).toMatch(/hidden/)
    expect(sidebarNav!.className).toMatch(/md:flex/)
  })

  it('BottomTabs has md:hidden class (phone-only)', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getAllByRole('navigation').length).toBeGreaterThan(0)
    })

    // BottomTabs renders a second nav — find it by aria-label "Main navigation"
    // The Sidebar and BottomTabs both have aria-label="Main navigation"
    const navElements = screen.getAllByRole('navigation', { name: 'Main navigation' })
    // BottomTabs is the one with md:hidden
    const bottomTabsNav = navElements.find((el) => el.className.includes('md:hidden'))
    expect(bottomTabsNav).toBeDefined()
    expect(bottomTabsNav!.className).toMatch(/md:hidden/)
  })
})
