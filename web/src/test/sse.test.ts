// PA-127 · holdNextEventStream: retiene el siguiente `/events` hasta que la prueba lo suelta; después responde la API
// simulada; closeOpenEventStreams suelta los retenidos. Sin reloj. Datos sintéticos (DEMO-3, qa-demo, csrf-ficticio).
import { afterEach, describe, expect, it } from 'vitest'
import type { ConversationCreateIn, ConversationOut } from '../api/types.ts'
import { mockDb, mockServer } from '../mocks/node.ts'
import { closeOpenEventStreams, holdNextEventStream } from './sse.ts'

const CSRF = 'csrf-ficticio'
const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

/** Una suite de DEMO-3 recién pedida (state=generating): su `/events` la lleva a revisión. */
async function generatingConversation(): Promise<string> {
  mockDb.session = { username: 'qa-demo', role: 'qa', csrf: CSRF }
  const body: ConversationCreateIn = {
    origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' },
    flow: 'tests',
    excluded_sources: [],
    feedback: ['Incluye casos: positivos, negativos.'],
  }
  const created = await fetch(url('/conversations'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
    body: JSON.stringify(body),
  })
  return ((await created.json()) as { id: string }).id
}

/** Cuenta las peticiones a `/events` que ya han llegado a MSW. */
function eventsRequests(): () => number {
  let count = 0
  mockServer.events.on('request:start', ({ request }) => {
    if (new URL(request.url).pathname.endsWith('/events')) count += 1
  })
  return () => count
}

/** Promesa con su estado visible, para comprobar que sigue pendiente. */
function track<T>(promise: Promise<T>): { settled: () => boolean; promise: Promise<T> } {
  let done = false
  const tracked = promise.finally(() => {
    done = true
  })
  return { settled: () => done, promise: tracked }
}

/** Deja pasar varias vueltas del bucle de eventos (sin esperar un tiempo fijo). */
async function flushEventLoop(turns = 5): Promise<void> {
  for (let turn = 0; turn < turns; turn += 1) await new Promise((resolve) => setTimeout(resolve, 0))
}

const conversationState = async (id: string) => ((await (await fetch(url(`/conversations/${id}`))).json()) as ConversationOut).state

afterEach(() => mockServer.events.removeAllListeners())

describe('holdNextEventStream (PA-127)', () => {
  it('test_held_event_stream_stays_pending_until_released', async () => {
    /** Criterio 1: mientras está retenido, el `/events` no responde y la conversación sigue generando. */
    const id = await generatingConversation()
    const requests = eventsRequests()
    const release = holdNextEventStream()
    const events = track(fetch(url(`/conversations/${id}/events`)))
    await expect.poll(requests).toBe(1)
    await flushEventLoop()
    expect(events.settled()).toBe(false)
    expect(await conversationState(id)).toBe('generating')
    release()
    await events.promise
  })

  it('test_released_event_stream_is_answered_by_the_mock_api', async () => {
    /** Criterio 1: al soltarlo responde el handler normal de la API simulada (progreso y review_ready). */
    const id = await generatingConversation()
    const release = holdNextEventStream()
    const events = fetch(url(`/conversations/${id}/events`))
    release()
    const response = await events
    expect(response.headers.get('Content-Type')).toBe('text/event-stream')
    const text = await response.text()
    expect(text).toContain('event: progress')
    expect(text).toContain('event: review_ready')
    expect(await conversationState(id)).toBe('in_review')
  })

  it('test_only_the_next_event_stream_is_held', async () => {
    /** Criterio 1 (límite): solo se retiene el siguiente `/events`; el de después responde sin soltar nada. */
    const id = await generatingConversation()
    const requests = eventsRequests()
    const release = holdNextEventStream()
    const first = track(fetch(url(`/conversations/${id}/events`)))
    await expect.poll(requests).toBe(1)
    const second = await fetch(url(`/conversations/${id}/events`))
    expect(second.status).toBe(200)
    await second.text()
    expect(first.settled()).toBe(false)
    release()
    expect((await first.promise).status).toBe(200)
  })

  it('test_close_open_event_streams_releases_held_ones', async () => {
    /** Criterio 1: closeOpenEventStreams() suelta los retenidos: ninguna petición queda colgada. */
    const id = await generatingConversation()
    const requests = eventsRequests()
    const release = holdNextEventStream()
    const events = track(fetch(url(`/conversations/${id}/events`)))
    await expect.poll(requests).toBe(1)
    await flushEventLoop()
    expect(events.settled()).toBe(false)
    closeOpenEventStreams()
    const text = await (await events.promise).text()
    expect(text).toContain('event: review_ready')
    // Soltar después del cierre no falla (ya no está retenido).
    expect(() => release()).not.toThrow()
  })

  it('test_close_open_event_streams_releases_several_held_streams', async () => {
    /** Criterio 1 (límite): con dos retenciones a la vez, el cierre suelta las dos. */
    const first = await generatingConversation()
    const second = await generatingConversation()
    const requests = eventsRequests()
    holdNextEventStream()
    holdNextEventStream()
    const a = track(fetch(url(`/conversations/${first}/events`)))
    const b = track(fetch(url(`/conversations/${second}/events`)))
    await expect.poll(requests).toBe(2)
    await flushEventLoop()
    expect(a.settled() || b.settled()).toBe(false)
    closeOpenEventStreams()
    const responses = await Promise.all([a.promise, b.promise])
    expect(responses.map((response) => response.status)).toEqual([200, 200])
    await Promise.all(responses.map((response) => response.text()))
  })
})
