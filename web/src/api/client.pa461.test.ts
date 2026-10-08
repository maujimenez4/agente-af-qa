// PA-461: si se inicia sesión en otra pestaña, esta se queda con el token CSRF antiguo y cada acción daba
// «Sin permiso» sin salida. Ante un 403 en un método que modifica, el cliente pide /auth/me una sola vez: la misma
// persona con otro token → guarda el nuevo y reintenta una vez solo lo que se puede repetir; el mismo token → el
// 403 es de permisos y se muestra; nunca hay bucles. Datos sintéticos (af-demo, DEMO).
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mockDb, mockServer } from '../mocks/node.ts'
import { api, ApiRequestError, onSessionChecked, onUnauthenticated, SESSION_RENEWED_MESSAGE, setCsrfToken } from './client.ts'

const OLD = 'csrf-ficticio-antiguo'
const NEW = 'csrf-ficticio-nuevo'

/** Esta pestaña tiene el token antiguo; en «otra pestaña» se inició sesión y la API ya espera el nuevo. */
function staleTab(username = 'af-demo', role: 'functional' | 'qa' | 'admin' = 'functional') {
  setCsrfToken(OLD)
  mockDb.session = { username, role, csrf: NEW }
}

/** Peticiones por «MÉTODO ruta», con el token que llevaban. */
function recordRequests() {
  const seen: { call: string; csrf: string | null }[] = []
  mockServer.events.on('request:start', ({ request }) => {
    seen.push({ call: `${request.method} ${new URL(request.url).pathname}`, csrf: request.headers.get('X-CSRF-Token') })
  })
  const count = (call: string) => seen.filter((item) => item.call === call).length
  return { seen, count }
}

// Como `SessionProvider` en la app: confirma que /auth/me es de la misma persona (af-demo).
let stopCheck: () => void = () => undefined
beforeEach(() => {
  stopCheck = onSessionChecked((session) => session.user.username === 'af-demo')
})

afterEach(() => {
  stopCheck()
  mockServer.events.removeAllListeners()
  setCsrfToken(null)
})

