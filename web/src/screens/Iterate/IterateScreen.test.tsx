import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { IterateIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { modelLabel, proposalVersions } from './iterateText.ts'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'

const EXAMPLE_ID = '8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d'

/** Abre la conversación de ejemplo (en revisión) desde la lista: retomar (T-52). */
async function openFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

const panel = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
const log = () => screen.getByRole('log', { name: 'Conversación' })

describe('Iterar (Mixta 3, UI.md §4.5)', () => {
  it('retomar desde la lista abre la propuesta en revisión con su fase y versión', async () => {
    await openFromList()
    expect(screen.getByRole('heading', { level: 1, name: 'Evolucionar DEMO-3' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Avance: fase 2 de 4, Generar' })).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel()).getByText(/persona socia de la biblioteca/)).toHaveTextContent(/^Como persona socia de la biblioteca quiero/)
  })

  it('el asistente resume la versión sin LLM, con el modelo usado y las sugerencias', async () => {
    await openFromList()
    expect(within(log()).getByText(/Versión 2 lista\. CA-02: se añade el aviso de reservas pendientes/)).toBeInTheDocument()
    expect(within(log()).getByText(/Afecta también a DEMO-2/)).toBeInTheDocument()
    expect(within(log()).getByText('Generado con local · qwen3:4b-instruct · 2 fuentes')).toBeInTheDocument()
    expect(within(log()).getByRole('button', { name: /Propuesta de HU, versión 2/ })).toHaveAttribute('aria-pressed', 'true')
    const suggestions = within(log()).getByRole('list', { name: 'Cambios sugeridos' })
    await userEvent.click(within(suggestions).getByRole('button', { name: 'Añade un criterio de error' }))
    expect(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' })).toHaveValue('Añade un criterio de error')
  })

  it('el feedback anterior de la conversación sale en la conversación', async () => {
    await openFromList()
    expect(within(log()).getByText('Mismas reglas que en la web.')).toBeInTheDocument()
  })

  it('las pestañas muestran cambios, impacto y fuentes con sus recuentos', async () => {
    await openFromList()
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Cambios (1)' }))
    expect(within(panel()).getByRole('tabpanel')).toHaveTextContent('CA-02')
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Impacto (1)' }))
    expect(within(panel()).getByRole('tabpanel')).toHaveTextContent('DEMO-2')
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Fuentes (2)' }))
    expect(within(panel()).getByRole('tabpanel')).toHaveTextContent('DOC-01')
  })

  it('pedir un cambio escribe la respuesta, crea la versión siguiente y la marca como cambiada', async () => {
    const bodies: IterateIn[] = []
    mockServer.events.on('request:start', async ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/iterate')) bodies.push((await request.clone().json()) as IterateIn)
    })
    await openFromList()
    await userEvent.type(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' }), 'El CA-01 debe hablar de la app')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(within(log()).getByText('El CA-01 debe hablar de la app')).toBeInTheDocument()
    expect(bodies).toEqual([{ feedback: 'El CA-01 debe hablar de la app' }])

    expect(await within(panel()).findByRole('button', { name: 'Versión 3' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'false')
    const changed = within(panel()).getByText('Renovación permitida (revisado en v3)').closest('li') as HTMLElement
    expect(within(changed).getByText('Cambiado en v3')).toBeInTheDocument()
    expect(within(log()).getByRole('button', { name: /Propuesta de HU, versión 3/ })).toBeInTheDocument()
    await waitFor(() => expect(within(log()).getAllByText(/Versión 3 lista\. CA-01: El CA-01 debe hablar de la app/).length).toBeGreaterThan(0))
    mockServer.events.removeAllListeners()
  })

  it('mientras se itera, el compositor espera y aparece «Escribiendo la respuesta»', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => new HttpResponse(': latido\n\n', { headers: { 'Content-Type': 'text/event-stream' } })))
    mockServer.use(
      http.get(`/api/v1/conversations/${EXAMPLE_ID}`, () =>
        HttpResponse.json({ ...examples['GET /api/v1/conversations/{conversation_id} 200'], state: mockDb.runs.get(EXAMPLE_ID)?.conversation.state ?? 'in_review' }),
      ),
    )
    await openFromList()
    await userEvent.type(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' }), 'Aclara el alcance')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(await screen.findByRole('status', { name: '' })).toHaveTextContent('Escribiendo la respuesta')
    expect(screen.getByRole('textbox', { name: 'Espera a la propuesta para pedir cambios' })).toBeDisabled()
    expect(within(panel()).getByRole('button', { name: 'Descartar' })).toBeDisabled()
  })

  it('volver a una versión anterior la abre en el panel', async () => {
    await openFromList()
    await userEvent.type(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' }), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await within(panel()).findByRole('button', { name: 'Versión 3' })
    await userEvent.click(within(panel()).getByRole('button', { name: 'Versión 2' }))
    expect(within(panel()).getByText('Renovación permitida')).toBeInTheDocument()
    expect(within(panel()).queryByText('Cambiado en v3')).toBeNull()
  })

  it('un error al iterar muestra su tarjeta', async () => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/iterate', () =>
        HttpResponse.json(
          { error: { code: 'not_in_review', message: 'La conversación no tiene una propuesta en revisión (está generando o ya terminó).' } },
          { status: 409 },
        ),
      ),
    )
    await openFromList()
    await userEvent.type(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' }), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'La revisión ya no está abierta' })).toBeInTheDocument()
  })

  it('«Editar a mano» está como «disponible pronto» y no hace nada', async () => {
    await openFromList()
    for (const name of ['Editar a mano']) {
      const button = within(panel()).getByRole('button', { name })
      expect(button).toHaveAttribute('aria-disabled', 'true')
      expect(button).toHaveAccessibleDescription('Disponible pronto: llega después del punto de control de la demo.')
      await userEvent.click(button)
    }
    expect(screen.getByRole('complementary', { name: 'Propuesta de HU' })).toBeInTheDocument()
  })

  it('«Revisar y aprobar» abre el recibo con la versión en revisión (UI.md §4.6)', async () => {
    await openFromList()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Revisar y aprobar' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Versión 2 lista para revisar' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Avance: fase 3 de 4, Revisión' })).toBeInTheDocument()
  })

  it('descartar pide confirmación, llama a /discard y vuelve a Inicio', async () => {
    await openFromList()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Descartar' }))
    const confirm = within(panel()).getByRole('group', { name: 'Confirmar el descarte' })
    await userEvent.click(within(confirm).getByRole('button', { name: 'Seguir revisando' }))
    expect(within(panel()).queryByRole('group', { name: 'Confirmar el descarte' })).toBeNull()
    await userEvent.click(within(panel()).getByRole('button', { name: 'Descartar' }))
    await userEvent.click(within(panel()).getByRole('button', { name: 'Sí, descartar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
    expect(mockDb.conversations.find((item) => item.thread_id === EXAMPLE_ID)?.status).toBe('discarded')
  })

  it('una conversación descartada se abre con su aviso', async () => {
    const summary = mockDb.conversations.find((item) => item.thread_id === EXAMPLE_ID)
    if (summary) summary.status = 'discarded'
    mockServer.use(
      http.get(`/api/v1/conversations/${EXAMPLE_ID}`, () =>
        HttpResponse.json({ ...examples['GET /api/v1/conversations/{conversation_id} 200'], state: 'discarded', review: null }),
      ),
    )
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    expect(await screen.findByText('Propuesta descartada: no se publicó nada en Jira.')).toBeInTheDocument()
  })

  it('el recorrido completo: Inicio → Origen → Generando → Iterar', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    const before = screen.getByRole('complementary', { name: 'Antes de generar' })
    await within(before).findByRole('checkbox', { name: /HU de origen/ })
    await userEvent.click(within(before).getByRole('button', { name: 'Generar propuesta' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Ver la propuesta' }))
    expect(await screen.findByRole('complementary', { name: 'Propuesta de HU' })).toBeInTheDocument()
    expect(within(log()).getByText(/Versión 2 lista/)).toBeInTheDocument()
  })
})

describe('textos de Iterar', () => {
  const example = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut

  it('une las versiones guardadas y la de la revisión, sin repetir y en orden', () => {
    expect(proposalVersions(example).map((item) => item.version)).toEqual([2])
    const withOld = { ...example, versions: [{ ...example.versions[0], version: 1 }, ...example.versions] } as ConversationOut
    expect(proposalVersions(withOld).map((item) => item.version)).toEqual([1, 2])
  })

  it('el modelo usado se lee «proveedor · modelo»', () => {
    expect(modelLabel('local/qwen3:4b-instruct')).toBe('local · qwen3:4b-instruct')
    expect(modelLabel(null)).toBeUndefined()
  })
})
