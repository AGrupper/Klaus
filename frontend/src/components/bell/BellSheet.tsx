/**
 * BellSheet.tsx — the notification center. Reviews · alerts · Klaus's
 * actions · system notices, grouped by day, every row deep-linked:
 *
 *  - review  → claude_session_url (exact session) or the Claude Project URL
 *  - alert   → close the sheet (the day view behind it is the target)
 *  - action  → no link; it's a record ("Klaus did")
 *  - system  → /settings (system health lives there), rendered dimmed
 *
 * All content renders as plain React text — never HTML (T-28-xss).
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ArrowUpRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { fetchAgentStatus } from '../../api/agent'
import type { BellItem } from '../../api/notifications'
import { Sheet } from '../shared/Sheet'

const KIND_STYLES: Record<BellItem['type'], { label: string; bg: string; color: string }> = {
  review: { label: 'Review', bg: 'color-mix(in srgb, var(--accent) 10%, var(--surface))', color: 'var(--accent)' },
  alert: { label: 'Alert', bg: 'var(--flame-soft)', color: 'var(--flame)' },
  action: { label: 'Klaus did', bg: 'var(--good-soft)', color: 'var(--good)' },
  system: { label: 'System', bg: 'var(--ground)', color: 'var(--muted)' },
}

const TIME_FORMAT = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Jerusalem',
})

function dayLabel(at: string): string {
  const day = at.slice(0, 10)
  const today = new Date().toISOString().slice(0, 10)
  const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)
  if (day === today) return 'Today'
  if (day === yesterday) return 'Yesterday'
  const parsed = new Date(`${day}T00:00:00`)
  return Number.isNaN(parsed.getTime())
    ? day
    : new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'short', day: 'numeric' }).format(parsed)
}

function timeLabel(at: string): string {
  const parsed = new Date(at)
  return Number.isNaN(parsed.getTime()) ? '' : TIME_FORMAT.format(parsed)
}

interface BellSheetProps {
  open: boolean
  onClose: () => void
  items: BellItem[]
  loading: boolean
}

export function BellSheet({ open, onClose, items, loading }: BellSheetProps) {
  const navigate = useNavigate()
  // Project URL fallback for fallback-published reviews without a session URL.
  const { data: agentStatus } = useQuery({
    queryKey: ['agent', 'status'],
    queryFn: fetchAgentStatus,
    staleTime: 10 * 60_000,
    enabled: open,
  })

  function reviewUrl(item: BellItem): string | null {
    return item.claude_session_url || agentStatus?.claude_project_url || null
  }

  // Group consecutive items by calendar day (items arrive newest-first).
  const groups: Array<{ label: string; items: BellItem[] }> = []
  for (const item of items) {
    const label = dayLabel(item.at)
    const last = groups[groups.length - 1]
    if (last && last.label === label) {
      last.items.push(item)
    } else {
      groups.push({ label, items: [item] })
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Bell" ariaLabel="Notifications">
      {loading && (
        <p style={{ color: 'var(--muted)', fontSize: '14px', padding: '12px 0' }}>Loading…</p>
      )}
      {!loading && items.length === 0 && (
        <p style={{ color: 'var(--muted)', fontSize: '14px', padding: '12px 0' }}>
          Nothing yet — reviews and alerts will land here.
        </p>
      )}
      {groups.map((group) => (
        <div key={group.label}>
          <div
            style={{
              fontSize: '11px',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--muted)',
              fontWeight: 600,
              margin: '12px 0 8px',
            }}
          >
            {group.label}
          </div>
          {group.items.map((item) => {
            const kind = KIND_STYLES[item.type]
            return (
              <div
                key={`${item.type}:${item.id}:${item.at}`}
                style={{
                  background: 'var(--surface)',
                  borderRadius: 'var(--r)',
                  padding: '12px 14px',
                  marginBottom: '8px',
                  opacity: item.type === 'system' ? 0.7 : 1,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                  <span
                    style={{
                      fontSize: '10.5px',
                      fontWeight: 700,
                      letterSpacing: '0.07em',
                      textTransform: 'uppercase',
                      borderRadius: '5px',
                      padding: '2px 7px',
                      background: kind.bg,
                      color: kind.color,
                    }}
                  >
                    {kind.label}
                  </span>
                  <span
                    style={{
                      marginLeft: 'auto',
                      fontSize: '12px',
                      color: 'var(--faint)',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {timeLabel(item.at)}
                  </span>
                </div>
                <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--ink)' }}>
                  {item.title}
                </div>
                {item.body && (
                  <div style={{ fontSize: '14px', lineHeight: 1.5, color: 'var(--muted)', marginTop: '4px' }}>
                    {item.body}
                  </div>
                )}

                {item.type === 'review' && reviewUrl(item) && (
                  <a
                    href={reviewUrl(item) ?? undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      marginTop: '8px',
                      fontSize: '13.5px',
                      fontWeight: 600,
                      color: 'var(--accent)',
                      textDecoration: 'none',
                    }}
                  >
                    Continue in Claude
                    <ArrowUpRight size={13} strokeWidth={2.2} aria-hidden="true" />
                  </a>
                )}
                {item.type === 'alert' && (
                  <button
                    onClick={() => {
                      onClose()
                      navigate('/')
                    }}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      marginTop: '8px',
                      fontSize: '13.5px',
                      fontWeight: 600,
                      color: 'var(--accent)',
                      border: 'none',
                      background: 'none',
                      padding: 0,
                      cursor: 'pointer',
                    }}
                  >
                    Open in Today
                    <ArrowRight size={13} strokeWidth={2.2} aria-hidden="true" />
                  </button>
                )}
                {item.type === 'system' && (
                  <button
                    onClick={() => {
                      onClose()
                      navigate('/settings')
                    }}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      marginTop: '8px',
                      fontSize: '13.5px',
                      fontWeight: 600,
                      color: 'var(--muted)',
                      border: 'none',
                      background: 'none',
                      padding: 0,
                      cursor: 'pointer',
                    }}
                  >
                    System status
                    <ArrowRight size={13} strokeWidth={2.2} aria-hidden="true" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </Sheet>
  )
}
