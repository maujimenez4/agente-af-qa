// Editar a mano, parte A (T-56, RF-32): `POST /api/v1/conversations/{id}/edit` en la API simulada, como `_edit`
// (core/graph/nodes.py). Aún no está en `createHandlers`: cada prueba lo registra con `mockServer.use`.
// Datos sintéticos (DEMO-3, af-demo).
import { beforeEach, describe, expect, it } from 'vitest'
import type { components } from '../api/schema'
import type { ConversationOut, SessionOut } from '../api/types.ts'
import { DEMO_PASSWORD } from './db.ts'
import { diffAgainst, editHandlers, invalidStoryFields, MAX_EDIT_REJECTIONS, TOO_MANY_REJECTIONS, UNCHANGED } from './editHandler.ts'
import { example } from './examples.ts'
import { FINGERPRINT_MISMATCH } from './handlers.ts'
import { mockDb, mockServer } from './node.ts'

type UserStory = components['schemas']['UserStory']

const FINGERPRINT = '4f'.repeat(32)
const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

async function login(username = 'af-demo'): Promise<string> {
  const response = await fetch(url('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: DEMO_PASSWORD }),
  })
  return ((await response.json()) as SessionOut).csrf_token
}

function edit(id: string, csrf: string | undefined, body: unknown) {
  return fetch(url(`/conversations/${id}/edit`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  })
}

/** La conversación de ejemplo de la lista (DEMO-3, en revisión, v2). */
function listedId(): string {
  const first = mockDb.conversations[0]
  if (!first) throw new Error('Falta la conversación de ejemplo de la lista')
  return first.thread_id
}

/** Abre la conversación con el GET del MSW para que exista en `db.runs`. */
async function open(): Promise<ConversationOut> {
  const response = await fetch(url(`/conversations/${listedId()}`))
  return (await response.json()) as ConversationOut
}

const exampleStory = (): UserStory =>
  example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200').review?.artifact.content as UserStory

function editedStory(change: (story: UserStory) => void = (s) => (s.title = 'Renovar un préstamo (editado)')): UserStory {
  const story = exampleStory()
  change(story)
  return story
}

async function ready(): Promise<{ csrf: string; id: string }> {
  const csrf = await login()
  await open()
  return { csrf, id: listedId() }
}

beforeEach(() => {
  mockServer.use(...editHandlers(mockDb))
})

