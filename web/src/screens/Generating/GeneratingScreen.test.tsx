import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { readyHeadline } from './headline.ts'

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

describe('Generando (Mixta 2b, UI.md §4.4)', () => {
  it('muestra el evento, la cabecera de fase 2, el compositor desactivado y el panel en espera', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => sse(': latido\n\n')),
      http.get('/api/v1/conversations/:id', ({ params }) => HttpResponse.json(runOf(String(params.id)))),
    )
    await generateFromHome()
    expect(screen.getByRole('heading', { level: 1, name: 'Evolucionar DEMO-3' })).toBeInTheDocument()
    expect(within(screen.getByRole('log')).getByText('Generar propuesta · Evolucionar DEMO-3')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Espera a la propuesta para pedir cambios' })).toBeDisabled()
    const panel = screen.getByRole('complementary', { name: 'Propuesta de HU' })
    expect(within(panel).getByText('La propuesta aparece aquí cuando las citas están comprobadas.')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
  })

  it('sigue los pasos del SSE y al llegar review_ready ofrece ver la propuesta', async () => {
    await generateFromHome()
    expect(await screen.findByRole('heading', { name: 'Propuesta lista · Versión 2 · 1 cambio frente a Jira' })).toBeInTheDocument()
    const steps = within(screen.getByRole('status')).getAllByRole('listitem')
    expect(steps.map((step) => step.textContent)).toEqual([
      'Cargar el origen(hecho)',
      'Recuperar contexto(hecho)',
      'Generar la propuesta, validar las citas y analizar el impacto(hecho)',
    ])
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'false')
    await userEvent.click(screen.getByRole('button', { name: 'Ver la propuesta de FAQ' }))
    expect(await screen.findByRole('complementary', { name: 'Propuesta de HU' })).toHaveTextContent('Renovar un préstamo')
  })

  it('la lista de conversaciones incluye la nueva conversación', async () => {
    await generateFromHome()
    const list = screen.getByRole('complementary', { name: 'Conversaciones' })
    await waitFor(() => expect(within(list).getAllByRole('button', { name: /Evolucionar DEMO-3/ })).toHaveLength(2))
  })

  it('un error de la generación muestra su tarjeta y «Volver a generar» vuelve a Origen', async () => {
    const failure = { error: { code: 'citation_failed', message: 'La propuesta cita fuentes que no están en el contexto recibido.' } }
    mockServer.use(http.get('/api/v1/conversations/:id/events', () => sse(`event: error\ndata: ${JSON.stringify(failure)}\n\n`)))
    await generateFromHome()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'FAQ no ha podido citar sus fuentes' })).toBeInTheDocument()
    expect(alert).toHaveTextContent('La propuesta cita fuentes que no están en el contexto recibido.')
    await userEvent.click(within(alert).getByRole('button', { name: 'Volver a generar' }))
    expect(await screen.findByRole('complementary', { name: 'Antes de generar' })).toBeInTheDocument()
  })

  it('si el SSE se corta, consulta el estado con GET y termina igual', async () => {
    let gets = 0
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => HttpResponse.error()),
      http.get('/api/v1/conversations/:id', ({ params }) => {
        gets += 1
        return HttpResponse.json({ ...runOf(String(params.id)), state: 'in_review', review: { version: 1, artifact: { impact: { diffs: [] } } } })
      }),
    )
    await generateFromHome()
    expect(await screen.findByRole('heading', { name: 'Propuesta lista · Versión 1 · 0 cambios frente a Jira' })).toBeInTheDocument()
    expect(gets).toBeGreaterThanOrEqual(1)
  })

  it('una conversación en estado error al consultar muestra su error', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => sse('')),
      http.get('/api/v1/conversations/:id', ({ params }) =>
        HttpResponse.json({
          ...runOf(String(params.id)),
          state: 'error',
          error: { code: 'provider_timeout', message: 'El modelo no respondió a tiempo.' },
        }),
      ),
    )
    await generateFromHome()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'El modelo no respondió a tiempo' })).toBeInTheDocument()
  })

  it('un error HTTP al consultar el estado se muestra con su tarjeta', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => HttpResponse.error()),
      http.get('/api/v1/conversations/:id', () =>
        HttpResponse.json({ error: { code: 'not_found', message: 'No existe esa conversación o no es tuya.' } }, { status: 404 }),
      ),
    )
    await generateFromHome()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('No existe esa conversación o no es tuya.'))
  })
})

describe('readyHeadline', () => {
  const base = { flow: 'evolve', versions: [], review: { version: 3, artifact: { impact: { diffs: [{}, {}] } } } } as unknown as ConversationOut

  it('en una evolución cuenta los cambios frente a Jira', () => {
    expect(readyHeadline(base)).toBe('Propuesta lista · Versión 3 · 2 cambios frente a Jira')
  })

  it('en singular con un solo cambio', () => {
    const one = { ...base, review: { version: 1, artifact: { impact: { diffs: [{}] } } } } as unknown as ConversationOut
    expect(readyHeadline(one)).toBe('Propuesta lista · Versión 1 · 1 cambio frente a Jira')
  })

  it('en una HU nueva no hay cambios frente a Jira', () => {
    expect(readyHeadline({ ...base, flow: 'need' } as ConversationOut)).toBe('Propuesta lista · Versión 3')
  })
})
