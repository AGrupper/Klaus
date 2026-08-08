import { useQuery } from '@tanstack/react-query'
import { ExternalLink, MessageCircle } from 'lucide-react'
import { fetchAgentStatus } from '../../api/agent'

export function ClaudeLaunchPanel() {
  const { data } = useQuery({
    queryKey: ['agent', 'status'],
    queryFn: fetchAgentStatus,
  })
  const href = data?.claude_project_url ?? undefined

  return (
    <aside
      className="hidden md:flex"
      aria-label="Ask Claude"
      style={{
        width: '240px',
        flexShrink: 0,
        borderLeft: '1px solid #2A2A2A',
        backgroundColor: '#111111',
        padding: '20px 16px',
        flexDirection: 'column',
        gap: '12px',
      }}
    >
      <MessageCircle size={22} color="#6366F1" aria-hidden="true" />
      <strong style={{ color: '#F9FAFB', fontSize: '16px' }}>Ask Claude</strong>
      <p style={{ color: '#9CA3AF', fontSize: '13px', lineHeight: 1.5, margin: 0 }}>
        Open the Klaus Project for conversation and actions. Your Hub data stays authoritative.
      </p>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            marginTop: '4px',
            minHeight: '44px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            borderRadius: '8px',
            backgroundColor: '#6366F1',
            color: '#FFFFFF',
            textDecoration: 'none',
            fontSize: '14px',
            fontWeight: 600,
          }}
        >
          Open Claude
          <ExternalLink size={16} aria-hidden="true" />
        </a>
      ) : (
        <span style={{ color: '#6B7280', fontSize: '12px' }}>Project URL not configured</span>
      )}
    </aside>
  )
}
