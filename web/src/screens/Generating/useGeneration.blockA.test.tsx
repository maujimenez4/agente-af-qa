// Bloque A (T-56): requestStop (POST /cancel, PA-314) y useGeneration al cambiar de conversación (POST /retry,
// PA-276). DESIGN-DECISIONS.md §4 bis, Generando: Error y Detener. Datos sintéticos.
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { mockServer } from '../../mocks/node.ts'
import { requestStop, useGeneration } from './useGeneration.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut

const generating = (id: string, extra: Partial<ConversationOut> = {}): ConversationOut => ({
  ...EXAMPLE,
  id,
  state: 'generating',
  review: null,
  error: null,
  cancel_requested: false,
  ...extra,
})

const apiError = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message, retry_after: null } }, { status })

/** Flujo SSE que no termina (latido): la generación sigue en «running». */
function openStream() {
  return new HttpResponse(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(': latido\n\n'))
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  )
}

describe('requestStop con cada respuesta de /cancel (bloque A)', () => {
  it('202 con cancel_requested=true → sigue deteniéndose', async () => {
    /** §4 bis: «Deteniendo…» mientras termina el paso en curso. */
    mockServer.use(http.post('/api/v1/conversations/:id/cancel', () => HttpResponse.json(generating('c-1', { cancel_requested: true }), { status: 202 })))
    expect(await requestStop('c-1')).toEqual({ stopping: true })
  })

  it('202 aún generando aunque cancel_requested=false → sigue deteniéndose', async () => {
    mockServer.use(http.post('/api/v1/conversations/:id/cancel', () => HttpResponse.json(generating('c-1'), { status: 202 })))
    expect(await requestStop('c-1')).toEqual({ stopping: true })
  })

  it('202 ya en revisión (el siguiente paso era la revisión) → deja de detenerse', async () => {
    /** README «Novedades»: si el siguiente paso era la revisión, `state=in_review` con `cancel_requested=false`. */
    mockServer.use(http.post('/api/v1/conversations/:id/cancel', () => HttpResponse.json({ ...EXAMPLE, cancel_requested: false }, { status: 202 })))
    expect(await requestStop('c-1')).toEqual({ stopping: false })
  })

  it('409 not_cancellable → no es un error', async () => {
    /** §4 bis: «Un not_cancellable no se muestra (ya había terminado)». */
    mockServer.use(http.post('/api/v1/conversations/:id/cancel', () => apiError(409, 'not_cancellable', 'No hay nada que detener (ficticio).')))
    expect(await requestStop('c-1')).toEqual({ stopping: false })
  })

  it.each([
    [503, 'service_unavailable'],
    [404, 'not_found'],
    [401, 'unauthenticated'],
    [429, 'rate_limited'],
  ])('%i %s → error para mostrar y deja de detenerse', async (status, code) => {
    /** §4 bis: «otro error sí [se muestra], y la generación sigue». */
    mockServer.use(http.post('/api/v1/conversations/:id/cancel', () => apiError(status, code, `Fallo ficticio ${code}.`)))
    const result = await requestStop('c-1')
    expect(result.stopping).toBe(false)
    expect(result.error).toMatchObject({ code, message: `Fallo ficticio ${code}.` })
  })

  it('un fallo de red → error, no una excepción', async () => {
    mockServer.use(http.post('/api/v1/conversations/:id/cancel', () => HttpResponse.error()))
    const result = await requestStop('c-1')
    expect(result.stopping).toBe(false)
    expect(result.error).toBeDefined()
  })
})

describe('useGeneration al cambiar de conversación (bloque A)', () => {
  function serveEvents() {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', ({ params }) => {
        if (params.id === 'c-falla') {
          const failure = { ...generating('c-falla'), state: 'error', error: { code: 'cancelled', message: 'Generación detenida (ficticio).', retry_after: null } }
          return new HttpResponse(`event: error\ndata: ${JSON.stringify(failure)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
        }
        return openStream()
      }),
    )
  }

  it('tras un error reintentable, al seguir la conversación que devuelve /retry vuelve a «running»', async () => {
    /** §4 bis: *Reintentar* repite el paso con POST /retry «y se sigue el SSE de nuevo». */
    serveEvents()
    const { result, rerender } = renderHook(({ conversation }) => useGeneration(conversation), {
      initialProps: { conversation: generating('c-falla') },
    })
    await waitFor(() => expect(result.current.state.status).toBe('error'))
    expect(result.current.state).toMatchObject({ retryable: true, error: { code: 'cancelled' } })

    const retried = generating('c-otra', { progress: EXAMPLE.progress.map((step) => ({ ...step, state: 'pending' as const })) })
    rerender({ conversation: retried })
    expect(result.current.state).toEqual({ status: 'running', steps: retried.progress })
    expect(result.current.stopping).toBe(false)
    expect(result.current.stopError).toBeUndefined()
  })

  it('al cambiar a una conversación con cancel_requested=true empieza «Deteniendo…»', async () => {
    /** README «Novedades»: mientras termina el paso en curso, `cancel_requested=true` («Deteniendo…»). */
    serveEvents()
    const { result, rerender } = renderHook(({ conversation }) => useGeneration(conversation), {
      initialProps: { conversation: generating('c-a') },
    })
    expect(result.current.stopping).toBe(false)
    rerender({ conversation: generating('c-b', { cancel_requested: true }) })
    expect(result.current.state.status).toBe('running')
    expect(result.current.stopping).toBe(true)
  })

  it('stopping solo vale mientras genera: tras el error vuelve a false', async () => {
    /** §4 bis: tras *Detener* acaba en `cancelled` y el botón deja de decir «Deteniendo…». */
    serveEvents()
    // Objeto estable: useGeneration sigue otra conversación cuando cambia la referencia.
    const conversation = generating('c-falla', { cancel_requested: true })
    const { result } = renderHook(() => useGeneration(conversation))
    await waitFor(() => expect(result.current.state.status).toBe('error'))
    expect(result.current.stopping).toBe(false)
  })

  it('stop() con un 503 deja stopError y no se queda «Deteniendo…»', async () => {
    serveEvents()
    mockServer.use(http.post('/api/v1/conversations/:id/cancel', () => apiError(503, 'service_unavailable', 'Servicio no disponible (ficticio).')))
    const conversation = generating('c-sigue')
    const { result } = renderHook(() => useGeneration(conversation))
    act(() => result.current.stop())
    await waitFor(() => expect(result.current.stopError).toMatchObject({ code: 'service_unavailable' }))
    expect(result.current.stopping).toBe(false)
    expect(result.current.state.status).toBe('running')
  })
})
