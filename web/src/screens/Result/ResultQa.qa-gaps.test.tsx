// Huecos de prueba de QA 5 · Resultado (UI.md §6.5): los tres modos de una suite renderizados directamente,
// parcial solo con `failed_ids`, enlace a Jira, retomar desde la lista y el flujo unido fuera de la entrega.
// Datos sintéticos (DEMO-3, qa-demo, «(ficticio)»).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { mockSuiteConversation } from '../../mocks/qaSuite.ts'
import { ResultScreen } from './ResultScreen.tsx'
import { QA_OUTCOME_TEXTS } from './resultText.ts'

const QA_REVIEW = mockSuiteConversation('DEMO-3')
const PLAN = QA_REVIEW.review?.plan ?? []

type WithResult = ConversationOut & { result: PublishOutcome }

function suiteResult(state: ConversationOut['state'], result: Partial<PublishOutcome>): WithResult {
  return {
    ...QA_REVIEW,
    title: 'Preparar pruebas de DEMO-3',
    state,
    review: null,
    result: {
      simulated: false,
      plan: PLAN,
      approved_by: 'qa-demo',
      approved_at: '2026-10-05T10:30:00Z',
      published_keys: [],
      errors: [],
      failed_ids: [],
      ...result,
    },
  } as WithResult
}

const SIMULATED = suiteResult('simulated', { simulated: true })
const PUBLISHED = suiteResult('published', { published_keys: ['DEMO-21', 'DEMO-22', 'DEMO-23', 'DEMO-24'] })
const PARTIAL_IDS_ONLY = suiteResult('approved', { published_keys: ['DEMO-21'], failed_ids: ['CP-02', 'CP-03'] })