describe('MSW · POST /edit · errores HTTP', () => {
  it('sin sesión → 401 unauthenticated', async () => {
    /** 401 sin sesión. */
    const response = await edit(listedId(), undefined, { fingerprint: FINGERPRINT, content: editedStory() })
    expect(response.status).toBe(401)
    expect(await response.json()).toMatchObject({ error: { code: 'unauthenticated' } })
  })

  it('sin X-CSRF-Token → 403 forbidden', async () => {
    /** 403 sin X-CSRF-Token. */
    await ready()
    const response = await edit(listedId(), undefined, { fingerprint: FINGERPRINT, content: editedStory() })
    expect(response.status).toBe(403)
    expect(await response.json()).toMatchObject({ error: { code: 'forbidden' } })
  })

  it('con un X-CSRF-Token incorrecto → 403 forbidden', async () => {
    /** 403 con token que no casa. */
    await ready()
    const response = await edit(listedId(), 'token-ficticio-incorrecto', { fingerprint: FINGERPRINT, content: editedStory() })
    expect(response.status).toBe(403)
  })

  it('una conversación que no está en db.runs → 404 not_found', async () => {
    /** 404 si no hay db.runs.get(id). */
    const csrf = await login()
    const response = await edit('00000000-0000-4000-8000-000000000000', csrf, { fingerprint: FINGERPRINT, content: editedStory() })
    expect(response.status).toBe(404)
    expect(await response.json()).toMatchObject({ error: { code: 'not_found' } })
  })

  it('una conversación que no está en revisión → 409 not_in_review', async () => {
    /** 409 not_in_review. */
    const { csrf, id } = await ready()
    const run = mockDb.runs.get(id)!
    run.conversation = { ...run.conversation, state: 'generating' }
    const response = await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory() })
    expect(response.status).toBe(409)
    expect(await response.json()).toMatchObject({ error: { code: 'not_in_review' } })
  })

  it('en revisión pero sin review → 409 not_in_review', async () => {
    /** 409 sin propuesta abierta. */
    const { csrf, id } = await ready()
    const run = mockDb.runs.get(id)!
    run.conversation = { ...run.conversation, review: null }
    const response = await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory() })
    expect(response.status).toBe(409)
  })

  it.each<[string, unknown]>([
    ['huella que no es hexadecimal', { fingerprint: 'zz'.repeat(32), content: {} }],
    ['huella en mayúsculas', { fingerprint: '4F'.repeat(32), content: {} }],
    ['huella de 63 caracteres', { fingerprint: '4'.repeat(63), content: {} }],
    ['sin huella', { content: {} }],
    ['sin content', { fingerprint: FINGERPRINT }],
    ['feedback vacía', { fingerprint: FINGERPRINT, content: {}, feedback: '' }],
    ['feedback de 1001 caracteres', { fingerprint: FINGERPRINT, content: {}, feedback: 'n'.repeat(1001) }],
    ['feedback que no es texto', { fingerprint: FINGERPRINT, content: {}, feedback: 7 }],
    ['cuerpo que no es JSON', 'esto no es json'],
  ])('%s → 422 invalid_request', async (_name, body) => {
    /** 422 si la huella no es 64 hex, falta content o feedback vacía / > 1000. */
    const { csrf, id } = await ready()
    const response = await edit(id, csrf, body)
    expect(response.status).toBe(422)
    expect(await response.json()).toMatchObject({ error: { code: 'invalid_request' } })
  })

  it('feedback de 1000 caracteres se acepta', async () => {
    /** Límite: 1000 sí. */
    const { csrf, id } = await ready()
    const response = await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory(), feedback: 'n'.repeat(1000) })
    expect(response.status).toBe(200)
    expect(((await response.json()) as ConversationOut).review?.version).toBe(3)
  })

  it('feedback null se acepta', async () => {
    /** feedback opcional. */
    const { csrf, id } = await ready()
    const response = await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory(), feedback: null })
    expect(response.status).toBe(200)
  })
})

