// Afirmaciones de docs/specs/UI.md v2.0 (T-56) sobre lo ya fusionado que no tenían una prueba que las respaldara:
// el pie de Origen (§4.3), la nota de la memoria del Resultado real (§4.7) y los textos fijos de Administración (§10).
// Solo datos sintéticos (DEMO-3, af-demo, admin-demo) y la API simulada (MSW).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import examples from '../api/examples.json'
import type {
  ConversationOut,
  IssueSummary,
  PublishOutcome,
  QualityFinding,
  QualityReport,
  QualityReviewOut,
  QualityReviewSummary,
  StartProposal,
} from '../api/types.ts'
import { App } from '../App.tsx'
import { qualityReviewView, subtitle } from '../components/ConversationList/conversationLabels.ts'
import { mockDb, mockServer } from '../mocks/node.ts'
import type { StartRequest } from '../screens/Home/HomeScreen.tsx'
import qualityCss from '../screens/Quality/Quality.module.css?raw'
import { QualityScreen } from '../screens/Quality/QualityScreen.tsx'
import { findingTag, QUALITY_POLL_MS, reviewCandidates } from '../screens/Quality/qualityText.ts'
import { ResultScreen } from '../screens/Result/ResultScreen.tsx'
import tokensCss from '../styles/tokens.css?raw'

type WithResult = ConversationOut & { result: PublishOutcome }

const APPROVED = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as WithResult

function storyResult(result: Partial<PublishOutcome>, state: ConversationOut['state']): WithResult {
  return { ...APPROVED, state, result: { ...APPROVED.result, ...result } } as WithResult
}

describe('UI.md §4.3 · Origen fijado, pie del panel', () => {
  it('test_generate_footer_says_one_model_call_when_operation_fixed', async () => {
    /** UI.md §4.3 Panel · Pie: *Generar propuesta* · «Una llamada al modelo. Después itera conversando.» */
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))

    const panel = screen.getByRole('complementary', { name: 'Antes de generar' })
    expect(within(panel).getByRole('button', { name: 'Generar propuesta' })).toBeInTheDocument()
    expect(within(panel).getByText('Una llamada al modelo. Después itera conversando.')).toBeInTheDocument()
  })
})

describe('UI.md §4.7 · Resultado de la HU, nota de la memoria', () => {
  it('test_published_story_says_memory_generated_and_indexed_when_real', () => {
    /** UI.md §4.7 Real: «… se ha generado e indexado; tendrá prioridad en las próximas propuestas.» */
    render(<ResultScreen conversation={storyResult({ simulated: false, published_keys: ['DEMO-3'] }, 'published')} />)
    const region = screen.getByRole('region', { name: 'Publicado en Jira' })
    expect(within(region).getByText(/se ha generado e indexado; tendrá prioridad en las próximas propuestas\.$/)).toBeInTheDocument()
  })

  it.each<[string, Partial<PublishOutcome>, ConversationOut['state'], RegExp]>([
    ['simulated', { simulated: true }, 'simulated', /Publicación simulada/],
    ['partial', { simulated: false, published_keys: ['DEMO-3'], errors: ['Fallo ficticio al vincular.'] }, 'approved', /Publicada en parte/],
  ])('test_memory_indexed_note_absent_when_%s', (_name, result, state, region) => {
    /** UI.md §4.7: la nota «generado e indexado» es solo del modo real con todo publicado. */
    render(<ResultScreen conversation={storyResult(result, state)} />)
    expect(within(screen.getByRole('region', { name: region })).queryByText(/se ha generado e indexado/)).toBeNull()
  })
})

