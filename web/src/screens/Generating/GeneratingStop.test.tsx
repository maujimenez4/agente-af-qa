// Detener (POST /cancel, PA-314) y Reintentar (POST /retry, PA-276) en Generando e Iterar. Datos sintéticos.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { CANCELLED_MESSAGE } from '../../mocks/handlers.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'

/** Pasos del SSE simulado lo bastante lentos para pulsar *Detener* a mitad. */
const SLOW_STEP_MS = 150

async function generateFromHome() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  mockDb.stepDelayMs = SLOW_STEP_MS
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

function posts(): string[] {
  const calls: string[] = []
  mockServer.events.on('request:start', ({ request }) => {
    if (request.method === 'POST') calls.push(new URL(request.url).pathname.split('/').at(-1) ?? '')
  })
  return calls
}

afterEach(() => mockServer.events.removeAllListeners())

describe('Generando · Detener y Reintentar', () => {
  it('«Detener» pide /cancel, dice «Deteniendo…» y termina en «Generación detenida» con el mensaje de la API', async () => {
    const calls = posts()
    await generateFromHome()
    await userEvent.click(screen.getByRole('button', { name: 'Detener la generación' }))
    expect(await screen.findByRole('button', { name: 'Deteniendo la generación…' })).toBeDisabled()
    expect(screen.getByText('Deteniendo la generación…', { selector: '*:not(button)' })).toBeInTheDocument()

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Generación detenida' })).toBeInTheDocument()
    expect(alert).toHaveTextContent(CANCELLED_MESSAGE)
    expect(calls).toContain('cancel')
    expect(screen.queryByRole('button', { name: /Detener/ })).toBeNull()
  })

  it('«Reintentar» tras detener llama a /retry y la generación llega a la propuesta', async () => {
    const calls = posts()
    await generateFromHome()
    await userEvent.click(screen.getByRole('button', { name: 'Detener la generación' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('button', { name: 'Ver la propuesta' }, { timeout: 4000 })).toBeInTheDocument()
    expect(calls.filter((call) => call === 'retry')).toHaveLength(1)
  })

  it('un not_cancellable (ya había terminado) no es un error: la generación sigue y termina', async () => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/cancel', () =>
        HttpResponse.json({ error: { code: 'not_cancellable', message: 'No hay nada que detener (ficticio).', retry_after: null } }, { status: 409 }),
      ),
    )
    await generateFromHome()
    await userEvent.click(screen.getByRole('button', { name: 'Detener la generación' }))
    expect(await screen.findByRole('button', { name: 'Ver la propuesta' }, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.queryByText('No hay nada que detener (ficticio).')).toBeNull()
  })

  it('si falla la petición de detener, lo dice y la generación sigue', async () => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/cancel', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 }),
      ),
    )
    await generateFromHome()
    await userEvent.click(screen.getByRole('button', { name: 'Detener la generación' }))
    expect(await screen.findByText('Servicio no disponible (ficticio).')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Detener la generación' })).toBeEnabled()
  })
})

describe('Iterar · Detener y Reintentar', () => {
  async function openAndAsk(change: string) {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    mockDb.stepDelayMs = SLOW_STEP_MS
    await userEvent.type(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta' }), change)
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
  }

  it('mientras se itera, «Detener» sustituye a enviar y la iteración termina como «Generación detenida»', async () => {
    await openAndAsk('Cambio ficticio')
    await userEvent.click(await screen.findByRole('button', { name: 'Detener la generación' }))
    expect(await screen.findByText('Deteniendo la generación…')).toBeInTheDocument()
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Generación detenida' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Enviar' })).toBeInTheDocument()
  })

  it('«Reintentar» repite la iteración con /retry, sin repetir el cambio en el chat, y sale la v3', async () => {
    const calls = posts()
    await openAndAsk('Cambio ficticio')
    await userEvent.click(await screen.findByRole('button', { name: 'Detener la generación' }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Reintentar' }))
    const panel = screen.getByRole('complementary', { name: 'Propuesta de HU' })
    expect(await within(panel).findByRole('button', { name: 'Versión 3' }, { timeout: 4000 })).toBeInTheDocument()
    expect(calls).toEqual(['iterate', 'cancel', 'retry'])
    await waitFor(() => expect(within(screen.getByRole('log', { name: 'Conversación' })).getAllByText('Cambio ficticio')).toHaveLength(1))
  })
})

describe('Generando · fallos del propio /retry (H-1) y detener justo antes de la revisión', () => {
  it('un 429 en /retry muestra su tarjeta y «Reintentar» vuelve a pedir /retry, sin abandonar la conversación', async () => {
    const calls = posts()
    await generateFromHome()
    await userEvent.click(screen.getByRole('button', { name: 'Detener la generación' }))
    mockServer.use(
      http.post(
        '/api/v1/conversations/:id/retry',
        () => HttpResponse.json({ error: { code: 'rate_limited', message: 'Límite de uso (ficticio).', retry_after: 0 } }, { status: 429 }),
        { once: true },
      ),
    )
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Reintentar' }))
    const limited = await screen.findByText('Límite de uso (ficticio).')
    await userEvent.click(within(limited.closest('[role=alert]') as HTMLElement).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('button', { name: 'Ver la propuesta' }, { timeout: 4000 })).toBeInTheDocument()
    expect(calls.filter((call) => call === 'retry')).toHaveLength(2)
    expect(calls.filter((call) => call === 'conversations')).toHaveLength(1)
  })

  it('si al detener el siguiente paso era la revisión, termina en la propuesta y no en «Generación detenida»', async () => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/cancel', ({ params }) => {
        const run = mockDb.runs.get(String(params.id))
        if (!run) return HttpResponse.json({ error: { code: 'not_found', message: 'x', retry_after: null } }, { status: 404 })
        // Como la API: la generación ya no tiene más pasos que cortar y pasa a la revisión.
        run.script = []
        return HttpResponse.json({ ...run.conversation, cancel_requested: true }, { status: 202 })
      }),
    )
    await generateFromHome()
    await userEvent.click(screen.getByRole('button', { name: 'Detener la generación' }))
    expect(await screen.findByRole('button', { name: 'Ver la propuesta' }, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.queryByText('Generación detenida')).toBeNull()
  })
})