describe('MSW · POST /edit · rechazos como _edit (200 con review.error)', () => {
  async function expectRejected(body: unknown, message: string | RegExp) {
    const { csrf, id } = await ready()
    const response = await edit(id, csrf, body)
    expect(response.status).toBe(200)
    const conversation = (await response.json()) as ConversationOut
    expect(conversation.state).toBe('in_review')
    expect(conversation.review?.fingerprint).toBe(FINGERPRINT)
    expect(conversation.review?.version).toBe(2)
    expect(conversation.versions).toHaveLength(1)
    if (typeof message === 'string') expect(conversation.review?.error).toBe(message)
    else expect(conversation.review?.error).toMatch(message)
    // Queda guardado: el GET devuelve lo mismo.
    const read = (await (await fetch(url(`/conversations/${id}`))).json()) as ConversationOut
    expect(read.review?.error).toBe(conversation.review?.error)
    return conversation
  }

  it('huella distinta → FINGERPRINT_MISMATCH', async () => {
    /** Rechazo por huella distinta. */
    await expectRejected({ fingerprint: 'ab'.repeat(32), content: editedStory() }, FINGERPRINT_MISMATCH)
  })

  it('una suite → «aún no está disponible»', async () => {
    /** Rechazo de la suite. */
    const { csrf, id } = await ready()
    const run = mockDb.runs.get(id)!
    const review = run.conversation.review!
    run.conversation = { ...run.conversation, review: { ...review, artifact: { ...review.artifact, type: 'test_suite' } } }
    const response = await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory() })
    expect(response.status).toBe(200)
    const conversation = (await response.json()) as ConversationOut
    expect(conversation.review?.error).toMatch(/aún no está disponible/)
    expect(conversation.review?.version).toBe(2)
  })

  it('contenido inválido → «El contenido editado no es válido; revisa: …»', async () => {
    /** Rechazo por contenido inválido con los campos. */
    const content = editedStory((s) => {
      s.title = ''
      s.acceptance_criteria[0]!.given = []
    })
    await expectRejected({ fingerprint: FINGERPRINT, content }, 'El contenido editado no es válido; revisa: acceptance_criteria.0.given, title.')
  })

  it('el mensaje de contenido inválido lista como mucho 8 campos', async () => {
    /** Como mucho 8 campos. */
    const content = editedStory((s) => {
      s.title = ''
      s.acceptance_criteria = s.acceptance_criteria.map((item) => ({ ...item, id: 'x', title: '', given: [], when: [], then: [] }))
    })
    const conversation = await expectRejected({ fingerprint: FINGERPRINT, content }, /^El contenido editado no es válido; revisa: /)
    const listed = conversation.review!.error!.replace(/^.*revisa: /, '').replace(/\.$/, '').split(', ')
    expect(listed).toHaveLength(8)
    expect(invalidStoryFields(content).length).toBeGreaterThan(8)
  })

  it('jira_key cambiada → rechazo', async () => {
    /** jira_key no se puede cambiar. */
    await expectRejected({ fingerprint: FINGERPRINT, content: editedStory((s) => (s.jira_key = 'DEMO-99')) }, 'El campo jira_key no se puede cambiar al editar.')
  })

  it('internal_id cambiado → rechazo', async () => {
    /** internal_id no se puede cambiar. */
    await expectRejected({ fingerprint: FINGERPRINT, content: editedStory((s) => (s.internal_id = 'HU-99')) }, 'El campo internal_id no se puede cambiar al editar.')
  })

  it('sin cambios → UNCHANGED', async () => {
    /** Rechazo sin cambios. */
    await expectRejected({ fingerprint: FINGERPRINT, content: exampleStory() }, UNCHANGED)
  })

  it('sin cambios aunque las claves vengan en otro orden → UNCHANGED', async () => {
    /** Comparación estructural sin importar el orden de claves. */
    const reversed = Object.fromEntries(Object.entries(exampleStory()).reverse())
    await expectRejected({ fingerprint: FINGERPRINT, content: reversed }, UNCHANGED)
  })
})

describe('MSW · POST /edit · demasiados rechazos', () => {
  it(`${MAX_EDIT_REJECTIONS} rechazos dan 200 y el siguiente, 409 restart`, async () => {
    /** Más de 20 rechazos seguidos → 409 restart. */
    expect(MAX_EDIT_REJECTIONS).toBe(20)
    const { csrf, id } = await ready()
    for (let i = 0; i < MAX_EDIT_REJECTIONS; i++) {
      const response = await edit(id, csrf, { fingerprint: FINGERPRINT, content: exampleStory() })
      expect(response.status, `rechazo ${i + 1}`).toBe(200)
    }
    const response = await edit(id, csrf, { fingerprint: FINGERPRINT, content: exampleStory() })
    expect(response.status).toBe(409)
    expect(await response.json()).toMatchObject({ error: { code: 'restart', message: TOO_MANY_REJECTIONS } })
  })

  it('un éxito reinicia el contador de rechazos', async () => {
    /** Contador reiniciado tras un éxito. */
    const { csrf, id } = await ready()
    for (let i = 0; i < MAX_EDIT_REJECTIONS; i++) await edit(id, csrf, { fingerprint: FINGERPRINT, content: exampleStory() })
    const ok = (await (await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory() })).json()) as ConversationOut
    expect(ok.review?.version).toBe(3)
    expect(ok.review?.error).toBeNull()
    const fingerprint = ok.review!.fingerprint
    const original = ok.review!.artifact.content as UserStory
    for (let i = 0; i < MAX_EDIT_REJECTIONS; i++) {
      const response = await edit(id, csrf, { fingerprint, content: original })
      expect(response.status, `rechazo ${i + 1} tras el éxito`).toBe(200)
    }
    expect((await edit(id, csrf, { fingerprint, content: original })).status).toBe(409)
  })

  it('los errores HTTP (422) no cuentan como rechazos', async () => {
    /** Solo los rechazos de _edit cuentan. */
    const { csrf, id } = await ready()
    for (let i = 0; i < MAX_EDIT_REJECTIONS + 2; i++) await edit(id, csrf, { fingerprint: 'no-hex', content: {} })
    expect((await edit(id, csrf, { fingerprint: FINGERPRINT, content: exampleStory() })).status).toBe(200)
  })
})