describe('Tras un 403 por un token CSRF antiguo (PA-461)', () => {
  it('una acción repetible se reintenta una vez con el token nuevo y sale bien', async () => {
    staleTab()
    const requests = recordRequests()
    const project = await api.chooseProject('DEMO')
    expect(project).toBeDefined()
    expect(requests.count('GET /api/v1/auth/me')).toBe(1)
    const posts = requests.seen.filter((item) => item.call === 'POST /api/v1/projects/choose')
    expect(posts.map((item) => item.csrf)).toEqual([OLD, NEW])
  })

  it('una acción que no se repite sola no se reenvía: avisa para repetirla, y la siguiente ya lleva el token nuevo', async () => {
    staleTab()
    const requests = recordRequests()
    const failure = (await api.discard('c-ficticia').catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure).toBeInstanceOf(ApiRequestError)
    expect(failure.error).toEqual({ code: 'operation_failed', message: SESSION_RENEWED_MESSAGE })
    expect(requests.count('POST /api/v1/conversations/c-ficticia/discard')).toBe(1) // nunca dos veces
    expect(requests.count('GET /api/v1/auth/me')).toBe(1)

    await api.chooseProject('DEMO')
    expect(requests.seen.filter((item) => item.call === 'POST /api/v1/projects/choose').map((item) => item.csrf)).toEqual([NEW])
  })

  it('con el mismo token, el 403 es de permisos de verdad: se muestra tal cual, sin reintentar', async () => {
    setCsrfToken(NEW)
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: NEW } // Administración es solo para admin
    const requests = recordRequests()
    const failure = (await api.adminConnectionsTest().catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.status).toBe(403)
    expect(failure.error.code).toBe('forbidden')
    expect(requests.count('POST /api/v1/admin/connections/test')).toBe(1)
    expect(requests.count('GET /api/v1/auth/me')).toBe(1)
  })

  it('varios 403 a la vez comparten una sola consulta a /auth/me', async () => {
    staleTab()
    const requests = recordRequests()
    await Promise.all([api.chooseProject('DEMO'), api.chooseProject('DEMO'), api.propose({ text: 'Renovar un préstamo', project: 'DEMO', mode: 'functional' })])
    expect(requests.count('GET /api/v1/auth/me')).toBe(1)
  })

  it('sin bucles: si el reintento vuelve a dar 403, se muestra ese error y no se pregunta más', async () => {
    staleTab()
    const requests = recordRequests()
    // La «otra pestaña» vuelve a renovar el token justo después: el reintento también llega con uno antiguo.
    mockServer.events.on('response:mocked', ({ request }) => {
      if (new URL(request.url).pathname === '/api/v1/auth/me' && mockDb.session) mockDb.session = { ...mockDb.session, csrf: 'csrf-ficticio-otro' }
    })
    const failure = (await api.chooseProject('DEMO').catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.status).toBe(403)
    expect(failure.error.code).toBe('forbidden')
    expect(requests.count('POST /api/v1/projects/choose')).toBe(2)
    expect(requests.count('GET /api/v1/auth/me')).toBe(1)
  })

  it('si /auth/me dice que es otra persona, no se reintenta y la sesión decide (vuelve al inicio de sesión)', async () => {
    staleTab('qa-demo', 'qa')
    const checked: string[] = []
    const stop = onSessionChecked((session) => {
      checked.push(session.user.username)
      return false // otra persona
    })
    const requests = recordRequests()
    const failure = (await api.chooseProject('DEMO').catch((cause: unknown) => cause)) as ApiRequestError
    stop()
    expect(checked).toEqual(['qa-demo'])
    expect(failure.status).toBe(403)
    expect(requests.count('POST /api/v1/projects/choose')).toBe(1)
  })

  it('sin nadie que confirme que es la misma persona, no se acepta el token ni se reintenta', async () => {
    stopCheck()
    staleTab()
    const requests = recordRequests()
    const failure = (await api.chooseProject('DEMO').catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.status).toBe(403)
    expect(requests.count('POST /api/v1/projects/choose')).toBe(1)
    await api.projects() // sigue con el token antiguo: el siguiente POST tampoco lo llevaría nuevo
    const again = (await api.chooseProject('DEMO').catch((cause: unknown) => cause)) as ApiRequestError
    expect(requests.seen.filter((item) => item.call === 'POST /api/v1/projects/choose').map((item) => item.csrf)).toEqual([OLD, OLD])
    expect(again.status).toBe(403)
  })

  it('si /auth/me no responde (503), se devuelve el 403 original sin reintentar', async () => {
    staleTab()
    mockServer.use(http.get('/api/v1/auth/me', () => HttpResponse.json({ error: { code: 'service_unavailable', message: 'Caído (ficticio).' } }, { status: 503 }), { once: true }))
    const requests = recordRequests()
    const failure = (await api.chooseProject('DEMO').catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.status).toBe(403)
    expect(failure.error.code).toBe('forbidden')
    expect(requests.count('POST /api/v1/projects/choose')).toBe(1)
  })

  it('si /auth/me da 401 (sesión caducada), avisa a la sesión y devuelve el 403 original', async () => {
    staleTab()
    mockServer.use(http.get('/api/v1/auth/me', () => HttpResponse.json({ error: { code: 'unauthenticated', message: 'Caducada (ficticio).' } }, { status: 401 }), { once: true }))
    const expired: string[] = []
    const stop = onUnauthenticated((error) => expired.push(error.message))
    const failure = (await api.chooseProject('DEMO').catch((cause: unknown) => cause)) as ApiRequestError
    stop()
    expect(expired).toEqual(['Caducada (ficticio).'])
    expect(failure.status).toBe(403)
  })

  it('un GET con 403 no pregunta a /auth/me (solo los métodos que modifican)', async () => {
    staleTab()
    mockServer.use(
      http.get('/api/v1/projects', () => HttpResponse.json({ error: { code: 'forbidden', message: 'Sin permiso (ficticio).' } }, { status: 403 })),
    )
    const requests = recordRequests()
    const failure = (await api.projects().catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.status).toBe(403)
    expect(requests.count('GET /api/v1/auth/me')).toBe(0)
  })
})
