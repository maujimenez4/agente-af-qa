// Ronda 8 (sesión UI): conversación en Origen y fuentes (UI.md §4.3). Antes, un segundo mensaje
// sin operación elegida se guardaba como detalle sin respuesta y parecía que el agente se colgaba.
// Datos sintéticos (DEMO, SOCI, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConversationCreateIn, ProposeIn, SourcesIn, StartProposal } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { ProposalMessage } from './ProposalMessage.tsx'

const NEED = 'Escribe otra necesidad o una clave de Jira'
const DETAILS = 'Añade detalles a la necesidad (opcional)'
const CAPABILITIES = 'Puedo crear una HU nueva, evolucionar una existente o preparar sus pruebas. No gestiono proyectos de Jira.'
const CAPABILITIES_QA = 'Puedo preparar las pruebas de una HU existente. No gestiono proyectos de Jira.'
const NOTED = 'Anotado: lo tendré en cuenta al generar.'

// El nombre accesible del composer añade la ayuda de teclado cuando está activo («… (Intro para enviar…)»).
const escapeRegExp = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const byStart = (text: string) => new RegExp(`^${escapeRegExp(text)}`)

async function startWithText(text: string) {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.type(screen.getByRole('textbox'), text)
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await screen.findByRole('log', { name: 'Conversación' })
}

async function send(text: string, placeholder = NEED) {
  await userEvent.type(screen.getByRole('textbox', { name: byStart(placeholder) }), text)
  await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
}

const log = () => screen.getByRole('log', { name: 'Conversación' })
const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })

/** Cuerpos JSON de las peticiones a `path` (p. ej. `/api/v1/start/propose`). */
function bodiesOf<T>(path: string): T[] {
  const bodies: T[] = []
  mockServer.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === path) bodies.push((await request.clone().json()) as T)
  })
  return bodies
}

