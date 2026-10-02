// Criterio 3 (T-56, días 2-4): huecos de handlers.test.ts. La API simulada no entra en el build, sigue los
// ejemplos del contrato, exige sesión y X-CSRF-Token, y responde 501 a lo que aún no simula (DESIGN-DECISIONS.md §4).
import { describe, expect, it } from 'vitest'
import examples from '../api/examples.json'
import type { SessionOut } from '../api/types.ts'
import mainSource from '../main.tsx?raw'
import { DEMO_PASSWORD } from './db.ts'
import { mockDb } from './node.ts'

const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)

async function login(username = 'af-demo', password = DEMO_PASSWORD): Promise<Response> {
  return fetch(url('/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

async function csrfOf(username = 'af-demo'): Promise<string> {
  return ((await (await login(username)).json()) as SessionOut).csrf_token
}

function send(method: string, path: string, csrf?: string, body: unknown = {}) {
  return fetch(url(path), {
    method,
    headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
    body: JSON.stringify(body),
  })
}

// Código de producción de src/ (sin pruebas, sin mocks ni el arranque de pruebas).
const productionSources = import.meta.glob<string>(
  ['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../test/**', '!../mocks/**'],
  { query: '?raw', import: 'default', eager: true },
)

interface ViteConfigLike {
  publicDir?: string | false
  server?: { proxy?: unknown }
}
type ConfigFactory = (env: { command: 'build' | 'serve'; mode: string }) => ViteConfigLike

async function viteConfig(command: 'build' | 'serve', mode: string): Promise<ViteConfigLike> {
  const path = '../../vite.config.ts'
  const module = (await import(/* @vite-ignore */ path)) as { default: ConfigFactory }
  return module.default({ command, mode })
}

describe('API simulada fuera del build (DESIGN-DECISIONS.md §4)', () => {
  it('test_build_has_no_public_dir_so_worker_is_not_copied', async () => {
    /** Criterio 3: en `vite build` (también con mode mock) no hay publicDir: mockServiceWorker.js no se copia. */
    expect((await viteConfig('build', 'production')).publicDir).toBe(false)
    expect((await viteConfig('build', 'mock')).publicDir).toBe(false)
  })

  it('test_dev_mock_mode_serves_worker_and_disables_proxy', async () => {
    /** Criterio 3: solo `vite --mode mock` sirve mock-public y no usa el proxy de la API real. */
    const mock = await viteConfig('serve', 'mock')
    expect(mock.publicDir).toBe('mock-public')
    expect(mock.server?.proxy).toBeUndefined()
  })

  it('test_dev_without_mock_uses_proxy_and_no_worker', async () => {
    /** Criterio 3 (negativo): `vite` sin mock no sirve el worker y reenvía /api al backend. */
    const dev = await viteConfig('serve', 'development')
    expect(dev.publicDir).toBe(false)
    expect(dev.server?.proxy).toHaveProperty('/api')
  })

  it('test_production_code_never_imports_mocks_statically', () => {
    /** Criterio 3: ningún módulo de producción importa src/mocks de forma estática (quedaría en el bundle). */
    expect(Object.keys(productionSources).length).toBeGreaterThan(10)
    for (const [file, source] of Object.entries(productionSources)) {
      expect(source, file).not.toMatch(/^\s*import\s[^;]*from\s+['"][^'"]*\/mocks\//m)
      expect(source, file).not.toMatch(/\bmsw\b['"/]/)
    }
  })

  it('test_main_loads_mock_worker_only_dynamically_in_dev', () => {
    /** Criterio 3: main.tsx carga el worker con import() y solo bajo import.meta.env.DEV. */
    const guard = mainSource.indexOf('import.meta.env.DEV')
    const dynamicImport = mainSource.indexOf("import('./mocks/browser.ts')")
    expect(guard).toBeGreaterThan(-1)
    expect(dynamicImport).toBeGreaterThan(guard)
  })
})

describe('API simulada: ejemplos del contrato', () => {
  it.each([
    ['/projects', 'GET /api/v1/projects 200'],
    ['/settings', 'GET /api/v1/settings 200'],
    ['/settings/usage', 'GET /api/v1/settings/usage 200'],
    ['/conversations', 'GET /api/v1/conversations 200'],
    ['/projects/DEMO/epics', 'GET /api/v1/projects/{project}/epics 200'],
  ] as const)('test_get_%s_returns_contract_example', async (path, key) => {
    /** Criterio 3: las lecturas responden con el ejemplo del contrato tal cual. */
    await login()
    expect(await (await fetch(url(path))).json()).toEqual(examples[key])
  })

  it('test_login_response_has_contract_shape', async () => {
    /** Criterio 3: el login devuelve las mismas claves que el ejemplo del contrato. */
    const session = (await (await login('qa-demo')).json()) as SessionOut
    const example = examples['POST /api/v1/auth/login 200'] as unknown as SessionOut
    expect(Object.keys(session).sort()).toEqual(Object.keys(example).sort())
    expect(Object.keys(session.user).sort()).toEqual(Object.keys(example.user).sort())
  })

  it('test_propose_without_key_keeps_contract_options_and_project', async () => {
    /** Criterio 3: sin clave en el texto, el arranque guiado propone evolucionar la HU parecida o crear una nueva, en el proyecto pedido. */
    const csrf = await csrfOf()
    const proposal = await (await send('POST', '/start/propose', csrf, { text: 'Renovar un préstamo', project: 'DEMO', mode: 'functional' })).json()
    const example = examples['POST /api/v1/start/propose 200']
    expect(proposal).toMatchObject({ project: 'DEMO', project_changed: false, ignored_projects: [], recognized: [] })
    expect(proposal.similar.map((issue: { key: string }) => issue.key)).toEqual(['DEMO-3'])
    expect(proposal.options.map((option: { kind: string }) => option.kind)).toEqual(example.options.map((option) => option.kind))
    expect(proposal.options[0]).toMatchObject({ kind: 'evolve', origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' } })
    expect(proposal.options[1]).toMatchObject({ kind: 'new_need', origin: { kind: 'need', text: 'Renovar un préstamo', project: 'DEMO' } })
  })

  it('test_issue_card_counts_and_epic_of_story', async () => {
    /** Criterio 3: la ficha de una HU trae su épica y recuentos; la de una épica, sin épica. */
    await login()
    expect(await (await fetch(url('/issues/demo-3'))).json()).toMatchObject({ key: 'DEMO-3', project: 'DEMO', epic_key: 'DEMO-1' })
    expect(await (await fetch(url('/issues/DEMO-1'))).json()).toMatchObject({ key: 'DEMO-1', epic_key: null, criteria_count: 0 })
  })

  it('test_search_ignores_accents_and_case', async () => {
    /** Criterio 3: la búsqueda simulada no distingue mayúsculas ni tildes. */
    await login()
    const found = (await (await fetch(url('/projects/DEMO/search?q=PRÉSTAMO'))).json()) as Array<{ key: string }>
    expect(found.map((item) => item.key)).toEqual(expect.arrayContaining(['DEMO-1', 'DEMO-3']))
  })

  it('test_unknown_conversation_and_stream_are_not_found', async () => {
    /** Criterio 3 (negativo): una conversación que no existe da 404 not_found, también en /events. */
    await login()
    for (const path of ['/conversations/no-existe', '/conversations/no-existe/events']) {
      const response = await fetch(url(path))
      expect(response.status, path).toBe(404)
      expect(await response.json()).toMatchObject({ error: { code: 'not_found', message: 'No existe esa conversación o no es tuya.' } })
    }
  })
})

describe('API simulada: sesión y CSRF', () => {
  it('test_each_login_issues_new_csrf_and_me_returns_it', async () => {
    /** Criterio 3: cada login da un token nuevo y GET /auth/me devuelve el de la sesión vigente. */
    const first = await csrfOf()
    const second = await csrfOf()
    expect(second).not.toBe(first)
    const me = (await (await fetch(url('/auth/me'))).json()) as SessionOut
    expect(me.csrf_token).toBe(second)
  })

  it('test_unknown_user_is_invalid_credentials_and_no_session', async () => {
    /** Criterio 3 (negativo): un usuario que no es demo no abre sesión. */
    const response = await login('persona-ficticia', DEMO_PASSWORD)
    expect(response.status).toBe(401)
    expect(await response.json()).toMatchObject({ error: { code: 'invalid_credentials', message: 'Usuario o contraseña incorrectos.' } })
    expect(mockDb.session).toBeNull()
  })

  it.each([
    ['sin token', undefined],
    ['con token de otra sesión', 'csrf-ficticio-ajeno'],
  ])('test_logout_%s_is_forbidden_and_keeps_session', async (_name, token) => {
    /** Criterio 3 (negativo): logout sin el X-CSRF-Token correcto da 403 y la sesión sigue abierta. */
    await login()
    const response = await send('POST', '/auth/logout', token)
    expect(response.status).toBe(403)
    expect(await response.json()).toMatchObject({ error: { code: 'forbidden' } })
    expect(mockDb.session).not.toBeNull()
  })

  it('test_logout_with_csrf_is_204_and_closes_session', async () => {
    /** Criterio 3: logout con el token responde 204 y cierra la sesión. */
    const csrf = await csrfOf()
    const response = await send('POST', '/auth/logout', csrf)
    expect(response.status).toBe(204)
    expect(mockDb.session).toBeNull()
    expect((await fetch(url('/auth/me'))).status).toBe(401)
  })

  it('test_mutation_without_session_is_unauthenticated_even_with_token', async () => {
    /** Criterio 3 (negativo): sin sesión, una modificación da 401 aunque traiga un token. */
    const response = await send('POST', '/projects/choose', 'csrf-ficticio', { project: 'DEMO' })
    expect(response.status).toBe(401)
    expect(await response.json()).toMatchObject({ error: { code: 'unauthenticated' } })
  })

  it('test_choose_unknown_project_is_project_not_found', async () => {
    /** Criterio 3 (negativo): elegir un proyecto que la conexión no ve da 404 project_not_found y no cambia nada. */
    const csrf = await csrfOf()
    const response = await send('POST', '/projects/choose', csrf, { project: 'NOEX' })
    expect(response.status).toBe(404)
    expect(await response.json()).toMatchObject({ error: { code: 'project_not_found' } })
    expect(mockDb.projects.preselected).toBe('DEMO')
  })

  it('test_reads_do_not_require_csrf', async () => {
    /** Criterio 3: las lecturas con sesión no piden X-CSRF-Token. */
    await login()
    expect((await fetch(url('/projects'))).status).toBe(200)
  })
})

describe('API simulada: 404 para lo que aún no simula', () => {
  it.each([
    ['GET', '/qa/handoffs'],
    ['POST', '/conversations/x/handoff'],
    ['POST', '/conversations/x/edit'],
    ['POST', '/conversations/x/approve'],
    ['PUT', '/settings/models/generate_story'],
    ['DELETE', '/settings/models/generate_story'],
  ])('test_%s_%s_is_not_simulated', async (method, path) => {
    /** Criterio 3: cualquier método sobre una ruta sin simular da 404 not_found con mensaje en español. */
    const csrf = await csrfOf()
    const response = method === 'GET' ? await fetch(url(path)) : await send(method, path, csrf)
    expect(response.status).toBe(404)
    expect(await response.json()).toEqual({
      error: { code: 'not_found', message: 'Aún no está en la API simulada del frontend.', retry_after: null },
    })
  })
})

describe('API simulada: título de la conversación como conversation_title() de core/conversations.py (PA-317)', () => {
  it.each([
    ['evolve', { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, 'Evolucionar DEMO-3'],
    ['need', { kind: 'epic', key: 'DEMO-1', project: 'DEMO' }, 'Nueva HU en DEMO-1'],
    ['need', { kind: 'need', key: null, text: 'Necesidad ficticia', project: 'DEMO' }, 'Nueva necesidad · DEMO'],
    ['tests', { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, 'Preparar pruebas de DEMO-3'],
  ] as const)('test_create_%s_%j_titles_like_backend', async (flow, origin, title) => {
    /** Paridad con _FLOW_TITLES: «flujo clave» o «flujo · proyecto», sin texto libre; la lista lleva el mismo título. */
    const csrf = await csrfOf()
    const response = await send('POST', '/conversations', csrf, { flow, origin, excluded_sources: [], feedback: [] })
    expect(response.status).toBe(202)
    const created = (await response.json()) as { id: string; title: string }
    expect(created.title).toBe(title)
    expect(mockDb.conversations.find((item) => item.thread_id === created.id)?.title).toBe(title)
  })

  it('test_create_title_never_contains_free_text', async () => {
    /** core/conversations.py: el título no incluye la necesidad ni las restricciones escritas. */
    const csrf = await csrfOf()
    const origin = { kind: 'need', key: null, text: 'Texto libre ficticio\n\nRestricciones: otra cosa', project: 'DEMO' }
    const created = (await (await send('POST', '/conversations', csrf, { flow: 'need', origin, excluded_sources: [], feedback: [] })).json()) as {
      title: string
    }
    expect(created.title).not.toMatch(/Texto libre|Restricciones/)
  })
})
