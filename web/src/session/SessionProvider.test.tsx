import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { hasCsrfToken } from '../api/client.ts'
import { DEMO_PASSWORD } from '../mocks/db.ts'
import { mockDb } from '../mocks/node.ts'
import { useSession } from './sessionContext.ts'
import { SessionProvider } from './SessionProvider.tsx'

function Probe({ password = DEMO_PASSWORD }: { password?: string }) {
  const { state, login, logout } = useSession()
  return (
    <div>
      <p data-testid="status">{state.status}</p>
      {state.status === 'authenticated' && <p data-testid="user">{`${state.user.username}:${state.user.role}`}</p>}
      {state.status === 'anonymous' && state.error && <p data-testid="error">{state.error.code}</p>}
      <button type="button" onClick={() => void login('af-demo', password)}>
        Entrar
      </button>
      <button type="button" onClick={() => void logout()}>
        Salir
      </button>
    </div>
  )
}

describe('SessionProvider', () => {
  it('sin sesión en la API queda anónima tras cargar', async () => {
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    )
    expect(screen.getByTestId('status')).toHaveTextContent('loading')
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
  })

  it('con sesión abierta (recarga) recupera el usuario y el token con GET /auth/me', async () => {
    mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('qa-demo:qa'))
    expect(hasCsrfToken()).toBe(true)
  })

  it('inicia y cierra sesión', async () => {
    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    await waitFor(() => expect(screen.getByTestId('user')).toHaveTextContent('af-demo:functional'))
    await userEvent.click(screen.getByRole('button', { name: 'Salir' }))
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    expect(hasCsrfToken()).toBe(false)
    expect(mockDb.session).toBeNull()
  })

  it('un login rechazado deja el error de la API', async () => {
    render(
      <SessionProvider>
        <Probe password="otra" />
      </SessionProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('invalid_credentials'))
  })
})
