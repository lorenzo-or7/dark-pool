/** Visual and default-value preferences. In the shared lab they belong to this browser only
 * (localStorage), never to the shared workspace. */

export type Prefs = {
  density: 'comfortable' | 'compact'
  reduced_motion: boolean
  default_min_price: number
  default_min_volume: number
  default_replays: number
  default_seed: number
}

export const DEFAULT_PREFS: Prefs = {
  density: 'comfortable',
  reduced_motion: false,
  default_min_price: 5,
  default_min_volume: 1_000_000,
  default_replays: 10_000,
  default_seed: 19,
}

const KEY = 'dp.prefs.v1'

export function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return DEFAULT_PREFS
    const p = JSON.parse(raw) as Partial<Prefs>
    return { ...DEFAULT_PREFS, ...p }
  } catch {
    return DEFAULT_PREFS
  }
}

export function savePrefs(p: Prefs): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
    return true
  } catch {
    return false
  }
}
