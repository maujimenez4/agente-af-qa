// Memoria (PA-329) · API simulada: GET /memories (project, q sin mayúsculas ni tildes, limit 1–200, orden por
// updated_at desc) y GET /memories/{key} (ejemplo del contrato, detalle construido, 404), sesión y
// `?simular=sin-memorias`. Solo datos sintéticos (DEMO-9001, DEMO-9002, af-demo).
import { describe, expect, it } from 'vitest'
import examples from '../api/examples.json'
import type { MemoryOut, MemorySummary } from '../api/types.ts'
import { noMemoriesFrom } from './db.ts'
import { filterMemories, mockMemoryDetails, mockMemorySummaries } from './memories.ts'
import { mockDb } from './node.ts'

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)
const SUMMARIES = examples['GET /api/v1/memories 200'] as unknown as MemorySummary[]
const DETAIL = examples['GET /api/v1/memories/{key} 200'] as unknown as MemoryOut

function signIn(): void {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
}

async function list(query = ''): Promise<{ status: number; body: unknown }> {
  const response = await fetch(url(`/memories${query}`))
  return { status: response.status, body: await response.json() }
}

async function keysOf(query = ''): Promise<string[]> {
  const { status, body } = await list(query)
  expect(status).toBe(200)
  return (body as MemorySummary[]).map((item) => item.key)
}

function summary(key: string, fields: Partial<MemorySummary> = {}): MemorySummary {
  return { key, project: 'DEMO', title: `Memoria ficticia ${key}`, version: 1, updated_at: '2026-10-01T09:00:00Z', indexed: false, ...fields }
}

describe('GET /memories (MSW)', () => {
  it('test_list_returns_contract_example_without_filters', async () => {
    /** Sin filtros, la lista del contrato: DEMO-9001 y DEMO-9002. */
    signIn()
    const { status, body } = await list()
    expect(status).toBe(200)
    expect(body).toEqual(SUMMARIES)
  })

  it('test_list_filters_by_exact_project', async () => {
    /** `project` exacto: DEMO trae las dos; SOCI ninguna; «demo» (otra caja) ninguna. */
    signIn()
    expect(await keysOf('?project=DEMO')).toEqual(['DEMO-9001', 'DEMO-9002'])
    expect(await keysOf('?project=SOCI')).toEqual([])
    expect(await keysOf('?project=demo')).toEqual([])
    expect(await keysOf('?project=DEM')).toEqual([])
  })

  it.each([
    // La memoria de DEMO-9001 cita a DEMO-9002 en sus dependencias y viceversa: la clave aparece en las dos.
    ['clave en minúsculas', 'demo-9002', ['DEMO-9001', 'DEMO-9002']],
    ['título sin tildes ni mayúsculas', 'RESERVAR UN LIBRO', ['DEMO-9002']],
    ['palabra con tilde escrita sin ella', 'renovar un prestamo', ['DEMO-9001']],
    ['palabra sin tilde escrita con ella', 'socía', ['DEMO-9001', 'DEMO-9002']],
    ['texto que solo está en el markdown', 'mostrador', ['DEMO-9001']],
    ['regla del markdown de DEMO-9002 construido', 'caduca a los 3 dias', ['DEMO-9002']],
    ['espacios alrededor', '  mostrador  ', ['DEMO-9001']],
    ['sin coincidencias', 'zzz-no-existe', []],
  ])('test_list_q_matches_%s', async (_name, q, keys) => {
    /** `q` busca en clave, título y markdown sin distinguir mayúsculas ni tildes. */
    signIn()
    expect(await keysOf(`?q=${encodeURIComponent(q)}`)).toEqual(keys)
  })

  it('test_list_combines_project_and_q', async () => {
    /** Proyecto y búsqueda a la vez: deben cumplirse los dos. */
    signIn()
    expect(await keysOf('?project=DEMO&q=mostrador')).toEqual(['DEMO-9001'])
    expect(await keysOf('?project=SOCI&q=mostrador')).toEqual([])
  })

  it.each(['0', '201', '-1', '1.5', 'abc', ''])('test_list_rejects_limit_%j_with_422', async (limit) => {
    /** `limit` fuera de 1–200 o no entero: 422 `invalid_request`. */
    signIn()
    const { status, body } = await list(`?limit=${limit}`)
    expect(status).toBe(422)
    expect(body).toMatchObject({ error: { code: 'invalid_request' } })
  })

  it.each(['1', '200'])('test_list_accepts_limit_boundary_%s', async (limit) => {
    /** Límites válidos del contrato: 1 y 200. */
    signIn()
    expect(await keysOf(`?limit=${limit}`)).toHaveLength(Math.min(Number(limit), SUMMARIES.length))
  })

  it('test_list_limit_cuts_after_sorting', async () => {
    /** Con `limit=1` sale la más reciente. */
    signIn()
    mockDb.memories = [summary('DEMO-9101', { updated_at: '2026-09-01T00:00:00Z' }), summary('DEMO-9102', { updated_at: '2026-10-03T00:00:00Z' })]
    expect(await keysOf('?limit=1')).toEqual(['DEMO-9102'])
  })

  it('test_list_sorted_by_updated_at_desc', async () => {
    /** Orden por `updated_at` de más reciente a más antigua, sea cual sea el orden de la base. */
    signIn()
    mockDb.memories = [
      summary('DEMO-9101', { updated_at: '2026-09-01T00:00:00Z' }),
      summary('DEMO-9102', { updated_at: '2026-10-03T00:00:00Z' }),
      summary('DEMO-9103', { updated_at: '2026-09-20T12:00:00Z' }),
    ]
    expect(await keysOf()).toEqual(['DEMO-9102', 'DEMO-9103', 'DEMO-9101'])
  })

  it('test_list_without_session_is_401', async () => {
    /** Sin sesión: 401 `unauthenticated`. */
    mockDb.session = null
    const { status, body } = await list()
    expect(status).toBe(401)
    expect(body).toMatchObject({ error: { code: 'unauthenticated' } })
  })

  it('test_list_empty_when_db_has_no_memories', async () => {
    /** Con la base vacía (como `?simular=sin-memorias`), lista vacía. */
    signIn()
    mockDb.memories = []
    expect(await keysOf()).toEqual([])
  })
})

