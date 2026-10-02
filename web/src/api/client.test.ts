import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { DEMO_PASSWORD } from '../mocks/db.ts'
import { mockServer } from '../mocks/node.ts'
import { api, ApiRequestError, hasCsrfToken, NETWORK_ERROR_MESSAGE, setCsrfToken, toApiError, UNEXPECTED_ERROR } from './client.ts'

async function loginAndKeepToken() {
  const session = await api.login('af-demo', DEMO_PASSWORD)
  setCsrfToken(session.csrf_token)
  return session
}

describe('cliente de la API', () => {
  it('llama a rutas del mismo origen bajo /api/v1', async () => {
    let seen = ''
    mockServer.use(
      http.get('/api/v1/projects', ({ request }) => {
        seen = request.url
        return HttpResponse.json({ projects: [], preselected: null })
      }),
    )
    await api.projects()
    expect(new URL(seen).origin).toBe(window.location.origin)
    expect(new URL(seen).pathname).toBe('/api/v1/projects')
  })

  it('envía X-CSRF-Token en lo que modifica algo, y no en GET', async () => {
    const session = await loginAndKeepToken()
    const headers: Record<string, string | null> = {}
    mockServer.use(
      http.get('/api/v1/settings', ({ request }) => {
        headers.get = request.headers.get('X-CSRF-Token')
        return HttpResponse.json({ publish_mode: 'simulation', tasks: [] })
      }),
      http.post('/api/v1/projects/choose', ({ request }) => {
        headers.post = request.headers.get('X-CSRF-Token')
        return HttpResponse.json({ project: 'DEMO' })
      }),
    )
    await api.settings()
    await api.chooseProject('DEMO')
    expect(headers.get).toBeNull()
    expect(headers.post).toBe(session.csrf_token)
  })

  it('el token anti-CSRF vive solo en memoria', async () => {
    expect(hasCsrfToken()).toBe(false)
    await loginAndKeepToken()
    expect(hasCsrfToken()).toBe(true)
    setCsrfToken(null)
    expect(hasCsrfToken()).toBe(false)
  })

  it('un error de la API llega como ApiRequestError con su ErrorBody tal cual', async () => {
    await loginAndKeepToken()
    const failure = await api.issue('DEMO-99').catch((cause: unknown) => cause)
    expect(failure).toBeInstanceOf(ApiRequestError)
    expect((failure as ApiRequestError).status).toBe(404)
    expect((failure as ApiRequestError).error).toEqual({
      code: 'not_found',
      message: 'La incidencia DEMO-99 no existe o no tienes permiso para verla.',
      retry_after: null,
    })
  })

  it('sin sesión, la API responde unauthenticated', async () => {
    const failure = (await api.me().catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.error.code).toBe('unauthenticated')
  })

  it('si no hay respuesta, da un error service_unavailable con mensaje del frontend', async () => {
    mockServer.use(http.get('/api/v1/settings', () => HttpResponse.error()))
    const failure = (await api.settings().catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.status).toBe(0)
    expect(failure.error).toEqual({ code: 'service_unavailable', message: NETWORK_ERROR_MESSAGE })
  })

  it('una respuesta de error sin ErrorBody se trata como unexpected', async () => {
    mockServer.use(http.get('/api/v1/settings', () => new HttpResponse('<html>', { status: 502 })))
    const failure = (await api.settings().catch((cause: unknown) => cause)) as ApiRequestError
    expect(failure.error.code).toBe('unexpected')
  })

  it('codifica las claves y el texto buscado en la URL', async () => {
    let seen = ''
    await loginAndKeepToken()
    mockServer.use(
      http.get('/api/v1/projects/:project/search', ({ request }) => {
        seen = request.url
        return HttpResponse.json([])
      }),
    )
    await api.search('DEMO', 'préstamo & más')
    expect(new URL(seen).searchParams.get('q')).toBe('préstamo & más')
  })

  it('crear una conversación devuelve el 202 con su estado inicial', async () => {
    await loginAndKeepToken()
    const conversation = await api.createConversation({
      flow: 'evolve',
      origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' },
      excluded_sources: [],
      feedback: [],
    })
    expect(conversation.state).toBe('generating')
  })
})

describe('toApiError', () => {
  it('devuelve el error de la API tal cual', () => {
    const error = { code: 'not_in_review', message: 'La conversación no está en revisión.' } as const
    expect(toApiError(new ApiRequestError(409, error))).toBe(error)
  })

  it.each([new TypeError('x is undefined'), 'texto', undefined])('un fallo que no es de la API da «unexpected» en español (%s)', (cause) => {
    expect(toApiError(cause)).toEqual(UNEXPECTED_ERROR)
    expect(UNEXPECTED_ERROR.code).toBe('unexpected')
    expect(UNEXPECTED_ERROR.message).toMatch(/^Ha ocurrido un error inesperado/)
  })
})
