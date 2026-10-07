// Editar a mano, parte B (T-56, RF-32): `api.edit` (POST /conversations/{id}/edit) con CSRF, huella, contenido y
// `feedback` solo si la nota no está vacía. Datos del ejemplo del contrato (DEMO-3, af-demo: sintéticos).
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import examples from './examples.json'
import { api, ApiRequestError, setCsrfToken } from './client.ts'
import type { ConversationOut, EditIn } from './types.ts'
import type { UserStory } from '../screens/Edit/storyDraft.ts'
import { mockDb, mockServer } from '../mocks/node.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const EXAMPLE_ID = EXAMPLE.id
const FINGERPRINT = EXAMPLE.review?.fingerprint ?? ''
const CSRF = 'csrf-ficticio'
const story = () => ({ ...(EXAMPLE.review?.artifact.content as UserStory), title: 'Renovar un préstamo ficticio' })

interface Seen {
  method: string
  path: string
  csrf: string | null
  body: Partial<EditIn> & Record<string, unknown>
}

/** Sustituye el handler de la API simulada para ver la petición tal cual y responder con el ejemplo. */
function captureEdit(): Seen[] {
  const seen: Seen[] = []
  mockServer.use(
    http.post('/api/v1/conversations/:id/edit', async ({ request }) => {
      seen.push({
        method: request.method,
        path: new URL(request.url).pathname,
        csrf: request.headers.get('X-CSRF-Token'),
        body: (await request.json()) as Seen['body'],
      })
      return HttpResponse.json(EXAMPLE)
    }),
  )
  return seen
}

beforeEach(() => {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: CSRF }
  setCsrfToken(CSRF)
})

afterEach(() => {
  mockServer.resetHandlers()
})

describe('api.edit (parte B)', () => {
  it('test_edit_posts_csrf_fingerprint_content_and_feedback_when_note_given', async () => {
    /** CA 1: POST /conversations/{id}/edit con X-CSRF-Token, fingerprint, content y feedback. */
    const seen = captureEdit()
    const content = story()
    await api.edit(EXAMPLE_ID, FINGERPRINT, content, 'Nota ficticia de la edición')
    expect(seen).toHaveLength(1)
    expect(seen[0]?.method).toBe('POST')
    expect(seen[0]?.path).toBe(`/api/v1/conversations/${EXAMPLE_ID}/edit`)
    expect(seen[0]?.csrf).toBe(CSRF)
    expect(seen[0]?.body).toEqual({ fingerprint: FINGERPRINT, content, feedback: 'Nota ficticia de la edición' })
  })

  it.each([
    ['sin nota', undefined],
    ['con null', null],
    ['con cadena vacía', ''],
    ['solo con espacios', '   \n  '],
  ])('test_edit_omits_feedback_when_note_empty: %s, sin la clave feedback', async (_label, note) => {
    /** CA 1: `feedback` solo si la nota no está vacía (ni siquiera `feedback: null`). */
    const seen = captureEdit()
    await api.edit(EXAMPLE_ID, FINGERPRINT, story(), note)
    expect(seen[0]?.body).not.toHaveProperty('feedback')
    expect(Object.keys(seen[0]?.body ?? {}).sort()).toEqual(['content', 'fingerprint'])
  })

  it('test_edit_encodes_id_when_it_has_reserved_characters', async () => {
    /** CA 1 (límite): el id va codificado en la ruta, sin salirse de /conversations/{id}/edit. */
    const seen: string[] = []
    mockServer.use(
      http.post('/api/v1/conversations/:id/edit', ({ request }) => {
        seen.push(new URL(request.url).pathname)
        return HttpResponse.json(EXAMPLE)
      }),
    )
    await api.edit('demo/../3', FINGERPRINT, story(), null)
    expect(seen).toEqual(['/api/v1/conversations/demo%2F..%2F3/edit'])
  })

  it('test_edit_returns_next_version_when_mock_api_accepts', async () => {
    /** CA 1 contra la API simulada: la respuesta es la versión 3, editada a mano y con huella nueva. */
    const next = await api.edit(EXAMPLE_ID, FINGERPRINT, story(), 'Nota ficticia')
    expect(next.review?.version).toBe(3)
    expect(next.review?.fingerprint).not.toBe(FINGERPRINT)
    expect(next.review?.error ?? null).toBeNull()
    expect(next.versions.at(-1)).toMatchObject({ version: 3, edited: true })
  })

  it('test_edit_rejected_with_403_when_csrf_missing', async () => {
    /** CA 1 (negativa): sin el token anti-CSRF en memoria, la API simulada responde 403 y llega como ApiRequestError. */
    setCsrfToken(null)
    const failure = await api.edit(EXAMPLE_ID, FINGERPRINT, story(), null).catch((cause: unknown) => cause)
    expect(failure).toBeInstanceOf(ApiRequestError)
    expect((failure as ApiRequestError).status).toBe(403)
    expect((failure as ApiRequestError).error.code).toBe('forbidden')
  })
})
