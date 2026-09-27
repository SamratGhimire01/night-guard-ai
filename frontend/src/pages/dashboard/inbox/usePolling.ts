import { useEffect, useRef } from 'react'

/** Runs `fn` now and then every `ms` while the tab is visible (paused when hidden, refreshed as soon as it is shown again).
 * `fn` may change every render — the latest one is always used. Pass `enabled=false` to stop; change `resetKey` (e.g. a
 * filter value) to run again immediately instead of waiting for the next tick. */
export function usePolling(fn: () => void | Promise<void>, ms: number, enabled = true, resetKey?: unknown) {
  const latest = useRef(fn)
  useEffect(() => {
    latest.current = fn
  })

  useEffect(() => {
    if (!enabled) return
    let timer: ReturnType<typeof setInterval> | null = null
    const tick = () => {
      if (!document.hidden) void latest.current()
    }
    const onVisibility = () => {
      if (!document.hidden) tick()
    }
    tick()
    timer = setInterval(tick, ms)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      if (timer) clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [ms, enabled, resetKey])
}
