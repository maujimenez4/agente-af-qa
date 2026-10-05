// Bloque A (T-56): API simulada de /cancel (PA-314), /retry (PA-276) y la versión «Jira» (PA-316, mockBaseline).
// docs/api/README.md «Novedades para el frontend» y DESIGN-DECISIONS.md §4 bis. Datos sintéticos.
import { describe, expect, it } from 'vitest'
import type { ConversationOut, SessionOut } from '../api/types.ts'
import { DEMO_PASSWORD } from './db.ts'
import { CANCELLED_MESSAGE } from './handlers.ts'
import { mockDb } from './node.ts'

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

async function login(username = 'af-demo'): Promise<string> {
  const response = await fetch(url('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: DEMO_PASSWORD }),
  })
  return ((await response.json()) as SessionOut).csrf_token
}

function post(path: string, csrf: string | undefined, body: unknown = {}) {
  return fetch(url(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
    body: JSON.stringify(body),
  })
}

async function events(id: string): Promise<Array<{ event: string; data: ConversationOut }>> {
  const text = await (await fetch(url(`/conversations/${id}/events`))).text()
  return text
    .split('\n\n')
    .filter(Boolean)
    .map((block) => ({
      event: /^event: (.*)$/m.exec(block)?.[1] ?? '',
      data: JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? 'null') as ConversationOut,
    }))
}

const lastEvent = async (id: string) => (await events(id)).at(-1)

async function create(csrf: string, flow: 'need' | 'evolve' | 'tests' = 'evolve'): Promise<ConversationOut> {
  const origin = flow === 'need' ? { kind: 'need', text: 'Necesidad ficticia', project: 'DEMO' } : { kind: 'story', key: 'DEMO-3', project: 'DEMO' }
  const response = await post('/conversations', csrf, { origin, flow, excluded_sources: [], feedback: [] })
  return (await response.json()) as ConversationOut
}

/** La conversación de la lista que evoluciona DEMO-3 (ejemplo del contrato, en revisión, v2). */
function listed(): string {
  const first = mockDb.conversations[0]
  if (!first) throw new Error('Falta la conversación de ejemplo de la lista')
  return first.thread_id
}

describe('MSW · POST /cancel (bloque A)', () => {
  it('detener una generación en curso da 202 con cancel_requested y el SSE acaba en error cancelled', async () => {
    /** README «Novedades» PA-314: 202 ConversationOut con cancel_requested=true; al acabar, state=error y code=cancelled. */
    const csrf = await login()
    const { id } = await create(csrf)
    const response = await post(`/conversations/${id}/cancel`, csrf)
    expect(response.status).toBe(202)
    expect(await response.json()).toMatchObject({ id, state: 'generating', cancel_requested: true })

    const last = await lastEvent(id)
    expect(last?.event).toBe('error')
    expect(last?.data).toMatchObject({ state: 'error', cancel_requested: false, error: { code: 'cancelled', message: CANCELLED_MESSAGE } })
    const read = (await (await fetch(url(`/conversations/${id}`))).json()) as ConversationOut
    expect(read).toMatchObject({ state: 'error', error: { code: 'cancelled' } })
  })

  it('una conversación en revisión no se detiene: 409 not_cancellable', async () => {
    /** README «Novedades» PA-314: 409 not_cancellable «también si no está generando». */
    const csrf = await login()
    const response = await post(`/conversations/${listed()}/cancel`, csrf)
    expect(response.status).toBe(409)
    expect(await response.json()).toMatchObject({ error: { code: 'not_cancellable' } })
  })

  it('una conversación que ya está en error no se detiene: 409 not_cancellable', async () => {
    const csrf = await login()
    const { id } = await create(csrf)
    await post(`/conversations/${id}/cancel`, csrf)
    await events(id)
    const again = await post(`/conversations/${id}/cancel`, csrf)
    expect(again.status).toBe(409)
    expect(await again.json()).toMatchObject({ error: { code: 'not_cancellable' } })
  })

  it('una conversación que no existe da 404 not_found', async () => {
    const csrf = await login()
    const response = await post('/conversations/no-existe-ficticia/cancel', csrf)
    expect(response.status).toBe(404)
    expect(await response.json()).toMatchObject({ error: { code: 'not_found' } })
  })

  it('sin X-CSRF-Token da 403 forbidden y no detiene nada', async () => {
    /** DESIGN-DECISIONS.md §4: todo POST lleva X-CSRF-Token. */
    const csrf = await login()
    const { id } = await create(csrf)
    const response = await post(`/conversations/${id}/cancel`, undefined)
    expect(response.status).toBe(403)
    expect((await lastEvent(id))?.event).toBe('review_ready')
  })

  // Fija un fallo ya corregido al cerrar el bloque A. Antes: handlers.ts:437 + handlers.ts:395 — si /cancel llega cuando ya no quedan pasos (el siguiente era
  // la revisión), el SSE emite review_ready pero `run.cancel` sigue a true; /iterate no lo limpia, así que la
  // siguiente iteración se detiene sola en su primer paso. Esperado: review_ready de la v3. Observado: error cancelled.
  it('detener justo antes de la revisión da la propuesta y no detiene la siguiente iteración', async () => {
    /** README «Novedades» PA-314: «si el siguiente paso era la revisión, state=in_review … y cancel_requested=false». */
    const csrf = await login()
    const { id } = await create(csrf)
    const run = mockDb.runs.get(id)
    if (run) run.script = [] // Todos los pasos hechos: lo siguiente es la revisión.
    expect((await post(`/conversations/${id}/cancel`, csrf)).status).toBe(202)
    const ready = await lastEvent(id)
    expect(ready?.event).toBe('review_ready')
    expect(ready?.data.cancel_requested).toBe(false)

    expect((await post(`/conversations/${id}/iterate`, csrf, { feedback: 'Cambio ficticio' })).status).toBe(202)
    const next = await lastEvent(id)
    expect(next?.event).toBe('review_ready')
  })
})

