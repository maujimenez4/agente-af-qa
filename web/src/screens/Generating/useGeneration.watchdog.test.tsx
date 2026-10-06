// PA-333: vigilante del flujo SSE en useGeneration. Antes solo se consultaba el estado si el flujo se
// cortaba: con `/events` encolado en el navegador (o abierto y mudo), «Aprobando y publicando…» no
// terminaba nunca aunque la conversación ya estuviera `simulated`.
// Deterministas: el flujo es un doble que la prueba controla (cabeceras, latidos, corte), la consulta
// de estado es un espía y el reloj es el falso de Vitest. Datos sintéticos.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiRequestError } from '../../api/client.ts'
import type { ConversationEvents } from '../../api/events.ts'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { OPEN_TIMEOUT_MS, POLL_MS, SILENCE_MS, WATCH_POLL_MS, useGeneration } from './useGeneration.ts'

// El flujo de eventos: la prueba recibe los manejadores y decide qué llega y cuándo.
const stream = vi.hoisted(() => ({ handlers: undefined as ConversationEvents | undefined, closed: 0 }))
vi.mock('../../api/events.ts', () => ({
  subscribeEvents: (_id: string, handlers: ConversationEvents) => {
    stream.handlers = handlers
    return () => {
      stream.closed += 1
    }
  },
}))

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const conversation = (state: ConversationOut['state']): ConversationOut => ({
  ...EXAMPLE,
  id: 'c-vigilante',
  state,
  review: null,
  error: null,
  cancel_requested: false,
})
const GENERATING = conversation('generating') // el mismo objeto en cada render

/** GET /conversations/{id}: devuelve lo que diga `answer` en cada consulta. */
function statusAnswers(answer: () => ConversationOut) {
  return vi.spyOn(api, 'conversation').mockImplementation(() => Promise.resolve(answer()))
}

const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))
/** Llega algo del flujo (dentro de `act`, como el lector real). */
const receive = (event: () => void) => act(event)

beforeEach(() => {
  vi.useFakeTimers()
  stream.handlers = undefined
  stream.closed = 0
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useGeneration · /events sin cabeceras (encolado o sin salir) · PA-333', () => {
  it('a los 5 s consulta el estado y termina con la conversación ya simulada', async () => {
    const gets = statusAnswers(() => conversation('simulated'))
    const { result } = renderHook(() => useGeneration(GENERATING))
    await advance(OPEN_TIMEOUT_MS - 1)
    expect(gets).not.toHaveBeenCalled()
    expect(result.current.state.status).toBe('running')

    await advance(1)
    expect(gets).toHaveBeenCalledTimes(1)
    expect(result.current.state.status).toBe('ready')
  })

  it('aún generando, consulta cada 3 s hasta un estado final y después para', async () => {
    let answer = conversation('generating')
    const gets = statusAnswers(() => answer)
    const { result } = renderHook(() => useGeneration(GENERATING))
    await advance(OPEN_TIMEOUT_MS)
    expect(gets).toHaveBeenCalledTimes(1)
    await advance(WATCH_POLL_MS - 1)
    expect(gets).toHaveBeenCalledTimes(1)
    await advance(1)
    expect(gets).toHaveBeenCalledTimes(2)

    answer = conversation('simulated')
    await advance(WATCH_POLL_MS)
    expect(gets).toHaveBeenCalledTimes(3)
    expect(result.current.state.status).toBe('ready')
    await advance(WATCH_POLL_MS * 5)
    expect(gets).toHaveBeenCalledTimes(3) // con un estado final, deja de consultar
  })

  it('si el flujo llega a abrirse mientras consulta, deja de consultar', async () => {
    const gets = statusAnswers(() => conversation('generating'))
    renderHook(() => useGeneration(GENERATING))
    await advance(OPEN_TIMEOUT_MS)
    expect(gets).toHaveBeenCalledTimes(1)

    await receive(() => {
      stream.handlers?.onOpen?.()
      stream.handlers?.onActivity?.()
    })
    await advance(SILENCE_MS - 1)
    expect(gets).toHaveBeenCalledTimes(1)
  })
})

