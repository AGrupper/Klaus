/**
 * CustomizeSheet.tsx — self-serve personalization.
 *
 *  - Accent + flame: a fixed swatch grid of Google Calendar's event colours
 *    (Amit's call — "use the same colours as Google Calendar and just leave
 *    it at that"). No hex field, no eyedropper: a closed set can't produce an
 *    unreadable theme, and the colours are already familiar.
 *  - Font: Notion-style Ag cards — SF / New York / SF Rounded / SF Mono
 *    (all native faces, zero downloads).
 *  - Home sections: iOS-style toggles for leave-by, numbers, corner, portfolio.
 *
 * Writes are debounced and last-write-wins (useUpdateSettings); the CSS
 * variables update on tap so the preview never lags the finger.
 */
import { Check } from 'lucide-react'
import {
  ACCENT_COLORS,
  applyAppearance,
  FLAME_COLORS,
  FONT_STACKS,
  type Appearance,
  type FontChoice,
} from '../../tokens'
import { defaultHomeSections, useSettings, useUpdateSettings } from '../../hooks/useSettings'
import type { HomeSections } from '../../api/settings'
import { Sheet } from '../shared/Sheet'
import { tapFeedback } from '../../utils/haptics'

const FONT_OPTIONS: Array<{ id: FontChoice; label: string }> = [
  { id: 'default', label: 'Default' },
  { id: 'serif', label: 'Serif' },
  { id: 'rounded', label: 'Rounded' },
  { id: 'mono', label: 'Mono' },
]

const SECTION_OPTIONS: Array<{ id: keyof HomeSections; label: string; sub: string }> = [
  { id: 'leaveby', label: 'Leave-by countdown', sub: 'Departure hero when a leave-by is near' },
  { id: 'stats', label: 'Morning numbers', sub: 'Sleep · HRV · battery · resting HR' },
  { id: 'corner', label: "Klaus's corner", sub: 'Follow-ups and what he filed' },
  { id: 'portfolio', label: 'Portfolio', sub: 'Weekly IBI valuation' },
]

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: '11px',
        letterSpacing: '0.1em',
        textTransform: 'uppercase',
        color: 'var(--muted)',
        fontWeight: 600,
        margin: '14px 0 8px',
      }}
    >
      {children}
    </div>
  )
}

interface SwatchGridProps {
  options: Array<{ name: string; hex: string }>
  value: string
  onChange: (hex: string) => void
  ariaLabel: string
}

function SwatchGrid({ options, value, onChange, ariaLabel }: SwatchGridProps) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '12px' }}
    >
      {options.map(({ name, hex }) => {
        const selected = value.toUpperCase() === hex.toUpperCase()
        return (
          <button
            key={hex}
            role="radio"
            aria-checked={selected}
            aria-label={name}
            title={name}
            className="press"
            onClick={() => {
              tapFeedback()
              onChange(hex)
            }}
            style={{
              aspectRatio: '1',
              width: '100%',
              borderRadius: '50%',
              border: 'none',
              background: hex,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: selected
                ? '0 0 0 3px var(--ground), 0 0 0 5px var(--ink)'
                : 'none',
              transition: 'box-shadow 0.18s ease',
            }}
          >
            {selected && <Check size={15} color="#FFFFFF" strokeWidth={3.5} aria-hidden="true" />}
          </button>
        )
      })}
    </div>
  )
}

interface CustomizeSheetProps {
  open: boolean
  onClose: () => void
}