describe('MSW · POST /retry (bloque A)', () => {
  it('una conversación en revisión no se reintenta: 409 not_in_error', async () => {
    /** README «Novedades» PA-276: 409 not_in_error si no está en error. */
    const csrf = await login()
    const response = await post(`/conversations/${listed()}/retry`, csrf)
    expect(response.status).toBe(409)
    expect(await response.json()).toMatchObject({ error: { code: 'not_in_error' } })
  })

  it('una conversación que está generando no se reintenta: 409 not_in_error', async () => {
    const csrf = await login()
    const { id } = await create(csrf)
    const response = await post(`/conversations/${id}/retry`, csrf)
    expect(response.status).toBe(409)
    expect(await response.json()).toMatchObject({ error: { code: 'not_in_error' } })
  })

  it('una conversación que no existe da 404 not_found', async () => {
    const csrf = await login()
    const response = await post('/conversations/no-existe-ficticia/retry', csrf)
    expect(response.status).toBe(404)
  })

  it('sin X-CSRF-Token da 403 forbidden', async () => {
    const csrf = await login()
    const { id } = await create(csrf)
    await post(`/conversations/${id}/cancel`, csrf)
    await events(id)
    expect((await post(`/conversations/${id}/retry`, undefined)).status).toBe(403)
  })

  it('tras detener, /retry da 202 generando, sin error y con los pasos pendientes, y el SSE llega a la propuesta', async () => {
    /** README «Novedades» PA-276: «Reintentar» cuando state=error (también tras cancelled) repite el paso. */
    const csrf = await login()
    const { id } = await create(csrf)
    await post(`/conversations/${id}/cancel`, csrf)
    await events(id)
    const response = await post(`/conversations/${id}/retry`, csrf)
    expect(response.status).toBe(202)
    const body = (await response.json()) as ConversationOut
    expect(body).toMatchObject({ id, state: 'generating', error: null, cancel_requested: false })
    expect(body.progress.every((step) => step.state === 'pending')).toBe(true)
    const last = await lastEvent(id)
    expect(last?.event).toBe('review_ready')
    expect(last?.data.state).toBe('in_review')
    expect(mockDb.conversations.find((item) => item.thread_id === id)?.status).toBe('in_review')
  })

  it('tras detener una iteración, /retry produce la versión siguiente sin repetir el cambio pedido', async () => {
    /** §4 bis Iterar: «si … se detuvo, POST /retry» repite la iteración; sale la v3 desde la v2. */
    const csrf = await login()
    const id = listed()
    await post(`/conversations/${id}/iterate`, csrf, { feedback: 'Cambio ficticio' })
    await post(`/conversations/${id}/cancel`, csrf)
    expect((await lastEvent(id))?.data.error?.code).toBe('cancelled')

    expect((await post(`/conversations/${id}/retry`, csrf)).status).toBe(202)
    const last = await lastEvent(id)
    expect(last?.event).toBe('review_ready')
    expect(last?.data.review?.version).toBe(3)
    expect(last?.data.feedback.filter((item) => item === 'Cambio ficticio')).toHaveLength(1)
    expect(last?.data.review?.artifact.content).toMatchObject({ changes_from_previous: ['CA-01: Cambio ficticio'] })
  })

  it('un segundo /retry seguido da 409 not_in_error (ya está generando)', async () => {
    const csrf = await login()
    const { id } = await create(csrf)
    await post(`/conversations/${id}/cancel`, csrf)
    await events(id)
    expect((await post(`/conversations/${id}/retry`, csrf)).status).toBe(202)
    expect((await post(`/conversations/${id}/retry`, csrf)).status).toBe(409)
  })
})

