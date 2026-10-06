// Memoria (PA-329) · pantalla dentro de la app para los tres roles contra la API simulada: lista con limit=200,
// detalle con sus secciones, indexado, descarga del .md, filtros (proyecto y búsqueda con espera), vacíos,
// errores y contenido pintado como texto. Solo datos sintéticos (DEMO-9001, DEMO-9002, af-demo, qa-demo, admin-demo).
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import examples from '../../api/examples.json'
import type { MemoryOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import * as download from '../../security/download.ts'
import { MEMORY_SECTIONS, NO_MATCHES, NO_MEMORIES } from './memoryText.ts'

type Role = 'functional' | 'qa' | 'admin'
const USERS: Record<Role, string> = { functional: 'af-demo', qa: 'qa-demo', admin: 'admin-demo' }
const ROLES = Object.keys(USERS) as Role[]
const DETAIL = examples['GET /api/v1/memories/{key} 200'] as unknown as MemoryOut

let listRequests: URL[] = []
let detailRequests: string[] = []
let spy: MockInstance<typeof download.downloadText>

beforeEach(() => {
  listRequests = []
  detailRequests = []
  mockServer.events.on('request:start', ({ request }) => {
    const target = new URL(request.url)
    if (target.pathname === '/api/v1/memories') listRequests.push(target)
    else if (target.pathname.startsWith('/api/v1/memories/')) detailRequests.push(target.pathname)
  })
  spy = vi.spyOn(download, 'downloadText').mockReturnValue(true)
})

afterEach(() => {
  mockServer.events.removeAllListeners()
  vi.restoreAllMocks()
})

/** Entra con el rol y abre Memoria desde el carril; devuelve la columna «Memorias». */
async function openMemory(role: Role = 'functional'): Promise<HTMLElement> {
  mockDb.session = { username: USERS[role], role, csrf: 'csrf-ficticio' }
  render(<App />)
  const nav = await screen.findByRole('navigation', { name: 'Zonas' })
  await userEvent.click(within(nav).getByRole('button', { name: 'Memoria' }))
  return screen.findByRole('complementary', { name: 'Memorias' })
}

async function pick(list: HTMLElement, key: string): Promise<HTMLElement> {
  await userEvent.click(await within(list).findByRole('button', { name: new RegExp(key) }))
  return screen.findByRole('article', { name: new RegExp(`^${key} · Memoria v\\d+$`) })
}

describe.each(ROLES)('Memoria en la app (%s)', (role) => {
  it('test_rail_has_memory_and_list_shows_both_with_limit_200', async () => {
    /** PA-329: el carril tiene «Memoria»; al abrirla se ve la lista con DEMO-9001 y DEMO-9002 pedida con limit=200. */
    const list = await openMemory(role)
    const nav = screen.getByRole('navigation', { name: 'Zonas' })
    expect(within(nav).getByRole('button', { name: 'Memoria' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('heading', { level: 1, name: 'Memoria' })).toBeInTheDocument()
    const first = await within(list).findByRole('button', { name: /DEMO-9001/ })
    const second = within(list).getByRole('button', { name: /DEMO-9002/ })
    expect(first).toHaveTextContent('v2')
    expect(first).toHaveTextContent('Indexada')
    expect(first).toHaveTextContent('DEMO · 2 oct')
    expect(second).toHaveTextContent('v1')
    expect(second).toHaveTextContent('No indexada')
    expect(listRequests.length).toBeGreaterThan(0)
    for (const request of listRequests) {
      expect(request.searchParams.get('limit')).toBe('200')
      expect(request.searchParams.has('project')).toBe(false)
      expect(request.searchParams.has('q')).toBe(false)
    }
    expect(within(list).queryByRole('button', { name: /Mostrar más/ })).toBeNull()
    const main = screen.getByRole('main', { name: 'Memoria elegida' })
    expect(within(main).getByText('Elige una memoria')).toBeInTheDocument()
    expect(detailRequests).toEqual([])
  })

  it('test_pick_9001_shows_sections_indexed_and_download', async () => {
    /** Elegir DEMO-9001: título, proyecto y fecha, «Indexada», nota, «Descargar la memoria» y las 8 secciones. */
    const list = await openMemory(role)
    const article = await pick(list, 'DEMO-9001')
    expect(within(list).getByRole('button', { name: /DEMO-9001/ })).toHaveAttribute('aria-current', 'true')
    expect(within(article).getByRole('heading', { level: 2, name: 'DEMO-9001 · Memoria v2' })).toBeInTheDocument()
    expect(within(article).getByText('Proyecto DEMO · Actualizada el 2 de octubre de 2026')).toBeInTheDocument()
    expect(within(article).getByText('Indexada')).toBeInTheDocument()
    expect(within(article).getByText(/^Está en la base de conocimiento/)).toBeInTheDocument()
    expect(within(article).getByRole('button', { name: 'Descargar la memoria' })).toHaveAccessibleDescription('Descarga el archivo memoria-DEMO-9001.md.')
    const titles = within(article).getAllByRole('heading', { level: 3 }).map((item) => item.textContent)
    expect(titles).toEqual(MEMORY_SECTIONS.map((section) => section.title))
    expect(within(within(article).getByRole('region', { name: 'Objetivo' })).getByText(DETAIL.memory.objective)).toBeInTheDocument()
    const rules = within(article).getByRole('region', { name: 'Reglas de negocio' })
    expect(within(rules).getAllByRole('listitem').map((item) => item.textContent)).toEqual(DETAIL.memory.business_rules)
    const criteria = within(article).getByRole('region', { name: 'Criterios de aceptación' })
    expect(within(criteria).getAllByRole('listitem').map((item) => item.textContent)).toEqual(DETAIL.memory.acceptance_criteria)
    expect(detailRequests).toEqual(['/api/v1/memories/DEMO-9001'])
  })

  it('test_pick_9002_shows_not_indexed', async () => {
    /** DEMO-9002: «No indexada» con su nota y sin «Indexada». */
    const list = await openMemory(role)
    const article = await pick(list, 'DEMO-9002')
    expect(within(article).getByRole('heading', { level: 2, name: 'DEMO-9002 · Memoria v1' })).toBeInTheDocument()
    expect(within(article).getByText('No indexada')).toBeInTheDocument()
    expect(within(article).queryByText('Indexada')).toBeNull()
    expect(within(article).getByText(/^Aún no está en la base de conocimiento/)).toBeInTheDocument()
    // DEMO-9002 construido: decisiones y cambios vacíos → «Ninguno.».
    expect(within(within(article).getByRole('region', { name: 'Decisiones' })).getByText('Ninguno.')).toBeInTheDocument()
    expect(within(within(article).getByRole('region', { name: 'Cambios' })).getByText('Ninguno.')).toBeInTheDocument()
  })

  it('test_download_sends_file_name_and_markdown_as_is', async () => {
    /** La descarga llama a `downloadText` con `memoria-DEMO-9001.md` y el markdown tal cual. */
    const list = await openMemory(role)
    const article = await pick(list, 'DEMO-9001')
    await userEvent.click(within(article).getByRole('button', { name: 'Descargar la memoria' }))
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith('memoria-DEMO-9001.md', DETAIL.markdown, 'text/markdown')
  })
})

describe('Memoria · filtros', () => {
  it('test_project_select_adds_project_to_request', async () => {
    /** Elegir un proyecto añade `project=` (con limit=200); SOCI no tiene memorias → NO_MATCHES. */
    const list = await openMemory()
    await within(list).findByRole('button', { name: /DEMO-9001/ })
    const select = within(list).getByRole('combobox', { name: 'Proyecto' })
    await within(select).findByRole('option', { name: 'DEMO · Biblioteca' })
    expect(within(select).getAllByRole('option').map((item) => item.textContent)).toEqual([
      'Todos los proyectos',
      'DEMO · Biblioteca',
      'SOCI · Gestión de personas socias',
    ])
    await userEvent.selectOptions(select, 'DEMO')
    await waitFor(() => expect(listRequests.at(-1)?.searchParams.get('project')).toBe('DEMO'))
    expect(listRequests.at(-1)?.searchParams.get('limit')).toBe('200')
    expect(await within(list).findByRole('button', { name: /DEMO-9001/ })).toBeInTheDocument()
    await userEvent.selectOptions(select, 'SOCI')
    expect(await within(list).findByText(NO_MATCHES)).toBeInTheDocument()
    expect(listRequests.at(-1)?.searchParams.get('project')).toBe('SOCI')
    await userEvent.selectOptions(select, '')
    expect(await within(list).findByRole('button', { name: /DEMO-9002/ })).toBeInTheDocument()
    expect(listRequests.at(-1)?.searchParams.has('project')).toBe(false)
  })

  it('test_search_waits_then_adds_q_once', async () => {
    /** El buscador no pide en cada pulsación: tras la espera sale una sola petición con el último `q`, recortado. */
    const list = await openMemory()
    await within(list).findByRole('button', { name: /DEMO-9001/ })
    const before = listRequests.length
    const search = within(list).getByRole('searchbox', { name: 'Buscar en las memorias' })
    // Dos cambios seguidos: el primero no llega a pedirse (la espera se reinicia con el segundo).
    fireEvent.change(search, { target: { value: 'reser' } })
    fireEvent.change(search, { target: { value: '  reservar  ' } })
    expect(listRequests.length).toBe(before)
    await waitFor(() => expect(listRequests.length).toBe(before + 1))
    expect(listRequests.at(-1)?.searchParams.get('q')).toBe('reservar')
    expect(listRequests.at(-1)?.searchParams.get('limit')).toBe('200')
    await waitFor(() => expect(within(list).queryByRole('button', { name: /DEMO-9001/ })).toBeNull())
    expect(within(list).getByRole('button', { name: /DEMO-9002/ })).toBeInTheDocument()
    expect(listRequests.some((request) => request.searchParams.get('q') === 'reser')).toBe(false)
  })

  it('test_search_with_fake_timers_waits_300ms', async () => {
    /** Con reloj falso: a los 299 ms aún no se pide; a los 300 ms sí. */
    const list = await openMemory()
    await within(list).findByRole('button', { name: /DEMO-9001/ })
    const before = listRequests.length
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      fireEvent.change(within(list).getByRole('searchbox', { name: 'Buscar en las memorias' }), { target: { value: 'mostrador' } })
      vi.advanceTimersByTime(299)
      await Promise.resolve()
      expect(listRequests.length).toBe(before)
      vi.advanceTimersByTime(1)
    } finally {
      vi.useRealTimers()
    }
    await waitFor(() => expect(listRequests.at(-1)?.searchParams.get('q')).toBe('mostrador'))
    expect(listRequests.length).toBe(before + 1)
  })

  it('test_search_with_no_match_shows_no_matches', async () => {
    /** Búsqueda sin resultados: NO_MATCHES, no NO_MEMORIES. */
    const list = await openMemory()
    await within(list).findByRole('button', { name: /DEMO-9001/ })
    await userEvent.type(within(list).getByRole('searchbox', { name: 'Buscar en las memorias' }), 'zzz-no-existe')
    expect(await within(list).findByText(NO_MATCHES)).toBeInTheDocument()
    expect(within(list).queryByText(NO_MEMORIES)).toBeNull()
  })
})

describe('Memoria · vacíos y errores', () => {
  it('test_empty_list_without_filters_shows_no_memories', async () => {
    /** Sin memorias y sin filtros: NO_MEMORIES. */
    mockDb.memories = []
    const list = await openMemory('qa')
    expect(await within(list).findByText(NO_MEMORIES)).toBeInTheDocument()
    expect(within(list).queryByText(NO_MATCHES)).toBeNull()
    expect(screen.getByRole('main', { name: 'Memoria elegida' })).toHaveTextContent('Elige una memoria')
  })

  it('test_list_error_shows_card_and_retry_requests_again', async () => {
    /** Error de la lista: ErrorCard con el mensaje tal cual; *Reintentar* vuelve a pedir y se ve la lista. */
    let fail = true
    mockServer.use(
      http.get('/api/v1/memories', () =>
        fail ? HttpResponse.json({ error: { code: 'service_unavailable', message: 'No se pudieron leer las memorias (ficticio).' } }, { status: 503 }) : undefined,
      ),
    )
    const list = await openMemory()
    const alert = await within(list).findByRole('alert')
    expect(alert).toHaveTextContent('No se pudieron leer las memorias (ficticio).')
    const before = listRequests.length
    fail = false
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await within(list).findByRole('button', { name: /DEMO-9001/ })).toBeInTheDocument()
    expect(listRequests.length).toBe(before + 1)
    expect(within(list).queryByRole('alert')).toBeNull()
  })

  it('test_detail_404_shows_not_found_card_inside_screen', async () => {
    /** 404 del detalle: tarjeta «No se encuentra» con el mensaje, dentro de la zona; la lista sigue. */
    mockDb.memoryDetails.delete('DEMO-9002')
    const list = await openMemory()
    await userEvent.click(await within(list).findByRole('button', { name: /DEMO-9002/ }))
    const main = screen.getByRole('main', { name: 'Memoria elegida' })
    const alert = await within(main).findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'No se encuentra' })).toBeInTheDocument()
    expect(alert).toHaveTextContent('No existe esa memoria o no la puedes ver.')
    expect(within(list).getByRole('button', { name: /DEMO-9001/ })).toBeInTheDocument()
    // Elegir otra memoria tras el error la abre.
    expect(await pick(list, 'DEMO-9001')).toBeInTheDocument()
    expect(within(main).queryByRole('alert')).toBeNull()
  })

  it('test_detail_error_retry_requests_again', async () => {
    /** Error recuperable del detalle: *Reintentar* vuelve a pedir la misma memoria. */
    let fail = true
    mockServer.use(
      http.get('/api/v1/memories/:key', () =>
        fail ? HttpResponse.json({ error: { code: 'service_unavailable', message: 'Fallo ficticio del detalle.' } }, { status: 503 }) : undefined,
      ),
    )
    const list = await openMemory()
    await userEvent.click(await within(list).findByRole('button', { name: /DEMO-9001/ }))
    const main = screen.getByRole('main', { name: 'Memoria elegida' })
    const alert = await within(main).findByRole('alert')
    expect(alert).toHaveTextContent('Fallo ficticio del detalle.')
    fail = false
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await within(main).findByRole('article', { name: 'DEMO-9001 · Memoria v2' })).toBeInTheDocument()
    expect(detailRequests).toEqual(['/api/v1/memories/DEMO-9001', '/api/v1/memories/DEMO-9001'])
  })
})