export function CustomizeSheet({ open, onClose }: CustomizeSheetProps) {
  const { appearance, homeSections } = useSettings()
  const { save, flush } = useUpdateSettings()

  function setAppearance(next: Appearance) {
    applyAppearance(next)   // live preview, instant
    save({ appearance: next })  // debounced write, last value wins
  }

  function toggleSection(id: keyof HomeSections) {
    tapFeedback()
    const next = { ...defaultHomeSections, ...homeSections, [id]: !homeSections[id] }
    save({ home_sections: next })
  }

  // Closing the sheet commits any value still inside the debounce window.
  function handleClose() {
    flush()
    onClose()
  }

  return (
    <Sheet open={open} onClose={handleClose} title="Customize">
      <Label>Accent</Label>
      <SwatchGrid
        options={ACCENT_COLORS}
        value={appearance.accent}
        onChange={(accent) => setAppearance({ ...appearance, accent })}
        ariaLabel="Accent colour"
      />

      <Label>Streak flame</Label>
      <SwatchGrid
        options={FLAME_COLORS}
        value={appearance.flame}
        onChange={(flame) => setAppearance({ ...appearance, flame })}
        ariaLabel="Flame colour"
      />

      <Label>Font</Label>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
        {FONT_OPTIONS.map(({ id, label }) => {
          const active = appearance.font === id
          return (
            <button
              key={id}
              className="press"
              onClick={() => {
                tapFeedback()
                setAppearance({ ...appearance, font: id })
              }}
              aria-pressed={active}
              style={{
                border: `1.5px solid ${active ? 'var(--accent)' : 'transparent'}`,
                background: 'var(--surface)',
                borderRadius: '12px',
                padding: '12px 4px 9px',
                display: 'flex',
                flexDirection: 'column',
                gap: '3px',
                alignItems: 'center',
                cursor: 'pointer',
              }}
            >
              <span
                style={{
                  fontSize: '24px',
                  fontWeight: 600,
                  lineHeight: 1,
                  color: 'var(--ink)',
                  fontFamily: FONT_STACKS[id].display,
                }}
              >
                Ag
              </span>
              <span
                style={{
                  fontSize: '11px',
                  color: active ? 'var(--accent)' : 'var(--muted)',
                  fontWeight: active ? 600 : 400,
                }}
              >
                {label}
              </span>
            </button>
          )
        })}
      </div>

      <Label>Home sections</Label>
      <div style={{ background: 'var(--surface)', borderRadius: 'var(--r)' }}>
        {SECTION_OPTIONS.map(({ id, label, sub }, index) => {
          const on = homeSections[id]
          return (
            <div
              key={id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                padding: '12px 14px',
                borderTop: index > 0 ? '1px solid var(--sep)' : 'none',
              }}
            >
              <span>
                <span style={{ display: 'block', fontSize: '15px', fontWeight: 500, color: 'var(--ink)' }}>
                  {label}
                </span>
                <span style={{ display: 'block', fontSize: '12px', color: 'var(--muted)', marginTop: '1px' }}>
                  {sub}
                </span>
              </span>
              <button
                role="switch"
                aria-checked={on}
                aria-label={label}
                onClick={() => toggleSection(id)}
                style={{
                  marginLeft: 'auto',
                  width: '48px',
                  height: '29px',
                  borderRadius: '15px',
                  border: 'none',
                  background: on ? 'var(--good)' : '#D9D9DE',
                  position: 'relative',
                  transition: 'background 0.2s',
                  flexShrink: 0,
                  cursor: 'pointer',
                }}
              >
                <span
                  style={{
                    position: 'absolute',
                    top: '2.5px',
                    left: '2.5px',
                    transform: on ? 'translateX(19px)' : 'translateX(0)',
                    width: '24px',
                    height: '24px',
                    borderRadius: '50%',
                    background: '#FFFFFF',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
                    transition: 'transform 0.24s cubic-bezier(0.32,1.4,0.5,1)',
                  }}
                  aria-hidden="true"
                />
              </button>
            </div>
          )
        })}
      </div>
      <p style={{ fontSize: '12.5px', color: 'var(--muted)', lineHeight: 1.5, margin: '12px 2px 6px' }}>
        Everything here saves to your account — same look on iPhone and Mac.
        Routines and their items are edited on the Routines tab.
      </p>
    </Sheet>
  )
}
