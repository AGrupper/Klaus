import { apiFetch } from './client'

export interface CapabilityGate {
  mcp_connector_verified: boolean
  private_skill_verified: boolean
  remote_routine_verified: boolean
  routine_publish_verified: boolean
  passed: boolean
}

export interface AgentStatus {
  interface: 'claude_project'
  claude_project_url: string | null
  ask_claude_configured: boolean
  expected_skill_version: string
  capability_gate: CapabilityGate
  features: Record<string, boolean>
  recent_runs: Array<Record<string, unknown>>
  usage: {
    claude_subscription: Record<string, unknown>
    gemini_embeddings: Record<string, unknown>
  }
}

export async function fetchAgentStatus(): Promise<AgentStatus> {
  return apiFetch<AgentStatus>('/api/agent/status')
}
