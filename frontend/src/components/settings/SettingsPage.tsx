/**
 * SettingsPage.tsx — /settings: push notifications, connection status,
 * sign-out. Appearance/module choices live in the Customize sheet (gear),
 * not here — this page holds the plumbing.
 */
import { useQuery } from '@tanstack/react-query'
import { fetchAgentStatus } from '../../api/agent'
import { logout, revokeAll } from '../../api/auth'
import { usePush } from '../../hooks/usePush'
import { useAuthStore } from '../../store/auth'

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section style={{ margin: '4px 20px 18px' }}>
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
    </section>
  )
}

function Group({ children }: { children: React.ReactNode }) {
  return <div style={{ background: 'var(--surface)', borderRadius: 'var(--r)' }}>{children}</div>
}

const rowText: React.CSSProperties = {
  fontSize: '13.5px',
  lineHeight: 1.5,
  color: 'var(--muted)',
}

export function SettingsPage() {
  const { permission, enablePush, needsReenable, neverAsked, isSubscribed } = usePush()
  const email = useAuthStore((s) => s.email)
  const storeSignOut = useAuthStore((s) => s.signOut)
  const { data: agentStatus } = useQuery({
    queryKey: ['agent', 'status'],
    queryFn: fetchAgentStatus,
    staleTime: 10 * 60_000,
  })

  async function handleSignOut(everywhere: boolean) {
    try {
      await (everywhere ? revokeAll() : logout())
    } finally {
      storeSignOut()
      window.location.reload()
    }
  }

  return (
    <div style={{ paddingBottom: '24px' }}>
      <h1
        style={{
          fontFamily: 'var(--font-display)',
          fontWeight: 700,
          letterSpacing: '-0.02em',
          fontSize: '28px',
          lineHeight: 1.12,
          margin: '12px 20px 18px',
          color: 'var(--ink)',
        }}
      >
        Settings
      </h1>

      <Section label="Push notifications">
        <Group>
          <div style={{ padding: '12px 14px' }}>
            {permission === 'unsupported' ? (
              <p style={rowText}>Push isn&rsquo;t supported on this device or browser.</p>
            ) : needsReenable ? (
              <p style={rowText}>
                Push was turned off in iOS Settings. Re-enable it: Settings &rarr; Notifications
                &rarr; Klaus &rarr; Allow Notifications.
              </p>
            ) : isSubscribed ? (
              <p style={rowText}>Push is enabled on this device.</p>
            ) : (
              <button
                type="button"
                onClick={() => void enablePush()}
                style={{
                  minHeight: '44px',
                  padding: '0 16px',
                  backgroundColor: 'var(--accent)',
                  color: 'var(--accent-ink)',
                  border: 'none',
                  borderRadius: '10px',
                  fontSize: '15px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                {neverAsked ? 'Enable push' : 'Enable push notifications'}
              </button>
            )}
          </div>
        </Group>
      </Section>

      <Section label="Klaus connection">
        <Group>
          <div style={{ padding: '12px 14px' }}>
            <p style={rowText}>
              {agentStatus
                ? agentStatus.capability_gate.passed
                  ? `Connector ready · skill ${agentStatus.expected_skill_version}`
                  : 'Configured · capability proof pending'
                : 'Checking the Claude connection…'}
            </p>
          </div>
        </Group>
      </Section>

      <Section label="Build">
        <Group>
          <div style={{ padding: '12px 14px' }}>
            <p style={rowText}>
              Built{' '}
              <strong style={{ color: 'var(--ink)' }}>
                {new Intl.DateTimeFormat(undefined, {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                }).format(new Date(__BUILD_ID__))}
              </strong>{' '}
              (your time). If this is older than a fix you are expecting, the
              app is still serving a cached version — close it fully and reopen.
            </p>
          </div>
        </Group>
      </Section>

      <Section label="Account">
        <Group>
          <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <p style={rowText}>{email ?? ''}</p>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <button
                onClick={() => void handleSignOut(false)}
                style={{
                  minHeight: '40px',
                  padding: '0 14px',
                  border: 'none',
                  borderRadius: '10px',
                  background: 'var(--ground)',
                  color: 'var(--ink)',
                  fontSize: '14px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Sign out
              </button>
              <button
                onClick={() => void handleSignOut(true)}
                style={{
                  minHeight: '40px',
                  padding: '0 14px',
                  border: 'none',
                  borderRadius: '10px',
                  background: 'var(--ground)',
                  color: 'var(--destructive)',
                  fontSize: '14px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Sign out everywhere
              </button>
            </div>
          </div>
        </Group>
      </Section>
    </div>
  )
}
