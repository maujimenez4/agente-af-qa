// Correcciones de la revisión de spec-checker sobre el marco (H-2 y H-3).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import examples from '../api/examples.json'
import type { ConversationOut } from '../api/types.ts'
import { App } from '../App.tsx'
import { mockDb, mockServer } from '../mocks/node.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut

async function resume(conversation: ConversationOut) {
  mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json(conversation)))
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
}

describe('Retomar una conversación generando (H-2, PA-276)', () => {
  it('si la generación falla con la conversación en error, «Volver a generar» repite con /retry y sigue generando', async () => {
    const failure = { ...EXAMPLE, state: 'error', review: null, error: { code: 'citation_failed', message: 'La propuesta cita fuentes que no están en el contexto recibido.' } }
    let retries = 0
    mockServer.use(
      http.get(
        '/api/v1/conversations/:id/events',
        () => new HttpResponse(`event: error\ndata: ${JSON.stringify(failure)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } }),
        { once: true },
      ),
      http.get('/api/v1/conversations/:id/events', () => new HttpResponse(': latido\n\n', { headers: { 'Content-Type': 'text/event-stream' } })),
      http.post('/api/v1/conversations/:id/retry', () => {
        retries += 1
        return HttpResponse.json({ ...EXAMPLE, state: 'generating', review: null, error: null }, { status: 202 })
      }),
    )
    await resume({ ...EXAMPLE, state: 'generating', review: null })
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Volver a generar' }))
    expect(await screen.findByText('Generando la propuesta…')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(retries).toBe(1)
  })

  it('sin conversación que reintentar (falla la lectura del estado), la acción lleva a Inicio y no a un Origen vacío', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => HttpResponse.error()),
      http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, state: 'generating', review: null }), { once: true }),
      http.get('/api/v1/conversations/:id', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 }),
      ),
    )
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    await userEvent.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Antes de generar' })).toBeNull()
  })
})

describe('Retomar una conversación terminada en error (H-3)', () => {
  it('muestra el mensaje de la API tal cual, sin «Volver a generar», y deja empezar otra', async () => {
    await resume({ ...EXAMPLE, state: 'error', review: null, error: { code: 'provider_timeout', message: 'El modelo no respondió a tiempo (mensaje ficticio).' } })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('El modelo no respondió a tiempo (mensaje ficticio).')
    expect(within(alert).queryByRole('button')).toBeNull()
    expect(screen.queryByText(/Esta conversación no puede continuar/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Empezar una conversación nueva' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('sin `error` en la respuesta usa el texto de respaldo y también ofrece «Reintentar»', async () => {
    await resume({ ...EXAMPLE, state: 'error', review: null, error: null })
    expect(await screen.findByText(/Esta conversación no puede continuar/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeEnabled()
  })
})

describe('Retomar una conversación terminada en error: Reintentar (PA-276)', () => {
  const failed = { ...EXAMPLE, state: 'error' as const, review: null, error: { code: 'cancelled' as const, message: 'Generación detenida (ficticio).', retry_after: null } }

  it('«Reintentar» llama a /retry y abre Generando', async () => {
    let retries = 0
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => new HttpResponse(': latido\n\n', { headers: { 'Content-Type': 'text/event-stream' } })),
      http.post('/api/v1/conversations/:id/retry', () => {
        retries += 1
        return HttpResponse.json({ ...EXAMPLE, state: 'generating', review: null, error: null }, { status: 202 })
      }),
    )
    await resume(failed)
    expect(await screen.findByRole('alert')).toHaveTextContent('Generación detenida (ficticio).')
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByText('Generando la propuesta…')).toBeInTheDocument()
    expect(retries).toBe(1)
  })

  it('si /retry responde not_in_error, muestra ese mensaje y deja empezar otra', async () => {
    mockServer.use(
      http.post('/api/v1/conversations/:id/retry', () =>
        HttpResponse.json({ error: { code: 'not_in_error', message: 'No hay nada que reintentar (ficticio).', retry_after: null } }, { status: 409 }),
      ),
    )
    await resume(failed)
    await userEvent.click(await screen.findByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByText('No hay nada que reintentar (ficticio).')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Empezar una conversación nueva' })).toBeInTheDocument()
  })
})

describe('Retomar en error: un fallo pasajero de /retry (H-2)', () => {
  it('con un 503 en /retry se muestra el mensaje y «Reintentar» sigue disponible y vuelve a pedirlo', async () => {
    const failed = { ...EXAMPLE, state: 'error' as const, review: null, error: { code: 'cancelled' as const, message: 'Generación detenida (ficticio).', retry_after: null } }
    let retries = 0
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () => new HttpResponse(': latido\n\n', { headers: { 'Content-Type': 'text/event-stream' } })),
      http.post('/api/v1/conversations/:id/retry', () => {
        retries += 1
        return retries === 1
          ? HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio no disponible (ficticio).', retry_after: null } }, { status: 503 })
          : HttpResponse.json({ ...EXAMPLE, state: 'generating', review: null, error: null }, { status: 202 })
      }),
    )
    await resume(failed)
    await userEvent.click(await screen.findByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByText('Servicio no disponible (ficticio).')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(await screen.findByText('Generando la propuesta…')).toBeInTheDocument()
    expect(retries).toBe(2)
  })
})
