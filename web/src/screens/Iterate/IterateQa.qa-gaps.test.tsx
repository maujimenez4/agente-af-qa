// Huecos de prueba de QA 3 · Iterar la suite (UI.md §6.3): teclado en las pestañas de la suite y en el Gherkin,
// estado mientras se itera, selector de versiones y `coverage_failed` al iterar (UI.md §7).
// Datos sintéticos (DEMO-3, qa-demo, «(ficticio)»).
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { openEventStream } from '../../test/sse.ts'
import { openSuiteInReview } from '../../test/qaFlow.tsx'

const panel = () => screen.getByRole('complementary', { name: 'Suite de pruebas' })
/** Mensajes de la persona en la conversación («Tú: …»). */
const userMessages = () => screen.getAllByText('Tú:', { exact: false, selector: 'span' }).map((item) => item.parentElement?.textContent ?? '')
const tab = (name: string | RegExp) => within(panel()).getByRole('tab', { name })

/** Mensaje de `CoverageError` (UI.md §7), tal cual. */
const COVERAGE_MESSAGE =
  'La suite de pruebas no cubre la HU: algún criterio no tiene casos, faltan casos positivos o negativos, se referencian CA/RN inexistentes o hay datos que parecen personales. Vuelve a generarla.'

function qaRun() {
  const run = [...mockDb.runs.values()].find((item) => item.conversation.mode === 'qa')
  if (!run) throw new Error('No hay conversación de QA en la API simulada')
  return run
}