describe('GET /memories/{key} (MSW)', () => {
  it('test_detail_9001_is_contract_example', async () => {
    /** El detalle de DEMO-9001 es el ejemplo del contrato tal cual. */
    signIn()
    const response = await fetch(url('/memories/DEMO-9001'))
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual(DETAIL)
  })

  it('test_detail_9002_is_built_from_its_summary', async () => {
    /** DEMO-9002 se construye: su clave, versión e indexado de la lista y un markdown con su clave. */
    signIn()
    const response = await fetch(url('/memories/DEMO-9002'))
    expect(response.status).toBe(200)
    const detail = (await response.json()) as MemoryOut
    const own = SUMMARIES.find((item) => item.key === 'DEMO-9002')
    expect(detail).toMatchObject({ ...own })
    expect(detail.key).toBe('DEMO-9002')
    expect(detail.version).toBe(1)
    expect(detail.indexed).toBe(false)
    expect(detail.memory.jira_key).toBe('DEMO-9002')
    expect(detail.memory.version).toBe(1)
    expect(detail.markdown).toContain('jira_key: DEMO-9002')
    expect(detail.markdown).toContain('# Memoria · DEMO-9002 (v1)')
    expect(detail.markdown).not.toContain('jira_key: DEMO-9001')
    for (const title of ['Objetivo', 'Alcance', 'Reglas de negocio', 'Decisiones', 'Dependencias', 'Cambios', 'Criterios de aceptación', 'Referencias']) {
      expect(detail.markdown).toContain(`## ${title}`)
    }
  })

  it('test_detail_9002_does_not_mutate_9001', () => {
    /** Construir DEMO-9002 no cambia el detalle de DEMO-9001 (copia, no referencia). */
    const details = mockMemoryDetails(mockMemorySummaries())
    expect(details.get('DEMO-9001')).toEqual(DETAIL)
    expect(details.get('DEMO-9002')?.memory).not.toBe(details.get('DEMO-9001')?.memory)
  })

  it.each(['DEMO-3', 'DEMO-9999', 'demo-9001'])('test_detail_unknown_key_%s_is_404', async (key) => {
    /** Clave que no está en la lista: 404 `not_found` con el mensaje del contrato. */
    signIn()
    const response = await fetch(url(`/memories/${key}`))
    expect(response.status).toBe(404)
    expect(await response.json()).toMatchObject({ error: { code: 'not_found', message: 'No existe esa memoria o no la puedes ver.' } })
  })

  it('test_detail_removed_from_list_is_404', async () => {
    /** Con la lista vacía, aunque el detalle siga en la base, la memoria no se ve (404). */
    signIn()
    mockDb.memories = []
    const response = await fetch(url('/memories/DEMO-9001'))
    expect(response.status).toBe(404)
  })

  it('test_detail_without_session_is_401', async () => {
    /** Sin sesión: 401. */
    mockDb.session = null
    const response = await fetch(url('/memories/DEMO-9001'))
    expect(response.status).toBe(401)
  })
})

describe('filterMemories y noMemoriesFrom', () => {
  it('test_filter_memories_does_not_mutate_input', () => {
    /** Ordenar no cambia la lista de la base. */
    const input = [summary('DEMO-9101', { updated_at: '2026-01-01T00:00:00Z' }), summary('DEMO-9102', { updated_at: '2026-02-01T00:00:00Z' })]
    const copy = structuredClone(input)
    filterMemories(input, new Map(), { project: null, q: '', limit: 200 })
    expect(input).toEqual(copy)
  })

  it.each([
    ['?simular=sin-memorias', true],
    ['?simular=publicado', false],
    ['', false],
    ['?otro=sin-memorias', false],
    ['?simular=SIN-MEMORIAS', false],
  ])('test_no_memories_from_%j', (search, expected) => {
    /** Solo `?simular=sin-memorias` vacía la lista en el navegador. */
    expect(noMemoriesFrom(search)).toBe(expected)
  })
})
