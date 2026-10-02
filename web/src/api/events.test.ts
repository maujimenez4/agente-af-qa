import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { DEMO_PASSWORD } from '../mocks/db.ts'
import { mockServer } from '../mocks/node.ts'
import { api, setCsrfToken } from './client.ts'
import { parseEventStream, subscribeEvents } from './events.ts'
import type { ProgressStep } from './types.ts'

async function startConversation(): Promise<string> {
  setCsrfToken((await api.login('af-demo', DEMO_PASSWORD)).csrf_token)
  const conversation = await api.createConversation({
    flow: 'evolve',
    origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' },
    excluded_sources: [],
    feedback: [],
  })
  return conversation.id
}

function streamOf(text: string) {
  return new HttpResponse(text, { headers: { 'Content-Type': 'text/event-stream' } })
}

describe('parseEventStream', () => {
  it('separa eventos completos y deja lo que está a medias', () => {
    const { events, rest } = parseEventStream('event: progress\ndata: {"a":1}\n\nevent: review_ready\ndata: {"b"')
    expect(events).toEqual([{ event: 'progress', data: '{"a":1}' }])
    expect(rest).toBe('event: review_ready\ndata: {"b"')
  })

  it('ignora comentarios y latidos, y admite CRLF', () => {
    const { events } = parseEventStream(': latido\r\n\r\nevent: progress\r\ndata: {"x":2}\r\n\r\n')
    expect(events).toEqual([{ event: 'progress', data: '{"x":2}' }])
  })
})

describe('subscribeEvents', () => {
  it('entrega cada ProgressStep con su label y luego review_ready', async () => {
    const id = await startConversation()
    const steps: ProgressStep[] = []
    const reviewReady = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents(id, { onProgress: (step) => steps.push(step), onReviewReady: reviewReady, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('ended'))
    expect(steps.map((step) => `${step.node}:${step.state}`)).toEqual([
      'load_origin:running',
      'load_origin:done',
      'retrieve_context:running',
      'retrieve_context:done',
      'generate:running',
      'generate:done',
    ])
    expect(steps[4]?.label).toBe('Generar la propuesta, validar las citas y analizar el impacto')
    expect(reviewReady).toHaveBeenCalledWith({ id, state: 'in_review' })
  })

  it('cierra el flujo tras result y no avisa de desconexión', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () =>
        streamOf('event: result\ndata: {"mode":"simulation"}\n\nevent: progress\ndata: {"node":"publish"}\n\n'),
      ),
    )
    const onResult = vi.fn()
    const onProgress = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents('x', { onResult, onProgress, onDisconnect })
    await vi.waitFor(() => expect(onResult).toHaveBeenCalledWith({ mode: 'simulation' }))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(onProgress).not.toHaveBeenCalled()
    expect(onDisconnect).not.toHaveBeenCalled()
  })

  it('un error HTTP al abrir el flujo llega por onError y avisa de desconexión', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () =>
        HttpResponse.json(
          { error: { code: 'too_many_streams', message: 'Tienes demasiadas pestañas siguiendo conversaciones.' } },
          { status: 429 },
        ),
      ),
    )
    const onError = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents('x', { onError, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('failed'))
    expect(onError).toHaveBeenCalledWith({
      code: 'too_many_streams',
      message: 'Tienes demasiadas pestañas siguiendo conversaciones.',
    })
  })

  it('si se corta la conexión avisa para consultar el estado con GET', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => HttpResponse.error()))
    const onDisconnect = vi.fn()
    subscribeEvents('x', { onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalledWith('failed'))
  })

  it('cerrar a mano no avisa de desconexión', async () => {
    const id = await startConversation()
    const onDisconnect = vi.fn()
    const close = subscribeEvents(id, { onDisconnect })
    close()
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(onDisconnect).not.toHaveBeenCalled()
  })

  it('ignora datos que no son JSON', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => streamOf('event: progress\ndata: <b>x</b>\n\n')))
    const onProgress = vi.fn()
    const onDisconnect = vi.fn()
    subscribeEvents('x', { onProgress, onDisconnect })
    await vi.waitFor(() => expect(onDisconnect).toHaveBeenCalled())
    expect(onProgress).not.toHaveBeenCalled()
  })
})