describe('QA 5 · simulación', () => {
  it('test_simulated_suite_shows_phase_3_texts_and_audit_actions', () => {
    // UI.md §6.5 Simulación: «Publicación simulada…», «La aprobación se ha usado…» (PA-412) y *Ver el registro de auditoría*.
    render(<ResultScreen conversation={SIMULATED} />)
    const region = screen.getByRole('region', { name: 'Publicación simulada' })
    expect(screen.getByRole('img', { name: 'Avance: fase 3 de 4, Aprobada' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Pruebas de DEMO-3' })).toBeInTheDocument()
    expect(
      within(region).getByText(
        'La aprobación se ha usado en esta simulación. Para publicar de verdad, activa el modo real y empieza de nuevo desde la misma HU para revisar la suite y aprobarla.',
      ),
    ).toBeInTheDocument()
    expect(within(region).queryByText(/sigue vigente/)).toBeNull()
    expect(within(region).getByRole('list', { name: 'Operaciones que se habrían hecho' })).toHaveTextContent('Crear 4 subtareas en DEMO-3')
    expect(within(region).getByRole('button', { name: 'Ver el registro de auditoría' })).toHaveAttribute('aria-disabled', 'true')
    // UI.md §6.5 Simulación: la única acción es *Ver el registro de auditoría*.
    expect(within(region).queryByRole('button', { name: 'Ir al historial' })).toBeNull()
    expect(within(region).queryByRole('button', { name: 'Registrar la ejecución' })).toBeNull()
    expect(within(region).queryByRole('link', { name: /Abrir .* en Jira/ })).toBeNull()
    expect(within(region).queryByText(/memoria/i)).toBeNull()
    expect(within(region).getByText(/^Suite versión 1 aprobada por qa-demo a las \d{2}:\d{2}$/)).toBeInTheDocument()
  })

  it('test_simulated_suite_never_offers_handoff_even_with_handoff_flags', () => {
    // UI.md §6.5 y features.ts: tras una simulación «Pedir sus pruebas a QA» no sale; en una suite, nunca.
    render(<ResultScreen conversation={SIMULATED} handoffSoon />)
    expect(screen.queryByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeNull()
  })

  // Defecto: ResultScreen.tsx:109 pinta HandoffAction en simulación sin comprobar `qa`; en publicada sí lo comprueba (:127).
  // Hoy no se alcanza desde AppShell (canHandoff ya exige mode !== 'qa' y QA_HANDOFF_ENABLED = false), pero el
  // componente contradice su propio contrato («QA y admin, no») si se reactiva el flujo unido o el plan trae publish_suite.
  it('test_simulated_suite_with_can_handoff_does_not_offer_handoff', () => {
    // UI.md §6.5: el resultado de una suite no ofrece pasar la HU a QA.
    render(<ResultScreen conversation={SIMULATED} canHandoff />)
    expect(screen.queryByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeNull()
  })
})

describe('QA 5 · publicada', () => {
  it('test_published_suite_links_to_the_story_in_jira', async () => {
    // UI.md §6.5 Real: *Abrir DEMO-3 en Jira* con `jira_browse_url` (PA-318), la HU de las subtareas.
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    render(<ResultScreen conversation={PUBLISHED} />)
    const link = await screen.findByRole('link', { name: /Abrir DEMO-3 en Jira/ })
    expect(link).toHaveAttribute('href', `${mockDb.settings.jira_browse_url ?? ''}DEMO-3`)
    expect(screen.getByRole('button', { name: 'Registrar la ejecución' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByText(QA_OUTCOME_TEXTS.published.note)).toBeInTheDocument()
  })

  it('test_published_suite_marks_each_operation_done', () => {
    // UI.md §6.5 Real: con todo publicado, cada operación se marca hecha.
    render(<ResultScreen conversation={PUBLISHED} />)
    const list = screen.getByRole('list', { name: 'Operaciones hechas en Jira' })
    expect(within(list).getByText('✓')).toBeInTheDocument()
  })

  it('test_published_suite_with_handoff_soon_does_not_offer_handoff', () => {
    // features.ts: «Pedir sus pruebas a QA» es del resultado de una HU, nunca del de una suite.
    render(<ResultScreen conversation={PUBLISHED} handoffSoon canHandoff />)
    expect(screen.queryByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Ver la memoria' })).toBeNull()
  })

  it('test_plan_with_publish_suite_uses_qa_texts_even_without_qa_mode', () => {
    // UI.md §6.5: el resultado de una suite se reconoce por `publish_suite` en el plan.
    render(<ResultScreen conversation={{ ...PUBLISHED, mode: 'functional' }} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Suite publicada en Jira' })).toBeInTheDocument()
  })
})

describe('QA 5 · parcial', () => {
  it('test_partial_with_only_failed_ids_is_partial_and_lists_them', () => {
    // UI.md §6.5 Parcial y PA-324: `approved` con `failed_ids` (sin `errors`) es «Publicada en parte».
    render(<ResultScreen conversation={PARTIAL_IDS_ONLY} />)
    const region = screen.getByRole('region', { name: 'Publicada en parte' })
    expect(screen.getByRole('img', { name: 'Avance: fase 4 de 4, Publicada en parte' })).toBeInTheDocument()
    expect(within(region).getByRole('alert')).toHaveTextContent('Fallaron: CP-02, CP-03')
    const list = within(region).getByRole('list', { name: 'Operaciones aprobadas' })
    expect(within(list).queryByText('✓')).toBeNull()
    expect(within(region).getByText(QA_OUTCOME_TEXTS.partial.note)).toBeInTheDocument()
    expect(QA_OUTCOME_TEXTS.partial.note).toMatch(/^Lo creado se mantiene./)
    // En parte, lo que toca es reintentar los fallidos (PA-05), no registrar la ejecución.
    expect(within(region).queryByRole('button', { name: 'Registrar la ejecución' })).toBeNull()
    // PA-325: cada clave puede ser un enlace a Jira (con texto oculto); se comparan solo las claves.
    expect(within(region).getByText(/^Claves en Jira:/, { selector: 'p' }).textContent?.match(/[A-Z][A-Z0-9_]*-\d+/g)).toEqual(['DEMO-21'])
  })

  it('test_partial_errors_with_html_render_as_text', () => {
    // UI.md §7: los errores de la publicación parcial llegan del backend y se pintan como texto.
    const hostile = '<img src=x onerror=alert(1)> No se pudo crear CP-04 (ficticio).'
    const { container } = render(<ResultScreen conversation={suiteResult('approved', { errors: [hostile], failed_ids: ['CP-04'] })} />)
    expect(screen.getByRole('alert')).toHaveTextContent(hostile)
    expect(container.querySelector('img')).toBeNull()
  })

  it('test_resuming_partial_suite_from_the_list_opens_its_result', async () => {
    // UI.md §6.5 y PA-324: una suite en `approved` con fallos se retoma en su resultado, no en un aviso.
    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json(PARTIAL_IDS_ONLY)))
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    const items = await within(list).findAllByRole('button', { name: /DEMO-3/ })
    await userEvent.click(items[0] as HTMLElement)
    expect(await screen.findByRole('heading', { level: 2, name: 'Publicada en parte' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Fallaron: CP-02, CP-03')
  })
})

describe('QA_OUTCOME_TEXTS', () => {
  it('test_qa_outcome_texts_never_mention_memory', () => {
    // UI.md §6.5: la memoria solo se genera al publicar una HU; los textos de la suite no la nombran.
    for (const texts of Object.values(QA_OUTCOME_TEXTS)) {
      expect(Object.values(texts).filter((value) => typeof value === 'string' && /memoria/i.test(value))).toEqual([])
    }
  })
})
