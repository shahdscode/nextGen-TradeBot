import { useEffect, useRef } from 'react'

/**
 * Polls a given async function every `interval` ms until
 * `shouldStop(result)` returns true or the component unmounts.
 */
export function usePoll(fn, shouldStop, interval = 2000, enabled = true) {
  const timer = useRef(null)

  useEffect(() => {
    if (!enabled) return
    let active = true

    const tick = async () => {
      try {
        const result = await fn()
        if (!active) return
        if (shouldStop(result)) return
        timer.current = setTimeout(tick, interval)
      } catch {
        if (active) timer.current = setTimeout(tick, interval)
      }
    }

    tick()
    return () => {
      active = false
      clearTimeout(timer.current)
    }
  }, [enabled])
}
