import { describe, it, expect } from 'vitest'
import { claudeAppUrl } from './claudeLink'

// iOS only opens claude.ai URLs in the Claude app when the path is one the app
// claims in its apple-app-site-association file. `/cowork` is claimed exactly —
// `/cowork/project/<id>` is not — so the Hub's project link lands in the PWA's
// in-app browser instead of the app (verified on device 2026-08-19).
describe('claudeAppUrl', () => {
  const project = 'https://claude.ai/cowork/project/019fe1a8-2c88-77d9-80bc-baa200346aad'

  it('rewrites an unclaimed claude.ai path to /cowork on iOS', () => {
    expect(claudeAppUrl(project, true)).toBe('https://claude.ai/cowork')
  })

  it('leaves the exact project URL alone everywhere else', () => {
    expect(claudeAppUrl(project, false)).toBe(project)
  })

  it.each([
    'https://claude.ai/code/session_abc',
    'https://claude.ai/artifacts/abc',
    'https://claude.ai/share/abc',
    'https://claude.ai/new',
    'https://claude.ai/cowork',
  ])('leaves an app-claimed path %s untouched on iOS', (url) => {
    expect(claudeAppUrl(url, true)).toBe(url)
  })

  it('leaves non-claude hosts untouched', () => {
    expect(claudeAppUrl('https://example.com/cowork/project/x', true)).toBe(
      'https://example.com/cowork/project/x',
    )
  })

  it.each([null, undefined, '', 'not a url'])('returns undefined for %j', (value) => {
    expect(claudeAppUrl(value, true)).toBeUndefined()
  })
})