describe('Memoria · contenido como texto', () => {
  it('test_html_in_memory_is_rendered_as_text', async () => {
    /** `<script>` y `<b>` en la lista y en el detalle se pintan como texto; no hay elementos HTML nuevos. */
    const evil = '<script>window.__pwned = 1</script>'
    mockDb.memories = mockDb.memories.map((item) => (item.key === 'DEMO-9001' ? { ...item, title: '<b>Título ficticio</b>' } : item))
    const base = mockDb.memoryDetails.get('DEMO-9001') as MemoryOut
    mockDb.memoryDetails.set('DEMO-9001', {
      ...base,
      memory: { ...base.memory, objective: evil, scope: '   ', business_rules: ['<b>RN ficticia</b>', '<img src=x onerror=alert(1)>'], decisions: [] },
    })
    const list = await openMemory()
    const row = await within(list).findByRole('button', { name: /DEMO-9001/ })
    expect(row).toHaveTextContent('<b>Título ficticio</b>')
    expect(row.querySelector('b')).toBeNull()
    const article = await pick(list, 'DEMO-9001')
    expect(within(within(article).getByRole('region', { name: 'Objetivo' })).getByText(evil)).toBeInTheDocument()
    const rules = within(article).getByRole('region', { name: 'Reglas de negocio' })
    expect(within(rules).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['<b>RN ficticia</b>', '<img src=x onerror=alert(1)>'])
    expect(article.querySelector('script, b, img')).toBeNull()
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined()
    // Vacíos: texto en blanco → «Sin datos.»; lista vacía → «Ninguno.».
    expect(within(within(article).getByRole('region', { name: 'Alcance' })).getByText('Sin datos.')).toBeInTheDocument()
    expect(within(within(article).getByRole('region', { name: 'Decisiones' })).getByText('Ninguno.')).toBeInTheDocument()
  })
})
