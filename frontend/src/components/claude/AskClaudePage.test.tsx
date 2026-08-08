import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom'
import { AskClaudePage } from './AskClaudePage'

vi.mock('../../api/agent', () => ({ fetchAgentStatus: vi.fn() }))

import { fetchAgentStatus } from '../../api/agent'

const mockFetchAgentStatus = vi.mocked(fetchAgentStatus)

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AskClaudePage />
    </QueryClientProvider>,
  )
}

describe('AskClaudePage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('launches the configured Klaus Claude Project in a new tab', async () => {
    mockFetchAgentStatus.mockResolvedValue({
      interface: 'claude_project',
      claude_project_url: 'https://claude.ai/project/klaus',
      ask_claude_configured: true,
      expected_skill_version: '7.0.0',
      capability_gate: {
        mcp_connector_verified: true,
        private_skill_verified: true,
        remote_routine_verified: true,
        routine_publish_verified: true,
        passed: true,
      },
      features: {},
      recent_runs: [],
      usage: { claude_subscription: {}, gemini_embeddings: {} },
    })
    renderPage()

    const link = await screen.findByRole('link', { name: /Open Klaus in Claude/i })
    expect(link).toHaveAttribute('href', 'https://claude.ai/project/klaus')
    expect(link).toHaveAttribute('target', '_blank')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('does not render embedded chat when project launch is unconfigured', async () => {
    mockFetchAgentStatus.mockResolvedValue({
      interface: 'claude_project',
      claude_project_url: null,
      ask_claude_configured: false,
      expected_skill_version: '7.0.0',
      capability_gate: {
        mcp_connector_verified: false,
        private_skill_verified: false,
        remote_routine_verified: false,
        routine_publish_verified: false,
        passed: false,
      },
      features: {},
      recent_runs: [],
      usage: { claude_subscription: {}, gemini_embeddings: {} },
    })
    renderPage()

    expect(await screen.findByText(/CLAUDE_PROJECT_URL/)).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})
