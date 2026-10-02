import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { App } from '../App.tsx'
import { mockDb, mockServer } from '../mocks/node.ts'

describe('AppShell: lista de conversaciones con error (UI.md §7)', () => {
  it('si GET /conversations falla, muestra la tarjeta de error con Reintentar en lugar del estado vacío', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    let fail = true
    mockServer.use(
      http.get('/api/v1/conversations', () =>
        fail
          ? HttpResponse.json(
              { error: { code: 'service_unavailable', message: 'No se pudieron leer las conversaciones.' } },
              { status: 503 },
            )
          : HttpResponse.json(mockDb.conversations),
      ),
    )
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    const alert = await within(list).findByRole('alert')
    expect(alert).toHaveTextContent('No se pudieron leer las conversaciones.')
    fail = false
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ })).toBeInTheDocument()
    expect(within(list).queryByRole('alert')).toBeNull()
  })
})
