// API simulada de QA encadenada (T-54): /handoff (analista), /qa/handoffs y /take (QA). Datos sintéticos.
import { describe, expect, it } from 'vitest'
import type { ConversationOut, HandoffOut, SessionOut } from '../api/types.ts'
import { DEMO_PASSWORD } from './db.ts'
import { mockDb } from './node.ts'

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

async function login(username: string): Promise<string> {
  const response = await fetch(url('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: DEMO_PASSWORD }),
  })
  return ((await response.json()) as SessionOut).csrf_token
}

const post = (path: string, csrf: string) => fetch(url(path), { method: 'POST', headers: { 'X-CSRF-Token': csrf } })

/** Una conversación del analista ya simulada (aprobada en modo de prueba). */
async function simulatedConversation(csrf: string): Promise<string> {
  const list = (await (await fetch(url('/conversations'))).json()) as Array<{ thread_id: string }>
  const id = list[0]?.thread_id ?? ''
  const conversation = (await (await fetch(url(`/conversations/${id}`))).json()) as ConversationOut
  const approved = await fetch(url(`/conversations/${id}/approve`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ fingerprint: conversation.review?.fingerprint }),
  })
  expect(approved.status).toBe(202)
  // El SSE termina la aprobación (simulada).
  await (await fetch(url(`/conversations/${id}/events`))).text()
  return id
}

describe('API simulada · QA encadenada', () => {
  it('el analista pasa a QA una conversación simulada: sin clave, idempotente y visible para QA', async () => {
    const csrf = await login('af-demo')
    const id = await simulatedConversation(csrf)
    const first = (await (await post(`/conversations/${id}/handoff`, csrf)).json()) as HandoffOut
    const again = (await (await post(`/conversations/${id}/handoff`, csrf)).json()) as HandoffOut
    expect(first).toMatchObject({ project: 'DEMO', story_key: null, from_user: 'af-demo' })
    expect(again.id).toBe(first.id)
    expect(mockDb.handoffs.filter((item) => item.id === first.id)).toHaveLength(1)

    await login('qa-demo')
    const pending = (await (await fetch(url('/qa/handoffs'))).json()) as HandoffOut[]
    expect(pending.map((item) => item.id)).toContain(first.id)
  })

  it('pasar a QA una conversación en revisión da 409 not_in_review', async () => {
    const csrf = await login('af-demo')
    const list = (await (await fetch(url('/conversations'))).json()) as Array<{ thread_id: string }>
    const response = await post(`/conversations/${list[0]?.thread_id ?? ''}/handoff`, csrf)
    expect(response.status).toBe(409)
    expect(await response.json()).toMatchObject({ error: { code: 'not_in_review' } })
  })

  it('solo QA ve la lista y recoge; solo el analista pasa a QA (403 forbidden)', async () => {
    const analyst = await login('af-demo')
    expect((await fetch(url('/qa/handoffs'))).status).toBe(403)
    expect((await post(`/qa/handoffs/${mockDb.handoffs[0]?.id ?? ''}/take`, analyst)).status).toBe(403)
    const qa = await login('qa-demo')
    expect((await post('/conversations/8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d/handoff', qa)).status).toBe(403)
  })

  it('recoger la saca de la lista y crea la conversación de QA; recogerla otra vez da 409 handoff_unavailable', async () => {
    const csrf = await login('qa-demo')
    const id = mockDb.handoffs[0]?.id ?? ''
    const taken = await post(`/qa/handoffs/${id}/take`, csrf)
    expect(taken.status).toBe(202)
    const conversation = (await taken.json()) as ConversationOut
    expect(conversation).toMatchObject({ mode: 'qa', flow: 'tests', state: 'generating' })
    expect(mockDb.handoffs.find((item) => item.id === id)).toBeUndefined()
    expect(mockDb.conversations[0]).toMatchObject({ thread_id: conversation.id, mode: 'qa' })
    const again = await post(`/qa/handoffs/${id}/take`, csrf)
    expect(again.status).toBe(409)
    expect(await again.json()).toMatchObject({ error: { code: 'handoff_unavailable' } })
  })

  it('?simular=ya-recogida: al recoger, otra persona se adelantó y la HU sale de la lista', async () => {
    const csrf = await login('qa-demo')
    mockDb.forceTaken = true
    const id = mockDb.handoffs[0]?.id ?? ''
    const response = await post(`/qa/handoffs/${id}/take`, csrf)
    expect(response.status).toBe(409)
    expect(mockDb.handoffs.find((item) => item.id === id)).toBeUndefined()
  })
})