describe('MSW · POST /edit · éxito', () => {
  it('crea la versión 3 con huella nueva, sin error y con edited: true', async () => {
    /** Éxito: versión+1, huella nueva de 64 hex, review.error null, versions con edited: true. */
    const { csrf, id } = await ready()
    const content = editedStory()
    const response = await edit(id, csrf, { fingerprint: FINGERPRINT, content, feedback: 'Nota ficticia' })
    expect(response.status).toBe(200)
    const conversation = (await response.json()) as ConversationOut
    expect(conversation.state).toBe('in_review')
    expect(conversation.review?.version).toBe(3)
    expect(conversation.review?.artifact.version).toBe(3)
    expect(conversation.review?.artifact.content).toEqual(content)
    expect(conversation.review?.error).toBeNull()
    expect(conversation.review?.fingerprint).toMatch(/^[0-9a-f]{64}$/)
    expect(conversation.review?.fingerprint).not.toBe(FINGERPRINT)
    expect(conversation.versions.map((item) => [item.version, item.edited])).toEqual([
      [2, false],
      [3, true],
    ])
    const read = (await (await fetch(url(`/conversations/${id}`))).json()) as ConversationOut
    expect(read.review?.version).toBe(3)
  })

  it('recalcula los diffs frente a jira_baseline: CA-01 cambiado y sin CA-02', async () => {
    /** impact.diffs con el formato del ejemplo (acceptance_criteria.CA-0X). */
    const { csrf, id } = await ready()
    const content = editedStory((s) => {
      s.acceptance_criteria[0]!.title = 'Renovación permitida (editado)'
      s.acceptance_criteria = s.acceptance_criteria.slice(0, 1)
    })
    const conversation = (await (await edit(id, csrf, { fingerprint: FINGERPRINT, content })).json()) as ConversationOut
    // El CA entero, como `_criterion_text` (core/impact/diff.py): título y pasos.
    const ca01 = exampleStory().acceptance_criteria[0]!
    const steps = [...ca01.given.map((x) => `Dado ${x}`), ...ca01.when.map((x) => `Cuando ${x}`), ...ca01.then.map((x) => `Entonces ${x}`)]
    const expected = [
      { field: 'acceptance_criteria.CA-01', before: ['Renovación permitida', ...steps].join('\n'), after: ['Renovación permitida (editado)', ...steps].join('\n') },
    ]
    expect(conversation.review?.impact?.diffs).toEqual(expected)
    expect(conversation.review?.artifact.impact?.diffs).toEqual(expected)
    // Lo demás del análisis de impacto se conserva.
    expect(conversation.review?.impact?.affected).toEqual([{ jira_key: 'DEMO-2', reason: 'Comparte la regla de reservas', kind: 'rule' }])
  })

  it('actualiza el resumen de la lista con la versión nueva', async () => {
    /** Resumen de la lista con la versión nueva. */
    const { csrf, id } = await ready()
    const before = mockDb.conversations.find((item) => item.thread_id === id)!.updated_at
    await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory() })
    const summary = mockDb.conversations.find((item) => item.thread_id === id)!
    expect(summary).toMatchObject({ status: 'in_review', version: 3 })
    expect(summary.updated_at).not.toBe(before)
    const list = (await (await fetch(url('/conversations'))).json()) as Array<{ thread_id: string; version: number }>
    expect(list.find((item) => item.thread_id === id)?.version).toBe(3)
  })

  it('una segunda edición parte de la nueva huella: con la antigua se rechaza', async () => {
    /** La huella cambia con cada versión. */
    const { csrf, id } = await ready()
    const first = (await (await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory() })).json()) as ConversationOut
    const stale = (await (await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory((s) => (s.title = 'Otro')) })).json()) as ConversationOut
    expect(stale.review?.error).toBe(FINGERPRINT_MISMATCH)
    expect(stale.review?.version).toBe(3)
    const second = (await (
      await edit(id, csrf, { fingerprint: first.review!.fingerprint, content: editedStory((s) => (s.title = 'Otro')) })
    ).json()) as ConversationOut
    expect(second.review?.version).toBe(4)
    expect(second.versions.map((item) => item.version)).toEqual([2, 3, 4])
  })

  it('tras un rechazo, un éxito limpia review.error', async () => {
    /** review.error null tras éxito. */
    const { csrf, id } = await ready()
    await edit(id, csrf, { fingerprint: FINGERPRINT, content: exampleStory() })
    const ok = (await (await edit(id, csrf, { fingerprint: FINGERPRINT, content: editedStory() })).json()) as ConversationOut
    expect(ok.review?.error).toBeNull()
  })
})

