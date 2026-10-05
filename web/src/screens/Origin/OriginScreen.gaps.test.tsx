// T-56: huecos de OriginScreen.test.tsx sobre UI.md §4.3 (Mixta 2 · Origen fijado), §7 y
// DESIGN-DECISIONS.md §4 bis (Origen y fuentes, plegar el panel). Datos sintéticos (DEMO, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ConversationCreateIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

function signIn() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
}

async function startWithText(text: string) {
  signIn()
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.type(screen.getByRole('textbox'), text)
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
}

async function evolveDemo3() {
  await startWithText('Renovar un préstamo desde la app')
  await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
  await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
}

const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })
const sse = (text: string) => new HttpResponse(text, { headers: { 'Content-Type': 'text/event-stream' } })

function createBodies(): ConversationCreateIn[] {
  const bodies: ConversationCreateIn[] = []
  mockServer.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/conversations') {
      bodies.push((await request.clone().json()) as ConversationCreateIn)
    }
  })
  return bodies
}

async function generate() {
  await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
  await screen.findByRole('img', { name: 'Avance: fase 2 de 4, Generar' })
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Origen y fuentes: huecos (UI.md §4.3, DESIGN-DECISIONS.md §4 bis)', () => {
  it('plegar y volver a mostrar el panel conserva las restricciones y las casillas, y se envían al generar', async () => {
    const bodies = createBodies()
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(': latido\n\n')))
    await evolveDemo3()
    await userEvent.type(within(panel()).getByLabelText('Restricciones (opcional)'), 'Sin cambios en la web.')
    await userEvent.click(within(panel()).getByRole('checkbox', { name: /Acta de la comisión de abril/ }))

    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    expect(screen.queryByRole('complementary', { name: 'Antes de generar' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Mostrar el panel' }))

    expect(within(panel()).getByLabelText('Restricciones (opcional)')).toHaveValue('Sin cambios en la web.')
    expect(within(panel()).getByRole('checkbox', { name: /Acta de la comisión de abril/ })).not.toBeChecked()
    expect(within(panel()).getByText('DOC-20 · No influirá en la propuesta')).toBeInTheDocument()
    await generate()
    expect(bodies[0]).toMatchObject({ excluded_sources: ['DOC-20'], feedback: ['Sin cambios en la web.'] })
  })

  it('volver a marcar una fuente la saca de excluded_sources y ya no dice «No influirá»', async () => {
    const bodies = createBodies()
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(': latido\n\n')))
    await evolveDemo3()
    const acta = within(panel()).getByRole('checkbox', { name: /Acta de la comisión de abril/ })
    await userEvent.click(acta)
    await userEvent.click(acta)
    expect(acta).toBeChecked()
    expect(within(panel()).getByText('DOC-20 · Procesos de negocio')).toBeInTheDocument()
    expect(within(panel()).queryByText(/No influirá en la propuesta/)).toBeNull()
    await generate()
    expect(bodies[0]?.excluded_sources).toEqual([])
  })

  it('la fuente de origen obligatoria no se puede excluir aunque se pulse', async () => {
    const bodies = createBodies()
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(': latido\n\n')))
    await evolveDemo3()
    const origin = within(panel()).getByRole('checkbox', { name: /HU de origen/ })
    await userEvent.click(origin)
    expect(origin).toBeChecked()
    await generate()
    expect(bodies[0]?.excluded_sources).not.toContain('DEMO-3')
  })

  it('desde una épica (flujo need), las restricciones van al texto del origen y no como feedback', async () => {
    const bodies = createBodies()
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(': latido\n\n')))
    signIn()
    render(<App />)
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-1 Épica · Préstamo digital' }))
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await within(panel()).findByRole('checkbox', { name: /Épica de origen/ })
    await userEvent.type(within(panel()).getByLabelText('Restricciones (opcional)'), 'Solo socios con carné')
    await generate()
    expect(bodies[0]).toMatchObject({
      flow: 'need',
      origin: { kind: 'epic', key: 'DEMO-1', project: 'DEMO', text: 'Restricciones: Solo socios con carné' },
      feedback: [],
    })
  })

  it('en una necesidad nueva, los detalles del compositor van al texto junto a las restricciones', async () => {
    const bodies = createBodies()
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(': latido\n\n')))
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await screen.findByRole('button', { name: 'Crear HU nueva' }))
    await userEvent.type(within(panel()).getByLabelText('Restricciones (opcional)'), 'Solo socios con carné')
    await userEvent.type(screen.getByRole('textbox', { name: 'Añade detalles a la necesidad (opcional)' }), 'También desde el aviso ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await generate()
    expect(bodies[0]?.feedback).toEqual([])
    expect(bodies[0]?.origin.text).toBe('Renovar un préstamo desde la app\n\nRestricciones: Solo socios con carné\nTambién desde el aviso ficticio')
  })

  it('fijada la operación, ninguna otra opción de la tarjeta se puede elegir', async () => {
    await evolveDemo3()
    expect(within(screen.getByRole('log')).getByRole('button', { name: 'Crear HU nueva' })).toBeDisabled()
  })

  it('con project_changed, el proyecto se fija una sola vez con POST /projects/choose', async () => {
    let chooses = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/projects/choose') chooses += 1
    })
    await startWithText('Cambiar SOCI-2')
    await screen.findByText(/la conversación pasa a SOCI/)
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar SOCI-2' }))
    await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
    await waitFor(() => expect(mockDb.projects.preselected).toBe('SOCI'))
    expect(chooses).toBe(1)
  })

  it('la tarjeta de error por code lleva su acción: «Reintentar» la cierra y deja volver a generar (UI.md §7)', async () => {
    mockServer.use(
      http.post('/api/v1/conversations', () =>
        HttpResponse.json(
          { error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.' } },
          { status: 503 },
        ),
      ),
    )
    await evolveDemo3()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('No se pudo conectar con Jira. Revisa la URL del sitio y la red.')
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(screen.queryByRole('alert')).toBeNull()
    expect(within(panel()).getByRole('button', { name: 'Generar propuesta' })).toBeEnabled()
  })
})
