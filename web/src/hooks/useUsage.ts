import { useEffect, useState } from 'react'
import { api } from '../api/client.ts'
import type { UsageTodayOut } from '../api/types.ts'

/** Cada cuánto se vuelve a pedir el consumo de hoy (el anillo no necesita más precisión). */
export const USAGE_REFRESH_MS = 60_000
/** PA-459: sin actividad de la persona durante este tiempo, la consulta se pausa. */
export const USAGE_IDLE_MS = 5 * 60_000

/** Lo que cuenta como actividad de la persona (no el movimiento del ratón sobre la página). */
const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const

/**
 * Consumo de tokens de hoy de toda la instalación (`GET /settings/usage`, PA-305).
 * Con 503 u otro error devuelve `undefined`: el anillo no se pinta.
 *
 * PA-459: cada consulta renueva la sesión en la API, así que no se pide con la pestaña oculta ni tras
 * `USAGE_IDLE_MS` sin actividad (si no, la caducidad por inactividad no llegaría nunca). Al volver la pestaña o la
 * actividad, se pide en el acto y se sigue cada `USAGE_REFRESH_MS`.
 */
export function useUsage(enabled = true): UsageTodayOut | undefined {
  const [usage, setUsage] = useState<UsageTodayOut | undefined>()

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let lastActivity = Date.now()
    const idle = () => Date.now() - lastActivity >= USAGE_IDLE_MS
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
    const tick = () => {
      if (!document.hidden && !idle()) load()
    }
    const onActivity = () => {
      const wasIdle = idle()
      lastActivity = Date.now()
      if (wasIdle && !document.hidden) load()
    }
    const onVisibility = () => {
      if (!document.hidden && !idle()) load()
    }

    load()
    const timer = window.setInterval(tick, USAGE_REFRESH_MS)
    for (const event of ACTIVITY_EVENTS) window.addEventListener(event, onActivity, { passive: true })
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      for (const event of ACTIVITY_EVENTS) window.removeEventListener(event, onActivity)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [enabled])

  return enabled ? usage : undefined
}
