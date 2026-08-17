import { access, mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { build } from 'vite'

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
let outputDirectory = ''

beforeAll(async () => {
  outputDirectory = await mkdtemp(join(tmpdir(), 'klaus-icon-assets-'))
  await build({
    root: frontendRoot,
    configFile: resolve(frontendRoot, 'vite.config.ts'),
    logLevel: 'silent',
    build: {
      outDir: outputDirectory,
      emptyOutDir: true,
    },
  })
})

afterAll(async () => {
  if (outputDirectory) {
    await rm(outputDirectory, { recursive: true, force: true })
  }
})

describe('built app icon assets', () => {
  it('publishes versioned icon URLs everywhere an installed app can cache them', async () => {
    const manifest = JSON.parse(
      await readFile(join(outputDirectory, 'manifest.webmanifest'), 'utf8'),
    ) as { icons: Array<{ src: string }> }
    const html = await readFile(join(outputDirectory, 'index.html'), 'utf8')
    const serviceWorker = await readFile(join(outputDirectory, 'sw.js'), 'utf8')

    const manifestIconUrls = manifest.icons.map((icon) => icon.src)
    expect(manifestIconUrls).toHaveLength(3)
    for (const iconUrl of manifestIconUrls) {
      expect(iconUrl).toMatch(/^\/icon-(?:192|512|512-maskable)-v\d+\.png$/)
      await expect(access(join(outputDirectory, iconUrl.slice(1)))).resolves.toBeUndefined()
    }

    expect(html).toMatch(/href="\/apple-touch-icon-v\d+\.png"/)
    expect(html).toMatch(/href="\/icon-192-v\d+\.png"/)
    expect(serviceWorker).toMatch(/\/icon-192-v\d+\.png/)
  })
})
