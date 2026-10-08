// Ronda 12 (auditoría 2026-10-08, frontend): arreglos pequeños. Buscador de Memoria con el largo del contrato,
// «Volver al inicio» en Calidad con not_found o forbidden, «Reintentar» de las fuentes en Origen, y en la lista de
// conversaciones: el error se borra con «Nueva conversación», su «Reintentar» reabre y una respuesta vieja se descarta.
// Deterministas: las respuestas se retienen hasta que la prueba las suelta. Datos sintéticos (DEMO, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../App.tsx'
import { mockDb, mockServer } from '../mocks/node.ts'
import { QualityScreen } from '../screens/Quality/QualityScreen.tsx'

const unavailable = (message: string) => HttpResponse.json({ error: { code: 'service_unavailable', message } }, { status: 503 })

/** Retiene la siguiente respuesta de `method path` hasta `release()`; después responde la API simulada. */
function hold(method: 'get' | 'post', path: string) {
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  mockServer.use(
    http[method](
      path,
      async () => {
        await gate
        return undefined
      },
      { once: true },
    ),
  )
  return { release: () => release() }
}

function signIn() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
}

const list = () => screen.getByRole('complementary', { name: 'Conversaciones' })

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Memoria · buscador (auditoría)', () => {
  it('admite como mucho 100 caracteres (q de GET /memories)', async () => {
    signIn()
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Memoria' }))
    expect(await screen.findByRole('searchbox', { name: 'Buscar en las memorias' })).toHaveAttribute('maxLength', '100')
  })
})

describe('Revisar la calidad · error sin reintento (auditoría)', () => {
  it.each([
    [404, 'not_found'],
    [403, 'forbidden'],
  ])('con %i (%s) ofrece «Volver al inicio»', async (status, code) => {
    mockServer.use(http.get('/api/v1/quality-reviews/:id', () => HttpResponse.json({ error: { code, message: 'Mensaje ficticio.' } }, { status })))
    const onBack = vi.fn()
    render(<QualityScreen reviewId="r-ficticia" onBack={onBack} onChanged={() => undefined} onEvolve={() => undefined} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Volver al inicio' }))
    expect(onBack).toHaveBeenCalledTimes(1)
  })

  it('con un error que sí se reintenta (503) no añade «Volver al inicio»', async () => {
    mockServer.use(http.get('/api/v1/quality-reviews/:id', () => unavailable('Servicio ficticio caído.')))
    render(<QualityScreen reviewId="r-ficticia" onBack={() => undefined} onChanged={() => undefined} onEvolve={() => undefined} />)
    expect(await screen.findByRole('button', { name: 'Reintentar' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Volver al inicio' })).toBeNull()
  })
})

describe('Origen · fuentes con su carga y su «Reintentar» (auditoría)', () => {
  async function toOrigin() {
    signIn()
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    return screen.findByRole('button', { name: 'Evolucionar DEMO-3' })
  }
  const panel = () => screen.getByRole('complementary', { name: 'Antes de generar' })

  it('mientras llegan las fuentes dice «Cargando las fuentes…»', async () => {
    const evolve = await toOrigin()
    const sources = hold('post', '/api/v1/start/sources')
    await userEvent.click(evolve)
    expect(within(panel()).getByText('Cargando las fuentes…')).toHaveAttribute('aria-busy', 'true')
    sources.release()
    expect(await within(panel()).findByRole('checkbox', { name: /HU de origen/ })).toBeInTheDocument()
    expect(within(panel()).queryByText('Cargando las fuentes…')).toBeNull()
  })

  it('si fallan las fuentes, «Reintentar» las vuelve a pedir y aparecen', async () => {
    const evolve = await toOrigin()
    mockServer.use(http.post('/api/v1/start/sources', () => unavailable('Fuentes ficticias caídas.'), { once: true }))
    await userEvent.click(evolve)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Fuentes ficticias caídas.')
    expect(within(panel()).queryByRole('checkbox', { name: /HU de origen/ })).toBeNull()

    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await within(panel()).findByRole('checkbox', { name: /HU de origen/ })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('Lista de conversaciones · abrir una (auditoría)', () => {
  async function home() {
    signIn()
    render(<App />)
    return within(await screen.findByRole('complementary', { name: 'Conversaciones' })).findByRole('button', { name: /Evolucionar DEMO-3/ })
  }

  it('«Nueva conversación» borra el error de una conversación que no se pudo abrir', async () => {
    const item = await home()
    mockServer.use(http.get('/api/v1/conversations/:id', () => unavailable('No se pudo abrir (ficticio).'), { once: true }))
    await userEvent.click(item)
    expect(await screen.findByText('No se pudo abrir (ficticio).')).toBeInTheDocument()
    await userEvent.click(within(list()).getByRole('button', { name: 'Nueva conversación' }))
    expect(screen.queryByText('No se pudo abrir (ficticio).')).toBeNull()
  })

  it('«Reintentar» del error vuelve a abrir esa conversación', async () => {
    const item = await home()
    mockServer.use(http.get('/api/v1/conversations/:id', () => unavailable('No se pudo abrir (ficticio).'), { once: true }))
    await userEvent.click(item)
    const alert = await screen.findByRole('alert')
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('complementary', { name: 'Propuesta de HU' })).toBeInTheDocument()
    expect(screen.queryByText('No se pudo abrir (ficticio).')).toBeNull()
  })

  it('tras abrir una con éxito y fallar otra, «Reintentar» reabre la que falló, no la vieja', async () => {
    const item = await home()
    mockServer.use(http.get('/api/v1/conversations/:id', () => unavailable('No se pudo abrir (ficticio).'), { once: true }))
    await userEvent.click(item)
    await screen.findByRole('alert')
    await userEvent.click(within(list()).getByRole('button', { name: 'Nueva conversación' }))
    expect(screen.queryByRole('alert')).toBeNull()
    await userEvent.click(item) // ahora sí se abre
    expect(await screen.findByRole('complementary', { name: 'Propuesta de HU' })).toBeInTheDocument()
  })

  it('una respuesta que llega tarde de una conversación anterior se descarta', async () => {
    const item = await home()
    const late = hold('get', '/api/v1/conversations/:id')
    await userEvent.click(item) // queda en curso
    await userEvent.click(within(list()).getByRole('button', { name: /Revisar la calidad de DEMO-3/ }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Calidad de DEMO-3' })).toBeInTheDocument()

    late.release()
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'Calidad de DEMO-3' })).toBeInTheDocument())
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
  })
})