describe('UI.md §10 · Administración, textos fijos', () => {
  async function openAdmin() {
    mockDb.session = { username: 'admin-demo', role: 'admin', csrf: 'csrf-ficticio' }
    render(<App />)
    return screen.findByRole('heading', { level: 1, name: 'Ajustes' })
  }

  it('test_admin_page_subtitle_and_footer_when_admin_enters', async () => {
    /** UI.md §10: subtítulo «Comprueba los servicios…» y pie «Las claves se leen del .env…» (D-01). */
    await openAdmin()
    expect(
      screen.getByText('Comprueba los servicios y consulta la configuración. Desde aquí no se genera ni se publica nada.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Las claves se leen del .env y nunca se muestran. El administrador configura, pero no genera ni publica artefactos (D-01).',
      ),
    ).toBeInTheDocument()
  })

  it('test_models_card_says_read_only_config_file_when_admin_enters', async () => {
    /** UI.md §10 Modelos por tarea: «Solo lectura: los modelos se cambian en config/models.yaml.» */
    await openAdmin()
    const card = screen.getByRole('region', { name: 'Modelos por tarea' })
    expect(within(card).getByText('Solo lectura: los modelos se cambian en config/models.yaml.')).toBeInTheDocument()
  })

  it('test_publish_mode_live_text_when_publish_mode_live', async () => {
    /** UI.md §10 Modo de publicación, en real: «Al aprobar, se escribe en Jira lo que la persona confirma.» */
    mockDb.settings = { ...mockDb.settings, publish_mode: 'live' }
    await openAdmin()
    const card = screen.getByRole('region', { name: 'Modo de publicación' })
    expect(await within(card).findByText('Al aprobar, se escribe en Jira lo que la persona confirma.')).toBeInTheDocument()
    expect(within(card).queryByText('Simulación: no se escribe nada en Jira')).toBeNull()
  })

  it('test_publish_mode_simulation_text_when_publish_mode_simulation', async () => {
    /** UI.md §10 Modo de publicación, en simulación: «Simulación: no se escribe nada en Jira» (texto literal). */
    await openAdmin()
    const card = screen.getByRole('region', { name: 'Modo de publicación' })
    expect(await within(card).findByText('Simulación: no se escribe nada en Jira')).toBeInTheDocument()
    expect(within(card).queryByText('Al aprobar, se escribe en Jira lo que la persona confirma.')).toBeNull()
  })
})