describe('MSW · versión «Jira» (mockBaseline, bloque A)', () => {
  it('al evolucionar, review_ready trae la HU de Jira sin los CA que los diffs dan por nuevos', async () => {
    /** §4 bis Iterar: la simulada se construye quitando lo que los diffs dan por nuevo. */
    const csrf = await login()
    const { id } = await create(csrf, 'evolve')
    const ready = await lastEvent(id)
    const baseline = ready?.data.jira_baseline
    expect(baseline?.acceptance_criteria.map((item) => item.id)).toEqual(['CA-01'])
    expect(baseline?.business_rules.map((item) => item.id)).toEqual(['RN-01', 'RN-02'])
    expect(baseline?.changes_from_previous).toEqual([])
  })

  it.each([['need'], ['tests']] as const)('con el flujo %s (HU nueva o QA) jira_baseline es null', async (flow) => {
    /** README «Novedades» PA-316: null en una HU nueva y en QA. */
    const csrf = await login(flow === 'tests' ? 'qa-demo' : 'af-demo')
    const created = await create(csrf, flow)
    const ready = await lastEvent(created.id)
    expect(ready?.event).toBe('review_ready')
    expect(ready?.data.mode).toBe(flow === 'tests' ? 'qa' : 'functional')
    expect(ready?.data.jira_baseline).toBeNull()
  })

  it('sin diffs, la versión «Jira» es la propuesta entera (no quita ningún CA ni RN)', async () => {
    /** Límite: sin `impact` no hay nada nuevo frente a Jira. */
    const csrf = await login()
    const id = listed()
    await fetch(url(`/conversations/${id}`))
    const run = mockDb.runs.get(id)
    if (!run?.conversation.review) throw new Error('Falta la conversación de ejemplo')
    run.conversation = {
      ...run.conversation,
      jira_baseline: null,
      review: { ...run.conversation.review, impact: null, artifact: { ...run.conversation.review.artifact, impact: null } },
    }
    await post(`/conversations/${id}/iterate`, csrf, { feedback: 'Cambio ficticio' })
    const baseline = (await lastEvent(id))?.data.jira_baseline
    expect(baseline?.acceptance_criteria.map((item) => item.id)).toEqual(['CA-01', 'CA-02'])
    expect(baseline?.business_rules.map((item) => item.id)).toEqual(['RN-01', 'RN-02'])
    expect(baseline?.changes_from_previous).toEqual([])
  })

  it('sin review, la versión «Jira» es null', async () => {
    /** Límite: «null … antes de la primera versión». */
    const csrf = await login()
    const id = listed()
    await fetch(url(`/conversations/${id}`))
    const run = mockDb.runs.get(id)
    if (!run) throw new Error('Falta la conversación de ejemplo')
    run.conversation = { ...run.conversation, jira_baseline: null, review: null, state: 'in_review' }
    await post(`/conversations/${id}/iterate`, csrf, { feedback: 'Cambio ficticio' })
    const ready = await lastEvent(id)
    expect(ready?.event).toBe('review_ready')
    expect(ready?.data.jira_baseline).toBeNull()
  })

  it('la conversación de la lista abierta con GET ya trae su versión «Jira»', async () => {
    await login()
    const read = (await (await fetch(url(`/conversations/${listed()}`))).json()) as ConversationOut
    expect(read.jira_baseline?.acceptance_criteria.map((item) => item.id)).toEqual(['CA-01'])
  })
})