/** El siguiente SSE de la conversación termina en `coverage_failed` (la conversación queda en `state=error`). */
function failNextStreamWithCoverage() {
  mockServer.use(
    http.get(
      '/api/v1/conversations/:id/events',
      () => {
        const run = qaRun()
        run.script = []
        run.conversation = { ...run.conversation, state: 'error', error: { code: 'coverage_failed', message: COVERAGE_MESSAGE, retry_after: null } } as ConversationOut
        return new HttpResponse(`event: error\ndata: ${JSON.stringify(run.conversation)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } })
      },
      { once: true },
    ),
  )
}

afterEach(() => mockServer.events.removeAllListeners())

describe('QA 3 · pestañas de la suite con el teclado', () => {
  it('test_suite_tabs_move_with_arrow_keys_and_show_their_view', async () => {
    // UI.md §6.3: pestañas Casos, Cobertura, Datos y riesgos y Estrategia; con flechas se cambia y se enfoca.
    await openSuiteInReview()
    tab('Casos (4)').focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(tab('Cobertura')).toHaveAttribute('aria-selected', 'true')
    expect(tab('Cobertura')).toHaveFocus()
    expect(within(panel()).getByRole('table', { name: 'Qué casos verifican cada CA y cada RN' })).toBeInTheDocument()
    await userEvent.keyboard('{ArrowRight}')
    expect(tab('Datos y riesgos')).toHaveFocus()
    expect(within(panel()).getByRole('table', { name: 'Datos sintéticos de la suite' })).toBeInTheDocument()
    await userEvent.keyboard('{ArrowLeft}')
    expect(tab('Cobertura')).toHaveAttribute('aria-selected', 'true')
  })

  it('test_suite_tabs_wrap_around_and_support_home_end', async () => {
    // UI.md §6.3: desde Casos, ← va a Estrategia; Inicio y Fin van a la primera y la última.
    await openSuiteInReview()
    tab('Casos (4)').focus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(tab('Estrategia')).toHaveAttribute('aria-selected', 'true')
    expect(tab('Estrategia')).toHaveFocus()
    expect(within(panel()).getByRole('heading', { name: 'Estrategia de pruebas · DEMO-3' })).toBeInTheDocument()
    await userEvent.keyboard('{ArrowRight}')
    expect(tab('Casos (4)')).toHaveFocus()
    await userEvent.keyboard('{End}')
    expect(tab('Estrategia')).toHaveFocus()
    await userEvent.keyboard('{Home}')
    expect(tab('Casos (4)')).toHaveAttribute('aria-selected', 'true')
  })

  it('test_suite_tabs_roving_tabindex_and_tabpanel_label', async () => {
    // UI.md §6.3: solo la pestaña elegida entra en el orden de Tab y el panel se nombra con ella.
    await openSuiteInReview()
    const tabs = within(panel()).getAllByRole('tab')
    expect(tabs.map((item) => item.getAttribute('tabindex'))).toEqual(['0', '-1', '-1', '-1'])
    expect(within(panel()).getByRole('tabpanel', { name: 'Casos (4)' })).toBeInTheDocument()
    await userEvent.click(tab('Cobertura'))
    expect(within(panel()).getByRole('tabpanel', { name: 'Cobertura' })).toBeInTheDocument()
  })

  it('test_gherkin_in_the_suite_panel_opens_with_the_keyboard', async () => {
    // UI.md §6.3: el Gherkin desplegable de cada caso se abre con el teclado dentro del panel.
    await openSuiteInReview()
    const toggle = within(panel()).getAllByRole('button', { name: 'Ver el Gherkin' })[0] as HTMLElement
    toggle.focus()
    await userEvent.keyboard('{Enter}')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(within(panel()).getByText(/Dado un préstamo activo sin renovaciones ni reservas/, { selector: 'pre' })).toBeVisible()
  })
})

describe('QA 3 · mientras se itera y versiones', () => {
  it('test_while_iterating_composer_and_review_are_disabled_and_panel_says_generating', async () => {
    // UI.md §6.3 (indicador «FAQ está preparando una nueva versión…», PA-430) y §6.2: compositor desactivado con su texto de la suite.
    await openSuiteInReview()
    mockServer.use(http.get('/api/v1/conversations/:id/events', openEventStream))
    await userEvent.click(screen.getByRole('button', { name: 'Añade un caso de excepción' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(await screen.findByRole('textbox', { name: /^Espera a la suite para pedir cambios/ })).toBeDisabled()
    expect(within(panel()).getByText('Preparar pruebas de DEMO-3 · generando')).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: 'Revisar y aprobar' })).toBeDisabled()
    expect(within(panel()).getByRole('button', { name: 'Descartar' })).toBeDisabled()
    expect(screen.queryByRole('list', { name: 'Cambios sugeridos' })).toBeNull()
    expect(userMessages().filter((text) => text === 'Tú: Añade un caso de excepción')).toHaveLength(1)
  })

  it('test_iterating_from_another_tab_returns_to_cases', async () => {
    // UI.md §6.3: la versión nueva se abre en Casos, donde se ve el caso «nuevo en v2».
    await openSuiteInReview()
    await userEvent.click(tab('Estrategia'))
    await userEvent.click(screen.getByRole('button', { name: 'Añade un caso negativo con datos no válidos' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await screen.findByText(/^Versión 2: añadí el CP-05 \(negativo\)/)
    expect(tab('Casos (5)')).toHaveAttribute('aria-selected', 'true')
    expect(within(panel()).getByText('Nuevo en v2')).toBeInTheDocument()
  })

  it('test_selecting_v1_after_iterating_shows_its_cases_without_new_marks', async () => {
    // UI.md §6.3: versiones v1, v2 en el panel; la v1 no tiene casos «nuevo».
    await openSuiteInReview()
    await userEvent.click(screen.getByRole('button', { name: 'Añade un caso de excepción' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await screen.findByText(/^Versión 2: añadí el CP-05/)
    const versions = within(panel()).getByRole('group', { name: 'Versiones' })
    await userEvent.click(within(versions).getByRole('button', { name: 'Versión 1' }))
    expect(tab('Casos (4)')).toBeInTheDocument()
    expect(within(panel()).queryByText(/^Nuevo en v/)).toBeNull()
    // La tarjeta de la v1 del chat queda como la abierta.
    expect(screen.getByRole('button', { name: /Suite de pruebas, versión 1/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /Suite de pruebas, versión 2/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('test_assistant_card_says_coverage_validated_and_model', async () => {
    // UI.md §6.3: la tarjeta dice el modelo, las fuentes (la única del ejemplo, en singular: PA-328) y «cobertura validada».
    await openSuiteInReview()
    expect(screen.getByText(/^Generado con .+ · 1 fuente · cobertura validada$/)).toBeInTheDocument()
  })

  it('test_confirming_discard_of_the_suite_returns_home', async () => {
    // UI.md §6.3 pie: *Descartar* (con confirmación) termina la conversación sin publicar.
    await openSuiteInReview()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Descartar' }))
    await userEvent.click(within(panel()).getByRole('button', { name: 'Sí, descartar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
    expect(qaRun().conversation.state).toBe('discarded')
  })

  it('test_edit_by_hand_is_available_soon_in_qa', async () => {
    // UI.md §6.3 pie: *Editar a mano* (T-51) aún no está: «disponible pronto».
    await openSuiteInReview()
    expect(within(panel()).getByRole('button', { name: 'Editar a mano' })).toHaveAttribute('aria-disabled', 'true')
  })
})

describe('QA 3 · coverage_failed al iterar (UI.md §7)', () => {
  it('test_coverage_failed_while_iterating_shows_card_with_message_verbatim', async () => {
    // UI.md §7: `CoverageError` → «FAQ no ha podido cubrir todos los criterios» con el mensaje de la excepción tal cual y *Volver a generar*.
    await openSuiteInReview()
    failNextStreamWithCoverage()
    await userEvent.click(screen.getByRole('button', { name: 'Añade un caso de excepción' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    const card = await screen.findByRole('alert')
    expect(card).toHaveTextContent('FAQ no ha podido cubrir todos los criterios')
    expect(card).toHaveTextContent(COVERAGE_MESSAGE)
    expect(within(card).getByRole('button', { name: 'Volver a generar' })).toBeInTheDocument()
    // La v1 sigue en el panel y la conversación sigue abierta.
    expect(tab('Casos (4)')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /^Pide un cambio a la suite/ })).toBeEnabled()
  })

  it('test_regenerate_after_coverage_failed_retries_and_brings_v2', async () => {
    // UI.md §7: *Volver a generar* repite el mismo cambio con POST /retry (PA-276) y llega la v2.
    await openSuiteInReview()
    failNextStreamWithCoverage()
    const retries: string[] = []
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && request.url.endsWith('/retry')) retries.push(request.url)
    })
    await userEvent.click(screen.getByRole('button', { name: 'Añade un caso de excepción' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    const card = await screen.findByRole('alert')
    await userEvent.click(within(card).getByRole('button', { name: 'Volver a generar' }))
    expect(await screen.findByText(/^Versión 2: añadí el CP-05 \(excepción\)/)).toBeInTheDocument()
    expect(retries).toHaveLength(1)
    expect(screen.queryByRole('alert')).toBeNull()
    // El cambio pedido aparece una sola vez en la conversación (repetir no lo duplica).
    expect(userMessages().filter((text) => text === 'Tú: Añade un caso de excepción')).toHaveLength(1)
  })
})
