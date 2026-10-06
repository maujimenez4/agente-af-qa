// PA-336: POST /start/sources se seguía llamando durante la generación (17–35 s cada consulta con la API
// real) y competía con ella por los embeddings. Ahora la consulta en curso se aborta al pulsar «Generar»
// o al salir de la pantalla, y no sale ninguna nueva. Deterministas: la consulta de fuentes queda
// pendiente hasta que la prueba mira su señal. Datos sintéticos (DEMO, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { openEventStream } from '../../test/sse.ts'

const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })

async function evolveDemo3() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
  await within(panel()).findByRole('checkbox', { name: /HU de origen/ })
}

/**
 * A partir de ahora, cada POST /start/sources queda pendiente. Devuelve la señal con la que la pantalla
 * hizo cada consulta (la de la petición que ve MSW no refleja el `abort` del cliente).
 */
function holdSources() {
  const held: AbortSignal[] = []
  mockServer.use(http.post('/api/v1/start/sources', () => new Promise<never>(() => undefined)))
  const original = api.sources
  vi.spyOn(api, 'sources').mockImplementation((origin, excluded, signal) => {
    if (signal) held.push(signal)
    return original(origin, excluded, signal)
  })
  return held
}

/** Cuenta todas las peticiones a POST /start/sources (también las que respondan otros handlers). */
function countSources() {
  const seen = { count: 0 }
  mockServer.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/start/sources') seen.count += 1
  })
  return seen
}

afterEach(() => {
  mockServer.events.removeAllListeners()
  vi.restoreAllMocks()
})

describe('Origen y fuentes · consultas de fuentes durante la generación (PA-336)', () => {
  it('«Generar propuesta» aborta la consulta de presupuesto en curso y no pide más fuentes', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id/events', openEventStream))
    await evolveDemo3()
    const held = holdSources()
    const seen = countSources()
    // Desmarcar una fuente pide el presupuesto (tras la espera entre clics): queda en curso.
    const optional = within(panel())
      .getAllByRole('checkbox')
      .find((box) => !box.hasAttribute('disabled'))
    expect(optional).toBeDefined()
    if (optional) await userEvent.click(optional)
    await waitFor(() => expect(held).toHaveLength(1))
    expect(held[0]?.aborted).toBe(false)

    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
    expect(await screen.findByRole('img', { name: 'Avance: fase 2 de 4, Generar' })).toBeInTheDocument()
    expect(held[0]?.aborted).toBe(true)
    expect(seen.count).toBe(1) // en Generando no sale ninguna consulta de fuentes más
  })

  it('«Cambiar» (salir de Origen) aborta la consulta de la lista de fuentes en curso', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    const held = holdSources()
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    await waitFor(() => expect(held).toHaveLength(1))
    expect(held[0]?.aborted).toBe(false)

    await userEvent.click(within(panel()).getByRole('button', { name: 'Cambiar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
    expect(held[0]?.aborted).toBe(true)
  })

  it('cambiar otra casilla aborta la consulta de presupuesto anterior antes de pedir la nueva', async () => {
    await evolveDemo3()
    const held = holdSources()
    const optional = within(panel())
      .getAllByRole('checkbox')
      .filter((box) => !box.hasAttribute('disabled'))
    expect(optional.length).toBeGreaterThan(1)
    if (optional[0]) await userEvent.click(optional[0])
    await waitFor(() => expect(held).toHaveLength(1))
    if (optional[1]) await userEvent.click(optional[1])
    await waitFor(() => expect(held).toHaveLength(2))
    expect(held[0]?.aborted).toBe(true)
    expect(held[1]?.aborted).toBe(false)
  })
})

// Si la consulta respondiera tarde, ya sin pantalla, no hay nada que pintar: la prueba de la lista
// también comprueba que «Cambiar» no deja errores en la conversación.
describe('Origen y fuentes · una consulta abortada no es un error (PA-336)', () => {
  it('abortar la consulta no muestra la tarjeta de error', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id/events', openEventStream))
    await evolveDemo3()
    const held = holdSources()
    const optional = within(panel())
      .getAllByRole('checkbox')
      .find((box) => !box.hasAttribute('disabled'))
    if (optional) await userEvent.click(optional)
    await waitFor(() => expect(held).toHaveLength(1))
    await userEvent.click(within(panel()).getByRole('button', { name: 'Generar propuesta' }))
    await screen.findByRole('img', { name: 'Avance: fase 2 de 4, Generar' })
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
