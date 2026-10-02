// Criterio 6 (T-56, días 2-4, PA-311): huecos de LoginScreen.test.tsx. Validación, invalid_credentials y
// too_many_attempts, que desactiva el envío hasta retry_after (DESIGN-DECISIONS.md §6).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LoginIn } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { DEMO_PASSWORD } from '../../mocks/db.ts'
import { mockServer } from '../../mocks/node.ts'

async function openLogin() {
  render(<App />)
  await screen.findByRole('heading', { name: 'Agente AF y QA' })
}

const usernameField = () => screen.getByLabelText('Usuario')
const passwordField = () => screen.getByLabelText('Contraseña')
const submitButton = () => screen.getByRole('button', { name: /Iniciar sesión|Entrando…/ })

function tooManyAttempts(retryAfter: number | null) {
  return http.post('/api/v1/auth/login', () =>
    HttpResponse.json(
      { error: { code: 'too_many_attempts', message: 'Demasiados intentos de inicio de sesión (ficticio).', retry_after: retryAfter } },
      { status: 429 },
    ),
  )
}

function loginBodies(): LoginIn[] {
  const bodies: LoginIn[] = []
  mockServer.events.on('request:start', ({ request }) => {
    if (new URL(request.url).pathname === '/api/v1/auth/login') {
      void request.clone().json().then((body) => bodies.push(body as LoginIn))
    }
  })
  return bodies
}

afterEach(() => {
  mockServer.events.removeAllListeners()
  vi.useRealTimers()
})

describe('Login: validación', () => {
  it('test_whitespace_username_is_missing', async () => {
    /** Criterio 6 (negativo): un usuario con solo espacios cuenta como vacío. */
    await openLogin()
    await userEvent.type(usernameField(), '   ')
    await userEvent.type(passwordField(), 'x')
    await userEvent.click(submitButton())
    expect(usernameField()).toHaveAccessibleDescription('Escribe tu usuario.')
    expect(passwordField()).not.toHaveAttribute('aria-invalid')
  })

  it('test_only_password_missing_marks_only_password', async () => {
    /** Criterio 6 (negativo): falta solo la contraseña; el usuario no se marca. */
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.click(submitButton())
    expect(passwordField()).toHaveAttribute('aria-invalid', 'true')
    expect(usernameField()).not.toHaveAttribute('aria-invalid')
  })

  it('test_username_trimmed_password_sent_as_typed', async () => {
    /** Criterio 6: el usuario se envía sin espacios alrededor y la contraseña tal cual. */
    const bodies = loginBodies()
    await openLogin()
    await userEvent.type(usernameField(), '  af-demo  ')
    await userEvent.type(passwordField(), ' clave ficticia ')
    await userEvent.click(submitButton())
    await screen.findByRole('alert')
    await waitFor(() => expect(bodies).toEqual([{ username: 'af-demo', password: ' clave ficticia ' }]))
  })

  it('test_validation_errors_clear_on_valid_resubmit', async () => {
    /** Criterio 6: al reenviar con datos, desaparecen los errores de campo. */
    await openLogin()
    await userEvent.click(submitButton())
    expect(usernameField()).toHaveAttribute('aria-invalid', 'true')
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), DEMO_PASSWORD)
    await userEvent.click(submitButton())
    expect(await screen.findByRole('navigation', { name: 'Zonas' })).toBeInTheDocument()
  })

  it('test_enter_in_password_submits_form', async () => {
    /** Criterio 6: Intro en la contraseña envía el formulario. */
    await openLogin()
    await userEvent.type(usernameField(), 'qa-demo')
    await userEvent.type(passwordField(), `${DEMO_PASSWORD}{Enter}`)
    expect(await screen.findByRole('navigation', { name: 'Zonas' })).toBeInTheDocument()
  })

  it('test_submit_disabled_and_labelled_while_sending', async () => {
    /** Criterio 6: mientras se envía, el botón dice «Entrando…» y está desactivado (sin doble envío). */
    mockServer.use(
      http.post('/api/v1/auth/login', async () => {
        await delay(150)
        return HttpResponse.json({ error: { code: 'invalid_credentials', message: 'Usuario o contraseña incorrectos.' } }, { status: 401 })
      }),
    )
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'otra')
    await userEvent.click(submitButton())
    expect(screen.getByRole('button', { name: 'Entrando…' })).toBeDisabled()
    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'Iniciar sesión' })).toBeEnabled()
  })
})

