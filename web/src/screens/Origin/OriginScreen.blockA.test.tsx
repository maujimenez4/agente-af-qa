// Bloque A (T-56): Origen · presupuesto de tokens en pantalla (PA-102): aria-live, posición, barra, aviso del 90 %
// y teclado. DESIGN-DECISIONS.md §4 bis (Origen: presupuesto). Datos sintéticos (DEMO, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import type { ContextBudget, SourcesIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const SOURCES = [
  { ref: 'DEMO-3', kind: 'jira', title: 'HU de origen: Renovar un préstamo', category: 'Story', required: true },
  { ref: 'DOC-01', kind: 'rag', title: 'Reglamento de préstamo', category: 'politicas', required: false },
]

function serveBudget(budget: ContextBudget) {
  mockServer.use(http.post('/api/v1/start/sources', () => HttpResponse.json({ sources: SOURCES, budget })))
}

async function evolveDemo3() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.click(screen.getByRole('textbox'))
  await userEvent.paste('Renovar un préstamo desde la app')
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
  await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
}

const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })
const budgetBox = async () => (await within(panel()).findByText(/^Contexto ·/)).parentElement as HTMLElement

afterEach(() => mockServer.events.removeAllListeners())

describe('Origen · presupuesto en pantalla (bloque A)', () => {
  it('el presupuesto confirmado se anuncia con aria-live="polite" y la barra es solo visual', async () => {
    /** §4 bis y PA-330: un lector de pantalla oye el presupuesto confirmado sin perder el foco; la caja visible no es una región viva (las estimaciones no se anuncian). */
    await evolveDemo3()
    const box = await budgetBox()
    expect(box).not.toHaveAttribute('aria-live')
    const live = within(panel()).getByText(/^Presupuesto confirmado:/)
    expect(live).toHaveAttribute('aria-live', 'polite')
    const track = box.querySelector('[aria-hidden="true"]')
    expect(track).not.toBeNull()
  })

  it('va debajo de las fuentes', async () => {
    /** §4 bis: «… con una barra, debajo de las fuentes». */
    await evolveDemo3()
    const box = await budgetBox()
    const fieldset = within(panel()).getByRole('checkbox', { name: /HU de origen/ }).closest('fieldset') as HTMLElement
    expect(fieldset.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('la barra se rellena en proporción y el texto lleva separador de miles', async () => {
    serveBudget({ used: 2350, limit: 6000, dropped_sources: 0, truncated_sources: 0 })
    await evolveDemo3()
    const box = await budgetBox()
    expect(within(box).getByText('Contexto · 2.350 de 6.000 tokens')).toBeInTheDocument()
    expect((box.querySelector('[aria-hidden="true"] > span') as HTMLElement).style.width).toBe('39%')
    expect(box).not.toHaveAttribute('data-warning')
  })

  it('al 90 % sin fuentes descartadas avisa (data-warning) y no añade frases', async () => {
    /** §4 bis: «Aviso (borde y barra ámbar) desde el 90 %». */
    serveBudget({ used: 5400, limit: 6000, dropped_sources: 0, truncated_sources: 0 })
    await evolveDemo3()
    const box = await budgetBox()
    expect(box).toHaveAttribute('data-warning')
    expect(within(box).getAllByText(/./)).toHaveLength(1)
  })

  it('con el teclado: Espacio en una casilla vuelve a pedir el presupuesto con esa fuente excluida', async () => {
    /** §4 bis: al cambiar las casillas se vuelve a pedir el presupuesto con `excluded_sources`. */
    const bodies: SourcesIn[] = []
    mockServer.events.on('request:start', async ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/start/sources') bodies.push((await request.clone().json()) as SourcesIn)
    })
    await evolveDemo3()
    await budgetBox()
    const box = within(panel()).getByRole('checkbox', { name: /Reglamento de préstamo/ })
    box.focus()
    await userEvent.keyboard(' ')
    expect(box).not.toBeChecked()
    await waitFor(() => expect(bodies.at(-1)?.excluded_sources).toEqual(['DOC-01']))
  })

  it('la casilla de la fuente de origen no cambia el presupuesto (está desactivada)', async () => {
    /** §4 bis: la de origen es obligatoria; no se puede excluir ni con el teclado. */
    let calls = 0
    await evolveDemo3()
    await budgetBox()
    mockServer.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/start/sources') calls += 1
    })
    const origin = within(panel()).getByRole('checkbox', { name: /HU de origen/ })
    expect(origin).toBeDisabled()
    await userEvent.click(origin)
    await new Promise((resolve) => setTimeout(resolve, 400))
    expect(calls).toBe(0)
  })
})
