// Revisar la calidad (UI.md §4.8 · Mixta 5; T-48; ronda 4 bloque 2): arranque desde Inicio, progreso consultando
// la revisión, informe campo a campo, lista con «Informe listo» y errores. Solo datos sintéticos (DEMO-3, DEMO-4).
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../../App.tsx'
import examples from '../../api/examples.json'
import type { ConversationCreateIn, QualityReviewIn, QualityReviewOut } from '../../api/types.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import * as download from '../../security/download.ts'
import { QUALITY_POLL_MS } from './qualityText.ts'

/**
 * La prueba decide cuándo vence la espera de QUALITY_POLL_MS: el sondeo se guarda en lugar de programarse.
 * Captura cualquier `setTimeout` de ese valor; en estas pantallas solo lo usa el sondeo de la calidad.
 */
function capturePolls(): Array<() => void> {
  const polls: Array<() => void> = []
  const realSetTimeout = window.setTimeout.bind(window)
  vi.spyOn(window, 'setTimeout').mockImplementation(((handler: () => void, ms?: number, ...args: unknown[]) => {
    if (ms === QUALITY_POLL_MS) {
      polls.push(handler)
      return 0
    }
    return realSetTimeout(handler, ms, ...args)
  }) as typeof window.setTimeout)
  return polls
}

async function openReviewFlow(text = 'Revisar DEMO-4') {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.click(within(screen.getByRole('group', { name: 'Qué quieres hacer' })).getByRole('button', { name: 'Revisar la calidad de una HU' }))
  await userEvent.type(screen.getByRole('textbox'), text)
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await screen.findByRole('heading', { level: 1, name: 'Revisar la calidad' })
}

const panel = () => screen.getByRole('complementary', { name: 'Informe de calidad' })
const list = () => screen.getByRole('complementary', { name: 'Conversaciones' })

afterEach(() => {
  vi.restoreAllMocks()
  mockServer.events.removeAllListeners()
})

