// Criterio 4 (T-56, días 2-4): huecos de SessionProvider.test.tsx. GET /auth/me al cargar, el error del
// login se conserva y el cierre de sesión borra el token aunque falle la API (DESIGN-DECISIONS.md §4).
import { act, render, screen, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { hasCsrfToken, setCsrfToken } from '../api/client.ts'
import { DEMO_PASSWORD } from '../mocks/db.ts'
import { mockDb, mockServer } from '../mocks/node.ts'
import { useSession, type SessionContextValue } from './sessionContext.ts'
import { SessionProvider } from './SessionProvider.tsx'

// Último valor del contexto, guardado tras pintar (no durante el render).
const probe: { current?: SessionContextValue } = {}

function Probe() {
  const value = useSession()
  useEffect(() => {
    probe.current = value
  })
  const { state } = value
  return (
    <div>
      <p data-testid="status">{state.status}</p>
      {state.status === 'anonymous' && state.error && <p data-testid="error">{`${state.error.code}|${state.error.message}`}</p>}
    </div>
  )
}

function renderSession() {
  return render(
    <SessionProvider>
      <Probe />
    </SessionProvider>,
  )
}

const status = () => screen.getByTestId('status')

function countRequests(method: string, path: string): () => number {
  let count = 0
  mockServer.events.on('request:start', ({ request }) => {
    if (request.method === method && new URL(request.url).pathname === path) count += 1
  })
  return () => count
}

afterEach(() => {
  mockServer.events.removeAllListeners()
  probe.current = undefined
})

describe('SessionProvider: carga', () => {
  it('test_me_requested_once_on_mount', async () => {
    /** Criterio 4: al cargar se pide GET /auth/me una vez. */
    const meCalls = countRequests('GET', '/api/v1/auth/me')
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('anonymous'))
    expect(meCalls()).toBe(1)
  })

  it('test_reload_restores_token_from_me_not_from_storage', async () => {
    /** Criterio 4: el token llega de /auth/me; no se lee del almacenamiento del navegador. */
    const getItem = vi.spyOn(Storage.prototype, 'getItem')
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio-recarga' }
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('authenticated'))
    expect(hasCsrfToken()).toBe(true)
    // MSW (dependencia de pruebas) lee «debugLevel»; la app no lee nada de sesión.
    const keys = getItem.mock.calls.map(([key]) => key)
    expect(keys.filter((key) => /csrf|token|session|sesion|user/i.test(key))).toEqual([])
  })

  it('test_me_service_unavailable_falls_back_to_anonymous_without_error', async () => {
    /** Criterio 4 (error): si /auth/me falla con 503, queda anónima (sin error de login que mostrar) y sin token. */
    mockServer.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio ficticio caído.' } }, { status: 503 }),
      ),
    )
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('anonymous'))
    expect(screen.queryByTestId('error')).toBeNull()
    expect(hasCsrfToken()).toBe(false)
  })

  it('test_unmount_before_me_resolves_does_not_update', async () => {
    /** Criterio 4 (límite): desmontar antes de que responda /auth/me no deja el token puesto. */
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    const { unmount } = renderSession()
    unmount()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(hasCsrfToken()).toBe(false)
  })
})

