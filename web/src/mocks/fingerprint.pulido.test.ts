// Pulido final (ensayo de la demo): en la API simulada, toda versión nueva lleva una huella con el formato del
// contrato (64 hexadecimales). Antes, iterar daba «huella-ficticia-…» y editar a mano tras iterar respondía 422.
// Datos sintéticos (DEMO-3, af-demo).
import { describe, expect, it } from 'vitest'
import type { ConversationOut } from '../api/types.ts'
import type { UserStory } from '../components/Proposal/index.ts'
import { DEMO_PASSWORD } from './db.ts'
import { randomFingerprint } from './fingerprint.ts'
import { mockSuiteConversation, nextSuiteVersion } from './qaSuite.ts'

const HEX64 = /^[0-9a-f]{64}$/
const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

async function login(): Promise<string> {
  const response = await fetch(url('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'af-demo', password: DEMO_PASSWORD }),
  })
  return ((await response.json()) as { csrf_token: string }).csrf_token
}

const post = (path: string, csrf: string, body: unknown) =>
  fetch(url(path), { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(body) })

/** Sigue el SSE hasta el final y devuelve el estado de la conversación. */
async function settle(id: string): Promise<ConversationOut> {
  await (await fetch(url(`/conversations/${id}/events`))).text()
  return (await (await fetch(url(`/conversations/${id}`))).json()) as ConversationOut
}

describe('API simulada · huellas con el formato del contrato', () => {
  it('test_random_fingerprint_is_64_hex_and_changes', () => {
    expect(randomFingerprint()).toMatch(HEX64)
    expect(randomFingerprint()).not.toBe(randomFingerprint())
  })

  it('test_next_suite_version_fingerprint_is_64_hex', () => {
    expect(nextSuiteVersion(mockSuiteConversation('DEMO-3'), 'Añade un caso ficticio').review?.fingerprint).toMatch(HEX64)
  })

  it('test_edit_after_iterate_saves_instead_of_422', async () => {
    const csrf = await login()
    const created = (await (await post('/conversations', csrf, { origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, flow: 'evolve', excluded_sources: [], feedback: [] })).json()) as ConversationOut
    await settle(created.id)
    await post(`/conversations/${created.id}/iterate`, csrf, { feedback: 'Añade un criterio de error (ficticio)' })
    const iterated = await settle(created.id)
    const review = iterated.review
    expect(review?.fingerprint).toMatch(HEX64)
    const content = { ...(review?.artifact.content as UserStory), title: 'Título editado a mano (ficticio)' }
    const response = await post(`/conversations/${created.id}/edit`, csrf, { fingerprint: review?.fingerprint, content, feedback: 'Nota ficticia' })
    expect(response.status).toBe(200)
    const edited = (await response.json()) as ConversationOut
    expect(edited.review?.error ?? null).toBeNull()
    expect(edited.review?.version).toBe((review?.version ?? 0) + 1)
  })
})
