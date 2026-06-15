/**
 * Vitest global setup.
 *
 * This Node + jsdom combination ships a non-functional `localStorage` (it emits
 * a `--localstorage-file` warning and its methods like `getItem`/`clear` are not
 * callable). Component code that reads localStorage (e.g. the install-banner
 * dismiss gate) then throws mid-render. Install a clean in-memory Storage so
 * every test sees a deterministic, fully-functional localStorage.
 */
import { afterEach } from 'vitest'

class MemoryStorage implements Storage {
  private store = new Map<string, string>()

  get length(): number {
    return this.store.size
  }

  clear(): void {
    this.store.clear()
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}

const memoryLocalStorage = new MemoryStorage()

Object.defineProperty(globalThis, 'localStorage', {
  value: memoryLocalStorage,
  configurable: true,
  writable: true,
})
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'localStorage', {
    value: memoryLocalStorage,
    configurable: true,
    writable: true,
  })
}

// Keep tests isolated — clear persisted keys between specs.
afterEach(() => {
  memoryLocalStorage.clear()
})
