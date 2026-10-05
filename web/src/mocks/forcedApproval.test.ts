// Interruptor `?simular=` de la API simulada (solo `npm run dev:mock`): casos de POST /approve
// que la pantalla no puede provocar por sí sola.
import { describe, expect, it } from 'vitest'
import type { ConversationOut } from '../api/types.ts'
import { forcedApprovalFrom } from './db.ts'
import { FINGERPRINT_MISMATCH } from './handlers.ts'
import { mockDb } from './node.ts'

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)
const ID = '8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d'

async function approve(): Promise<Response> {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  const conversation = (await (await fetch(url(`/conversations/${ID}`))).json()) as ConversationOut
  return fetch(url(`/conversations/${ID}/approve`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-ficticio' },
    body: JSON.stringify({ fingerprint: conversation.review?.fingerprint }),
  })
}

async function finalEvent(): Promise<{ event: string; data: ConversationOut }> {
  const text = await (await fetch(url(`/conversations/${ID}/events`))).text()
  const block = text.trim().split('\n\n').at(-1) ?? ''
  const event = /^event: (.+)$/m.exec(block)?.[1] ?? ''
  const data = JSON.parse(/^data: (.+)$/m.exec(block)?.[1] ?? 'null') as ConversationOut
  return { event, data }
}

describe('forcedApprovalFrom', () => {
  it.each([
    ['?simular=huella', 'fingerprint'],
    ['?simular=aprobacion-rechazada', 'approval_rejected'],
    ['?simular=no-en-revision', 'not_in_review'],
    ['?mock=1&simular=huella', 'fingerprint'],
  ])('%s → %s', (search, forced) => {
    expect(forcedApprovalFrom(search)).toBe(forced)
  })

  it.each(['', '?simular=', '?simular=otra', '?simular=toString', '?simular=__proto__'])('%j → ninguna', (search) => {
    expect(forcedApprovalFrom(search)).toBeUndefined()
  })
})

describe('API simulada: POST /approve forzado', () => {
  it('sin forzar, la huella exacta termina en `result` simulado', async () => {
    expect((await approve()).status).toBe(202)
    const { event, data } = await finalEvent()
    expect(event).toBe('result')
    expect(data.state).toBe('simulated')
  })

  it('huella: vuelve a la revisión con review.error', async () => {
    mockDb.forceApprove = 'fingerprint'
    expect((await approve()).status).toBe(202)
    const { event, data } = await finalEvent()
    expect(event).toBe('review_ready')
    expect(data.state).toBe('in_review')
    expect(data.review?.error).toBe(FINGERPRINT_MISMATCH)
  })

  it.each([
    ['approval_rejected', 'approval_rejected'],
    ['not_in_review', 'not_in_review'],
  ] as const)('%s: 409 con su código y la conversación sigue en revisión', async (forced, code) => {
    mockDb.forceApprove = forced
    const response = await approve()
    expect(response.status).toBe(409)
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe(code)
    expect(((await (await fetch(url(`/conversations/${ID}`))).json()) as ConversationOut).state).toBe('in_review')
  })
})
