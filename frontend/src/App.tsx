/**
 * App.tsx — minimal placeholder shell for Phase 26-01.
 *
 * Renders the "Klaus" wordmark on the dark background (#0A0A0A).
 * Real layout (sidebar + timeline + chat) ships in Phase 26-09 (AppShell).
 */
import { dominant, accent, textPrimary, textSecondary, typography } from './tokens'

export default function App() {
  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: dominant,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8px',
      }}
    >
      {/* Klaus wordmark — Display size per UI-SPEC */}
      <h1
        style={{
          fontSize: typography.display.fontSize,
          fontWeight: typography.display.fontWeight,
          lineHeight: typography.display.lineHeight,
          color: textPrimary,
          letterSpacing: '-0.01em',
        }}
      >
        Klaus
      </h1>
      <p
        style={{
          fontSize: typography.label.fontSize,
          fontWeight: typography.label.fontWeight,
          lineHeight: typography.label.lineHeight,
          color: textSecondary,
        }}
      >
        Your personal agent
      </p>
      {/* Accent indicator — verifies accent color renders */}
      <div
        aria-hidden="true"
        style={{
          marginTop: '24px',
          width: '32px',
          height: '4px',
          borderRadius: '2px',
          backgroundColor: accent,
        }}
      />
    </div>
  )
}
