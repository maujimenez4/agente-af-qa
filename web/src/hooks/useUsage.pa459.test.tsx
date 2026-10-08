// PA-459: la consulta de uso (`GET /settings/usage`, cada 60 s) renovaba la sesión y la caducidad por inactividad no
// llegaba nunca. Ahora se pausa con la pestaña oculta y tras 5 minutos sin actividad, y se reanuda al volver.
// Deterministas: reloj falso de Vitest y la consulta espiada.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client.ts'
import type { UsageTodayOut } from '../api/types.ts'
import { USAGE_IDLE_MS, USAGE_REFRESH_MS, useUsage } from './useUsage.ts'

const USAGE = { tokens_today: 1200, daily_token_warning: 100000 } as unknown as UsageTodayOut

let hidden = false
function setHidden(value: boolean) {
  hidden = value
  document.dispatchEvent(new Event('visibilitychange'))
}

const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

beforeEach(() => {
  vi.useFakeTimers()
  hidden = false
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  Reflect.deleteProperty(document, 'hidden') // vuelve la propiedad del prototipo
})

describe('useUsage · la consulta no mantiene viva la sesión (PA-459)', () => {
  it('con actividad, consulta al montar y cada 60 s', async () => {
    const usage = vi.spyOn(api, 'usage').mockResolvedValue(USAGE)
    renderHook(() => useUsage())
    expect(usage).toHaveBeenCalledTimes(1)
    for (let minute = 1; minute <= 3; minute += 1) {
      await advance(USAGE_REFRESH_MS - 1000)
      window.dispatchEvent(new Event('pointerdown'))
      await advance(1000)
      expect(usage).toHaveBeenCalledTimes(1 + minute)
    }
  })

  it('con la pestaña oculta no consulta; al volver a mostrarse, consulta en el acto', async () => {
    const usage = vi.spyOn(api, 'usage').mockResolvedValue(USAGE)
    renderHook(() => useUsage())
    expect(usage).toHaveBeenCalledTimes(1)
    await act(async () => setHidden(true))
    await advance(USAGE_REFRESH_MS * 3)
    expect(usage).toHaveBeenCalledTimes(1)

    await act(async () => setHidden(false))
    expect(usage).toHaveBeenCalledTimes(2)
    await advance(USAGE_REFRESH_MS)
    expect(usage).toHaveBeenCalledTimes(3)
  })

  it('tras 5 minutos sin actividad se pausa; una pulsación la reanuda en el acto', async () => {
    const usage = vi.spyOn(api, 'usage').mockResolvedValue(USAGE)
    renderHook(() => useUsage())
    await advance(USAGE_IDLE_MS - 1) // las de los minutos 1 a 4 salen
    const beforeIdle = usage.mock.calls.length
    expect(beforeIdle).toBe(1 + Math.floor((USAGE_IDLE_MS - 1) / USAGE_REFRESH_MS))
    await advance(USAGE_REFRESH_MS * 5) // ya sin actividad: ninguna más
    expect(usage).toHaveBeenCalledTimes(beforeIdle)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }))
    expect(usage).toHaveBeenCalledTimes(beforeIdle + 1)
    await advance(USAGE_REFRESH_MS)
    expect(usage).toHaveBeenCalledTimes(beforeIdle + 2)
  })

  it('volver a la pestaña tras más de 5 minutos sin actividad no consulta hasta que haya actividad', async () => {
    const usage = vi.spyOn(api, 'usage').mockResolvedValue(USAGE)
    renderHook(() => useUsage())
    await act(async () => setHidden(true))
    await advance(USAGE_IDLE_MS + USAGE_REFRESH_MS)
    await act(async () => setHidden(false))
    expect(usage).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new Event('pointerdown'))
    expect(usage).toHaveBeenCalledTimes(2)
  })

  it('desactivada, no consulta ni escucha', async () => {
    const usage = vi.spyOn(api, 'usage').mockResolvedValue(USAGE)
    renderHook(() => useUsage(false))
    window.dispatchEvent(new Event('pointerdown'))
    await advance(USAGE_REFRESH_MS * 2)
    expect(usage).not.toHaveBeenCalled()
  })
})