describe('Revisar la calidad · arranque y progreso', () => {
  it('test_start_sends_issue_key_with_csrf_and_polls_until_report', async () => {
    /** Revisar DEMO-4: POST con la clave y CSRF (202 `running`), «Revisando…» y, al consultar, el informe. */
    const polls = capturePolls()
    const posts: { body: QualityReviewIn; csrf: string | null }[] = []
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/quality-reviews') {
        void request.clone().json().then((body: QualityReviewIn) => posts.push({ body, csrf: request.headers.get('X-CSRF-Token') }))
      }
    })
    await openReviewFlow()
    expect(screen.queryByRole('complementary', { name: 'Antes de generar' })).toBeNull()
    expect(screen.queryByRole('textbox')).toBeNull() // sin restricciones ni compositor

    await userEvent.click(screen.getByRole('button', { name: 'Revisar DEMO-4' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Calidad de DEMO-4' })).toBeInTheDocument()
    expect(screen.getByText('Revisar la calidad · solo lectura')).toBeInTheDocument()
    const status = screen.getByRole('status')
    expect(within(status).getByRole('heading', { name: 'Revisando la calidad de DEMO-4…' })).toBeInTheDocument()
    expect(posts).toEqual([{ body: { issue_key: 'DEMO-4', excluded_sources: [] }, csrf: 'csrf-ficticio' }])

    await waitFor(() => expect(polls).toHaveLength(1))
    act(() => polls[0]?.())
    expect(await screen.findByRole('complementary', { name: 'Informe de calidad' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Revisando la calidad de DEMO-4…' })).toBeNull()
    const log = screen.getByRole('log')
    expect(within(log).getByText('He revisado DEMO-4 con INVEST y contra las fuentes.')).toBeInTheDocument()
    expect(within(log).getByText('Hay 2 puntos a mejorar. No he cambiado nada en Jira.')).toBeInTheDocument()
  })

  it('test_running_review_keeps_polling_until_done', async () => {
    /** Mientras la API diga `running`, se vuelve a consultar cada QUALITY_POLL_MS; nada antes. */
    const polls = capturePolls()
    let gets = 0
    mockServer.use(
      http.get('/api/v1/quality-reviews/:id', ({ params }) => {
        gets += 1
        const item = mockDb.qualityReviews.find((found) => found.review.id === params.id)
        if (gets === 1 && item) return HttpResponse.json({ ...item.review, state: 'running' })
        return undefined
      }),
    )
    await openReviewFlow()
    await userEvent.click(screen.getByRole('button', { name: 'Revisar DEMO-4' }))
    await waitFor(() => expect(polls).toHaveLength(1))
    expect(gets).toBe(0)
    act(() => polls[0]?.())
    await waitFor(() => expect(polls).toHaveLength(2))
    expect(gets).toBe(1)
    expect(screen.getByRole('heading', { name: 'Revisando la calidad de DEMO-4…' })).toBeInTheDocument()
    act(() => polls[1]?.())
    expect(await screen.findByRole('complementary', { name: 'Informe de calidad' })).toBeInTheDocument()
    expect(gets).toBe(2)
  })

  it('test_unknown_text_offers_back_to_home', async () => {
    /** Sin ninguna HU reconocida ni parecida, no se puede empezar: se vuelve a Inicio. */
    mockServer.use(
      http.post('/api/v1/start/propose', () =>
        HttpResponse.json({ project: 'DEMO', project_changed: false, ignored_projects: [], recognized: [], similar: [], options: [] }),
      ),
    )
    await openReviewFlow('algo sin clave')
    expect(screen.getByText(/No encuentro esa HU/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Revisar / })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Volver al inicio' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })
})

describe('Revisar la calidad · informe', () => {
  async function reportReady() {
    const polls = capturePolls()
    await openReviewFlow()
    await userEvent.click(screen.getByRole('button', { name: 'Revisar DEMO-4' }))
    await waitFor(() => expect(polls).toHaveLength(1))
    act(() => polls[0]?.())
    return screen.findByRole('complementary', { name: 'Informe de calidad' })
  }

  it('test_report_invest_findings_questions_and_sources_field_by_field', async () => {
    /** INVEST en seis casillas («Bien» / «Mejorable»), hallazgos con su tipo, preguntas y fuentes; como texto. */
    const report = await reportReady()
    // Cabecera: resumen contado del veredicto (5 «Bien», una ambigüedad y un hueco), sin puntuaciones.
    expect(within(report).getByText('INVEST: 5 de 6 bien · 1 ambigüedad · 1 hueco')).toBeInTheDocument()
    const invest = within(report).getByRole('region', { name: 'INVEST' })
    const letters = within(invest).getAllByRole('listitem').slice(0, 6)
    expect(letters.map((item) => item.getAttribute('data-verdict'))).toEqual(['ok', 'ok', 'ok', 'ok', 'ok', 'improvable'])
    expect(within(letters[5] as HTMLElement).getByText('Testeable')).toBeInTheDocument()
    expect(within(letters[5] as HTMLElement).getByText('Mejorable')).toBeInTheDocument()
    expect(within(letters[0] as HTMLElement).getByText('Bien')).toBeInTheDocument()

    const findings = within(report).getByRole('region', { name: 'Hallazgos' })
    expect(within(findings).getByText('Ambigüedad · CA-02')).toBeInTheDocument()
    expect(within(findings).getByText('«Avisar pronto» no se puede probar.')).toBeInTheDocument()
    expect(within(findings).getByText('Propuesta: Avisar en menos de 15 minutos.')).toBeInTheDocument()
    expect(within(findings).getByText('Hueco')).toBeInTheDocument()

    const questions = within(report).getByRole('region', { name: 'Preguntas para negocio' })
    expect(within(questions).getByText('¿Hay un máximo de renovaciones por año? (ficticio)')).toBeInTheDocument()
    const sources = within(report).getByRole('region', { name: 'Fuentes' })
    expect(within(sources).getByText('DOC-01')).toBeInTheDocument()
    expect(within(sources).getByText('Documento')).toBeInTheDocument()
    // El Markdown no se pinta: nada de «#» ni «**» en el panel.
    expect(report.textContent).not.toMatch(/\*\*|# Calidad/)
  })

  it('test_report_text_is_rendered_as_text_never_html', async () => {
    /** El informe lo escribe el LLM: una marca HTML se ve tal cual y no crea elementos. */
    const malicious = structuredClone(examples['POST /api/v1/quality-reviews 202']) as unknown as QualityReviewOut
    if (malicious.report?.findings[0]) malicious.report.findings[0].explanation = '<img src=x onerror=alert(1)>Texto'
    mockServer.use(
      http.get('/api/v1/quality-reviews/:id', ({ params }) =>
        HttpResponse.json({ ...malicious, id: String(params.id), issue_key: 'DEMO-4', state: 'done' }),
      ),
    )
    const report = await reportReady()
    expect(within(report).getByText('<img src=x onerror=alert(1)>Texto')).toBeInTheDocument()
    expect(report.querySelector('img')).toBeNull()
  })

  it('test_download_report_markdown_only_as_file', async () => {
    /** *Descargar informe*: el `report_markdown` de la API, como archivo calidad-DEMO-4.md. */
    const spy = vi.spyOn(download, 'downloadText').mockReturnValue(true)
    const report = await reportReady()
    await userEvent.click(within(report).getByRole('button', { name: 'Descargar informe' }))
    expect(spy).toHaveBeenCalledTimes(1)
    const [fileName, text] = spy.mock.calls[0] ?? []
    expect(fileName).toBe('calidad-DEMO-4.md')
    expect(text).toMatch(/^# Calidad de DEMO-4/)
  })

  it('test_evolve_with_this_opens_a_new_conversation_with_the_feedback', async () => {
    /** *Evolucionar DEMO-4 con esto*: conversación nueva de evolución con `evolve_feedback`; no publica nada. */
    const bodies: ConversationCreateIn[] = []
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/conversations') {
        void request.clone().json().then((body: ConversationCreateIn) => bodies.push(body))
      }
    })
    const report = await reportReady()
    expect(within(report).getByText(/Este flujo no publica en Jira/)).toBeInTheDocument()
    await userEvent.click(within(report).getByRole('button', { name: 'Evolucionar DEMO-4 con esto' }))
    await screen.findByRole('img', { name: /Avance: fase 2 de 4/ })
    expect(bodies).toEqual([
      {
        flow: 'evolve',
        origin: { kind: 'story', key: 'DEMO-4', project: 'DEMO' },
        excluded_sources: [],
        feedback: ['CA-02: Avisar en menos de 15 minutos.', 'Añadir un criterio de error.'],
      },
    ])
  })
})

describe('Revisar la calidad · lista y errores', () => {
  it('test_list_merges_reviews_with_report_ready', async () => {
    /** GET /quality-reviews junto a las conversaciones: «Revisar la calidad · Informe listo»; se abre el informe. */
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const item = await within(await screen.findByRole('complementary', { name: 'Conversaciones' })).findByRole('button', {
      name: /Revisar la calidad de DEMO-3/,
    })
    expect(within(item).getByText('Revisar la calidad · Informe listo')).toBeInTheDocument()
    expect(within(list()).getByRole('button', { name: /Evolucionar DEMO-3/ })).toBeInTheDocument()

    await userEvent.click(item)
    expect(await screen.findByRole('heading', { level: 1, name: 'Calidad de DEMO-3' })).toBeInTheDocument()
    expect(within(panel()).getByText('Ambigüedad · CA-02')).toBeInTheDocument()
    expect(item).toHaveAttribute('aria-current', 'true')
  })

  it('test_list_orders_reviews_and_conversations_by_updated_at', async () => {
    /** Se juntan por `updated_at`: una revisión más reciente va antes que la conversación. */
    const review = mockDb.qualityReviews[0]
    if (review) review.review = { ...review.review, updated_at: '2099-01-02T10:00:00Z' }
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    await within(await screen.findByRole('complementary', { name: 'Conversaciones' })).findByRole('button', { name: /Revisar la calidad de DEMO-3/ })
    const titles = within(list())
      .getAllByRole('button')
      .map((button) => button.textContent ?? '')
      .filter((text) => /Revisar la calidad de DEMO-3|Evolucionar DEMO-3/.test(text))
    expect(titles[0]).toMatch(/Revisar la calidad de DEMO-3/)
    expect(titles[1]).toMatch(/Evolucionar DEMO-3/)
  })

  it('test_list_keeps_conversations_when_only_quality_reviews_fail', async () => {
    /** Si solo falla GET /quality-reviews, la lista sigue con las conversaciones y sin tarjeta de error. */
    mockServer.use(
      http.get('/api/v1/quality-reviews', () => HttpResponse.json(examples['GET /api/v1/quality-reviews 500'], { status: 500 })),
    )
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    expect(await within(await screen.findByRole('complementary', { name: 'Conversaciones' })).findByRole('button', { name: /Evolucionar DEMO-3/ })).toBeInTheDocument()
    expect(within(list()).queryByRole('alert')).toBeNull()
    expect(within(list()).queryByText(/Revisar la calidad de/)).toBeNull()
  })

  it('test_new_review_appears_in_the_list', async () => {
    /** Al empezar una revisión, la lista se vuelve a pedir y aparece («Revisando» y luego «Informe listo»). */
    const polls = capturePolls()
    await openReviewFlow()
    await userEvent.click(screen.getByRole('button', { name: 'Revisar DEMO-4' }))
    expect(await within(list()).findByText('Revisar la calidad · Revisando')).toBeInTheDocument()
    await waitFor(() => expect(polls).toHaveLength(1))
    act(() => polls[0]?.())
    await screen.findByRole('complementary', { name: 'Informe de calidad' })
    const item = within(list()).getByRole('button', { name: /Revisar la calidad de DEMO-4/ })
    await waitFor(() => expect(within(item).getByText('Revisar la calidad · Informe listo')).toBeInTheDocument())
  })

  it('test_qa_does_not_get_quality_reviews_in_the_list', async () => {
    /** QA no revisa la calidad (UI.md §3): ni la tarjeta activa ni la consulta de revisiones. */
    const paths: string[] = []
    mockServer.events.on('request:start', ({ request }) => paths.push(new URL(request.url).pathname))
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    render(<App />)
    await screen.findByRole('complementary', { name: 'Conversaciones' })
    await waitFor(() => expect(paths).toContain('/api/v1/conversations'))
    expect(paths).not.toContain('/api/v1/quality-reviews')
  })

  it('test_failed_review_shows_api_message_and_retries', async () => {
    /** `state=error` con `quality_failed`: su mensaje tal cual, «Nada se ha escrito en Jira» y *Reintentar*. */
    const polls = capturePolls()
    mockDb.forceQualityError = true
    await openReviewFlow()
    await userEvent.click(screen.getByRole('button', { name: 'Revisar DEMO-4' }))
    await waitFor(() => expect(polls).toHaveLength(1))
    act(() => polls[0]?.())
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'FAQ no ha podido revisar la calidad' })).toBeInTheDocument()
    expect(within(alert).getByText(/el modelo no devolvió un informe válido/)).toBeInTheDocument()
    expect(screen.getByText('Nada se ha escrito en Jira.')).toBeInTheDocument()

    mockDb.forceQualityError = false
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(polls).toHaveLength(2))
    act(() => polls[1]?.())
    expect(await screen.findByRole('complementary', { name: 'Informe de calidad' })).toBeInTheDocument()
  })

  it('test_unknown_issue_ends_in_not_found_error', async () => {
    /** Una HU que no existe llega después en `state=error` (consultando la revisión), no como error HTTP. */
    const polls = capturePolls()
    mockServer.use(
      http.post('/api/v1/start/propose', () =>
        HttpResponse.json({
          project: 'DEMO',
          project_changed: false,
          ignored_projects: [],
          recognized: [{ key: 'DEMO-999', summary: 'HU ficticia que no existe', issue_type: 'Story', status: 'Abierta' }],
          similar: [],
          options: [],
        }),
      ),
    )
    await openReviewFlow('DEMO-999')
    await userEvent.click(screen.getByRole('button', { name: 'Revisar DEMO-999' }))
    await waitFor(() => expect(polls).toHaveLength(1))
    act(() => polls[0]?.())
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByText('No existe la incidencia DEMO-999 o no la puedes ver.')).toBeInTheDocument()
  })

  it('test_rate_limited_start_shows_countdown_card', async () => {
    /** Un 429 al empezar (ejemplo del contrato) se muestra con su tarjeta y no deja la pantalla a medias. */
    mockServer.use(
      http.post('/api/v1/quality-reviews', () => HttpResponse.json(examples['POST /api/v1/quality-reviews 429'], { status: 429 })),
    )
    await openReviewFlow()
    await userEvent.click(screen.getByRole('button', { name: 'Revisar DEMO-4' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Límite de uso alcanzado' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revisar DEMO-4' })).toBeEnabled()
  })
})
