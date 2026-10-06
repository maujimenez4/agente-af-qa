// Huecos de prueba de QA 2 · Generando (UI.md §6.2 y §7): `coverage_failed` al generar la suite, *Volver a generar*
// con POST /retry, `onReviewReady` una sola vez y titulares límite. Datos sintéticos (DEMO-3, qa-demo).
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { mockSuiteConversation } from '../../mocks/qaSuite.ts'
import { generateSuiteForDemo3 } from '../../test/qaFlow.tsx'
import { GeneratingScreen } from './GeneratingScreen.tsx'
import { qaHeaderTitle, readyHeadline } from './headline.ts'

const TAKEN = examples['POST /api/v1/qa/handoffs/{handoff_id}/take 202'] as unknown as ConversationOut
const SUITE = mockSuiteConversation('DEMO-3')

/** Mensaje de `CoverageError` (UI.md §7), tal cual. */
const COVERAGE_MESSAGE =
  'La suite de pruebas no cubre la HU: algún criterio no tiene casos, faltan casos positivos o negativos, se referencian CA/RN inexistentes o hay datos que parecen personales. Vuelve a generarla.'

function sse(event: string, data: unknown) {
  return new HttpResponse(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
}

const coverageFailed = (conversation: ConversationOut): ConversationOut => ({
  ...conversation,
  state: 'error',
  error: { code: 'coverage_failed', message: COVERAGE_MESSAGE, retry_after: null },
})

afterEach(() => mockServer.events.removeAllListeners())

describe('readyHeadline / qaHeaderTitle · límites', () => {
  it('test_ready_headline_without_review_uses_last_version_and_omits_cases', () => {
    // UI.md §6.2: «Suite lista · Versión N · N casos»; sin revisión no se sabe cuántos casos hay.
    expect(readyHeadline({ ...SUITE, review: null })).toBe('Suite lista · Versión 1')
  })

  it('test_ready_headline_with_zero_cases_uses_plural', () => {
    // UI.md §6.2: titular con el número de casos; 0 en plural.
    const empty = structuredClone(SUITE)
    const content = empty.review?.artifact.content
    if (content && 'cases' in content) content.cases = []
    expect(readyHeadline(empty)).toBe('Suite lista · Versión 1 · 0 casos')
  })

  it('test_qa_header_title_only_replaces_the_prefix', () => {
    // UI.md §6.2 (lienzo QaGenerando): cabecera «Pruebas de DEMO-3»; solo cambia el prefijo.
    expect(qaHeaderTitle('Revisar Preparar pruebas de DEMO-3')).toBe('Revisar Preparar pruebas de DEMO-3')
    expect(qaHeaderTitle('')).toBe('')
  })
})

describe('QA 2 · coverage_failed (UI.md §7)', () => {
  it('test_coverage_failed_shows_card_title_and_message_verbatim', async () => {
    // UI.md §6.2 («CoverageError si no se cumple») y §7: título «La suite no es válida» y el mensaje tal cual.
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse('error', coverageFailed(TAKEN))))
    render(<GeneratingScreen conversation={TAKEN} onReady={vi.fn()} onRetry={vi.fn()} />)
    const card = await screen.findByRole('alert')
    expect(card).toHaveTextContent('La suite no es válida')
    expect(card).toHaveTextContent(COVERAGE_MESSAGE)
    expect(within(card).getByRole('button', { name: 'Volver a generar' })).toBeInTheDocument()
    // La suite no llega al panel ni se ofrece *Ver la suite*.
    expect(screen.queryByRole('button', { name: 'Ver la suite' })).toBeNull()
    expect(within(screen.getByRole('complementary', { name: 'Suite de pruebas' })).getByText('La suite aparece aquí cuando la cobertura está comprobada.')).toBeInTheDocument()
  })

  it('test_coverage_failed_regenerate_calls_retry_and_reaches_ready', async () => {
    // UI.md §7: *Volver a generar* repite el paso con POST /retry (PA-276) y la suite llega con su titular.
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    const retried = { ...TAKEN, state: 'generating' as const, error: null }
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => sse('error', coverageFailed(TAKEN)), { once: true }),
      http.post('/api/v1/conversations/:id/retry', () => HttpResponse.json(retried, { status: 202 })),
      http.get('/api/v1/conversations/:id/events', () => sse('review_ready', { ...SUITE, id: TAKEN.id, title: TAKEN.title })),
    )
    const onRetry = vi.fn()
    render(<GeneratingScreen conversation={TAKEN} onReady={vi.fn()} onRetry={onRetry} />)
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Volver a generar' }))
    expect(await screen.findByRole('heading', { name: 'Suite lista · Versión 1 · 4 casos' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ver la suite' })).toBeInTheDocument()
    expect(onRetry).not.toHaveBeenCalled()
  })

  it('test_coverage_failed_in_the_app_keeps_the_qa_header', async () => {
    // UI.md §6.2: la cabecera sigue siendo «Pruebas de DEMO-3» aunque la generación falle.
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', ({ params }) => {
        const run = mockDb.runs.get(String(params.id))
        return sse('error', coverageFailed(run?.conversation ?? TAKEN))
      }),
    )
    await generateSuiteForDemo3()
    const card = await screen.findByRole('alert')
    expect(card).toHaveTextContent('La suite no es válida')
    expect(screen.getByRole('heading', { level: 1, name: 'Pruebas de DEMO-3' })).toBeInTheDocument()
  })
})

describe('QA 2 · review_ready', () => {
  it('test_on_review_ready_is_called_once_when_suite_arrives', async () => {
    // UI.md §6.2 (titular → *Ver la suite*) y PA-327: la lista se recarga una vez al llegar la suite.
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse('review_ready', { ...SUITE, id: TAKEN.id, title: TAKEN.title })))
    const onReviewReady = vi.fn()
    const onReady = vi.fn()
    render(<GeneratingScreen conversation={TAKEN} onReady={onReady} onRetry={vi.fn()} onReviewReady={onReviewReady} />)
    await screen.findByRole('button', { name: 'Ver la suite' })
    // El aviso llega en un efecto, después de pintar: se espera a él.
    await waitFor(() => expect(onReviewReady).toHaveBeenCalledTimes(1))
    // *Ver la suite* entrega la conversación con la suite.
    await userEvent.click(screen.getByRole('button', { name: 'Ver la suite' }))
    expect(onReady).toHaveBeenCalledTimes(1)
    expect((onReady.mock.calls[0]?.[0] as ConversationOut).review?.artifact.type).toBe('test_suite')
    expect(onReviewReady).toHaveBeenCalledTimes(1)
  })

  it('test_ready_suite_disables_stop_and_fills_the_q', async () => {
    // UI.md §6.2 y PA-327: con la suite lista ya no hay nada que detener y la Q está completa.
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse('review_ready', { ...SUITE, id: TAKEN.id, title: TAKEN.title })))
    render(<GeneratingScreen conversation={TAKEN} onReady={vi.fn()} onRetry={vi.fn()} />)
    await screen.findByRole('button', { name: 'Ver la suite' })
    expect(screen.queryByRole('button', { name: 'Detener la generación' })).toBeNull()
    expect(screen.getByRole('status').querySelector('[data-q-state]')?.getAttribute('data-q-state')).toBe('loading-4')
  })
})
