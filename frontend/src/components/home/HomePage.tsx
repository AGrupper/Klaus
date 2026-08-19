/**
 * HomePage.tsx — the day at a glance: greeting, Talk to Klaus, leave-by hero,
 * today's timeline, morning numbers, Klaus's corner, optional portfolio.
 *
 * Section visibility is account-driven (home_sections via useSettings) — the
 * Customize sheet is the only writer. Null fields from /api/today are D-06
 * "not yet available" states, not errors.
 *
 * TIME-03 invariant: meal slot labels are canonical names, never eating
 * times; meals render as a totals row, not timed entries.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Clock, PenTool } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { fetchAgentStatus } from '../../api/agent'
import { fetchPortfolio } from '../../api/portfolio'
import type { TimedEvent, TodayData } from '../../api/today'
import { useFollowups, useNotifications } from '../../hooks/useNotifications'
import { useRoutines } from '../../hooks/useRoutines'
import { useSettings } from '../../hooks/useSettings'
import { useToday } from '../../hooks/useToday'
import { PushEnableBanner } from '../shared/PushEnableBanner'

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

const TIME_FORMAT = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Jerusalem',
})

function timeOf(iso: string): string {
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? '' : TIME_FORMAT.format(parsed)
}

function sleepLabel(hours: number | null): string | null {
  if (hours == null) return null
  const h = Math.floor(hours)
  const m = Math.round((hours - h) * 60)
  return `${h}:${String(m).padStart(2, '0')}`
}

function greetingFor(hour: number): string {
  if (hour < 5) return 'Up late, Sir.'
  if (hour < 12) return 'Good morning, Sir.'
  if (hour < 18) return 'Good afternoon, Sir.'
  return 'Good evening, Sir.'
}

// ---------------------------------------------------------------------------
// Section shells
// ---------------------------------------------------------------------------

function Section({
  label,
  children,
  step = 0,
}: {
  label: string
  children: React.ReactNode
  step?: number
}) {
  return (
    <div className={`rise${step ? ` rise-${step}` : ''}`} style={{ margin: '4px 20px 18px' }}>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: '18px',
          fontWeight: 700,
          letterSpacing: '-0.02em',
          marginBottom: '8px',
          color: 'var(--ink)',
        }}
      >
        {label}
      </div>
      {children}
    </div>
  )
}

function Group({ children }: { children: React.ReactNode }) {
  return <div style={{ background: 'var(--surface)', borderRadius: 'var(--r)' }}>{children}</div>
}

// ---------------------------------------------------------------------------
// Talk to Klaus
// ---------------------------------------------------------------------------

function KlausCta() {
  const { data } = useQuery({
    queryKey: ['agent', 'status'],
    queryFn: fetchAgentStatus,
    staleTime: 10 * 60_000,
  })
  const url = data?.claude_project_url
  return (
    <a
      href={url ?? undefined}
      target="_blank"
      rel="noopener noreferrer"
      aria-disabled={!url}
      className="press rise"
      style={{
        margin: '0 20px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        borderRadius: 'var(--r)',
        background: 'var(--accent)',
        color: 'var(--accent-ink)',
        padding: '13px 16px',
        textDecoration: 'none',
        opacity: url ? 1 : 0.55,
        pointerEvents: url ? 'auto' : 'none',
      }}
    >
      <span
        style={{
          width: '36px',
          height: '36px',
          borderRadius: '10px',
          flexShrink: 0,
          background: 'rgba(255,255,255,0.16)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <PenTool size={19} strokeWidth={1.7} aria-hidden="true" />
      </span>
      <span>
        <span style={{ display: 'block', fontSize: '16px', fontWeight: 600 }}>Talk to Klaus</span>
        <span style={{ display: 'block', fontSize: '12.5px', opacity: 0.72, marginTop: '1px' }}>
          Dump a thought — he'll file it
        </span>
      </span>
      <ArrowRight size={17} strokeWidth={2} style={{ marginLeft: 'auto', opacity: 0.7 }} aria-hidden="true" />
    </a>
  )
}

// ---------------------------------------------------------------------------
// Leave-by hero
// ---------------------------------------------------------------------------

function nextDeparture(events: TimedEvent[], now: Date): { event: TimedEvent; minutes: number } | null {
  for (const event of events) {
    if (!event.leave_by) continue
    const leaveBy = new Date(event.leave_by)
    if (Number.isNaN(leaveBy.getTime())) continue
    const minutes = Math.round((leaveBy.getTime() - now.getTime()) / 60_000)
    if (minutes >= 0 && minutes <= 120) return { event, minutes }
  }
  return null
}

function LeaveByHero({ events }: { events: TimedEvent[] }) {
  // Re-evaluate every 30s so the countdown stays honest while the app is open.
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(id)
  }, [])

  const departure = nextDeparture(events, now)
  if (!departure) return null
  const { event, minutes } = departure

  return (
    <div
      style={{
        margin: '0 20px 16px',
        borderRadius: 'var(--r)',
        background: 'var(--surface)',
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
      }}
    >
      <Clock size={20} strokeWidth={1.9} color="var(--flame)" style={{ flexShrink: 0 }} aria-hidden="true" />
      <span>
        <span style={{ display: 'block', fontSize: '14.5px', fontWeight: 600, color: 'var(--ink)' }}>
          Leave for {event.title}
        </span>
        <span style={{ display: 'block', fontSize: '12.5px', color: 'var(--muted)', marginTop: '1px' }}>
          {event.leave_by ? `${timeOf(event.leave_by)} · ` : ''}starts {timeOf(event.start)}
        </span>
      </span>
      <span
        style={{
          marginLeft: 'auto',
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          fontSize: '22px',
          color: 'var(--flame)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {minutes === 0 ? 'now' : `${minutes} min`}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

function Row({
  time,
  dot,
  title,
  sub,
  dimmed,
  first,
}: {
  time: string
  dot: string
  title: string
  sub: string | null
  dimmed?: boolean
  first?: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '11px 14px',
        borderTop: first ? 'none' : '1px solid var(--sep)',
        opacity: dimmed ? 0.45 : 1,
      }}
    >
      <span
        style={{
          width: '44px',
          flexShrink: 0,
          fontSize: '13px',
          color: 'var(--muted)',
          fontVariantNumeric: 'tabular-nums',
          fontWeight: 600,
        }}
      >
        {time}
      </span>
      <span style={{ width: '7px', height: '7px', borderRadius: '50%', flexShrink: 0, background: dot }} aria-hidden="true" />
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: 'block', fontSize: '15px', fontWeight: 600, color: 'var(--ink)' }}>{title}</span>
        {sub && (
          <span style={{ display: 'block', fontSize: '12.5px', color: 'var(--muted)', marginTop: '1px' }}>{sub}</span>
        )}
      </span>
    </div>
  )
}

function Timeline({ today }: { today: TodayData }) {
  const navigate = useNavigate()
  const { data: routines = [] } = useRoutines()
  const now = new Date()

  const totals = today.nutrition_totals
  const mealsCount = today.meals.length

  // Written-at stamp for the coach note. Guarded against an unparseable value so a
  // malformed timestamp degrades to an unstamped note, never a blank Today view.
  const coachNoteAt = (() => {
    if (!today.coach_note_at) return null
    const parsed = new Date(today.coach_note_at)
    if (Number.isNaN(parsed.getTime())) return null
    return new Intl.DateTimeFormat('en-GB', {
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Jerusalem',
    }).format(parsed)
  })()

  /**
   * Every row carries a sort key in minutes-from-midnight so the day reads in
   * real order. Routines sort by their anchor_time — that's what puts the
   * morning routine above a 10:00 meeting instead of at the bottom of the day
   * (Amit's UAT: "the morning routine should be the first thing in the day").
   * Rows with no natural time (all-day events, meal totals) get sentinels that
   * pin them to the top and bottom respectively.
   */
  const TOP = -1
  const BOTTOM = 24 * 60 + 1

  function minutesOf(iso: string): number {
    const parsed = new Date(iso)
    if (Number.isNaN(parsed.getTime())) return BOTTOM
    const hhmm = new Intl.DateTimeFormat('en-GB', {
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Jerusalem',
    }).format(parsed)
    const [h, m] = hhmm.split(':').map(Number)
    return h * 60 + m
  }

  function minutesOfClock(hhmm: string): number {
    const [h, m] = hhmm.split(':').map(Number)
    return Number.isNaN(h) || Number.isNaN(m) ? BOTTOM : h * 60 + m
  }

  type Row = {
    key: string
    sort: number
    time: string
    dot: string
    title: string
    sub: string | null
    dimmed?: boolean
    onClick?: () => void
  }

  const rows: Row[] = []

  for (const title of today.calendar.all_day) {
    rows.push({ key: `allday-${title}`, sort: TOP, time: 'All day', dot: 'var(--faint)', title, sub: null })
  }

  for (const event of today.calendar.timed) {
    const past = new Date(event.end).getTime() < now.getTime()
    rows.push({
      key: event.id,
      sort: minutesOf(event.start),
      time: timeOf(event.start),
      dot: past ? 'var(--faint)' : 'var(--accent)',
      title: event.title,
      sub: event.leave_by ? `leave by ${timeOf(event.leave_by)}` : (event.location ?? null),
      dimmed: past,
    })
  }

  // Training: the calendar already names today's session, so this row exists
  // only to say where you are in the block. Amit doesn't want the block's
  // name ("What is Deep Waters Peak Engine?") — just the week count, and only
  // when a block is actually running.
  const weekLabel = today.training?.block_context?.match(/Week\s+\d+\s+of\s+\d+/i)?.[0]
  if (weekLabel) {
    rows.push({
      key: 'training',
      sort: BOTTOM - 1,
      time: 'Block',
      dot: 'var(--flame)',
      title: weekLabel,
      sub: null,
    })
  }

  for (const routine of routines) {
    if (routine.scheduled_today === 0) continue
    const anchor = routine.anchor_time
    rows.push({
      key: `routine-${routine.id ?? 'unassigned'}`,
      sort: anchor ? minutesOfClock(anchor) : BOTTOM,
      time: anchor ?? '',
      dot: routine.color ?? 'var(--flame)',
      title: `${routine.emoji ? `${routine.emoji} ` : ''}${routine.name}`,
      sub: `${routine.completed_today}/${routine.scheduled_today} done · 🔥 ${routine.streak}`,
      dimmed: routine.done_today,
      onClick: () => navigate('/routines'),
    })
  }

  if (mealsCount > 0) {
    rows.push({
      key: 'meals',
      sort: BOTTOM,
      time: 'Meals',
      dot: 'var(--good)',
      title: `${mealsCount} logged · ${Math.round(totals.kcal)} kcal`,
      sub: `${Math.round(totals.protein_g)}g protein · ${Math.round(totals.fiber_g)}g fiber`,
    })
  }

  rows.sort((a, b) => a.sort - b.sort)

  return (
    <Section label="Today" step={1}>
      <Group>
        {rows.length === 0 && (
          <div style={{ padding: '14px', fontSize: '14px', color: 'var(--muted)' }}>
            A clear day, Sir. Nothing scheduled.
          </div>
        )}
        {rows.map((row, index) => {
          const rendered = (
            <Row
              time={row.time}
              dot={row.dot}
              title={row.title}
              sub={row.sub}
              dimmed={row.dimmed}
              first={index === 0}
            />
          )
          return row.onClick ? (
            <button
              key={row.key}
              onClick={row.onClick}
              className="press-row"
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                border: 'none', background: 'none', padding: 0, cursor: 'pointer',
              }}
            >
              {rendered}
            </button>
          ) : (
            <div key={row.key}>{rendered}</div>
          )
        })}
      </Group>
      {today.coach_note && (
        <p style={{ margin: '10px 2px 0', fontSize: '13.5px', lineHeight: 1.5, color: 'var(--muted)' }}>
          {today.coach_note}
          {/* The note is written once by the morning review and never recomposed,
              so stamp it — otherwise a 07:40 read looks like live advice at 18:00. */}
          {coachNoteAt && (
            <span style={{ opacity: 0.65 }}>{` · ${coachNoteAt}`}</span>
          )}
        </p>
      )}
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Morning numbers
// ---------------------------------------------------------------------------

