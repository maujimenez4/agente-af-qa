// Bloque B · API simulada de POST /approve y el interruptor `?simular=` (web/README.md, «API simulada»;
// DESIGN-DECISIONS.md §4 bis, «Resultado»). Solo datos sintéticos.
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ConversationOut } from '../api/types.ts'
import { forcedApprovalFrom, type MockDb } from './db.ts'
import { PARTIAL_ERROR } from './handlers.ts'
import { mockDb } from './node.ts'

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)
const ID = '8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d'
const HEADERS = { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-ficticio' }

async function current(): Promise<ConversationOut> {
  return (await (await fetch(url(`/conversations/${ID}`))).json()) as ConversationOut
}

async function approve(fingerprint?: string): Promise<Response> {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  const conversation = await current()
  return fetch(url(`/conversations/${ID}/approve`), { method: 'POST', headers: HEADERS, body: JSON.stringify({ fingerprint: fingerprint ?? conversation.review?.fingerprint }) })
}

async function finalEvent(): Promise<{ event: string; data: ConversationOut }> {
  const text = await (await fetch(url(`/conversations/${ID}/events`))).text()
  const block = text.trim().split('\n\n').at(-1) ?? ''
  return { event: /^event: (.+)$/m.exec(block)?.[1] ?? '', data: JSON.parse(/^data: (.+)$/m.exec(block)?.[1] ?? 'null') as ConversationOut }
}

describe('forcedApprovalFrom: publicado y parcial', () => {
  it.each([
    ['?simular=publicado', 'published'],
    ['?simular=parcial', 'partial'],
    ['?simular=parcial&simular=huella', 'partial'],
  ])('%s → %s', (search, forced) => {
    expect(forcedApprovalFrom(search)).toBe(forced)
  })

  it.each(['?simular=PUBLICADO', '?simular=hasOwnProperty', '?simular=constructor', '?simular= parcial', '?Simular=parcial'])('%j → ninguna', (search) => {
    expect(forcedApprovalFrom(search)).toBeUndefined()
  })
})

describe('API simulada: final de la aprobación', () => {
  it('?simular=publicado: `result` con estado `published`, la clave de DEMO-3 y sin errores', async () => {
    mockDb.forceApprove = 'published'
    expect((await approve()).status).toBe(202)
    const { event, data } = await finalEvent()
    expect(event).toBe('result')
    expect(data.state).toBe('published')
    expect(data.review).toBeNull()
    expect(data.result).toMatchObject({ simulated: false, published_keys: ['DEMO-3'], errors: [], failed_ids: [], approved_by: 'af-demo' })
  })

  it('?simular=parcial: `published` con el error ficticio en `result.errors` (no es un error HTTP)', async () => {
    mockDb.forceApprove = 'partial'
    expect((await approve()).status).toBe(202)
    const { event, data } = await finalEvent()
    expect(event).toBe('result')
    expect(data.state).toBe('published')
    expect(data.result?.errors).toEqual([PARTIAL_ERROR])
  })

  it('con `publish_mode: live` en los ajustes, publica sin forzar nada', async () => {
    mockDb.settings = { ...mockDb.settings, publish_mode: 'live' }
    await approve()
    expect((await finalEvent()).data.state).toBe('published')
  })

  it('una huella distinta de la vigente vuelve a la revisión con `review.error` y la huella vigente', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    const vigente = (await current()).review?.fingerprint
    expect(vigente).toBeTruthy()
    await approve('huella-ficticia-que-no-casa')
    const { event, data } = await finalEvent()
    expect(event).toBe('review_ready')
    expect(data.review?.fingerprint).toBe(vigente)
    expect(data.review?.error).toBeTruthy()
  })

  it('una segunda aprobación mientras publica da 409 `not_in_review`', async () => {
    expect((await approve()).status).toBe(202)
    const second = await fetch(url(`/conversations/${ID}/approve`), { method: 'POST', headers: HEADERS, body: JSON.stringify({ fingerprint: 'huella-ficticia' }) })
    expect(second.status).toBe(409)
    expect(((await second.json()) as { error: { code: string } }).error.code).toBe('not_in_review')
  })

  it('aprobar no se puede detener: POST /cancel da 409 `not_cancellable`', async () => {
    await approve()
    const response = await fetch(url(`/conversations/${ID}/cancel`), { method: 'POST', headers: HEADERS })
    expect(response.status).toBe(409)
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe('not_cancellable')
  })

  it('tras publicar, la lista de conversaciones refleja el estado nuevo', async () => {
    await approve()
    await finalEvent()
    const list = (await (await fetch(url('/conversations'))).json()) as { thread_id: string; status: string }[]
    expect(list.find((item) => item.thread_id === ID)?.status).toBe('simulated')
  })
})

describe('browser.ts aplica `?simular=` al arrancar la API simulada', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/')
    vi.doUnmock('msw/browser')
    vi.doUnmock('./handlers.ts')
    vi.resetModules()
  })

  async function startWith(search: string): Promise<MockDb | undefined> {
    window.history.replaceState(null, '', `/${search}`)
    let captured: MockDb | undefined
    vi.resetModules()
    vi.doMock('msw/browser', () => ({ setupWorker: () => ({ start: () => Promise.resolve() }) }))
    vi.doMock('./handlers.ts', () => ({
      createHandlers: (db: MockDb) => {
        captured = db
        return []
      },
    }))
    const { startMockApi } = await import('./browser.ts')
    await startMockApi()
    return captured
  }

  it('con ?simular=parcial la base simulada fuerza la publicación en parte', async () => {
    expect((await startWith('?simular=parcial'))?.forceApprove).toBe('partial')
  })

  it('sin el parámetro no fuerza nada', async () => {
    expect((await startWith(''))?.forceApprove).toBeUndefined()
  })
})