describe('Login: invalid_credentials', () => {
  it('test_invalid_credentials_keeps_username_and_allows_retry', async () => {
    /** Criterio 6: tras credenciales incorrectas se conserva el usuario y se puede volver a intentar ya. */
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'otra')
    await userEvent.click(submitButton())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveAttribute('data-tone', 'error')
    expect(usernameField()).toHaveValue('af-demo')
    expect(submitButton()).toBeEnabled()
    expect(within(alert).queryByRole('button')).toBeNull()
  })

  it('test_password_never_shown_in_error', async () => {
    /** Criterio 6 (seguridad): la contraseña escrita no aparece en la tarjeta de error. */
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'clave-ficticia-123')
    await userEvent.click(submitButton())
    const alert = await screen.findByRole('alert')
    expect(alert).not.toHaveTextContent('clave-ficticia-123')
    expect(document.body).not.toHaveTextContent('clave-ficticia-123')
  })

  it('test_api_message_shown_as_text_not_html', async () => {
    /** Criterio 6 (seguridad): el mensaje de la API se pinta como texto. */
    mockServer.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({ error: { code: 'invalid_credentials', message: '<img src=x onerror=alert(1)>' } }, { status: 401 }),
      ),
    )
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'otra')
    await userEvent.click(submitButton())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('<img src=x onerror=alert(1)>')
    expect(alert.querySelector('img')).toBeNull()
  })

  it('test_mock_users_note_hidden_outside_mock_mode', async () => {
    /** Criterio 6 (seguridad): la nota con la contraseña ficticia solo sale con la API simulada en desarrollo. */
    await openLogin()
    expect(screen.queryByText(/API simulada: usuarios/)).toBeNull()
  })
})

describe('Login: too_many_attempts', () => {
  it('test_too_many_attempts_shows_warning_and_countdown', async () => {
    /** Criterio 6: aviso «Demasiados intentos» con la cuenta atrás de retry_after y frase fija para lectores. */
    mockServer.use(tooManyAttempts(5))
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'otra')
    await userEvent.click(submitButton())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveAttribute('data-tone', 'warning')
    expect(within(alert).getByRole('heading', { name: 'Demasiados intentos' })).toBeInTheDocument()
    expect(alert).toHaveTextContent('Podrás reintentar dentro de 5 segundos.')
    expect(alert).toHaveTextContent('Reintento disponible en 5 s')
    expect(submitButton()).toBeDisabled()
  })

  it('test_too_many_attempts_enter_does_not_submit_while_blocked', async () => {
    /** Criterio 6 (negativo): durante la espera, Intro en la contraseña no vuelve a llamar a la API. */
    mockServer.use(tooManyAttempts(30))
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'otra')
    await userEvent.click(submitButton())
    await screen.findByRole('alert')
    const bodies = loginBodies()
    await userEvent.type(passwordField(), `otra{Enter}`)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(bodies).toEqual([])
  })

  it.each([
    ['null', null],
    ['0', 0],
    ['negativo', -3],
  ])('test_too_many_attempts_without_wait_%s_keeps_submit_enabled', async (_name, retryAfter) => {
    /** Criterio 6 (límite): sin retry_after positivo, el botón no se bloquea. */
    mockServer.use(tooManyAttempts(retryAfter))
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'otra')
    await userEvent.click(submitButton())
    await screen.findByRole('alert')
    expect(submitButton()).toBeEnabled()
  })

  it('test_too_many_attempts_unblocks_exactly_after_retry_after', async () => {
    /** Criterio 6 (límite): con retry_after = 2 sigue bloqueado al segundo y se libera a los 2 s. */
    mockServer.use(tooManyAttempts(2))
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'otra')
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'], shouldAdvanceTime: true })
    await userEvent.click(submitButton())
    await screen.findByRole('alert')
    expect(submitButton()).toBeDisabled()
    await vi.advanceTimersByTimeAsync(1000)
    expect(submitButton()).toBeDisabled()
    await vi.advanceTimersByTimeAsync(1100)
    await waitFor(() => expect(submitButton()).toBeEnabled())
  })

  it('test_invalid_credentials_after_block_does_not_block', async () => {
    /** Criterio 6: un invalid_credentials posterior a la espera no vuelve a bloquear. */
    mockServer.use(tooManyAttempts(1))
    await openLogin()
    await userEvent.type(usernameField(), 'af-demo')
    await userEvent.type(passwordField(), 'otra')
    await userEvent.click(submitButton())
    await screen.findByRole('alert')
    await waitFor(() => expect(submitButton()).toBeEnabled(), { timeout: 2500 })
    mockServer.resetHandlers()
    await userEvent.type(passwordField(), 'otra')
    await userEvent.click(submitButton())
    expect(await screen.findByRole('heading', { name: 'No se pudo iniciar sesión' })).toBeInTheDocument()
    expect(submitButton()).toBeEnabled()
  })
})
