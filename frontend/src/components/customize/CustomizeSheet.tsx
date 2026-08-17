/**
 * CustomizeSheet.tsx — self-serve personalization (the mockup-gate winner).
 *
 *  - Accent + flame: 4 presets each, a native color picker behind a rainbow
 *    swatch, and a typeable hex field. Live preview via applyAppearance();
 *    persisted whole to PATCH /api/settings on change (account-wide).
 *  - Font: Notion-style Ag cards — SF / New York / SF Rounded / SF Mono
 *    (all native faces, zero downloads).
 *  - Home sections: iOS-style toggles for leave-by, numbers, corner, portfolio.
 */
import { useRef } from 'react'
import { Check } from 'lucide-react'
import {
  applyAppearance,
  FONT_STACKS,
  normalizeHex,
  type Appearance,
  type FontChoice,
} from '../../tokens'
import { defaultHomeSections, useSettings, useUpdateSettings } from '../../hooks/useSettings'
import type { HomeSections } from '../../api/settings'
import { Sheet } from '../shared/Sheet'

const ACCENT_PRESETS = ['#1C2540', '#1C1C1E', '#1F4E63', '#20563A']
const FLAME_PRESETS = ['#B02A2A', '#8F2D3C', '#C2410C', '#B0762A']

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

interface ColorRowProps {
  presets: string[]
  value: string
  onChange: (hex: string) => void
  ariaLabel: string
}

function ColorRow({ presets, value, onChange, ariaLabel }: ColorRowProps) {
  const pickerRef = useRef<HTMLInputElement>(null)
  const isCustom = !presets.includes(value)

  function Ring({ on }: { on: boolean }) {
    return on ? (
      <span
        style={{
          position: 'absolute',
          inset: '-5px',
          borderRadius: '50%',
          border: '2px solid var(--ink)',
        }}
        aria-hidden="true"
      />
    ) : null
  }

  return (
    <>
      <div style={{ display: 'flex', gap: '10px' }} role="radiogroup" aria-label={ariaLabel}>
        {presets.map((hex) => (
          <button
            key={hex}
            role="radio"
            aria-checked={value === hex}
            aria-label={hex}
            onClick={() => onChange(hex)}
            style={{
              width: '44px',
              height: '44px',
              borderRadius: '50%',
              border: 'none',
              position: 'relative',
              background: hex,
              cursor: 'pointer',
            }}
          >
            <Ring on={value === hex} />
            {value === hex && (
              <Check size={16} color="#FFFFFF" strokeWidth={3} aria-hidden="true" />
            )}
          </button>
        ))}
        {/* Rainbow swatch → native color picker */}
        <button
          aria-label={`Custom ${ariaLabel}`}
          onClick={() => pickerRef.current?.click()}
          style={{
            width: '44px',
            height: '44px',
            borderRadius: '50%',
            border: 'none',
            position: 'relative',
            background: 'conic-gradient(#E8453C, #E8A23D, #3FA55B, #2E7CF6, #7C5CD6, #E8453C)',
            cursor: 'pointer',
          }}
        >
          <Ring on={isCustom} />
          <input
            ref={pickerRef}
            type="color"
            value={value}
            onChange={(e) => onChange(e.target.value.toUpperCase())}
            aria-hidden="true"
            tabIndex={-1}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              opacity: 0,
              border: 'none',
              padding: 0,
              cursor: 'pointer',
            }}
          />
        </button>
      </div>
      {/* Hex field */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '2px',
          marginTop: '10px',
          background: 'var(--surface)',
          borderRadius: '10px',
          padding: '9px 12px',
          width: 'fit-content',
        }}
      >
        <span
          style={{
            color: 'var(--faint)',
            fontWeight: 600,
            fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
            fontSize: '14px',
          }}
        >
          #
        </span>
        <input
          value={value.replace(/^#/, '')}
          maxLength={6}
          spellCheck={false}
          autoComplete="off"
          aria-label={`${ariaLabel} hex value`}
          onChange={(e) => {
            const hex = normalizeHex(e.target.value)
            if (hex) onChange(hex)
          }}
          style={{
            border: 'none',
            background: 'none',
            outline: 'none',
            width: '74px',
            fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
            fontSize: '14px',
            fontWeight: 600,
            color: 'var(--ink)',
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}
        />
        <span
          style={{
            width: '18px',
            height: '18px',
            borderRadius: '6px',
            marginLeft: '6px',
            background: value,
          }}
          aria-hidden="true"
        />
      </div>
    </>
  )
}

interface CustomizeSheetProps {
  open: boolean
  onClose: () => void
}

export function CustomizeSheet({ open, onClose }: CustomizeSheetProps) {
  const { appearance, homeSections } = useSettings()
  const update = useUpdateSettings()

  function setAppearance(next: Appearance) {
    applyAppearance(next) // live preview, instant
    update.mutate({ appearance: next })
  }

  function toggleSection(id: keyof HomeSections) {
    const next = { ...defaultHomeSections, ...homeSections, [id]: !homeSections[id] }
    update.mutate({ home_sections: next })
  }

  return (
    <Sheet open={open} onClose={onClose} title="Customize">
      <Label>Accent</Label>
      <ColorRow
        presets={ACCENT_PRESETS}
        value={appearance.accent.toUpperCase()}
        onChange={(accent) => setAppearance({ ...appearance, accent })}
        ariaLabel="Accent color"
      />

      <Label>Streak flame</Label>
      <ColorRow
        presets={FLAME_PRESETS}
        value={appearance.flame.toUpperCase()}
        onChange={(flame) => setAppearance({ ...appearance, flame })}
        ariaLabel="Flame color"
      />

      <Label>Font</Label>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
        {FONT_OPTIONS.map(({ id, label }) => {
          const active = appearance.font === id
          return (
            <button
              key={id}
              onClick={() => setAppearance({ ...appearance, font: id })}
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
                    left: on ? '21.5px' : '2.5px',
                    width: '24px',
                    height: '24px',
                    borderRadius: '50%',
                    background: '#FFFFFF',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
                    transition: 'left 0.2s',
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
