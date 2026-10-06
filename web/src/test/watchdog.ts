// PA-333: reloj falso para los plazos del vigilante de useGeneration (5 s, 20 s y 3 s). Los temporizadores
// con esos plazos se guardan y vencen cuando la prueba lo decide; el resto (los de MSW) siguen reales.
import { act } from '@testing-library/react'
import { expect, vi } from 'vitest'
import { OPEN_TIMEOUT_MS, SILENCE_MS, WATCH_POLL_MS } from '../screens/Generating/useGeneration.ts'

/** Reloj falso para los plazos del vigilante: los temporizadores con esos plazos se guardan y vencen a mano. */
export function watchdogClock() {
  const delays = new Set([OPEN_TIMEOUT_MS, SILENCE_MS, WATCH_POLL_MS])
  const pending = new Map<number, { ms: number; handler: () => void }>()
  let next = 1_000_000
  const realSetTimeout = window.setTimeout.bind(window)
  const realClearTimeout = window.clearTimeout.bind(window)
  vi.spyOn(window, 'setTimeout').mockImplementation(((handler: () => void, ms?: number, ...args: unknown[]) => {
    if (ms !== undefined && delays.has(ms)) {
      next += 1
      pending.set(next, { ms, handler })
      return next
    }
    return realSetTimeout(handler, ms, ...args)
  }) as typeof window.setTimeout)
  vi.spyOn(window, 'clearTimeout').mockImplementation((id?: number) => {
    if (id !== undefined && pending.delete(id)) return
    realClearTimeout(id)
  })
  return {
    /** Plazos programados ahora mismo. */
    armed: () => [...pending.values()].map((timer) => timer.ms).sort((a, b) => a - b),
    /** Vence el temporizador programado con ese plazo (debe haber exactamente uno). */
    fire: (ms: number) => {
      const entries = [...pending.entries()].filter(([, timer]) => timer.ms === ms)
      expect(entries).toHaveLength(1)
      const [id, timer] = entries[0] ?? []
      if (id === undefined || !timer) return
      pending.delete(id)
      act(() => timer.handler())
    },
  }
}

/**
 * Espera a que se cumpla `check` dejando correr las promesas (fetch simulado, lectura del flujo) con el
 * reloj real. No usa `waitFor`: con `setTimeout` espiado, su espera no termina.
 */
export async function until(check: () => void, attempts = 200) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      check()
      return
    } catch (failure) {
      if (attempt >= attempts) throw failure
    }
    await act(() => new Promise<void>((resolve) => window.setTimeout(resolve, 5)))
  }
}
