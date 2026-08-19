/**
 * BellSheet.tsx — the notification center. Reviews · alerts · Klaus's
 * actions · system notices, grouped by day, every row deep-linked:
 *
 *  - review  → claude_session_url (exact session) or the Claude Project URL
 *  - alert   → close the sheet (the day view behind it is the target)
 *  - action  → no link; it's a record ("Klaus did")
 *  - system  → /settings (system health lives there), rendered dimmed
 *
 * Read marking (Amit, 2026-08-19: "it doesn't automatically mark what I
 * interact with as read... I'd like it to mark the things I can see in my
 * direct vicinity"). A row marks itself read the moment half of it is on
 * screen — no dwell — via one IntersectionObserver shared by every row, and
 * tapping a row's action marks it too. Unread rows carry an accent dot that
 * fades as they are marked, so the clearing is visible rather than silent.
 *
 * All content renders as plain React text — never HTML (T-28-xss).
 */
import { useCallback, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ArrowUpRight, CheckCheck } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { fetchAgentStatus } from '../../api/agent'
import { claudeAppUrl } from '../../utils/claudeLink'
import { itemKey, type BellItem } from '../../api/notifications'
import { useNotifications } from '../../hooks/useNotifications'
import { Sheet } from '../shared/Sheet'

/** Fraction of a row that must be on screen before it counts as seen. */
const SEEN_THRESHOLD = 0.5

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
  const { markRead, markAllRead, dismissOne, unread, unreadKeys } = useNotifications()
  const unreadSet = new Set(unreadKeys)

  // Project URL fallback for fallback-published reviews without a session URL.
  const { data: agentStatus } = useQuery({
    queryKey: ['agent', 'status'],
    queryFn: fetchAgentStatus,
    staleTime: 10 * 60_000,
    enabled: open,
  })

  // --- viewport read-marking -----------------------------------------------
  // markRead's identity churns (it depends on the settings mutation), so it is
  // held in a ref: the observer is built once per open, not per keystroke of
  // React state, and rows keep their subscription across re-renders.
  const markReadRef = useRef(markRead)
  markReadRef.current = markRead
  const byKey = useRef(new Map<string, BellItem>())
  byKey.current = new Map(items.map((item) => [itemKey(item), item]))

  const observer = useRef<IntersectionObserver | null>(null)
  const rows = useRef(new Set<Element>())

  useEffect(() => {
    if (!open || typeof IntersectionObserver === 'undefined') return
    const created = new IntersectionObserver(
      (entries) => {
        const seen = entries
          .filter((entry) => entry.isIntersecting)
          .map((entry) => byKey.current.get((entry.target as HTMLElement).dataset.key ?? ''))
          .filter((item): item is BellItem => item !== undefined)
        if (seen.length > 0) markReadRef.current(seen)
      },
      { threshold: SEEN_THRESHOLD },
    )
    observer.current = created
    // Rows that mounted before this effect ran still need observing.
    rows.current.forEach((node) => created.observe(node))
    return () => {
      created.disconnect()
      observer.current = null
    }
  }, [open])

  // Stable ref callback (React 19 cleanup form) so rows attach exactly once.
  const registerRow = useCallback((node: HTMLDivElement) => {
    rows.current.add(node)
    observer.current?.observe(node)
    return () => {
      rows.current.delete(node)
      observer.current?.unobserve(node)
    }
  }, [])

  function reviewUrl(item: BellItem): string | null {
    return item.claude_session_url || claudeAppUrl(agentStatus?.claude_project_url) || null
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
      {!loading && items.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '2px' }}>
          <button
            onClick={markAllRead}
            disabled={unread === 0}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              border: 'none',
              background: 'none',
              padding: '4px 0',
              fontSize: '13px',
              fontWeight: 600,
              color: unread > 0 ? 'var(--accent)' : 'var(--faint)',
              cursor: unread > 0 ? 'pointer' : 'default',
            }}
          >
            <CheckCheck size={14} strokeWidth={2.2} aria-hidden="true" />
            Mark all read
          </button>
        </div>
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
            const key = itemKey(item)
            const isUnread = unreadSet.has(key)
            return (
              <div
                key={key}
                ref={registerRow}
                data-key={key}
                data-testid={`bell-row-${key}`}
                data-unread={isUnread ? 'true' : 'false'}
                style={{
                  background: isUnread
                    ? 'color-mix(in srgb, var(--accent) 6%, var(--surface))'
                    : 'var(--surface)',
                  borderRadius: 'var(--r)',
                  padding: '12px 14px',
                  marginBottom: '8px',
                  opacity: item.type === 'system' ? 0.7 : 1,
                  transition: 'background 260ms ease',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                  <span
                    aria-label={isUnread ? 'Unread' : undefined}
                    style={{
                      width: '7px',
                      height: '7px',
                      borderRadius: '50%',
                      flex: '0 0 auto',
                      background: 'var(--accent)',
                      opacity: isUnread ? 1 : 0,
                      // Collapse the gap once it fades, so read rows sit flush.
                      marginRight: isUnread ? 0 : '-15px',
                      transition: 'opacity 260ms ease, margin-right 260ms ease',
                    }}
                  />
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
                    onClick={() => dismissOne(item)}
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
                      dismissOne(item)
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
                      dismissOne(item)
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
