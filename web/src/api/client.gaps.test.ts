// Criterio 1 (T-56, días 2-4): huecos de client.test.ts. X-CSRF-Token solo en lo que modifica algo,
// token solo en memoria, 204, cancelación y errores sin ErrorBody (DESIGN-DECISIONS.md §4).
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockDb, mockServer } from '../mocks/node.ts'
import { api, ApiRequestError, hasCsrfToken, setCsrfToken } from './client.ts'

const TOKEN = 'csrf-ficticio-de-prueba'
const BAD_RESPONSE_MESSAGE = 'Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo.'

function signIn() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: TOKEN }
  setCsrfToken(TOKEN)
}

/** Cabecera X-CSRF-Token de cada petición, por «MÉTODO ruta». */
function recordCsrf(): Map<string, string | null> {
  const seen = new Map<string, string | null>()
  mockServer.events.on('request:start', ({ request }) => {
    seen.set(`${request.method} ${new URL(request.url).pathname}`, request.headers.get('X-CSRF-Token'))
  })
  return seen
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('cliente: X-CSRF-Token solo en lo que modifica algo', () => {
  it('test_get_requests_never_send_csrf_with_token_in_memory', async () => {
    /** Criterio 1: ningún GET lleva X-CSRF-Token aunque haya token en memoria. */
    signIn()
    const seen = recordCsrf()
    await api.me()
    await api.projects()
    await api.epics('DEMO')
    await api.search('DEMO', 'renovar')
    await api.stories('DEMO-1')
    await api.issue('DEMO-3')
    await api.conversations()
    await api.settings()
    await api.usage()
    expect(seen.size).toBe(9)
    for (const [request, header] of seen) {
      expect(request.startsWith('GET ')).toBe(true)
      expect(header, request).toBeNull()
    }
  })

  it('test_post_requests_send_csrf_from_memory_on_every_mutation', async () => {
    /** Criterio 1: todo POST del cliente lleva el token de memoria. */
    signIn()
    const seen = recordCsrf()
    await api.chooseProject('DEMO')
    await api.propose({ text: 'Cambiar DEMO-3', project: 'DEMO', mode: 'functional' })
    await api.sources({ kind: 'story', key: 'DEMO-3', project: 'DEMO' })
    await api.createConversation({
      flow: 'evolve',
      origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' },
      excluded_sources: [],
      feedback: [],
    })
    await api.logout()
    expect([...seen.keys()]).toEqual([
      'POST /api/v1/projects/choose',
      'POST /api/v1/start/propose',
      'POST /api/v1/start/sources',
      'POST /api/v1/conversations',
      'POST /api/v1/auth/logout',
    ])
    for (const [request, header] of seen) expect(header, request).toBe(TOKEN)
  })

  it('test_post_without_token_omits_csrf_header', async () => {
    /** Criterio 1 (negativo): sin token en memoria no se envía la cabecera, ni vacía. */
    const seen = recordCsrf()
    await api.login('af-demo', 'contraseña-ficticia').catch(() => undefined)
    expect(seen.get('POST /api/v1/auth/login')).toBeNull()
  })

  it('test_csrf_header_stops_after_token_cleared', async () => {
    /** Criterio 1 (límite): tras setCsrfToken(null) los POST ya no llevan token. */
    signIn()
    setCsrfToken(null)
    const seen = recordCsrf()
    const failure = (await api.chooseProject('DEMO').catch((cause: unknown) => cause)) as ApiRequestError
    expect(seen.get('POST /api/v1/projects/choose')).toBeNull()
    expect(failure.status).toBe(403)
  })

  it('test_mutations_send_json_body_and_same_origin_credentials', async () => {
    /** Criterio 1: el POST va en JSON y el GET sin Content-Type. */
    signIn()
    const types = new Map<string, string | null>()
    mockServer.events.on('request:start', ({ request }) => {
      types.set(request.method, request.headers.get('Content-Type'))
    })
    await api.chooseProject('SOCI')
    await api.projects()
    expect(types.get('POST')).toBe('application/json')
    expect(types.get('GET')).toBeNull()
  })
})

describe('cliente: el token vive solo en memoria', () => {
  it('test_login_and_logout_never_write_browser_storage_or_cookies', async () => {
    /** Criterio 1: ni localStorage, ni sessionStorage, ni document.cookie se escriben. */
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const cookie = vi.spyOn(Document.prototype, 'cookie', 'set')
    const session = await api.login('af-demo', 'demo')
    setCsrfToken(session.csrf_token)
    await api.me()
    await api.chooseProject('DEMO')
    await api.logout()
    setCsrfToken(null)
    expect(setItem).not.toHaveBeenCalled()
    expect(cookie).not.toHaveBeenCalled()
  })

  it('test_token_not_kept_when_login_fails', async () => {
    /** Criterio 1 (negativo): un login fallido no deja token. */
    await api.login('af-demo', 'otra').catch(() => undefined)
    expect(hasCsrfToken()).toBe(false)
  })
})

describe('cliente: 204 sin cuerpo', () => {
  it('test_logout_204_resolves_undefined', async () => {
    /** Criterio 1: el 204 de logout se resuelve sin intentar leer JSON. */
    signIn()
    await expect(api.logout()).resolves.toBeUndefined()
  })

  it('test_any_204_resolves_undefined_even_on_get', async () => {
    /** Criterio 1 (límite): un 204 en cualquier ruta no rompe el cliente. */
    mockServer.use(http.get('/api/v1/settings', () => new HttpResponse(null, { status: 204 })))
    await expect(api.settings()).resolves.toBeUndefined()
  })
})

// DEFECTO D-01: client.ts reconoce la cancelación con `cause instanceof DOMException`. Con jsdom, el fetch
// de Node rechaza con el DOMException de Node (otro «realm») y el cliente lo convierte en service_unavailable.
// En el navegador los realms coinciden; comprobar `cause.name === 'AbortError'` lo hace robusto en ambos.
// `it.fails`: empezará a fallar (y habrá que cambiarlo a `it`) cuando se corrija.
describe('cliente: cancelación', () => {
  it('test_abort_rejects_with_abort_error_not_api_error', async () => {
    /** Criterio 1: la cancelación llega a quien llama como AbortError, no como service_unavailable. */
    signIn()
    mockServer.use(
      http.get('/api/v1/projects/:project/search', async () => {
        await delay('infinite')
        return HttpResponse.json([])
      }),
    )
    const controller = new AbortController()
    const pending = api.search('DEMO', 'renovar', controller.signal).catch((cause: unknown) => cause)
    controller.abort()
    const failure = await pending
    expect(failure).not.toBeInstanceOf(ApiRequestError)
    expect((failure as Error).name).toBe('AbortError')
  })

  it('test_already_aborted_signal_rejects_with_abort_error', async () => {
    /** Criterio 1 (límite): una señal ya cancelada no llega a pedir nada. */
    signIn()
    const controller = new AbortController()
    controller.abort()
    const failure = await api.search('DEMO', 'x', controller.signal).catch((cause: unknown) => cause)
    expect(failure).not.toBeInstanceOf(ApiRequestError)
    expect((failure as Error).name).toBe('AbortError')
  })
})

describe('cliente: errores sin ErrorBody', () => {
  it.each([
    ['HTML', () => new HttpResponse('<h1>Bad gateway</h1>', { status: 502, headers: { 'Content-Type': 'text/html' } })],
    ['cuerpo vacío', () => new HttpResponse(null, { status: 500 })],
    ['JSON sin error', () => HttpResponse.json({ detail: 'x' }, { status: 400 })],
    ['JSON con error null', () => HttpResponse.json({ error: null }, { status: 500 })],
  ])('test_error_without_error_body_is_unexpected_%s', async (_name, resolver) => {
    /** Criterio 1: una respuesta de error que no trae ErrorBody se trata como unexpected, con su estado. */
    mockServer.use(http.get('/api/v1/settings', resolver))
    const failure = (await api.settings().catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure).toBeInstanceOf(ApiRequestError)
    expect(failure.error).toEqual({ code: 'unexpected', message: BAD_RESPONSE_MESSAGE })
    expect(failure.message).toBe(BAD_RESPONSE_MESSAGE)
    expect(failure.status).toBeGreaterThanOrEqual(400)
  })

  it('test_error_message_never_includes_response_body', async () => {
    /** Criterio 1 (seguridad): el cuerpo crudo de un error no llega al mensaje para la UI. */
    mockServer.use(http.get('/api/v1/settings', () => new HttpResponse('Traceback: TU_API_KEY', { status: 500 })))
    const failure = (await api.settings().catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.error.message).not.toContain('TU_API_KEY')
  })

  it('test_api_error_keeps_retry_after', async () => {
    /** Criterio 1: un ErrorBody del contrato llega tal cual, con retry_after. */
    mockServer.use(
      http.get('/api/v1/settings', () =>
        HttpResponse.json(
          { error: { code: 'rate_limited', message: 'Límite de uso ficticio.', retry_after: 30 } },
          { status: 429 },
        ),
      ),
    )
    const failure = (await api.settings().catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.status).toBe(429)
    expect(failure.error).toEqual({ code: 'rate_limited', message: 'Límite de uso ficticio.', retry_after: 30 })
  })
})
