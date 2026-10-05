// T-56: huecos de GeneratingScreen.test.tsx sobre UI.md §4.4 (Mixta 2b · Generando), §7 y
// DESIGN-DECISIONS.md §4 bis (Generando). Datos sintéticos (DEMO-3, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { POLL_MS } from './useGeneration.ts'

async function generateFromHome() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
  const panel = screen.getByRole('complementary', { name: 'Antes de generar' })
  await within(panel).findByRole('checkbox', { name: /HU de origen/ })
  await userEvent.click(within(panel).getByRole('button', { name: 'Generar propuesta' }))
  await screen.findByRole('img', { name: 'Avance: fase 2 de 4, Generar' })
}

const sse = (text: string) => new HttpResponse(text, { headers: { 'Content-Type': 'text/event-stream' } })

function runOf(id: string): ConversationOut {
  const run = mockDb.runs.get(id)
  if (!run) throw new Error(`Sin conversación ${id}`)
  return run.conversation
}

const inReview = (conversation: ConversationOut): ConversationOut =>
  ({ ...conversation, state: 'in_review', review: { version: 1, artifact: { impact: { diffs: [] } } } }) as unknown as ConversationOut

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Generando: huecos (UI.md §4.4, DESIGN-DECISIONS.md §4 bis)', () => {
  it('si el SSE se corta sin evento final, consulta GET /conversations/{id} cada 2 s mientras siga generando', async () => {
    expect(POLL_MS).toBe(2000)
    const timeout = vi.spyOn(window, 'setTimeout')
    const times: number[] = []
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => HttpResponse.error()),
      http.get('/api/v1/conversations/:id', ({ params }) => {
        times.push(Date.now())
        const current = runOf(String(params.id))
        if (times.length === 1) {
          // Sigue generando: los pasos avanzan con lo que devuelve el GET.
          return HttpResponse.json({ ...current, state: 'generating', progress: [{ node: 'load_origin', label: 'Cargar el origen', state: 'done' }] })
        }
        return HttpResponse.json(inReview(current))
      }),
    )
    await generateFromHome()
    expect(await within(screen.getByRole('status')).findByText(/Cargar el origen/)).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Propuesta lista · Versión 1 · 0 cambios frente a Jira' }, { timeout: 5000 })).toBeInTheDocument()
    expect(times).toHaveLength(2)
    expect((times[1] ?? 0) - (times[0] ?? 0)).toBeGreaterThanOrEqual(POLL_MS - 100)
    expect(timeout.mock.calls.some(([, ms]) => ms === POLL_MS)).toBe(true)
  }, 10000)

  it('un too_many_streams al abrir el SSE no es un fallo de la generación: consulta el estado y termina', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () =>
        HttpResponse.json({ error: { code: 'too_many_streams', message: 'Hay demasiadas pestañas abiertas con esta conversación.' } }, { status: 429 }),
      ),
      http.get('/api/v1/conversations/:id', ({ params }) => HttpResponse.json(inReview(runOf(String(params.id))))),
    )
    await generateFromHome()
    expect(await screen.findByRole('heading', { name: 'Propuesta lista · Versión 1 · 0 cambios frente a Jira' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('mientras genera, el compositor ofrece «Detener la generación» en lugar de enviar (PA-314)', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => sse(': latido\n\n')),
      http.get('/api/v1/conversations/:id', ({ params }) => HttpResponse.json(runOf(String(params.id)))),
    )
    await generateFromHome()
    expect(screen.getByRole('button', { name: 'Detener la generación' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Enviar' })).toBeNull()
  })

  it('«Volver a generar» vuelve a Origen y fuentes con la misma petición (la necesidad escrita sigue en la conversación)', async () => {
    const failure = { error: { code: 'invalid_model_output', message: 'La respuesta del modelo no tiene el formato esperado.' } }
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(`event: error\ndata: ${JSON.stringify(failure)}\n\n`)))
    await generateFromHome()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'La respuesta del modelo no es válida' })).toBeInTheDocument()
    await userEvent.click(within(alert).getByRole('button', { name: 'Volver a generar' }))
    await screen.findByRole('complementary', { name: 'Antes de generar' })
    expect(screen.getByRole('heading', { level: 1, name: 'Renovar un préstamo desde la app' })).toBeInTheDocument()
    expect(within(screen.getByRole('log')).getByText('Renovar un préstamo desde la app')).toBeInTheDocument()
    expect(within(screen.getByRole('log')).getByRole('button', { name: 'Evolucionar DEMO-3' })).toBeEnabled()
  })

  it('un error de la generación con la conversación entera usa sus pasos y su code (rate_limited → Reintentar con espera)', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', ({ params }) => {
        const conversation = {
          ...runOf(String(params.id)),
          state: 'error',
          error: {
            code: 'rate_limited',
            message: 'Todos los proveedores de la tarea «generate_story» han alcanzado su límite de uso. Espera unos minutos o elige otro modelo.',
            retry_after: 30,
          },
        }
        return sse(`event: error\ndata: ${JSON.stringify(conversation)}\n\n`)
      }),
    )
    await generateFromHome()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Límite de uso alcanzado' })).toBeInTheDocument()
    expect(alert).toHaveTextContent('Todos los proveedores de la tarea «generate_story» han alcanzado su límite de uso.')
    expect(within(alert).getByRole('button', { name: /Reintentar/ })).toBeDisabled()
  })

  it('mientras genera, el panel dice que la propuesta aparece cuando las citas están comprobadas y, al terminar, que está lista', async () => {
    await generateFromHome()
    await screen.findByRole('button', { name: 'Ver la propuesta' })
    const panel = screen.getByRole('complementary', { name: 'Propuesta de HU' })
    await waitFor(() => expect(within(panel).getByText('La propuesta está lista. Ábrela para revisarla.')).toBeInTheDocument())
    expect(within(panel).queryByText('La propuesta aparece aquí cuando las citas están comprobadas.')).toBeNull()
  })
})