describe('useGeneration · flujo abierto · PA-333', () => {
  it('con las cabeceras ya no cuentan los 5 s: una generación pasa minutos sin eventos de datos', async () => {
    const gets = statusAnswers(() => conversation('generating'))
    renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await advance(SILENCE_MS - 1)
    expect(gets).not.toHaveBeenCalled()
    await advance(1)
    expect(gets).toHaveBeenCalledTimes(1)
  })

  it('un «: ping» (latido de la API cada 15 s) es señal de vida: solo consulta tras 20 s sin nada', async () => {
    const gets = statusAnswers(() => conversation('generating'))
    renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    for (let beat = 0; beat < 4; beat += 1) {
      await advance(15_000)
      await receive(() => stream.handlers?.onActivity?.())
    }
    expect(gets).not.toHaveBeenCalled() // un minuto con latidos y sin consultas

    await advance(SILENCE_MS)
    expect(gets).toHaveBeenCalledTimes(1)
  })

  it('las consultas se paran en cuanto vuelve a llegar algo del flujo', async () => {
    const gets = statusAnswers(() => conversation('generating'))
    const { result } = renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await advance(SILENCE_MS)
    await advance(WATCH_POLL_MS)
    expect(gets).toHaveBeenCalledTimes(2)

    await receive(() => stream.handlers?.onActivity?.())
    await advance(WATCH_POLL_MS * 3)
    expect(gets).toHaveBeenCalledTimes(2)
    expect(result.current.state.status).toBe('running')
  })

  it('un evento final del flujo termina sin consultar y sin dejar temporizadores', async () => {
    const gets = statusAnswers(() => conversation('generating'))
    const { result } = renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await receive(() => stream.handlers?.onResult?.(conversation('simulated')))
    expect(result.current.state.status).toBe('ready')
    await advance(SILENCE_MS * 3)
    expect(gets).not.toHaveBeenCalled()
  })

  it('si el flujo se corta, sigue el sondeo de siempre cada 2 s (sin el vigilante)', async () => {
    let answer = conversation('generating')
    const gets = statusAnswers(() => answer)
    const { result } = renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await receive(() => stream.handlers?.onDisconnect?.('ended'))
    expect(gets).toHaveBeenCalledTimes(1)
    await advance(POLL_MS)
    expect(gets).toHaveBeenCalledTimes(2)
    answer = conversation('simulated')
    await advance(POLL_MS)
    expect(result.current.state.status).toBe('ready')
    await advance(SILENCE_MS)
    expect(gets).toHaveBeenCalledTimes(3)
  })

  it('un fallo pasajero en una consulta del vigilante no termina la generación: vuelve a consultar', async () => {
    let calls = 0
    const gets = vi.spyOn(api, 'conversation').mockImplementation(() => {
      calls += 1
      if (calls === 1) return Promise.reject(new ApiRequestError(503, { code: 'service_unavailable', message: 'Servicio ficticio caído.' }))
      return Promise.resolve(conversation('simulated'))
    })
    const { result } = renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await advance(SILENCE_MS)
    expect(gets).toHaveBeenCalledTimes(1)
    expect(result.current.state.status).toBe('running') // el flujo no se ha cortado: no es un error

    await advance(WATCH_POLL_MS)
    expect(gets).toHaveBeenCalledTimes(2)
    expect(result.current.state.status).toBe('ready')
  })

  it('si el flujo ya se cortó, un fallo de la consulta sí se muestra (como antes)', async () => {
    vi.spyOn(api, 'conversation').mockRejectedValue(new ApiRequestError(503, { code: 'service_unavailable', message: 'Servicio ficticio caído.' }))
    const { result } = renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onDisconnect?.('failed'))
    await advance(0)
    expect(result.current.state.status).toBe('error')
  })

  it('una consulta antigua que responde tarde no abre una segunda cadena de consultas', async () => {
    let release: (value: ConversationOut) => void = () => undefined
    let calls = 0
    const gets = vi.spyOn(api, 'conversation').mockImplementation(() => {
      calls += 1
      // La primera consulta tarda: llega actividad y vuelve a vencer el silencio antes de que responda.
      if (calls === 1) return new Promise<ConversationOut>((resolve) => (release = resolve))
      return Promise.resolve(conversation('generating'))
    })
    renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await advance(SILENCE_MS) // 1.ª cadena: consulta en curso
    await receive(() => stream.handlers?.onActivity?.())
    await advance(SILENCE_MS) // 2.ª cadena
    expect(gets).toHaveBeenCalledTimes(2)
    await act(async () => release(conversation('generating'))) // responde la antigua
    await advance(WATCH_POLL_MS)
    expect(gets).toHaveBeenCalledTimes(3) // solo la 2.ª cadena sigue: una consulta, no dos
  })

  it('al llegar a un estado final por consulta, cierra el flujo SSE (no ocupa una plaza de too_many_streams)', async () => {
    statusAnswers(() => conversation('simulated'))
    const { result } = renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await advance(SILENCE_MS)
    expect(result.current.state.status).toBe('ready')
    expect(stream.closed).toBe(1) // con la pantalla aún montada
  })

  it.each([
    [404, 'not_found'],
    [403, 'forbidden'],
  ])('en modo vigilante, un %i (permanente) se muestra y no se reintenta', async (status, code) => {
    const gets = vi
      .spyOn(api, 'conversation')
      .mockRejectedValue(new ApiRequestError(status, { code: code as 'not_found', message: 'Error permanente ficticio.' }))
    const { result } = renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await advance(SILENCE_MS)
    expect(result.current.state.status).toBe('error')
    expect(stream.closed).toBe(1) // el flujo abierto se cierra
    await advance(WATCH_POLL_MS * 3)
    expect(gets).toHaveBeenCalledTimes(1)
  })

  it('en modo vigilante, un 429 (pasajero) se reintenta a los 3 s', async () => {
    let calls = 0
    vi.spyOn(api, 'conversation').mockImplementation(() => {
      calls += 1
      if (calls === 1) return Promise.reject(new ApiRequestError(429, { code: 'rate_limited', message: 'Límite ficticio.' }))
      return Promise.resolve(conversation('simulated'))
    })
    const { result } = renderHook(() => useGeneration(GENERATING))
    await receive(() => stream.handlers?.onOpen?.())
    await advance(SILENCE_MS)
    expect(result.current.state.status).toBe('running')
    await advance(WATCH_POLL_MS)
    expect(result.current.state.status).toBe('ready')
  })

  it('al desmontar, cierra el flujo y no deja consultas pendientes', async () => {
    const gets = statusAnswers(() => conversation('generating'))
    const { unmount } = renderHook(() => useGeneration(GENERATING))
    unmount()
    expect(stream.closed).toBe(1)
    await advance(OPEN_TIMEOUT_MS + SILENCE_MS)
    expect(gets).not.toHaveBeenCalled()
  })
})
