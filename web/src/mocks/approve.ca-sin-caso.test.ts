// T-56 · pulido final, bloque 2: la API simulada rechaza aprobar una suite con algún CA sin caso (vuelve a
// `in_review` con `review.error`, sin publicar); las RN sin caso no bloquean. Datos sintéticos (DEMO-3, qa-demo).
import { describe, expect, it } from 'vitest'
import type { ConversationOut } from '../api/types.ts'
import { DEMO_PASSWORD } from './db.ts'
import { uncoveredCriteriaRejection } from './handlers.ts'
import { mockDb } from './node.ts'
import { MOCK_UNCOVERED } from './qaSuite.ts'

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

async function login(username = 'qa-demo'): Promise<string> {
  const response = await fetch(url('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password: DEMO_PASSWORD }),
  })
  return ((await response.json()) as { csrf_token: string }).csrf_token
}

function post(path: string, csrf: string, body: unknown = {}) {
  return fetch(url(path), { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify(body) })
}

/** El último evento del SSE (el final: `review_ready` o `result`). */
async function lastEvent(id: string): Promise<{ event: string; data: ConversationOut }> {
  const text = await (await fetch(url(`/conversations/${id}/events`))).text()
  const block = text.split('\n\n').filter(Boolean).at(-1) ?? ''
  return { event: /^event: (.*)$/m.exec(block)?.[1] ?? '', data: JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? 'null') as ConversationOut }
}

/** Suite de DEMO-3 en revisión; `uncovered`, si se da, se fija en la revisión del servidor antes de aprobar. */
async function suiteInReview(csrf: string, uncovered?: { criteria: string[]; rules: string[] }): Promise<ConversationOut> {
  const created = (await (await post('/conversations', csrf, { origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, flow: 'tests', excluded_sources: [], feedback: [] })).json()) as ConversationOut
  const { data } = await lastEvent(created.id)
  const run = mockDb.runs.get(created.id)
  if (uncovered && run?.conversation.review) run.conversation.review.uncovered = uncovered
  return run?.conversation ?? data
}

async function approve(csrf: string, conversation: ConversationOut) {
  const response = await post(`/conversations/${conversation.id}/approve`, csrf, { fingerprint: conversation.review?.fingerprint })
  return { status: response.status, final: await lastEvent(conversation.id) }
}

describe('API simulada · aprobar una suite con CA sin caso', () => {
  it('test_approve_suite_with_uncovered_criterion_returns_to_review_with_error', async () => {
    /** Criterio 5: con CA-03 sin caso (?simular=sin-cubrir), vuelve a `in_review` con `review.error` y sin `result`. */
    mockDb.forceCoverage = 'gaps'
    const csrf = await login()
    const reviewing = await suiteInReview(csrf)
    expect(reviewing.review?.uncovered).toEqual(MOCK_UNCOVERED)
    const { status, final } = await approve(csrf, reviewing)
    // Como la API real: 202 y el final por el SSE (no es un error HTTP).
    expect(status).toBe(202)
    expect(final.event).toBe('review_ready')
    expect(final.data.state).toBe('in_review')
    expect(final.data.review?.error).toBe(uncoveredCriteriaRejection(['CA-03']))
    expect(final.data.result ?? null).toBeNull()
    // La misma revisión: misma huella y los mismos huecos.
    expect(final.data.review?.fingerprint).toBe(reviewing.review?.fingerprint)
    expect(final.data.review?.uncovered).toEqual(MOCK_UNCOVERED)
  })

  it('test_get_conversation_after_rejection_is_still_in_review_with_error', async () => {
    /** Criterio 5: GET /conversations/{id} tras el rechazo da lo mismo que el SSE; nada publicado. */
    mockDb.forceCoverage = 'gaps'
    const csrf = await login()
    const reviewing = await suiteInReview(csrf)
    await approve(csrf, reviewing)
    const current = (await (await fetch(url(`/conversations/${reviewing.id}`))).json()) as ConversationOut
    expect(current.state).toBe('in_review')
    expect(current.review?.error).toBe(uncoveredCriteriaRejection(['CA-03']))
    expect(current.result ?? null).toBeNull()
  })

  it('test_approve_suite_with_uncovered_criterion_does_not_publish_even_in_live_mode', async () => {
    /** Criterio 5 (negativo): con `?simular=publicado` tampoco se publica: el CA sin caso va antes. */
    mockDb.forceCoverage = 'gaps'
    mockDb.forceApprove = 'published'
    const csrf = await login()
    const { final } = await approve(csrf, await suiteInReview(csrf))
    expect(final.data.state).toBe('in_review')
    expect(final.data.review?.error).toBe(uncoveredCriteriaRejection(['CA-03']))
    expect(final.data.result ?? null).toBeNull()
  })

  it('test_rejection_lists_every_uncovered_criterion', async () => {
    /** Criterio 5 (límite): con varios CA sin caso, el rechazo los nombra todos. */
    const csrf = await login()
    const { final } = await approve(csrf, await suiteInReview(csrf, { criteria: ['CA-02', 'CA-03'], rules: [] }))
    expect(final.data.review?.error).toBe(uncoveredCriteriaRejection(['CA-02', 'CA-03']))
    expect(final.data.review?.error).toContain('CA-02, CA-03')
  })

  it('test_approve_suite_with_only_uncovered_rules_is_simulated', async () => {
    /** Criterio 5: con solo RN sin caso, la aprobación sigue normal (simulada) y sin `review.error`. */
    const csrf = await login()
    const { final } = await approve(csrf, await suiteInReview(csrf, { criteria: [], rules: ['RN-03'] }))
    expect(final.event).toBe('result')
    expect(final.data.state).toBe('simulated')
    expect(final.data.review).toBeNull()
    expect(final.data.result?.simulated).toBe(true)
    expect(final.data.result?.approved_by).toBe('qa-demo')
  })

  it('test_approve_suite_with_only_uncovered_rules_publishes_in_live_mode', async () => {
    /** Criterio 5: con solo RN sin caso y publicación real simulada, se crean las subtareas. */
    mockDb.forceApprove = 'published'
    const csrf = await login()
    const { final } = await approve(csrf, await suiteInReview(csrf, { criteria: [], rules: ['RN-03'] }))
    expect(final.event).toBe('result')
    expect(final.data.state).toBe('published')
    expect(final.data.result?.simulated).toBe(false)
    expect(final.data.result?.published_keys.length).toBeGreaterThan(0)
  })

  it.each([
    ['todo cubierto', { criteria: [], rules: [] }],
    ['sin saber (null)', null],
  ] as const)('test_approve_suite_with_%s_is_simulated', async (_name, uncovered) => {
    /** Criterio 5: sin CA sin caso conocido, la API simulada no rechaza. */
    const csrf = await login()
    const reviewing = await suiteInReview(csrf)
    const run = mockDb.runs.get(reviewing.id)
    if (run?.conversation.review) run.conversation.review.uncovered = uncovered === null ? null : { criteria: [...uncovered.criteria], rules: [...uncovered.rules] }
    const { final } = await approve(csrf, reviewing)
    expect(final.data.state).toBe('simulated')
    expect(final.data.result?.simulated).toBe(true)
  })
})
