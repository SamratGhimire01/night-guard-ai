import { useCallback, useState } from 'react'

/** useState that survives a reload, kept in this browser only (a per-person preference, never shared data).
 * Storage can be blocked (private mode, strict settings) — then it simply behaves like useState. */
export function useStoredState<T>(key: string, initial: T): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })
  const set = useCallback(
    (next: T) => {
      setValue(next)
      try {
        window.localStorage.setItem(key, JSON.stringify(next))
      } catch {
        /* storage blocked: keep it for this visit only */
      }
    },
    [key],
  )
  return [value, set]
}