describe('diffAgainst e invalidStoryFields', () => {
  it('diffAgainst: un paso o una lista cambiados dan diff, y los CA salen ordenados por número', () => {
    const base = exampleStory()
    const story = structuredClone(base)
    story.acceptance_criteria[0]!.then = [...story.acceptance_criteria[0]!.then, 'se avisa por correo (ficticio)']
    story.scope_excludes = [...story.scope_excludes, 'Pagos (ficticio)']
    story.acceptance_criteria.push({ id: 'CA-10', title: 'Décimo', given: ['a'], when: ['b'], then: ['c'] }, { id: 'CA-9', title: 'Noveno', given: ['a'], when: ['b'], then: ['c'] })
    const fields = diffAgainst(base, story).map((diff) => diff.field)
    expect(fields).toEqual(['scope_excludes', 'acceptance_criteria.CA-01', 'acceptance_criteria.CA-9', 'acceptance_criteria.CA-10'])
  })

  it('diffAgainst sin cambios no da diffs', () => {
    /** Diff vacío entre iguales. */
    expect(diffAgainst(exampleStory(), exampleStory())).toEqual([])
  })

  it('diffAgainst da before null en un CA añadido y after null en uno quitado', () => {
    /** Emparejado por id. */
    const base = exampleStory()
    const story = editedStory((s) => {
      s.title = base.title
      s.acceptance_criteria = [s.acceptance_criteria[1]!]
    })
    const ca01 = base.acceptance_criteria[0]!
    const text = [ca01.title, ...ca01.given.map((x) => `Dado ${x}`), ...ca01.when.map((x) => `Cuando ${x}`), ...ca01.then.map((x) => `Entonces ${x}`)].join('\n')
    expect(diffAgainst(base, story)).toEqual([{ field: 'acceptance_criteria.CA-01', before: text, after: null }])
    expect(diffAgainst(story, base)).toEqual([{ field: 'acceptance_criteria.CA-01', before: null, after: text }])
  })

  it('invalidStoryFields acepta la HU del ejemplo y rechaza lo que no es un objeto', () => {
    /** Validación del contenido como UserStory. */
    expect(invalidStoryFields(exampleStory())).toEqual([])
    expect(invalidStoryFields(null)).toEqual(['contenido'])
    expect(invalidStoryFields('texto')).toEqual(['contenido'])
  })

  it('invalidStoryFields detecta ids repetidos y prioridad desconocida', () => {
    /** ids repetidos y priority. */
    const story = editedStory((s) => {
      s.acceptance_criteria[1]!.id = 'CA-01'
      ;(s as { priority: string }).priority = 'Urgente'
    })
    expect(invalidStoryFields(story)).toEqual(['ids', 'priority'])
  })
})
