import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { ConversationCreateIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

async function startWithText(text: string, flow?: string) {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  if (flow) await userEvent.click(within(screen.getByRole('group', { name: 'Qué quieres hacer' })).getByRole('button', { name: flow }))
  await userEvent.type(screen.getByRole('textbox'), text)
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
}

function panel() {
  return screen.getByRole('complementary', { name: 'Antes de generar' })
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

describe('Origen y fuentes (Mixta 2, UI.md §4.3)', () => {
  it('con una HU parecida la propone sin IA, con su épica y recuentos, y deja elegir', async () => {
    await startWithText('Renovar un préstamo desde la app')
    const log = await screen.findByRole('log', { name: 'Conversación' })
    expect(within(log).getByText('Renovar un préstamo desde la app')).toBeInTheDocument()
    expect(within(log).getByText('Búsqueda en Jira por texto · sin IA')).toBeInTheDocument()
    expect(within(log).getByText('DEMO-3, Renovar un préstamo')).toBeInTheDocument()
    expect(await within(log).findByText('Épica DEMO-1 · 2 criterios y 2 reglas')).toBeInTheDocument()
    expect(within(log).getByRole('button', { name: 'Evolucionar DEMO-3' })).toBeInTheDocument()
    expect(within(log).getByRole('button', { name: 'Crear HU nueva' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Avance: fase 1 de 4, Contexto' })).toBeInTheDocument()
    expect(within(panel()).getByText('Elige la operación en la conversación para ver las fuentes que se usarán.')).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: 'Generar propuesta' })).toBeDisabled()
  })

  it('una clave escrita se reconoce en Jira sin IA', async () => {
    await startWithText('Cambiar DEMO-3 para la app')
    expect(await screen.findByText('Clave reconocida en Jira · sin IA')).toBeInTheDocument()
  })

  it('al elegir la operación queda fijada y el panel muestra operación, restricciones y fuentes', async () => {
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    const log = screen.getByRole('log')
    expect(within(log).getByText('Operación fijada: evolucionar DEMO-3')).toBeInTheDocument()
    expect(within(log).getByText('No cambia durante la conversación; es lo único que se podrá aprobar y publicar.')).toBeInTheDocument()
    expect(within(log).getByRole('button', { name: 'Evolucionar DEMO-3' })).toBeDisabled()

    expect(within(panel()).getByText('Evolucionar DEMO-3 · Renovar un préstamo')).toBeInTheDocument()
    expect(within(panel()).getByLabelText('Restricciones (opcional)')).toBeInTheDocument()
    const origin = await within(panel()).findByRole('checkbox', { name: /HU de origen: Renovar un préstamo/ })
    expect(origin).toBeChecked()
    expect(origin).toBeDisabled()
    expect(within(panel()).getByText('DEMO-3 · Jira, obligatoria')).toBeInTheDocument()
    expect(within(panel()).getByText('DOC-01 · Políticas y reglas operativas')).toBeInTheDocument()
    expect(within(panel()).getByText('memoria-DEMO-2 · Memoria, prioritaria')).toBeInTheDocument()
  })

  it('una fuente desmarcada indica que no influirá', async () => {
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    const acta = await within(panel()).findByRole('checkbox', { name: /Acta de la comisión de abril/ })
    await userEvent.click(acta)
    expect(acta).not.toBeChecked()
    expect(within(panel()).getByText('DOC-20 · No influirá en la propuesta')).toBeInTheDocument()
  })

  it('«Generar propuesta» crea la conversación con la operación, las fuentes excluidas y las restricciones', async () => {
    const bodies = createBodies()
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    await userEvent.click(await within(panel()).findByRole('checkbox', { name: /Acta de la comisión de abril/ }))
    await userEvent.type(within(panel()).getByLabelText('Restricciones (opcional)'), 'Mismas reglas que en la web.')
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
    expect(await screen.findByRole('img', { name: 'Avance: fase 2 de 4, Generar' })).toBeInTheDocument()
    expect(bodies).toEqual([
      {
        flow: 'evolve',
        origin: { kind: 'story', key: 'DEMO-3', text: null, project: 'DEMO' },
        excluded_sources: ['DOC-20'],
        feedback: ['Mismas reglas que en la web.'],
      },
    ])
    mockServer.events.removeAllListeners()
  })

  it('«Crear HU nueva» lleva el texto y las restricciones en el origen', async () => {
    const bodies = createBodies()
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await screen.findByRole('button', { name: 'Crear HU nueva' }))
    expect(screen.getByText('Operación fijada: HU nueva')).toBeInTheDocument()
    await userEvent.type(within(panel()).getByLabelText('Restricciones (opcional)'), 'Solo socios con carné')
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
    await screen.findByRole('img', { name: 'Avance: fase 2 de 4, Generar' })
    expect(bodies[0]).toMatchObject({
      flow: 'need',
      origin: { kind: 'need', text: 'Renovar un préstamo desde la app\n\nRestricciones: Solo socios con carné' },
      feedback: [],
    })
    mockServer.events.removeAllListeners()
  })

  it('los detalles del compositor salen en la conversación y van con las restricciones', async () => {
    const bodies = createBodies()
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Añade detalles a la necesidad (opcional) (Intro para enviar, Mayús+Intro para nueva línea)' }), 'También desde el correo de aviso')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(within(screen.getByRole('log')).getByText('También desde el correo de aviso')).toBeInTheDocument()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
    await screen.findByRole('img', { name: 'Avance: fase 2 de 4, Generar' })
    expect(bodies[0]?.feedback).toEqual(['También desde el correo de aviso'])
    mockServer.events.removeAllListeners()
  })

  it('una clave de otro proyecto cambia el de la conversación, lo fija y lo avisa (PA-313)', async () => {
    await startWithText('Cambiar SOCI-2')
    expect(await screen.findByText(/la conversación pasa a SOCI/)).toBeInTheDocument()
    await waitFor(() => expect(mockDb.projects.preselected).toBe('SOCI'))
  })

  it('avisa de las claves de otros proyectos que no se usan (PA-313)', async () => {
    mockServer.use(
      http.post('/api/v1/start/propose', () =>
        HttpResponse.json({ project: 'DEMO', project_changed: false, ignored_projects: ['SOCI'], recognized: [], similar: [], options: [] }),
      ),
    )
    await startWithText('Cambiar DEMO-3 y SOCI-2')
    expect(await screen.findByText('Las claves de otros proyectos (SOCI) no se usan en esta conversación.')).toBeInTheDocument()
  })

  it('«Cambiar» la operación vuelve a Inicio', async () => {
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    await userEvent.click(within(panel()).getByRole('button', { name: 'Cambiar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('si crear la conversación falla, muestra la tarjeta de error y no avanza', async () => {
    mockServer.use(
      http.post('/api/v1/conversations', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.' } }, { status: 503 }),
      ),
    )
    await startWithText('Renovar un préstamo desde la app')
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Servicio no disponible' })).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'Avance: fase 2 de 4, Generar' })).toBeNull()
  })

  it('un origen elegido en los recientes fija la operación directamente', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-1 Épica · Préstamo digital' }))
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    expect(await screen.findByText('Operación fijada: HU nueva en la épica DEMO-1')).toBeInTheDocument()
    expect(await within(panel()).findByRole('checkbox', { name: /Épica de origen: Préstamo digital/ })).toBeDisabled()
  })

  it('desde la épica DEMO-1 la conversación se titula «HU nueva en la épica DEMO-1», no «Evolucionar»', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => new HttpResponse(': latido\n\n', { headers: { 'Content-Type': 'text/event-stream' } })))
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const recents = await screen.findByRole('region', { name: 'Recientes en DEMO' })
    await userEvent.click(within(recents).getByRole('button', { name: 'DEMO-1 Épica · Préstamo digital' }))
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Crear una HU nueva en la épica DEMO-1' })).toBeInTheDocument()
    await within(panel()).findByRole('checkbox', { name: /Épica de origen/ })
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'HU nueva en la épica DEMO-1' })).toBeInTheDocument()
    expect(within(screen.getByRole('log')).getByText('Generar propuesta · HU nueva en la épica DEMO-1')).toBeInTheDocument()
    const list = screen.getByRole('complementary', { name: 'Conversaciones' })
    expect(await within(list).findByText('HU nueva en la épica DEMO-1')).toBeInTheDocument()
    expect(within(list).getByText(/^HU nueva en la épica DEMO-1 · /)).toBeInTheDocument()
    expect(screen.queryByText(/Evolucionar DEMO-1/)).toBeNull()
  })

  it('«Revisar la calidad» queda como «disponible pronto» en la demo', async () => {
    await startWithText('Revisar DEMO-4', 'Revisar la calidad de una HU')
    expect(await screen.findByRole('heading', { name: 'Revisar la calidad: disponible pronto' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Volver al inicio' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })
})