function StatsRow({ today }: { today: TodayData }) {
  const garmin = today.garmin
  const stats: Array<{ value: string; label: string }> = garmin
    ? [
        { value: sleepLabel(garmin.sleep) ?? '—', label: 'Sleep' },
        { value: garmin.hrv != null ? String(Math.round(garmin.hrv)) : '—', label: 'HRV' },
        { value: garmin.body_battery != null ? String(garmin.body_battery) : '—', label: 'Battery' },
        { value: garmin.resting_hr != null ? String(garmin.resting_hr) : '—', label: 'Rest HR' },
      ]
    : []

  return (
    <Section label={garmin?.stored ? 'This morning · stored' : 'This morning'} step={2}>
      {garmin ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
          {stats.map(({ value, label }) => (
            <div
              key={label}
              style={{
                background: 'var(--surface)',
                borderRadius: 'var(--r)',
                padding: '10px 4px 9px',
                textAlign: 'center',
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-display)',
                  fontWeight: 700,
                  fontSize: '19px',
                  color: 'var(--ink)',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {value}
              </div>
              <div style={{ fontSize: '10.5px', color: 'var(--muted)', marginTop: '2px' }}>{label}</div>
            </div>
          ))}
        </div>
      ) : (
        <Group>
          <div style={{ padding: '12px 14px', fontSize: '13.5px', color: 'var(--muted)' }}>
            Sleep stats syncing…
          </div>
        </Group>
      )}
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Klaus's corner — follow-ups + what he did
// ---------------------------------------------------------------------------

function KlausCorner() {
  const { data: followups = [] } = useFollowups()
  const { items } = useNotifications()

  const DUE_FORMAT = new Intl.DateTimeFormat('en-US', {
    weekday: 'long',
    timeZone: 'Asia/Jerusalem',
  })
  const upcoming = followups.slice(0, 2)
  const today = new Date().toISOString().slice(0, 10)
  const recentActions = items.filter((i) => i.type === 'action' && i.at.startsWith(today)).slice(0, 1)

  if (upcoming.length === 0 && recentActions.length === 0) return null

  const rows: Array<{ key: string; title: string; sub: string }> = [
    ...upcoming.map((f) => {
      const due = new Date(f.due_at)
      const day = Number.isNaN(due.getTime()) ? '' : DUE_FORMAT.format(due)
      return { key: `f-${f.id}`, title: day ? `${day} — follow-up` : 'Follow-up', sub: f.note }
    }),
    ...recentActions.map((a) => ({ key: `a-${a.id}`, title: 'Klaus did', sub: a.title })),
  ]

  return (
    <Section label="Klaus's corner" step={3}>
      <Group>
        {rows.map((row, index) => (
          <div
            key={row.key}
            style={{
              display: 'flex',
              gap: '12px',
              padding: '12px 14px',
              alignItems: 'center',
              borderTop: index > 0 ? '1px solid var(--sep)' : 'none',
            }}
          >
            <span
              style={{
                width: '30px',
                height: '30px',
                borderRadius: '8px',
                flexShrink: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'var(--ground)',
                color: 'var(--accent)',
              }}
            >
              <Clock size={15} strokeWidth={2} aria-hidden="true" />
            </span>
            <span style={{ minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: '14.5px', fontWeight: 600, color: 'var(--ink)' }}>
                {row.title}
              </span>
              <span style={{ display: 'block', fontSize: '12.5px', color: 'var(--muted)', marginTop: '1px' }}>
                {row.sub}
              </span>
            </span>
          </div>
        ))}
      </Group>
    </Section>
  )
}

// ---------------------------------------------------------------------------
// Portfolio (off by default)
// ---------------------------------------------------------------------------

function PortfolioCard() {
  const { data } = useQuery({
    queryKey: ['portfolio'],
    queryFn: fetchPortfolio,
    staleTime: 30 * 60_000,
  })
  const snapshots = data?.snapshots ?? []
  const latest = snapshots[0]?.total_ils
  const previous = snapshots[1]?.total_ils
  const change = latest != null && previous != null && previous > 0
    ? ((latest - previous) / previous) * 100
    : null

  // Klaus publishes a snapshot every week whether or not the research step
  // produced quotes, so a zero total means "no valuation yet", not ₪0.
  if (latest == null || latest === 0) {
    return (
      <Section label="Portfolio" step={4}>
        <Group>
          <div style={{ padding: '12px 14px', fontSize: '13.5px', color: 'var(--muted)' }}>
            No valuation yet — Klaus records one with the weekly review.
          </div>
        </Group>
      </Section>
    )
  }

  return (
    <Section label="Portfolio" step={4}>
      <Group>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', padding: '12px 14px' }}>
          <span
            style={{
              fontFamily: 'var(--font-display)',
              fontWeight: 700,
              fontSize: '19px',
              color: 'var(--ink)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            ₪{Math.round(latest).toLocaleString('en-US')}
          </span>
          {change != null && (
            <span
              style={{
                fontSize: '13px',
                fontWeight: 600,
                color: change >= 0 ? 'var(--good)' : 'var(--destructive)',
              }}
            >
              {change >= 0 ? '▲' : '▼'} {Math.abs(change).toFixed(1)}%
            </span>
          )}
          <span style={{ marginLeft: 'auto', fontSize: '12px', color: 'var(--faint)' }}>this week · IBI</span>
        </div>
      </Group>
    </Section>
  )
}

// ---------------------------------------------------------------------------
// HomePage
// ---------------------------------------------------------------------------

export function HomePage() {
  const { data: today, isLoading, isError } = useToday()
  const { homeSections } = useSettings()
  const hour = Number(
    new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hourCycle: 'h23', timeZone: 'Asia/Jerusalem' }).format(new Date()),
  )

  const sublineParts: string[] = []
  if (today?.weather) sublineParts.push(today.weather)
  const sleep = sleepLabel(today?.garmin?.sleep ?? null)
  if (sleep) sublineParts.push(`slept ${sleep}`)

  return (
    <div style={{ paddingBottom: '24px' }}>
      <h1
        className="rise"
        style={{
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          letterSpacing: '-0.02em',
          fontSize: '28px',
          lineHeight: 1.12,
          margin: '12px 20px 3px',
          color: 'var(--ink)',
          textWrap: 'balance',
        }}
      >
        {greetingFor(hour)}
      </h1>
      <p style={{ margin: '0 20px 16px', color: 'var(--muted)', fontSize: '14px' }}>
        {sublineParts.length > 0 ? sublineParts.join(' · ') : ' '}
      </p>

      <KlausCta />

      {isLoading && (
        <div style={{ margin: '0 20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div className="skeleton" style={{ height: '18px', width: '35%' }} />
          <div className="skeleton" style={{ height: '132px', borderRadius: 'var(--r)' }} />
          <div className="skeleton" style={{ height: '18px', width: '45%', marginTop: '8px' }} />
          <div className="skeleton" style={{ height: '68px', borderRadius: 'var(--r)' }} />
        </div>
      )}
      {isError && (
        <div style={{ margin: '0 20px', color: 'var(--muted)', fontSize: '14px' }}>
          Couldn't load today — pull down or check your connection.
        </div>
      )}

      {today && (
        <>
          {homeSections.leaveby && <LeaveByHero events={today.calendar.timed} />}
          <Timeline today={today} />
          {homeSections.stats && <StatsRow today={today} />}
          {homeSections.corner && <KlausCorner />}
          {homeSections.portfolio && <PortfolioCard />}
        </>
      )}

      <PushEnableBanner />
    </div>
  )
}
