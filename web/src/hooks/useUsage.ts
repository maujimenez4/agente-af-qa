import { useEffect, useState } from 'react'
import { api } from '../api/client.ts'
import type { UsageTodayOut } from '../api/types.ts'

/** Cada cuánto se vuelve a pedir el consumo de hoy (el anillo no necesita más precisión). */
export const USAGE_REFRESH_MS = 60_000

/**
 * Consumo de tokens de hoy de toda la instalación (`GET /settings/usage`, PA-305).
 * Con 503 u otro error devuelve `undefined`: el anillo no se pinta.
 */
export function useUsage(enabled = true): UsageTodayOut | undefined {
  const [usage, setUsage] = useState<UsageTodayOut | undefined>()

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    const load = () => {
      api
        .usage()
        .then((value) => {
          if (!cancelled) setUsage(value)
        })
        .catch(() => {
          if (!cancelled) setUsage(undefined)
        })
    }
    load()
    const timer = window.setInterval(load, USAGE_REFRESH_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [enabled])

  return enabled ? usage : undefined
}
