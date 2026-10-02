import { describe, expect, it } from 'vitest'
import type { ConversationOut, ProgressStep, SessionOut } from '../api/types.ts'
import { DEMO_PASSWORD } from './db.ts'
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

function post(path: string, body: unknown, csrf: string) {
  return fetch(url(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body),
  })
}

async function readEvents(response: Response): Promise<Array<{ event: string; data: unknown }>> {
  const text = await response.text()
  return text
    .split('\n\n')
    .filter(Boolean)
    .map((block) => {
      const event = /^event: (.*)$/m.exec(block)?.[1] ?? ''
      const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? 'null') as unknown
      return { event, data }
    })
}

describe('API simulada (MSW) con los ejemplos del contrato', () => {
  it('sin sesión responde 401 unauthenticated', async () => {
    const response = await fetch(url('/auth/me'))
    expect(response.status).toBe(401)
    expect(await response.json()).toMatchObject({ error: { code: 'unauthenticated' } })
  })

  it('el login con un usuario demo da la sesión con su rol y permisos', async () => {
    await login('qa-demo')
    const me = (await (await fetch(url('/auth/me'))).json()) as SessionOut
    expect(me.user).toEqual({
      username: 'qa-demo',
      role: 'qa',
      permissions: ['view_context', 'generate_tests', 'publish_tests', 'view_memory'],
    })
  })

  it('una contraseña incorrecta da 401 invalid_credentials', async () => {
    const response = await fetch(url('/auth/login'), {
      method: 'POST',
      body: JSON.stringify({ username: 'af-demo', password: 'otra' }),
    })
    expect(response.status).toBe(401)
    expect(await response.json()).toMatchObject({ error: { code: 'invalid_credentials' } })
  })

  it('lo que modifica algo exige X-CSRF-Token', async () => {
    await login()
    const sin = await fetch(url('/projects/choose'), { method: 'POST', body: JSON.stringify({ project: 'DEMO' }) })
    expect(sin.status).toBe(403)
    const conToken = await post('/projects/choose', { project: 'SOCI' }, mockDb.session?.csrf ?? '')
    expect(conToken.status).toBe(200)
    expect(mockDb.projects.preselected).toBe('SOCI')
  })

  it('proyectos, épicas, HU y búsqueda salen del Jira simulado', async () => {
    await login()
    expect(await (await fetch(url('/projects'))).json()).toMatchObject({ preselected: 'DEMO' })
    expect(await (await fetch(url('/projects/DEMO/epics'))).json()).toEqual([
      { key: 'DEMO-1', summary: 'Préstamo digital', issue_type: 'Epic', status: 'Abierta' },
    ])
    const stories = (await (await fetch(url('/epics/DEMO-1/stories'))).json()) as Array<{ key: string }>
    expect(stories.map((story) => story.key)).toEqual(['DEMO-2', 'DEMO-3', 'DEMO-4'])
    const found = (await (await fetch(url('/projects/DEMO/search?q=prestamo'))).json()) as Array<{ key: string }>
    expect(found.map((issue) => issue.key)).toContain('DEMO-3')
  })

  it('una incidencia que no existe da 404 not_found con su mensaje', async () => {
    await login()
    const response = await fetch(url('/issues/DEMO-99'))
    expect(response.status).toBe(404)
    expect(await response.json()).toMatchObject({
      error: { code: 'not_found', message: 'La incidencia DEMO-99 no existe o no tienes permiso para verla.' },
    })
  })

  it('el arranque guiado reconoce una clave escrita en el texto', async () => {
    const csrf = await login()
    const proposal = await (await post('/start/propose', { text: 'Cambiar DEMO-3', project: 'DEMO', mode: 'functional' }, csrf)).json()
    expect(proposal).toMatchObject({ recognized: [{ key: 'DEMO-3' }] })
  })

  it('crear una conversación responde 202 y el SSE emite los pasos uno a uno y review_ready', async () => {
    const csrf = await login()
    const created = await post(
      '/conversations',
      { flow: 'evolve', origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, excluded_sources: [], feedback: [] },
      csrf,
    )
    expect(created.status).toBe(202)
    const conversation = (await created.json()) as ConversationOut
    expect(conversation.state).toBe('generating')

    const events = await readEvents(await fetch(url(`/conversations/${conversation.id}/events`)))
    const progress = events.filter((item) => item.event === 'progress').map((item) => item.data as ProgressStep)
    expect(progress.map((step) => `${step.node}:${step.state}`)).toEqual([
      'load_origin:running',
      'load_origin:done',
      'retrieve_context:running',
      'retrieve_context:done',
      'generate:running',
      'generate:done',
    ])
    expect(progress.every((step) => step.label.length > 0)).toBe(true)
    expect(events.at(-1)?.event).toBe('review_ready')
    expect(events.at(-1)?.data).toMatchObject({ id: conversation.id, state: 'in_review' })

    const after = (await (await fetch(url(`/conversations/${conversation.id}`))).json()) as ConversationOut
    expect(after.state).toBe('in_review')
    expect(after.review?.fingerprint).toBeTruthy()
  })

  it('el consumo de hoy es global y, si no se puede leer, da 503', async () => {
    await login()
    expect(await (await fetch(url('/settings/usage'))).json()).toEqual({
      tokens_today: 42000,
      warning_threshold: 180000,
      scope: 'global',
    })
    mockDb.usage = 'unavailable'
    const response = await fetch(url('/settings/usage'))
    expect(response.status).toBe(503)
  })

  it('lo que aún no simula responde 501 not_implemented', async () => {
    const csrf = await login()
    const response = await post('/qa/handoffs/x/take', {}, csrf)
    expect(response.status).toBe(501)
    expect(await response.json()).toMatchObject({ error: { code: 'not_implemented' } })
  })
})
