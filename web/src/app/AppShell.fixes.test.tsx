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

describe('Retomar una conversación generando (H-2)', () => {
  it('si la generación falla, «Volver a generar» lleva a Inicio y no a un Origen vacío', async () => {
    const failure = { ...EXAMPLE, state: 'error', review: null, error: { code: 'citation_failed', message: 'La propuesta cita fuentes que no están en el contexto recibido.' } }
    mockServer.use(
      http.get('/api/v1/conversations/:id/events', () =>
        new HttpResponse(`event: error\ndata: ${JSON.stringify(failure)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } }),
      ),
    )
    await resume({ ...EXAMPLE, state: 'generating', review: null })
    const alert = await screen.findByRole('alert')
    await userEvent.click(within(alert).getByRole('button', { name: 'Volver a generar' }))
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

  it('sin `error` en la respuesta usa el texto de respaldo', async () => {
    await resume({ ...EXAMPLE, state: 'error', review: null, error: null })
    expect(await screen.findByText(/Esta conversación no puede continuar/)).toBeInTheDocument()
  })
})