/** Propuesta que no llega hasta que la prueba la suelta: el estado de espera no depende del tiempo. */
function heldProposal() {
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const proposal: StartProposal = {
    project: 'DEMO',
    project_changed: false,
    ignored_projects: [],
    recognized: [{ key: 'DEMO-3', summary: 'Renovar un préstamo', issue_type: 'Story', status: 'En curso' }],
    similar: [],
    options: [{ kind: 'evolve', label: 'Evolucionar DEMO-3', origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' } }],
  }
  let calls = 0
  mockServer.use(
    http.post('/api/v1/start/propose', async () => {
      calls += 1
      if (calls === 1) return undefined // la de Inicio: la de la API simulada
      await gate
      return HttpResponse.json(proposal)
    }),
  )
  return { release: () => release() }
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Origen y fuentes · conversación antes de elegir la operación (ronda 8)', () => {
  it('un segundo mensaje sin operación vuelve a pedir la propuesta y reconoce la clave', async () => {
    const bodies = bodiesOf<ProposeIn>('/api/v1/start/propose')
    await startWithText('Crea un nuevo proyecto en JIRA llamado pruebas')
    expect(await within(log()).findByText(CAPABILITIES)).toBeInTheDocument()

    await send('Evoluciona DEMO-3')
    expect(within(log()).getByText('Evoluciona DEMO-3')).toBeInTheDocument()
    expect(await within(log()).findByText('He reconocido DEMO-3 en el proyecto DEMO.')).toBeInTheDocument()
    expect(within(log()).getByText('Clave reconocida en Jira · sin IA')).toBeInTheDocument()
    await waitFor(() => expect(bodies).toHaveLength(2))
    expect(bodies[1]).toEqual({ text: 'Evoluciona DEMO-3', project: 'DEMO', mode: 'functional' })

    // Las opciones anteriores quedan desactivadas; solo la última propuesta se puede elegir.
    const news = within(log()).getAllByRole('button', { name: 'Crear HU nueva' })
    expect(news).toHaveLength(2)
    expect(news[0]).toBeDisabled()
    expect(news[1]).toBeEnabled()
    const evolve = within(log()).getByRole('button', { name: 'Evolucionar DEMO-3' })
    expect(evolve).toBeEnabled()

    await userEvent.click(evolve)
    expect(within(log()).getByText('Operación fijada: evolucionar DEMO-3')).toBeInTheDocument()
    expect(within(log()).getByRole('button', { name: 'Evolucionar DEMO-3' })).toBeDisabled()
    expect(within(log()).getAllByRole('button', { name: 'Crear HU nueva' }).every((button) => button.hasAttribute('disabled'))).toBe(true)
  })

  it('el composer queda desactivado mientras espera la propuesta y vuelve a activarse al llegar', async () => {
    const held = heldProposal()
    await startWithText('Renovar un préstamo desde la app')
    await send('Evoluciona DEMO-3')
    const composer = screen.getByRole('textbox', { name: byStart(NEED) })
    await waitFor(() => expect(composer).toBeDisabled())
    expect(within(log()).getByRole('button', { name: 'Evolucionar DEMO-3' })).toBeDisabled() // la primera, mientras espera

    held.release()
    expect(await within(log()).findByText('He reconocido DEMO-3 en el proyecto DEMO.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('textbox', { name: byStart(NEED) })).toBeEnabled())
    const options = within(log()).getAllByRole('button', { name: 'Evolucionar DEMO-3' })
    expect(options.at(-1)).toBeEnabled()
  })

  it('si /start/propose falla, sale la tarjeta de error, el mensaje se queda y se puede volver a escribir', async () => {
    let calls = 0
    mockServer.use(
      http.post('/api/v1/start/propose', () => {
        calls += 1
        if (calls === 1) return undefined
        return HttpResponse.json(
          { error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.' } },
          { status: 503 },
        )
      }),
    )
    await startWithText('Renovar un préstamo desde la app')
    await send('Evoluciona DEMO-3')
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Servicio no disponible' })).toBeInTheDocument()
    expect(within(log()).getByText('Evoluciona DEMO-3')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('textbox', { name: byStart(NEED) })).toBeEnabled())
    expect(within(log()).getByRole('button', { name: 'Evolucionar DEMO-3' })).toBeEnabled() // la propuesta anterior sigue valiendo
  })

  it('una clave de otro proyecto avisa y fija el proyecto con esa propuesta, pero el panel solo cambia al elegir (PA-313)', async () => {
    const sources = bodiesOf<SourcesIn>('/api/v1/start/sources')
    await startWithText('Renovar un préstamo desde la app')
    await send('Evoluciona SOCI-2')
    expect(await within(log()).findByText(/la conversación pasa a SOCI/)).toBeInTheDocument()
    await waitFor(() => expect(mockDb.projects.preselected).toBe('SOCI'))
    expect(within(panel()).getByText('Elige la operación en la conversación para ver las fuentes que se usarán.')).toBeInTheDocument()
    expect(sources).toEqual([])

    await userEvent.click(within(log()).getByRole('button', { name: 'Evolucionar SOCI-2' }))
    expect(await within(panel()).findByRole('checkbox', { name: /HU de origen/ })).toBeDisabled()
    await waitFor(() => expect(sources.length).toBeGreaterThan(0))
    expect(sources[0]?.origin).toMatchObject({ kind: 'story', key: 'SOCI-2', project: 'SOCI' })
  })
})

describe('Origen y fuentes · línea de capacidades (ronda 8)', () => {
  it('sale en la primera propuesta si fue una búsqueda por texto', async () => {
    await startWithText('Renovar un préstamo desde la app')
    expect(await within(log()).findByText('Búsqueda en Jira por texto · sin IA')).toBeInTheDocument()
    expect(within(log()).getByText(CAPABILITIES)).toBeInTheDocument()
  })

  it('sale también cuando la búsqueda por texto no encuentra HU parecidas', async () => {
    await startWithText('Crea un nuevo proyecto en JIRA llamado pruebas')
    expect(await within(log()).findByText('No he encontrado HU parecidas en el proyecto DEMO.')).toBeInTheDocument()
    expect(within(log()).getByText(CAPABILITIES)).toBeInTheDocument()
  })

  it('no sale con una clave reconocida', async () => {
    await startWithText('Cambiar DEMO-3 para la app')
    expect(await within(log()).findByText('Clave reconocida en Jira · sin IA')).toBeInTheDocument()
    expect(within(log()).queryByText(CAPABILITIES)).toBeNull()
  })

  it('en el flujo de QA dice la frase de pruebas (el flujo aún sale «disponible pronto» en Inicio)', () => {
    const proposal: StartProposal = { project: 'DEMO', project_changed: false, ignored_projects: [], recognized: [], similar: [], options: [] }
    render(
      <ul>
        <ProposalMessage proposal={proposal} mode="qa" disabled={false} onChoose={() => undefined} />
      </ul>,
    )
    expect(screen.getByText(CAPABILITIES_QA)).toBeInTheDocument()
    expect(screen.queryByText(CAPABILITIES)).toBeNull()
  })
})

describe('Origen y fuentes · con la operación elegida (ronda 8)', () => {
  it('el placeholder describe lo que hará el siguiente mensaje', async () => {
    await startWithText('Renovar un préstamo desde la app')
    expect(screen.getByRole('textbox', { name: byStart(NEED) })).toHaveAttribute('placeholder', NEED)
    await userEvent.click(await within(log()).findByRole('button', { name: 'Evolucionar DEMO-3' }))
    expect(screen.getByRole('textbox', { name: byStart(DETAILS) })).toHaveAttribute('placeholder', DETAILS)
    expect(screen.queryByRole('textbox', { name: byStart(NEED) })).toBeNull()
  })

  it('un detalle se confirma con «Anotado», no vuelve a proponer y va con las restricciones', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => new HttpResponse(': latido\n\n', { headers: { 'Content-Type': 'text/event-stream' } })))
    const proposes = bodiesOf<ProposeIn>('/api/v1/start/propose')
    const creates = bodiesOf<ConversationCreateIn>('/api/v1/conversations')
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await within(log()).findByRole('button', { name: 'Evolucionar DEMO-3' }))
    await within(panel()).findByRole('checkbox', { name: /HU de origen/ })

    await send('También desde el correo de aviso', DETAILS)
    expect(within(log()).getByText('También desde el correo de aviso')).toBeInTheDocument()
    expect(within(log()).getByText(NOTED)).toBeInTheDocument()
    expect(proposes).toHaveLength(1) // solo la de Inicio

    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
    await waitFor(() => expect(creates).toHaveLength(1))
    expect(creates[0]?.feedback).toEqual(['También desde el correo de aviso'])
  })
})
