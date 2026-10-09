import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../../App.tsx'
import { DEMO_PASSWORD } from '../../mocks/db.ts'
import { mockServer } from '../../mocks/node.ts'

async function openLogin() {
  render(<App />)
  await screen.findByRole('heading', { name: 'Hola de nuevo' })
}

async function fill(username: string, password: string) {
  if (username) await userEvent.type(screen.getByLabelText('Usuario'), username)
  if (password) await userEvent.type(screen.getByLabelText('Contraseña'), password)
  await userEvent.click(screen.getByRole('button', { name: 'Entrar en FAQ' }))
}

describe('LoginScreen (PA-311)', () => {
  it('pide usuario y contraseña con sus etiquetas, y el foco empieza en el usuario', async () => {
    await openLogin()
    await waitFor(() => expect(screen.getByLabelText('Usuario')).toHaveFocus())
    expect(screen.getByLabelText('Usuario')).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText('Contraseña')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText('Contraseña')).toHaveAttribute('autocomplete', 'current-password')
  })

  it('sin datos no llama a la API y marca cada campo con su error', async () => {
    const calls = vi.fn()
    mockServer.events.on('request:start', calls)
    await openLogin()
    calls.mockClear()
    await fill('', '')
    expect(screen.getByLabelText('Usuario')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Usuario')).toHaveAccessibleDescription('Escribe tu usuario.')
    expect(screen.getByLabelText('Contraseña')).toHaveAccessibleDescription('Escribe tu contraseña.')
    expect(calls).not.toHaveBeenCalled()
    mockServer.events.removeAllListeners()
  })

  it('con un usuario demo entra en la app', async () => {
    await openLogin()
    await fill('af-demo', DEMO_PASSWORD)
    expect(await screen.findByRole('navigation', { name: 'Zonas' })).toBeInTheDocument()
  })

  it('una contraseña incorrecta muestra la tarjeta de error con el mensaje de la API y vacía la contraseña', async () => {
    await openLogin()
    await fill('af-demo', 'otra')
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'No se pudo iniciar sesión' })).toBeInTheDocument()
    expect(alert).toHaveTextContent('Usuario o contraseña incorrectos.')
    expect(screen.getByLabelText('Contraseña')).toHaveValue('')
  })

  it('con too_many_attempts el botón espera a retry_after', async () => {
    mockServer.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json(
          { error: { code: 'too_many_attempts', message: 'Demasiados intentos; espera unos minutos.', retry_after: 1 } },
          { status: 429 },
        ),
      ),
    )
    await openLogin()
    await fill('af-demo', 'otra')
    await screen.findByRole('alert')
    const submit = screen.getByRole('button', { name: 'Entrar en FAQ' })
    expect(submit).toBeDisabled()
    await waitFor(() => expect(submit).toBeEnabled(), { timeout: 2500 })
  })
})
