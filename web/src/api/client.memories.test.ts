// Memoria (T-56, bloque Memoria): `api.memories` y `api.memory` piden lo que dice el contrato
// (GET /memories con project, q y limit; GET /memories/{key} con la clave codificada) y sin X-CSRF-Token.
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import examples from './examples.json'
import { mockServer } from '../mocks/node.ts'
import { api, memoryQuery, setCsrfToken } from './client.ts'

afterEach(() => {
  mockServer.events.removeAllListeners()
  setCsrfToken(null)
})

describe('memoryQuery', () => {
  it.each([
    [{}, ''],
    [{ project: 'DEMO' }, '?project=DEMO'],
    [{ project: null, q: '  ', limit: 200 }, '?limit=200'],
    [{ project: 'DEMO', q: ' renovar préstamo ', limit: 200 }, '?project=DEMO&q=renovar+pr%C3%A9stamo&limit=200'],
    [{ q: 'a&b=c#d' }, '?q=a%26b%3Dc%23d'],
  ])('%j → «%s»', (filters, query) => {
    expect(memoryQuery(filters)).toBe(query)
  })
})

describe('api.memories y api.memory', () => {
  it('piden las rutas del contrato, sin X-CSRF-Token, y devuelven el cuerpo tal cual', async () => {
    setCsrfToken('csrf-ficticio')
    const seen: { url: string; csrf: string | null }[] = []
    mockServer.events.on('request:start', ({ request }) => seen.push({ url: request.url, csrf: request.headers.get('X-CSRF-Token') }))
    mockServer.use(
      http.get('/api/v1/memories', () => HttpResponse.json(examples['GET /api/v1/memories 200'])),
      http.get('/api/v1/memories/:key', () => HttpResponse.json(examples['GET /api/v1/memories/{key} 200'])),
    )
    expect(await api.memories({ project: 'DEMO', q: 'renovar', limit: 200 })).toEqual(examples['GET /api/v1/memories 200'])
    expect(await api.memory('DEMO-9001')).toEqual(examples['GET /api/v1/memories/{key} 200'])
    const paths = seen.map((item) => new URL(item.url))
    expect(paths[0]?.pathname).toBe('/api/v1/memories')
    expect(paths[0]?.search).toBe('?project=DEMO&q=renovar&limit=200')
    expect(paths[1]?.pathname).toBe('/api/v1/memories/DEMO-9001')
    expect(seen.every((item) => item.csrf === null)).toBe(true)
  })

  it('codifica la clave en la ruta: una clave con «/» o «?» no cambia de ruta', async () => {
    const seen: string[] = []
    mockServer.events.on('request:start', ({ request }) => seen.push(new URL(request.url).pathname))
    mockServer.use(http.get('/api/v1/memories/:key', () => HttpResponse.json(examples['GET /api/v1/memories/{key} 404'], { status: 404 })))
    await expect(api.memory('../x?y=1')).rejects.toMatchObject({ status: 404, error: { code: 'not_found' } })
    expect(seen).toEqual(['/api/v1/memories/..%2Fx%3Fy%3D1'])
  })
})

describe('api.memory con «.» o «..»', () => {
  it.each(['.', '..'])('«%s» no sale de /memories: se rechaza sin petición', async (key) => {
    const seen: string[] = []
    mockServer.events.on('request:start', ({ request }) => seen.push(new URL(request.url).pathname))
    await expect(api.memory(key)).rejects.toMatchObject({ status: 400, error: { code: 'invalid_request' } })
    expect(seen).toEqual([])
  })
})
