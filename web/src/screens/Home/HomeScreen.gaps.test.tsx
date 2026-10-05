// Criterio 8 (T-56, días 2-4): huecos de HomeScreen.test.tsx sobre UI.md §4.1 (Mixta 1 · Inicio):
// flujos por permisos, QA por defecto, recientes, origen, arranque guiado, aviso de simulación y errores.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { IssueSummary, ProposeIn, StartProposal } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

type Demo = 'af-demo' | 'qa-demo'

async function openHome(username: Demo = 'af-demo') {
  mockDb.session = { username, role: username === 'qa-demo' ? 'qa' : 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
}

const flows = () => within(screen.getByRole('group', { name: 'Qué quieres hacer' }))
const flowCard = (label: string) => flows().getByRole('button', { name: label })
const continueButton = () => screen.getByRole('button', { name: 'Continuar' })

function proposeBodies(): ProposeIn[] {
  const bodies: ProposeIn[] = []
  mockServer.events.on('request:start', ({ request }) => {
    if (new URL(request.url).pathname === '/api/v1/start/propose') {
      void request.clone().json().then((body) => bodies.push(body as ProposeIn))
    }
  })
  return bodies
}

const issue = (key: string, summary: string, issue_type = 'Story'): IssueSummary => ({ key, summary, issue_type, status: 'Abierta' })

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Inicio: textos y flujos por permisos (UI.md §3, §4.1)', () => {
  it('test_hero_texts_match_ui_spec', async () => {
    /** Criterio 8: título y subtítulo de UI.md §4.1. */
    await openHome()
    expect(
      screen.getByText('Elige qué hacemos y de qué partimos. Después lo mejoramos conversando. Nada se publica en Jira sin tu aprobación.'),
    ).toBeInTheDocument()
  })

  it('test_only_one_flow_pressed_at_a_time', async () => {
    /** Criterio 8: elegir un flujo deja solo esa tarjeta con aria-pressed="true". */
    await openHome()
    await userEvent.click(flowCard('Revisar la calidad de una HU'))
    const pressed = flows()
      .getAllByRole('button')
      .filter((button) => button.getAttribute('aria-pressed') === 'true')
    expect(pressed.map((button) => button.textContent)).toEqual([expect.stringContaining('Revisar la calidad de una HU')])
    expect(screen.getByRole('textbox', { name: 'Escribe la clave de la HU que quieres revisar, por ejemplo DEMO-4. (Intro para enviar, Mayús+Intro para nueva línea)' })).toBeInTheDocument()
  })

  it('test_qa_clicking_disabled_story_flow_keeps_tests', async () => {
    /** Criterio 8 (negativo): QA no puede elegir un flujo de HU; «Preparar pruebas» sigue elegida. */
    await openHome('qa-demo')
    await userEvent.click(flowCard('Evolucionar una HU'))
    expect(flowCard('Preparar pruebas')).toHaveAttribute('aria-pressed', 'true')
    expect(flowCard('Evolucionar una HU')).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('textbox', { name: 'Escribe la clave de la HU para la que quieres pruebas, por ejemplo DEMO-3. (Intro para enviar, Mayús+Intro para nueva línea)' })).toBeInTheDocument()
  })

  it('test_qa_all_story_flows_disabled_with_hint', async () => {
    /** Criterio 8: para QA, las tres tarjetas de HU están desactivadas con la ayuda de UI.md §3. */
    await openHome('qa-demo')
    for (const label of ['Nueva necesidad', 'Evolucionar una HU', 'Revisar la calidad de una HU']) {
      expect(flowCard(label)).toHaveAttribute('aria-disabled', 'true')
      expect(flowCard(label)).toHaveAccessibleDescription('Disponible para el rol de analista funcional.')
    }
    expect(flowCard('Preparar pruebas')).not.toHaveAttribute('aria-disabled')
  })

  it('test_analyst_enabled_cards_describe_their_hint', async () => {
    /** Criterio 8: las tarjetas activas llevan su ayuda como descripción, no en el nombre. */
    await openHome()
    expect(flowCard('Evolucionar una HU')).toHaveAccessibleDescription('Parte de una HU de Jira y propón su nueva versión con el diff.')
  })
})

