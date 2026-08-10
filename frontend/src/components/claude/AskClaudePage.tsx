import { useQuery } from '@tanstack/react-query'
import { ExternalLink, ShieldCheck } from 'lucide-react'
import { fetchAgentStatus } from '../../api/agent'
import { ReviewInbox } from './ReviewInbox'
import {
  accent,
  border,
  dominant,
  fontFamily,
  secondary,
  textPrimary,
  textSecondary,
  typography,
} from '../../tokens'

export function AskClaudePage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['agent', 'status'],
    queryFn: fetchAgentStatus,
  })

  const configured = Boolean(data?.ask_claude_configured && data.claude_project_url)

  return (
    <div
      style={{
        flex: 1,
        minHeight: '100%',
        padding: '32px 20px 96px',
        backgroundColor: dominant,
        color: textPrimary,
        fontFamily,
      }}
    >
      <div style={{ maxWidth: '620px', margin: '0 auto' }}>
        <p
          style={{
            margin: '0 0 8px',
            color: accent,
            fontSize: typography.label.fontSize,
            fontWeight: 600,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
          }}
        >
          Klaus · Claude Project
        </p>
        <h1
          style={{
            margin: 0,
            fontSize: '32px',
            lineHeight: 1.15,
            fontWeight: 600,
          }}
        >
          Ask Claude
        </h1>
        <p style={{ color: textSecondary, lineHeight: 1.6, margin: '14px 0 28px' }}>
          Claude is the conversation surface. Klaus remains the authoritative home for your
          calendar, tasks, habits, health, memory, reviews, and actions.
        </p>

        <section
          style={{
            padding: '20px',
            backgroundColor: secondary,
            border: `1px solid ${border}`,
            borderRadius: '12px',
          }}
          aria-label="Claude connection"
        >
          {isLoading ? (
            <p style={{ margin: 0, color: textSecondary }}>Checking the Claude connection…</p>
          ) : isError ? (
            <p style={{ margin: 0, color: '#FCA5A5' }}>Klaus could not load the Claude launch configuration.</p>
          ) : configured ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
                <ShieldCheck size={20} color={data?.capability_gate.passed ? '#34D399' : '#FBBF24'} />
                <span style={{ color: textSecondary, fontSize: typography.label.fontSize }}>
                  {data?.capability_gate.passed
                    ? `Connector ready · skill ${data.expected_skill_version}`
                    : 'Launch configured · capability proof still pending'}
                </span>
              </div>
              <a
                href={data?.claude_project_url ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  minHeight: '48px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '10px',
                  padding: '0 18px',
                  borderRadius: '9px',
                  backgroundColor: accent,
                  color: '#FFFFFF',
                  textDecoration: 'none',
                  fontWeight: 600,
                }}
              >
                Open Klaus in Claude
                <ExternalLink size={18} aria-hidden="true" />
              </a>
            </>
          ) : (
            <p style={{ margin: 0, color: textSecondary, lineHeight: 1.55 }}>
              Add <code>CLAUDE_PROJECT_URL</code> after creating the private Klaus Project.
              Embedded Hub chat stays unavailable during the subscription capability gate.
            </p>
          )}
        </section>
        <ReviewInbox />
      </div>
    </div>
  )
}