describe('UI.md §4.8 · Revisar la calidad y §4.5 · PA-341, lo que no tenía prueba', () => {
  const QUALITY_EXAMPLE = examples['POST /api/v1/quality-reviews 202'] as unknown as QualityReviewOut
  const REPORT = QUALITY_EXAMPLE.report as QualityReport
  const noop = () => undefined

  const issue = (key: string, issue_type = 'Story'): IssueSummary => ({ key, summary: `HU ficticia ${key}`, issue_type, status: 'Abierta' })
  const proposal = (recognized: IssueSummary[], similar: IssueSummary[] = []): StartProposal => ({
    project: 'DEMO',
    project_changed: false,
    ignored_projects: [],
    recognized,
    similar,
    options: [],
  })
  const request = (extra: Partial<StartRequest>): StartRequest => ({ flow: 'review', text: 'Revisar DEMO-4', project: 'DEMO', ...extra })

  /** Abre una revisión guardada cuyo GET devuelve `review` (como al retomarla desde la lista). */
  function openReview(review: Partial<QualityReviewOut>) {
    const body = { ...QUALITY_EXAMPLE, id: 'rev-ficticia', issue_key: 'DEMO-4', ...review }
    mockServer.use(http.get('/api/v1/quality-reviews/:id', () => HttpResponse.json(body)))
    render(<QualityScreen reviewId="rev-ficticia" onBack={noop} onChanged={noop} onEvolve={noop} />)
  }

  it('test_choose_issue_shows_intro_and_one_card_per_story_when_recognized', async () => {
    /** §4.8 Elegir la HU: el texto de entrada y una tarjeta por HU reconocida; la épica no; sin POST antes de confirmar. */
    const posts: string[] = []
    const listener = ({ request: sent }: { request: Request }) => {
      if (sent.method === 'POST') posts.push(new URL(sent.url).pathname)
    }
    mockServer.events.on('request:start', listener)
    try {
      render(
        <QualityScreen
          request={request({ proposal: proposal([issue('DEMO-4'), issue('DEMO-1', 'Epic'), issue('DEMO-5')], [issue('DEMO-7')]) })}
          onBack={noop}
          onChanged={noop}
          onEvolve={noop}
        />,
      )
      expect(screen.getByText('Reviso la HU con INVEST y contra las fuentes, y te doy un informe. No cambio nada en Jira.')).toBeInTheDocument()
      const buttons = screen.getAllByRole('button', { name: /^Revisar DEMO-/ }).map((button) => button.textContent)
      expect(buttons).toEqual(['Revisar DEMO-4', 'Revisar DEMO-5'])
      expect(screen.getByRole('button', { name: 'Volver al inicio' })).toBeInTheDocument()
      await new Promise((resolve) => setTimeout(resolve, 50))
      expect(posts).not.toContain('/api/v1/quality-reviews')
    } finally {
      mockServer.events.removeListener('request:start', listener)
    }
  })

  it.each<[string, Partial<StartRequest>, string[]]>([
    ['the_issue_chosen_in_jira', { origin: issue('DEMO-8'), proposal: proposal([issue('DEMO-4')]) }, ['DEMO-8']],
    ['recognized_keys', { proposal: proposal([issue('DEMO-4')], [issue('DEMO-7')]) }, ['DEMO-4']],
    ['similar_when_none_recognized', { proposal: proposal([], [issue('DEMO-7'), issue('DEMO-2', 'Epic')]) }, ['DEMO-7']],
    ['none_when_only_epics', { origin: issue('DEMO-1', 'Epic') }, []],
  ])('test_review_candidates_are_%s', (_name, extra, keys) => {
    /** §4.8 Elegir la HU: la elegida en Jira o, si no, las reconocidas y, sin ninguna, las parecidas; las épicas no. */
    expect(reviewCandidates(request(extra)).map((item) => item.key)).toEqual(keys)
  })

  it('test_running_review_header_note_and_no_phase_q_when_in_progress', async () => {
    /** §4.8 Cabecera y En curso: «Calidad de DEMO-4», «… · solo lectura», sin Q de fases, la nota de las dos llamadas y sin pasos. */
    openReview({ state: 'running', report: null })
    expect(await screen.findByRole('heading', { level: 1, name: 'Calidad de DEMO-4' })).toBeInTheDocument()
    expect(screen.getByText('Revisar la calidad · solo lectura')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /Avance: fase/ })).toBeNull()
    const status = await screen.findByRole('status')
    expect(within(status).getByRole('heading', { name: 'Revisando la calidad de DEMO-4…' })).toBeInTheDocument()
    expect(within(status).queryAllByRole('listitem')).toHaveLength(0)
    expect(
      screen.getByText('Son dos llamadas al modelo: con el modelo local puede tardar unos minutos. No se escribe nada en Jira.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('test_poll_interval_is_two_seconds', () => {
    /** §4.8 En curso: `GET /quality-reviews/{id}` cada 2 s. */
    expect(QUALITY_POLL_MS).toBe(2000)
  })

  it('test_polling_stops_when_review_ends_in_error', async () => {
    /** §4.8 En curso: se consulta «hasta `done` o `error`»; con `error` no se programa otra consulta. */
    const timeout = vi.spyOn(window, 'setTimeout')
    openReview({ state: 'error', report: null, error: { code: 'quality_failed', message: 'Fallo ficticio del modelo.' } })
    expect(await screen.findByText('Fallo ficticio del modelo.')).toBeInTheDocument()
    expect(screen.getByText('Nada se ha escrito en Jira.')).toBeInTheDocument()
    expect(timeout.mock.calls.filter(([, ms]) => ms === QUALITY_POLL_MS)).toHaveLength(0)
  })

  it('test_done_conversation_has_report_summary_and_panel_card', async () => {
    /** §4.8 Conversación: el resumen del informe (`report.summary`) y la tarjeta «Informe de calidad de DEMO-4 · En el panel». */
    openReview({})
    const log = await screen.findByRole('log')
    expect(await within(log).findByText(REPORT.summary)).toBeInTheDocument()
    expect(within(log).getByText('Informe de calidad de DEMO-4')).toBeInTheDocument()
    expect(within(log).getByText('En el panel')).toBeInTheDocument()
  })

  it('test_report_panel_is_480px_and_invest_wraps_in_two_rows_of_three', async () => {
    /** §4.8 Panel «Informe de calidad» (480 px) e INVEST con las seis letras y su nombre, en dos filas de tres. */
    openReview({})
    const panel = await screen.findByRole('complementary', { name: 'Informe de calidad' })
    expect(panel).toHaveAttribute('data-size', 'md')
    expect(tokensCss).toMatch(/--panel-md:\s*480px;/)
    expect(qualityCss).toMatch(/@container \(max-width: 520px\) \{\s*\.invest \{\s*grid-template-columns: repeat\(3, minmax\(0, 1fr\)\);/)
    const letters = within(within(panel).getByRole('region', { name: 'INVEST' })).getAllByRole('listitem').slice(0, 6)
    expect(letters.map((item) => item.textContent?.split(':')[0])).toEqual([
      'IIndependienteBien',
      'NNegociableBien',
      'VValiosaBien',
      'EEstimableBien',
      'SPequeñaBien',
      'TTesteableMejorable',
    ])
  })

  it('test_finding_kinds_use_the_five_spanish_labels', () => {
    /** §4.8 Hallazgos: Ambigüedad, Hueco, Sin fuente, INVEST, Incoherencia con las fuentes; con el CA o la RN afectados. */
    const kinds: QualityFinding['kind'][] = ['ambiguity', 'gap', 'no_source', 'invest', 'inconsistency']
    expect(kinds.map((kind) => findingTag({ kind, explanation: 'Ficticio.', proposal: 'Ficticia.' }))).toEqual([
      'Ambigüedad',
      'Hueco',
      'Sin fuente',
      'INVEST',
      'Incoherencia con las fuentes',
    ])
    expect(findingTag({ kind: 'gap', target_id: 'RN-01', explanation: 'Ficticio.', proposal: 'Ficticia.' })).toBe('Hueco · RN-01')
  })

  it('test_no_findings_text_and_no_evolve_button_when_report_has_no_improvements', async () => {
    /** §4.8 Hallazgos: sin ninguno, «No hay hallazgos.»; Pie: *Evolucionar* solo si hay mejoras; la nota del pie, entera. */
    openReview({ report: { ...REPORT, findings: [] }, evolve_feedback: [] })
    const panel = await screen.findByRole('complementary', { name: 'Informe de calidad' })
    expect(within(within(panel).getByRole('region', { name: 'Hallazgos' })).getByText('No hay hallazgos.')).toBeInTheDocument()
    expect(within(panel).getByText('INVEST: 5 de 6 bien · sin hallazgos')).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: /^Evolucionar/ })).toBeNull()
    expect(within(panel).getByRole('button', { name: 'Descargar informe' })).toBeInTheDocument()
    expect(
      within(panel).getByText('Este flujo no publica en Jira. Evolucionar abre una conversación nueva con estas mejoras como punto de partida.'),
    ).toBeInTheDocument()
  })

  it.each<[QualityReviewSummary['state'], string]>([
    ['running', 'Revisar la calidad · Revisando'],
    ['done', 'Revisar la calidad · Informe listo'],
    ['error', 'Revisar la calidad · Con error'],
  ])('test_list_subtitle_when_review_%s', (state, text) => {
    /** §4.8 Lista de conversaciones: «Revisar la calidad · Revisando / Informe listo / Con error». */
    const summary: QualityReviewSummary = {
      id: 'rev-ficticia',
      issue_key: 'DEMO-4',
      project: 'DEMO',
      title: 'Revisar la calidad de DEMO-4',
      state,
      created_at: '2026-10-02T10:30:00Z',
      updated_at: '2026-10-02T10:30:00Z',
    }
    expect(subtitle(qualityReviewView(summary))).toBe(text)
  })

  it('test_contract_example_names_diffs_like_the_real_api', () => {
    /** §4.5 Panel · Pestañas (PA-341): el ejemplo del contrato nombra los CA y RN `acceptance_criteria[CA-02]`, como la API real. */
    const fields = [...JSON.stringify(examples).matchAll(/"field":"((?:acceptance_criteria|business_rules)[^"]*)"/g)].map((match) => match[1])
    expect(fields.length).toBeGreaterThan(0)
    for (const field of fields) expect(field).toMatch(/^(?:acceptance_criteria|business_rules)\[[A-Z]+-\d+\]$/)
  })
})
