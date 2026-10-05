// Presupuesto de tokens del panel «Antes de generar» (UI.md §4.3, PA-102). Datos sintéticos (DEMO, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { SourcesIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { budgetView } from './budget.ts'

async function evolveDemo3() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
  await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
}

const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })
const usedOf = (text: string | null) => Number((/Contexto · ([\d.]+) de/.exec(text ?? '')?.[1] ?? '').replace(/\./g, ''))

afterEach(() => mockServer.events.removeAllListeners())

describe('budgetView', () => {
  it('«Contexto · 2.350 de 6.000 tokens» con la barra en proporción', () => {
    expect(budgetView({ used: 2350, limit: 6000, dropped_sources: 0, truncated_sources: 0 })).toEqual({
      label: 'Contexto · 2.350 de 6.000 tokens',
      percent: 39,
      warning: false,
      notes: [],
    })
  })

  it('avisa desde el 90 % y acota la barra a 0–100', () => {
    expect(budgetView({ used: 5400, limit: 6000, dropped_sources: 0, truncated_sources: 0 })?.warning).toBe(true)
    expect(budgetView({ used: 9000, limit: 6000, dropped_sources: 0, truncated_sources: 0 })?.percent).toBe(100)
    expect(budgetView({ used: -5, limit: 6000, dropped_sources: 0, truncated_sources: 0 })).toMatchObject({ percent: 0, label: 'Contexto · 0 de 6.000 tokens' })
  })

  it.each([
    [1, 0, ['1 fuente no cabe y no se enviará al modelo.']],
    [3, 0, ['3 fuentes no caben y no se enviarán al modelo.']],
    [0, 1, ['1 incidencia se recorta para que quepa.']],
    [2, 2, ['2 fuentes no caben y no se enviarán al modelo.', '2 incidencias se recortan para que quepan.']],
  ])('%i descartadas y %i recortadas → sus avisos', (dropped, truncated, notes) => {
    const view = budgetView({ used: 1000, limit: 6000, dropped_sources: dropped, truncated_sources: truncated })
    expect(view?.notes).toEqual(notes)
    expect(view?.warning).toBe(dropped > 0)
  })

  it('sin presupuesto o con un límite no válido no pinta nada', () => {
    expect(budgetView(undefined)).toBeUndefined()
    expect(budgetView({ used: 10, limit: 0, dropped_sources: 0, truncated_sources: 0 })).toBeUndefined()
    expect(budgetView({ used: Number.NaN, limit: 6000, dropped_sources: 0, truncated_sources: 0 })).toBeUndefined()
  })
})

describe('Origen · presupuesto de tokens (PA-102)', () => {
  it('pinta el presupuesto que da /start/sources', async () => {
    await evolveDemo3()
    expect(await within(panel()).findByText(/^Contexto · [\d.]+ de 6\.000 tokens$/)).toBeInTheDocument()
  })

  it('al desmarcar una fuente se vuelve a pedir con excluded_sources, baja el presupuesto y la fuente sigue en la lista', async () => {
    const bodies: SourcesIn[] = []
    mockServer.events.on('request:start', async ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/start/sources') bodies.push((await request.clone().json()) as SourcesIn)
    })
    await evolveDemo3()
    const before = usedOf((await within(panel()).findByText(/^Contexto ·/)).textContent)
    await userEvent.click(within(panel()).getByRole('checkbox', { name: /Reglamento de préstamo/ }))
    await waitFor(() => expect(usedOf(within(panel()).getByText(/^Contexto ·/).textContent)).toBeLessThan(before))
    expect(bodies.at(-1)?.excluded_sources).toEqual(['DOC-01'])
    expect(within(panel()).getByRole('checkbox', { name: /Reglamento de préstamo/ })).not.toBeChecked()

    await userEvent.click(within(panel()).getByRole('checkbox', { name: /Reglamento de préstamo/ }))
    await waitFor(() => expect(usedOf(within(panel()).getByText(/^Contexto ·/).textContent)).toBe(before))
  })

  it('varios clics seguidos piden el presupuesto una sola vez', async () => {
    let calls = 0
    await evolveDemo3()
    await within(panel()).findByText(/^Contexto ·/)
    mockServer.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/start/sources') calls += 1
    })
    const box = within(panel()).getByRole('checkbox', { name: /Reglamento de préstamo/ })
    await userEvent.click(box)
    await userEvent.click(box)
    await userEvent.click(box)
    await waitFor(() => expect(calls).toBe(1))
  })

  it('avisa de las fuentes que no caben', async () => {
    mockServer.use(
      http.post('/api/v1/start/sources', () =>
        HttpResponse.json({
          sources: [{ ref: 'DEMO-3', kind: 'jira', title: 'HU de origen: Renovar un préstamo', category: 'Story', required: true }],
          budget: { used: 6000, limit: 6000, dropped_sources: 2, truncated_sources: 1 },
        }),
      ),
    )
    await evolveDemo3()
    const note = await within(panel()).findByText('2 fuentes no caben y no se enviarán al modelo.')
    expect(note.closest('[data-warning]')).not.toBeNull()
    expect(within(panel()).getByText('1 incidencia se recorta para que quepa.')).toBeInTheDocument()
  })

  it('si falla la nueva consulta del presupuesto, deja de pintarlo en lugar de mostrar uno viejo', async () => {
    await evolveDemo3()
    await within(panel()).findByText(/^Contexto ·/)
    mockServer.use(
      http.post('/api/v1/start/sources', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 }),
      ),
    )
    await userEvent.click(within(panel()).getByRole('checkbox', { name: /Reglamento de préstamo/ }))
    await waitFor(() => expect(within(panel()).queryByText(/^Contexto ·/)).toBeNull())
    expect(within(panel()).getByRole('checkbox', { name: /Reglamento de préstamo/ })).toBeInTheDocument()
  })
})
