// Huecos de prueba de QA 1 · Origen (UI.md §6.1): fuentes desmarcadas en el cuerpo, «Incluir además» vacío,
// teclado en los tipos de caso, error al generar la suite y «Generando…». Datos sintéticos (DEMO-3, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConversationCreateIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { openEventStream } from '../../test/sse.ts'
import { qaFeedback } from './qaOptions.ts'

const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })
const typesGroup = () => within(panel()).getByRole('group', { name: 'Tipos de caso' })
const sourcesGroup = () => within(panel()).getByRole('group', { name: 'Fuentes que se usarán' })
const extrasButton = () => within(panel()).getByRole('button', { name: /^Incluir además/ })

async function prepareTestsDemo3() {
  mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.click(screen.getAllByRole('textbox')[0] as HTMLElement)
  await userEvent.paste('DEMO-3')
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Preparar pruebas de DEMO-3' }))
  await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
}

function createBodies(): ConversationCreateIn[] {
  const bodies: ConversationCreateIn[] = []
  mockServer.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/conversations') {
      bodies.push((await request.clone().json()) as ConversationCreateIn)
    }
  })
  return bodies
}

afterEach(() => mockServer.events.removeAllListeners())

describe('qaFeedback · límites', () => {
  it('test_qa_feedback_keeps_canonical_order_regardless_of_selection_order', () => {
    // RF-22 · UI.md §6.1: «Incluye casos: …» siempre en el orden de las casillas.
    expect(qaFeedback(new Set(['exception', 'alternate']), new Set(['strategy', 'data']))).toEqual([
      'Incluye casos: positivos, negativos, alternos, de excepción.',
      'Incluye además: datos sintéticos de prueba (identificadores ficticios); estrategia de pruebas (alcance, niveles, entornos, criterios de entrada y salida, prioridad).',
    ])
  })

  it('test_qa_feedback_with_one_extra_has_no_separator', () => {
    // UI.md §6.1: «Incluir además» con un solo elemento.
    expect(qaFeedback(new Set(), new Set(['risks']))).toEqual(['Incluye casos: positivos, negativos.', 'Incluye además: riesgos, dependencias y áreas de impacto.'])
  })
})

describe('QA 1 · fuentes, extras y teclado', () => {
  it('test_story_source_is_required_and_cannot_be_unchecked', async () => {
    // UI.md §6.1 Fuentes: «HU de origen (obligatoria, sin casilla)»: marcada y desactivada.
    await prepareTestsDemo3()
    const story = within(sourcesGroup()).getByRole('checkbox', { name: /HU de origen/ })
    expect(story).toBeChecked()
    expect(story).toBeDisabled()
  })

  it('test_unchecked_source_goes_to_excluded_sources_when_generating_suite', async () => {
    // UI.md §6.1 Fuentes: marcar / desmarcar; las desmarcadas viajan en `excluded_sources` (T-51).
    const bodies = createBodies()
    mockServer.use(http.get('/api/v1/conversations/:id/events', openEventStream))
    await prepareTestsDemo3()
    const optional = within(sourcesGroup())
      .getAllByRole('checkbox')
      .find((box) => !(box as HTMLInputElement).disabled) as HTMLInputElement | undefined
    expect(optional).toBeDefined()
    const ref = (optional as HTMLInputElement).id.replace(/^source-/, '')
    await userEvent.click(optional as HTMLInputElement)
    expect(optional).not.toBeChecked()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar la suite' }))
    await screen.findByRole('img', { name: /Avance: fase 2 de 4/ })
    expect(bodies[0]?.excluded_sources).toEqual([ref])
    expect(bodies[0]?.flow).toBe('tests')
  })

  it('test_no_extras_selected_sends_only_case_types', async () => {
    // UI.md §6.1 Incluir además: si no se marca nada, el resumen dice «Ninguno incluido» y no hay «Incluye además».
    const bodies = createBodies()
    mockServer.use(http.get('/api/v1/conversations/:id/events', openEventStream))
    await prepareTestsDemo3()
    await userEvent.click(extrasButton())
    const extras = within(panel()).getByRole('group', { name: 'Incluir además' })
    for (const box of within(extras).getAllByRole('checkbox')) await userEvent.click(box)
    expect(extrasButton()).toHaveAccessibleName('Incluir además, Ninguno incluido')
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar la suite' }))
    await screen.findByRole('img', { name: /Avance: fase 2 de 4/ })
    expect(bodies[0]?.feedback).toEqual(['Incluye casos: positivos, negativos, alternos, de excepción.'])
  })

  it('test_extras_disclosure_controls_the_extras_group', async () => {
    // UI.md §6.1: «Incluir además» plegado; el botón dice qué grupo abre.
    await prepareTestsDemo3()
    const controls = extrasButton().getAttribute('aria-controls')
    expect(controls).toBeTruthy()
    expect(document.getElementById(controls ?? '')).not.toBeVisible()
    await userEvent.click(extrasButton())
    expect(document.getElementById(controls ?? '')).toBeVisible()
  })

  it('test_case_types_toggle_with_the_keyboard_and_required_ones_do_not', async () => {
    // RF-22 · UI.md §6.1: tipos de caso con el teclado; positivos y negativos no se pueden quitar.
    await prepareTestsDemo3()
    const alternate = within(typesGroup()).getByRole('checkbox', { name: 'Alternos' })
    alternate.focus()
    await userEvent.keyboard(' ')
    expect(alternate).not.toBeChecked()
    await userEvent.keyboard(' ')
    expect(alternate).toBeChecked()
    const positive = within(typesGroup()).getByRole('checkbox', { name: /^Positivos/ })
    await userEvent.click(positive)
    expect(positive).toBeChecked()
  })
})

describe('QA 1 · generar la suite', () => {
  it('test_generate_suite_error_shows_message_verbatim_and_stays_in_origin', async () => {
    // UI.md §7: el error se muestra con el mensaje de la API tal cual; se sigue en QA 1 para reintentar.
    const message = 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.'
    mockServer.use(
      http.post('/api/v1/conversations', () => HttpResponse.json({ error: { code: 'jira_unavailable', message, retry_after: null } }, { status: 503 })),
    )
    await prepareTestsDemo3()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar la suite' }))
    const card = await screen.findByRole('alert')
    expect(card).toHaveTextContent(message)
    expect(screen.getByRole('img', { name: /Avance: fase 1 de 4/ })).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: 'Generar la suite' })).toBeEnabled()
  })

  it('test_generate_suite_button_says_generating_while_request_is_pending', async () => {
    // UI.md §6.1 Pie: *Generar la suite* arranca el grafo; mientras se envía, no se puede pulsar dos veces.
    let release: () => void = () => undefined
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    let posts = 0
    mockServer.use(
      http.post('/api/v1/conversations', async () => {
        posts += 1
        await gate
        return HttpResponse.json({ error: { code: 'jira_unavailable', message: 'Fallo ficticio.', retry_after: null } }, { status: 503 })
      }),
    )
    await prepareTestsDemo3()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar la suite' }))
    const pending = await within(panel()).findByRole('button', { name: 'Generando…' })
    expect(pending).toBeDisabled()
    await userEvent.click(pending)
    release()
    await screen.findByRole('alert')
    expect(posts).toBe(1)
  })
})