describe('Inicio: arranque guiado (POST /start/propose)', () => {
  it('test_qa_propose_sends_qa_mode_and_trimmed_text', async () => {
    /** Criterio 8: QA envía mode «qa», el proyecto elegido y el texto sin espacios alrededor. */
    const bodies = proposeBodies()
    await openHome('qa-demo')
    await userEvent.type(screen.getByRole('textbox'), '  Pruebas de DEMO-3  ')
    await userEvent.click(continueButton())
    await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })
    expect(bodies).toEqual([{ text: 'Pruebas de DEMO-3', project: 'DEMO', mode: 'qa' }])
  })

  it.each(['Nueva necesidad', 'Evolucionar una HU', 'Revisar la calidad de una HU'])(
    'test_analyst_flow_%s_sends_functional_mode',
    async (label) => {
      /** Criterio 8: los flujos de la analista envían mode «functional». */
      const bodies = proposeBodies()
      await openHome()
      await userEvent.click(flowCard(label))
      await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3')
      await userEvent.click(continueButton())
      await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })
      expect(bodies.map((body) => body.mode)).toEqual(['functional'])
    },
  )

  it('test_whitespace_text_without_origin_cannot_continue', async () => {
    /** Criterio 8 (negativo): sin origen y con solo espacios no se puede continuar ni se llama a la API. */
    const bodies = proposeBodies()
    await openHome()
    await userEvent.type(screen.getByRole('textbox'), '    ')
    expect(continueButton()).toBeDisabled()
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    expect(bodies).toEqual([])
  })

  it('test_ctrl_enter_submits_from_home', async () => {
    /** Criterio 8: Ctrl + Intro en el compositor de Inicio lanza el arranque guiado. */
    await openHome()
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3{Control>}{Enter}{/Control}')
    expect(await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })).toBeInTheDocument()
  })

  it('test_continue_disabled_while_proposing_single_request', async () => {
    /** Criterio 8: mientras se espera la propuesta no se puede reenviar (una sola petición). */
    const bodies = proposeBodies()
    mockServer.use(
      http.post('/api/v1/start/propose', async () => {
        await delay(120)
        return HttpResponse.json(mockProposal())
      }),
    )
    await openHome()
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3')
    await userEvent.click(continueButton())
    expect(continueButton()).toBeDisabled()
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })
    expect(bodies).toHaveLength(1)
  })

  it('test_text_with_origin_passes_both', async () => {
    /** Criterio 8: con origen fijado y texto, la siguiente pantalla recibe los dos. */
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.type(screen.getByRole('textbox'), 'Añadir renovación desde la app')
    await userEvent.click(continueButton())
    await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })
    const log = screen.getByRole('log')
    expect(log).toHaveTextContent('Añadir renovación desde la app')
    expect(log).toHaveTextContent('Operación fijada: evolucionar DEMO-3')
  })

  it('test_error_cleared_when_retry_succeeds', async () => {
    /** Criterio 8 (error): tras un fallo, un nuevo intento correcto quita la tarjeta y avanza. */
    let fail = true
    mockServer.use(
      http.post('/api/v1/start/propose', () => {
        if (!fail) return HttpResponse.json(mockProposal())
        fail = false
        return HttpResponse.json({ error: { code: 'rate_limited', message: 'Límite ficticio.', retry_after: null } }, { status: 429 })
      }),
    )
    await openHome()
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3')
    await userEvent.click(continueButton())
    expect(await within(await screen.findByRole('alert')).findByRole('heading', { name: 'Límite de uso alcanzado' })).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('Cambiar DEMO-3')
    await userEvent.click(continueButton())
    expect(await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('test_project_changed_proposal_reaches_next_screen', async () => {
    /** Criterio 8 (hueco T-53): la propuesta con project_changed llega intacta a la siguiente pantalla. */
    mockServer.use(
      http.post('/api/v1/start/propose', () =>
        HttpResponse.json({ ...mockProposal(), project: 'SOCI', project_changed: true, options: [] }),
      ),
    )
    await openHome()
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar SOCI-2')
    await userEvent.click(continueButton())
    expect(await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })).toBeInTheDocument()
  })

  // HUECOS frente a UI.md §9 (T-53), no defectos de lo implementado en los días 2-4:
  it('la tarjeta de error de Inicio ofrece «Reintentar» (UI.md §7) y vuelve a cargar', async () => {
    let fail = true
    mockServer.use(
      http.get('/api/v1/projects', () =>
        fail
          ? HttpResponse.json(
              { error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.' } },
              { status: 503 },
            )
          : HttpResponse.json({ projects: [{ key: 'DEMO', name: 'Biblioteca' }], preselected: 'DEMO' }),
      ),
    )
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const alert = await screen.findByRole('alert')
    fail = false
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('button', { name: 'Proyecto de Jira: DEMO, Biblioteca. Cambiar' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('Inicio: recientes y origen', () => {
  it('test_recents_limited_to_four', async () => {
    /** Criterio 8 (límite): como mucho 4 recientes del proyecto. */
    mockServer.use(
      http.get('/api/v1/projects/:project/search', () =>
        HttpResponse.json(Array.from({ length: 7 }, (_, index) => issue(`DEMO-${index + 10}`, `HU ficticia ${index + 10}`))),
      ),
    )
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    expect(within(recents).getAllByRole('button')).toHaveLength(4)
  })

  it('test_recents_hidden_when_search_fails_without_error_card', async () => {
    /** Criterio 8 (error): si fallan los recientes, no hay sección ni tarjeta de error; Inicio sigue usable. */
    mockServer.use(
      http.get('/api/v1/projects/:project/search', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'Jira ficticio caído.' } }, { status: 503 }),
      ),
    )
    await openHome()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(screen.queryByRole('region', { name: /Recientes/ })).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('test_recents_hidden_when_project_has_none', async () => {
    /** Criterio 8 (límite): un proyecto sin incidencias no muestra la sección vacía. */
    mockServer.use(http.get('/api/v1/projects/:project/search', () => HttpResponse.json([])))
    await openHome()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(screen.queryByRole('region', { name: /Recientes/ })).toBeNull()
  })

  it('test_second_recent_replaces_origin', async () => {
    /** Criterio 8: elegir otro reciente sustituye al origen fijado (solo hay uno). */
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-1 Épica · Préstamo digital' }))
    expect(screen.getAllByText(/Origen:/)).toHaveLength(1)
    expect(screen.getByText(/Origen:/)).toHaveTextContent('Origen: DEMO-1 · Préstamo digital')
    expect(screen.queryByRole('button', { name: 'Quitar el origen DEMO-3' })).toBeNull()
  })

  it('test_removing_origin_disables_continue_without_text', async () => {
    /** Criterio 8: al quitar el origen y sin texto, ya no se puede continuar. */
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-3 Renovar un préstamo' }))
    expect(continueButton()).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Quitar el origen DEMO-3' }))
    expect(continueButton()).toBeDisabled()
  })

  it('test_origin_without_text_skips_propose', async () => {
    /** Criterio 8: con origen y sin texto no se llama al arranque guiado. */
    const bodies = proposeBodies()
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.click(continueButton())
    await screen.findByRole('heading', { name: /Antes de generar|disponible pronto/ })
    expect(bodies).toEqual([])
  })

  it('test_jira_project_change_without_origin_removes_previous_origin', async () => {
    /** Criterio 8: cambiar de proyecto en «Elegir en Jira» sin origen quita el origen del proyecto anterior. */
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.click(screen.getByRole('button', { name: 'Elegir en Jira' }))
    const dialog = screen.getByRole('dialog', { name: 'Elegir en Jira' })
    await userEvent.click(await within(dialog).findByRole('option', { name: 'SOCI Gestión de personas socias' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar el proyecto SOCI' }))
    await screen.findByRole('button', { name: /Proyecto de Jira: SOCI/ })
    expect(screen.queryByText(/Origen:/)).toBeNull()
  })

  it('test_origin_summary_rendered_as_text', async () => {
    /** Criterio 8 (seguridad): el título de Jira del origen se pinta como texto. */
    mockServer.use(http.get('/api/v1/projects/:project/search', () => HttpResponse.json([issue('DEMO-9', '<b>negrita</b>')])))
    await openHome()
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: /DEMO-9/ }))
    const origin = screen.getByText(/Origen:/)
    expect(origin).toHaveTextContent('<b>negrita</b>')
    expect(origin.querySelector('b b')).toBeNull()
  })
})

describe('Inicio: ajustes, simulación y errores de carga', () => {
  it('test_model_override_shown_read_only', async () => {
    /** Criterio 8: si la sesión fija un modelo, se ve «proveedor · modelo» y no es un control. */
    mockDb.settings.tasks = [
      { task: 'generate_story', chain: [{ provider: 'local', model: 'modelo-ficticio' }], override: { provider: 'groq', model: 'modelo-ficticio-70b' } },
    ]
    await openHome()
    expect(await screen.findByText('groq · modelo-ficticio-70b')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /modelo-ficticio/ })).toBeNull()
  })

  it('test_qa_model_uses_generate_tests_task', async () => {
    /** Criterio 8: QA mira el modelo de generate_tests; el override de generate_story no le aplica. */
    mockDb.settings.tasks = [
      { task: 'generate_story', chain: [{ provider: 'local', model: 'x' }], override: { provider: 'groq', model: 'solo-hu-ficticio' } },
    ]
    await openHome('qa-demo')
    expect(await screen.findByText('Modelo automático')).toBeInTheDocument()
    expect(screen.queryByText(/solo-hu-ficticio/)).toBeNull()
  })

  it('test_simulation_notice_for_qa_too', async () => {
    /** Criterio 8: el aviso de modo de prueba lo ve también QA. */
    await openHome('qa-demo')
    expect(await screen.findByRole('note')).toHaveTextContent('Modo de prueba')
  })

  it('test_settings_failure_shows_error_and_no_notice', async () => {
    /** Criterio 8 (error): si /settings falla, tarjeta de error y sin aviso de simulación (no se sabe el modo). */
    mockServer.use(
      http.get('/api/v1/settings', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'Ajustes ficticios no disponibles.' } }, { status: 503 }),
      ),
    )
    await openHome()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Ajustes ficticios no disponibles.')
    expect(screen.queryByRole('note')).toBeNull()
    expect(screen.getByText('Modelo automático')).toBeInTheDocument()
  })

  it('test_projects_failure_shows_error_and_blocks_continue', async () => {
    /** Criterio 8 (error): sin proyectos no hay proyecto elegido y no se puede continuar. */
    mockServer.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.' } }, { status: 503 }),
      ),
    )
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Servicio no disponible' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Elegir proyecto de Jira' })).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox'), 'Cambiar DEMO-3')
    expect(continueButton()).toBeDisabled()
  })

  it('test_preselected_null_uses_first_project', async () => {
    /** Criterio 8 (límite): sin último proyecto usado, se elige el primero que ve la conexión. */
    mockDb.projects.preselected = null
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Proyecto de Jira: DEMO, Biblioteca. Cambiar' })).toBeInTheDocument()
  })

  it('test_preselected_second_project_loads_its_recents', async () => {
    /** Criterio 8: con SOCI como último usado, los recientes son de SOCI. */
    mockDb.projects.preselected = 'SOCI'
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const recents = await screen.findByRole('region', { name: 'Recientes en SOCI' })
    await waitFor(() => expect(within(recents).getByRole('button', { name: /SOCI-2/ })).toBeInTheDocument())
  })
})

function mockProposal(): StartProposal {
  return {
    project: 'DEMO',
    project_changed: false,
    ignored_projects: [],
    recognized: [issue('DEMO-3', 'Renovar un préstamo')],
    similar: [],
    options: [
      { kind: 'evolve', label: 'Evolucionar DEMO-3', origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, issue: issue('DEMO-3', 'Renovar un préstamo') },
    ],
  }
}
