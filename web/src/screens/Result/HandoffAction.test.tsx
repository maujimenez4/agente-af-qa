// *Pedir sus pruebas a QA* en el Resultado (T-54): POST /conversations/{id}/handoff, solo el analista.
// Datos sintéticos (DEMO-3, af-demo).
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import { setCsrfToken } from '../../api/client.ts'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { HandoffAction } from './HandoffAction.tsx'
import { ResultScreen } from './ResultScreen.tsx'

const SIMULATED = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as ConversationOut & { result: PublishOutcome }
const HANDOFF = examples['POST /api/v1/conversations/{conversation_id}/handoff 200']

function asAnalyst() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  // Montado sin App: el token CSRF lo daría el inicio de sesión.
  setCsrfToken('csrf-ficticio')
}

describe('Pedir sus pruebas a QA', () => {
  it('pide /handoff y dice que QA la verá en Inicio', async () => {
    asAnalyst()
    mockServer.use(http.post('/api/v1/conversations/:id/handoff', () => HttpResponse.json(HANDOFF)))
    render(<HandoffAction conversationId={SIMULATED.id} />)
    await userEvent.click(screen.getByRole('button', { name: 'Pedir sus pruebas a QA' }))
    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('Enviada a QA. La verá quien tenga el rol QA en Inicio, en «Pendientes de pruebas».')
    expect(status).not.toHaveTextContent('Sin clave en Jira')
    expect(screen.queryByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeNull()
  })

  it('sin clave de Jira (aprobada en simulación) avisa de que QA no podrá publicar los casos', async () => {
    asAnalyst()
    mockServer.use(http.post('/api/v1/conversations/:id/handoff', () => HttpResponse.json({ ...HANDOFF, story_key: null })))
    render(<HandoffAction conversationId={SIMULATED.id} />)
    await userEvent.click(screen.getByRole('button', { name: 'Pedir sus pruebas a QA' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Sin clave en Jira: QA podrá generar y revisar los casos, pero no publicarlos hasta que se publique la HU.')
  })

  it('un doble clic pide /handoff una sola vez', async () => {
    asAnalyst()
    let calls = 0
    mockServer.use(
      http.post('/api/v1/conversations/:id/handoff', () => {
        calls += 1
        return HttpResponse.json(HANDOFF)
      }),
    )
    render(<HandoffAction conversationId={SIMULATED.id} />)
    const button = screen.getByRole('button', { name: 'Pedir sus pruebas a QA' })
    fireEvent.click(button)
    fireEvent.click(button)
    await screen.findByRole('status')
    expect(calls).toBe(1)
  })

  it('un fallo muestra su tarjeta con el mensaje tal cual y deja volver a pedirlo', async () => {
    asAnalyst()
    mockServer.use(
      http.post(
        '/api/v1/conversations/:id/handoff',
        () => HttpResponse.json({ error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira (ficticio).', retry_after: null } }, { status: 503 }),
        { once: true },
      ),
      http.post('/api/v1/conversations/:id/handoff', () => HttpResponse.json(HANDOFF)),
    )
    render(<HandoffAction conversationId={SIMULATED.id} />)
    await userEvent.click(screen.getByRole('button', { name: 'Pedir sus pruebas a QA' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('No se pudo conectar con Jira (ficticio).')
    await userEvent.click(screen.getByRole('button', { name: 'Pedir sus pruebas a QA' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Enviada a QA.')
  })

  it('en el Resultado solo sale si se puede pasar a QA; si no, no hay botón', () => {
    const { unmount } = render(<ResultScreen conversation={SIMULATED} canHandoff />)
    expect(screen.getByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeEnabled()
    unmount()
    render(<ResultScreen conversation={SIMULATED} />)
    expect(screen.queryByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeNull()
  })

  it('con la API simulada, una conversación aún en revisión no se pasa a QA (409, mensaje tal cual)', async () => {
    asAnalyst()
    render(<HandoffAction conversationId="8b0f3c2e-7d41-4a5e-9c6b-1e2f3a4b5c6d" />)
    // La conversación de ejemplo está en revisión: la API simulada responde 409 como la real.
    await userEvent.click(screen.getByRole('button', { name: 'Pedir sus pruebas a QA' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('La conversación tiene una operación en curso o aún no está aprobada.')
    expect(mockDb.handoffs.map((item) => item.id)).not.toContain('8b0f3c2e7d414a5e9c6b1e2f3a4b5c6d')
  })
})