describe('SessionProvider: login', () => {
  it('test_login_error_kept_with_api_message', async () => {
    /** Criterio 4: el ErrorBody del login rechazado queda en el estado tal cual. */
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('anonymous'))
    await act(() => probe.current?.login('af-demo', 'otra') ?? Promise.resolve())
    expect(screen.getByTestId('error')).toHaveTextContent('invalid_credentials|Usuario o contraseña incorrectos.')
    expect(hasCsrfToken()).toBe(false)
  })

  it('test_login_success_after_error_clears_error', async () => {
    /** Criterio 4: un login correcto tras un error lo borra. */
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('anonymous'))
    await act(() => probe.current?.login('af-demo', 'otra') ?? Promise.resolve())
    await act(() => probe.current?.login('af-demo', DEMO_PASSWORD) ?? Promise.resolve())
    expect(status()).toHaveTextContent('authenticated')
    expect(screen.queryByTestId('error')).toBeNull()
  })

  it('test_login_network_failure_is_service_unavailable_error', async () => {
    /** Criterio 4 (error): sin conexión, el login deja un error service_unavailable con el mensaje del frontend. */
    mockServer.use(http.post('/api/v1/auth/login', () => HttpResponse.error()))
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('anonymous'))
    await act(() => probe.current?.login('af-demo', DEMO_PASSWORD) ?? Promise.resolve())
    expect(screen.getByTestId('error')).toHaveTextContent(/^service_unavailable\|No se pudo conectar con el servidor/)
  })

  it('test_login_too_many_attempts_keeps_retry_after', async () => {
    /** Criterio 4: el error too_many_attempts conserva retry_after para la cuenta atrás. */
    mockServer.use(
      http.post('/api/v1/auth/login', () =>
        HttpResponse.json({ error: { code: 'too_many_attempts', message: 'Demasiados intentos (ficticio).', retry_after: 42 } }, { status: 429 }),
      ),
    )
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('anonymous'))
    await act(() => probe.current?.login('af-demo', 'otra') ?? Promise.resolve())
    const { state } = probe.current ?? {}
    expect(state?.status === 'anonymous' ? state.error?.retry_after : undefined).toBe(42)
  })
})

describe('SessionProvider: logout', () => {
  async function signedIn() {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('authenticated'))
    expect(hasCsrfToken()).toBe(true)
  }

  it.each([
    ['500 sin ErrorBody', () => new HttpResponse(null, { status: 500 })],
    ['sin conexión', () => HttpResponse.error()],
    ['403 forbidden', () => HttpResponse.json({ error: { code: 'forbidden', message: 'x' } }, { status: 403 })],
  ])('test_logout_clears_token_when_api_fails_%s', async (_name, resolver) => {
    /** Criterio 4: aunque la API falle, el cierre de sesión borra el token y deja la sesión anónima sin error. */
    await signedIn()
    mockServer.use(http.post('/api/v1/auth/logout', resolver))
    await act(() => probe.current?.logout() ?? Promise.resolve())
    expect(status()).toHaveTextContent('anonymous')
    expect(screen.queryByTestId('error')).toBeNull()
    expect(hasCsrfToken()).toBe(false)
  })

  it('test_logout_sends_csrf_of_session', async () => {
    /** Criterio 4: el logout lleva el X-CSRF-Token recuperado con /auth/me. */
    await signedIn()
    let header: string | null = null
    mockServer.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/auth/logout') header = request.headers.get('X-CSRF-Token')
    })
    await act(() => probe.current?.logout() ?? Promise.resolve())
    expect(header).toBe('csrf-ficticio')
    expect(mockDb.session).toBeNull()
  })

  it('test_logout_without_session_still_ends_anonymous', async () => {
    /** Criterio 4 (límite): cerrar sesión sin estar dentro no falla. */
    renderSession()
    await waitFor(() => expect(status()).toHaveTextContent('anonymous'))
    setCsrfToken(null)
    await act(() => probe.current?.logout() ?? Promise.resolve())
    expect(status()).toHaveTextContent('anonymous')
  })

  it('test_use_session_outside_provider_throws', () => {
    /** Criterio 4 (error): usar la sesión fuera del proveedor da un error claro. */
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    expect(() => render(<Probe />)).toThrow('useSession necesita un SessionProvider.')
  })
})

describe('SessionProvider: interacción', () => {
  it('test_login_from_user_event_reaches_authenticated', async () => {
    /** Criterio 4: el login desde la interfaz deja la sesión abierta. */
    function Button() {
      const { login } = useSession()
      return (
        <button type="button" onClick={() => void login('qa-demo', DEMO_PASSWORD)}>
          Entrar
        </button>
      )
    }
    render(
      <SessionProvider>
        <Probe />
        <Button />
      </SessionProvider>,
    )
    await waitFor(() => expect(status()).toHaveTextContent('anonymous'))
    await userEvent.click(screen.getByRole('button', { name: 'Entrar' }))
    await waitFor(() => expect(status()).toHaveTextContent('authenticated'))
  })
})
