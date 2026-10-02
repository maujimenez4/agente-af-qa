// Criterio 9 (T-56, días 2-4): huecos de ChooseInJira.test.tsx sobre UI.md §4.2 (Mixta 1b · Elegir en Jira):
// semántica del diálogo, foco atrapado y devuelto, búsqueda con espera, cambio de proyecto, épica/HU y teclado.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { ChooseInJira, SEARCH_DEBOUNCE_MS } from './ChooseInJira.tsx'

function signIn() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
}

async function openFromHome(opener: RegExp | string = 'Elegir en Jira') {
  signIn()
  render(<App />)
  const button = await screen.findByRole('button', { name: opener })
  await waitFor(() => expect(button).toBeEnabled())
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.click(button)
  const dialog = screen.getByRole('dialog', { name: 'Elegir en Jira' })
  await within(dialog).findByRole('listbox', { name: 'Épicas de DEMO' })
  return { dialog, opener: button }
}

/** Peticiones de búsqueda con texto (las de recientes van sin `q`). */
function searchQueries(): string[] {
  const queries: string[] = []
  mockServer.events.on('request:start', ({ request }) => {
    const target = new URL(request.url)
    if (target.pathname.endsWith('/search') && target.searchParams.has('q')) queries.push(target.searchParams.get('q') ?? '')
  })
  return queries
}

function choosePosts(): string[] {
  const posts: string[] = []
  mockServer.events.on('request:start', ({ request }) => {
    if (new URL(request.url).pathname === '/api/v1/projects/choose') {
      void request.clone().json().then((body) => posts.push((body as { project: string }).project))
    }
  })
  return posts
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Elegir en Jira: semántica del diálogo', () => {
  it('test_dialog_is_modal_and_labelled_by_title', async () => {
    /** Criterio 9: role="dialog", aria-modal y nombre por su título visible. */
    const { dialog } = await openFromHome()
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(within(dialog).getByRole('heading', { name: 'Elegir en Jira' }).id).toBe(dialog.getAttribute('aria-labelledby'))
  })

  it('test_columns_are_named_listboxes_with_counts', async () => {
    /** Criterio 9: las tres columnas de UI.md §4.2 con su recuento. */
    const { dialog } = await openFromHome()
    expect(within(dialog).getByText('Proyectos que ve la conexión (2)')).toBeInTheDocument()
    expect(within(dialog).getByText('Épicas de DEMO (1)')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('option', { name: 'DEMO-1 Préstamo digital' }))
    expect(await within(dialog).findByText('HU de DEMO-1 (3)')).toBeInTheDocument()
  })

  it('test_footer_without_selection_offers_only_cancel', async () => {
    /** Criterio 9: sin elegir nada, el pie invita a elegir y solo ofrece Cancelar (el proyecto ya es el de Inicio). */
    const { dialog } = await openFromHome()
    expect(within(dialog).getByText('Elige una épica o una HU.')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /^Usar/ })).toBeNull()
    expect(within(dialog).getByRole('button', { name: 'Cancelar' })).toBeInTheDocument()
  })

  it('test_selection_line_is_polite_live_region', async () => {
    /** Criterio 9: «Seleccionada: …» se anuncia de forma educada al cambiar. */
    const { dialog } = await openFromHome()
    expect(within(dialog).getByText('Elige una épica o una HU.').closest('[aria-live]')).toHaveAttribute('aria-live', 'polite')
  })
})

describe('Elegir en Jira: foco', () => {
  it('test_shift_tab_from_search_wraps_to_last_control', async () => {
    /** Criterio 9: Mayús + Tab desde el primer control va al último del diálogo (foco atrapado). */
    const { dialog } = await openFromHome()
    const search = within(dialog).getByRole('searchbox', { name: 'Buscar en Jira' })
    // El primer control del diálogo es «Cerrar» (cabecera); el buscador recibe el foco al abrir.
    await userEvent.tab({ shift: true })
    expect(within(dialog).getByRole('button', { name: 'Cerrar' })).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(within(dialog).getByRole('button', { name: 'Cancelar' })).toHaveFocus()
    await userEvent.tab()
    expect(within(dialog).getByRole('button', { name: 'Cerrar' })).toHaveFocus()
    await userEvent.tab()
    expect(search).toHaveFocus()
  })

  it('test_focus_stays_inside_dialog_over_full_tab_cycle', async () => {
    /** Criterio 9: recorrer con Tab nunca saca el foco del diálogo. */
    const { dialog } = await openFromHome()
    for (let index = 0; index < 12; index += 1) {
      await userEvent.tab()
      expect(dialog.contains(document.activeElement)).toBe(true)
    }
  })

  it('test_focus_returns_to_opener_after_use', async () => {
    /** Criterio 9: tras «Usar …» el foco vuelve a «Elegir en Jira». */
    const { dialog, opener } = await openFromHome()
    await userEvent.click(within(dialog).getByRole('option', { name: 'DEMO-1 Préstamo digital' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar la épica DEMO-1' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(opener).toHaveFocus()
  })

  it('test_focus_returns_to_project_button_after_close_x', async () => {
    /** Criterio 9: abierto desde el selector de proyecto, «Cerrar» devuelve el foco a ese botón. */
    const { dialog, opener } = await openFromHome(/Proyecto de Jira: DEMO/)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cerrar' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(opener).toHaveFocus()
  })

  it('test_escape_inside_listbox_closes', async () => {
    /** Criterio 9: Esc cierra también con el foco en una lista. */
    const { dialog } = await openFromHome()
    within(dialog).getByRole('listbox', { name: 'Proyectos' }).focus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})

describe('Elegir en Jira: búsqueda con espera', () => {
  it('test_typing_fast_sends_single_search_with_final_text', async () => {
    /** Criterio 9: escribir seguido manda una sola búsqueda, con el texto final. */
    const queries = searchQueries()
    const { dialog } = await openFromHome()
    await userEvent.type(within(dialog).getByRole('searchbox'), 'renovar')
    expect(queries).toEqual([])
    await within(dialog).findByRole('listbox', { name: 'HU encontradas en DEMO' }, { timeout: 2000 })
    expect(queries).toEqual(['renovar'])
  })

  it('test_no_search_before_debounce_elapses', async () => {
    /** Criterio 9 (límite): no se busca antes de SEARCH_DEBOUNCE_MS. */
    const queries = searchQueries()
    const { dialog } = await openFromHome()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true })
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      await user.type(within(dialog).getByRole('searchbox'), 'x')
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 50)
      expect(queries).toEqual([])
      await vi.advanceTimersByTimeAsync(100)
      await waitFor(() => expect(queries).toEqual(['x']))
    } finally {
      vi.useRealTimers()
    }
  })

  it('test_whitespace_query_does_not_search', async () => {
    /** Criterio 9 (negativo): solo espacios no busca y deja las columnas normales. */
    const queries = searchQueries()
    const { dialog } = await openFromHome()
    await userEvent.type(within(dialog).getByRole('searchbox'), '   ')
    await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 100))
    expect(queries).toEqual([])
    expect(within(dialog).getByRole('listbox', { name: 'Épicas de DEMO' })).toBeInTheDocument()
  })

  it('test_clearing_search_restores_columns', async () => {
    /** Criterio 9: al vaciar el buscador vuelven las épicas del proyecto. */
    const { dialog } = await openFromHome()
    const search = within(dialog).getByRole('searchbox')
    await userEvent.type(search, 'renovar')
    await within(dialog).findByRole('listbox', { name: 'HU encontradas en DEMO' }, { timeout: 2000 })
    await userEvent.clear(search)
    expect(within(dialog).getByRole('listbox', { name: 'Épicas de DEMO' })).toBeInTheDocument()
  })

  it('test_search_by_key_finds_story', async () => {
    /** Criterio 9: buscar por clave encuentra la HU. */
    const { dialog } = await openFromHome()
    await userEvent.type(within(dialog).getByRole('searchbox'), 'DEMO-4')
    const found = await within(dialog).findByRole('listbox', { name: 'HU encontradas en DEMO' }, { timeout: 2000 })
    expect(within(found).getAllByRole('option').map((option) => option.textContent)).toEqual([expect.stringContaining('DEMO-4')])
  })

  it('test_search_also_filters_projects_column', async () => {
    /** Criterio 9: el buscador filtra también la columna de proyectos. */
    const { dialog } = await openFromHome()
    await userEvent.type(within(dialog).getByRole('searchbox'), 'socias')
    const projects = within(dialog).getByRole('listbox', { name: 'Proyectos' })
    expect(within(projects).getAllByRole('option').map((option) => option.textContent)).toEqual(['SOCI Gestión de personas socias'])
  })

  it('test_story_found_in_search_can_be_used', async () => {
    /** Criterio 9: una HU encontrada se puede usar directamente como origen. */
    const { dialog } = await openFromHome()
    await userEvent.type(within(dialog).getByRole('searchbox'), 'renovar')
    const found = await within(dialog).findByRole('listbox', { name: 'HU encontradas en DEMO' }, { timeout: 2000 })
    await userEvent.click(within(found).getByRole('option', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar DEMO-3' }))
    expect(screen.getByText(/Origen:/)).toHaveTextContent('Origen: DEMO-3 · Renovar un préstamo')
  })

  // DEFECTO D-01 (ver client.gaps.test.ts): con jsdom la cancelación llega como ApiRequestError y la
  // pantalla pinta «Servicio no disponible» al reescribir durante una búsqueda en curso.
  it('test_aborted_previous_search_shows_no_error', async () => {
    /** Criterio 9 (error): cancelar la búsqueda anterior al seguir escribiendo no muestra error. */
    let first = true
    mockServer.use(
      http.get('/api/v1/projects/:project/search', async ({ request }) => {
        const q = new URL(request.url).searchParams.get('q')
        if (q && first) {
          first = false
          await delay(400)
        }
        return HttpResponse.json([])
      }),
    )
    const { dialog } = await openFromHome()
    const search = within(dialog).getByRole('searchbox')
    await userEvent.type(search, 're')
    await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 50))
    await userEvent.type(search, 'novar')
    await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 150))
    expect(within(dialog).queryByRole('alert')).toBeNull()
  })

  it('test_search_error_shows_card_in_dialog', async () => {
    /** Criterio 9 (error): una búsqueda que falla muestra la tarjeta dentro del diálogo, que sigue abierto. */
    mockServer.use(
      http.get('/api/v1/projects/:project/search', ({ request }) =>
        new URL(request.url).searchParams.has('q')
          ? HttpResponse.json({ error: { code: 'service_unavailable', message: 'No se pudo conectar con Jira. Revisa la URL del sitio y la red.' } }, { status: 503 })
          : HttpResponse.json([]),
      ),
    )
    const { dialog } = await openFromHome()
    await userEvent.type(within(dialog).getByRole('searchbox'), 'renovar')
    const alert = await within(dialog).findByRole('alert', {}, { timeout: 2000 })
    expect(alert).toHaveTextContent('No se pudo conectar con Jira. Revisa la URL del sitio y la red.')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  // DEFECTO D-02: ChooseInJira.tsx solo hace setError(cause.error) y nunca lo borra; la tarjeta de un fallo
  // anterior sigue visible aunque las peticiones siguientes vayan bien. `it.fails` hasta que se corrija.
  it('test_search_error_card_cleared_after_successful_search', async () => {
    /** Criterio 9 (error): tras un fallo, una búsqueda correcta quita la tarjeta de error. */
    let failNext = true
    mockServer.use(
      http.get('/api/v1/projects/:project/search', ({ request }) => {
        if (new URL(request.url).searchParams.has('q') && failNext) {
          failNext = false
          return HttpResponse.json({ error: { code: 'service_unavailable', message: 'Jira ficticio caído.' } }, { status: 503 })
        }
        return HttpResponse.json([])
      }),
    )
    const { dialog } = await openFromHome()
    const search = within(dialog).getByRole('searchbox')
    await userEvent.type(search, 'ren')
    await within(dialog).findByRole('alert', {}, { timeout: 2000 })
    await userEvent.type(search, 'ovar')
    await new Promise((resolve) => setTimeout(resolve, SEARCH_DEBOUNCE_MS + 150))
    expect(within(dialog).queryByRole('alert')).toBeNull()
  })
})

describe('Elegir en Jira: proyecto, épica y HU', () => {
  it('test_using_story_of_initial_project_does_not_post_choose', async () => {
    /** Criterio 9: si el proyecto no cambia, no se llama a POST /projects/choose. */
    const posts = choosePosts()
    const { dialog } = await openFromHome()
    await userEvent.click(within(dialog).getByRole('option', { name: 'DEMO-1 Préstamo digital' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar la épica DEMO-1' }))
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(posts).toEqual([])
  })

  it('test_project_change_posts_choose_once_with_new_key', async () => {
    /** Criterio 9: cambiar de proyecto envía POST /projects/choose una vez, con la clave nueva. */
    const posts = choosePosts()
    const { dialog } = await openFromHome()
    await userEvent.click(within(dialog).getByRole('option', { name: 'SOCI Gestión de personas socias' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar el proyecto SOCI' }))
    await waitFor(() => expect(posts).toEqual(['SOCI']))
  })

  it('test_choose_failure_keeps_dialog_open_with_error', async () => {
    /** Criterio 9 (error): si POST /projects/choose falla, el diálogo sigue abierto con la tarjeta y no fija nada. */
    mockServer.use(
      http.post('/api/v1/projects/choose', () =>
        HttpResponse.json(
          { error: { code: 'project_not_found', message: 'El proyecto SOCI no existe o la conexión no tiene acceso a él.', retry_after: null } },
          { status: 404 },
        ),
      ),
    )
    const { dialog } = await openFromHome()
    await userEvent.click(within(dialog).getByRole('option', { name: 'SOCI Gestión de personas socias' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar el proyecto SOCI' }))
    const alert = await within(dialog).findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'No se encuentra el proyecto' })).toBeInTheDocument()
    expect(alert).toHaveTextContent('El proyecto SOCI no existe o la conexión no tiene acceso a él.')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Usar el proyecto SOCI' })).toBeEnabled()
  })

  it('test_use_buttons_disabled_while_choosing', async () => {
    /** Criterio 9: mientras se fija el proyecto, «Usar …» está desactivado (sin doble envío). */
    mockServer.use(
      http.post('/api/v1/projects/choose', async () => {
        await delay(150)
        return HttpResponse.json({ project: 'SOCI' })
      }),
    )
    const { dialog } = await openFromHome()
    await userEvent.click(within(dialog).getByRole('option', { name: 'SOCI Gestión de personas socias' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Usar el proyecto SOCI' }))
    expect(within(dialog).getByRole('button', { name: 'Usar el proyecto SOCI' })).toBeDisabled()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('test_changing_project_clears_epic_and_story', async () => {
    /** Criterio 9: al cambiar de proyecto se pierden la épica y la HU elegidas del anterior. */
    const { dialog } = await openFromHome()
    await userEvent.click(within(dialog).getByRole('option', { name: 'DEMO-1 Préstamo digital' }))
    await userEvent.click(await within(dialog).findByRole('option', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.click(within(dialog).getByRole('option', { name: 'SOCI Gestión de personas socias' }))
    expect(within(dialog).getByText('Elige una épica o una HU.')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /Usar (la épica )?DEMO/ })).toBeNull()
    expect(await within(dialog).findByRole('listbox', { name: 'Épicas de SOCI' })).toBeInTheDocument()
  })

  it('test_changing_epic_clears_story', async () => {
    /** Criterio 9: al cambiar de épica se pierde la HU elegida. */
    const { dialog } = await openFromHome()
    await userEvent.click(within(dialog).getByRole('option', { name: 'SOCI Gestión de personas socias' }))
    await userEvent.click(await within(dialog).findByRole('option', { name: 'SOCI-1 Alta de personas socias en línea' }))
    await userEvent.click(await within(dialog).findByRole('option', { name: 'SOCI-3 Renovar el carné de persona socia' }))
    expect(within(dialog).getByRole('button', { name: 'Usar SOCI-3' })).toBeInTheDocument()
    // Volver a pulsar la misma épica no borra la HU.
    await userEvent.click(within(dialog).getByRole('option', { name: 'SOCI-1 Alta de personas socias en línea' }))
    expect(within(dialog).getByRole('button', { name: 'Usar SOCI-3' })).toBeInTheDocument()
  })

  it('test_epic_without_stories_shows_empty_text', async () => {
    /** Criterio 9 (límite): una épica sin HU lo dice y solo permite usar la épica. */
    mockServer.use(http.get('/api/v1/epics/:key/stories', () => HttpResponse.json([])))
    const { dialog } = await openFromHome()
    await userEvent.click(within(dialog).getByRole('option', { name: 'DEMO-1 Préstamo digital' }))
    expect(await within(dialog).findByText('Esta épica no tiene HU.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Usar la épica DEMO-1' })).toBeInTheDocument()
  })

  it('test_project_without_epics_shows_empty_text', async () => {
    /** Criterio 9 (límite): un proyecto sin épicas lo dice. */
    mockServer.use(http.get('/api/v1/projects/:project/epics', () => HttpResponse.json([])))
    signIn()
    render(<ChooseInJira initialProject="DEMO" onCancel={vi.fn()} onPick={vi.fn()} />)
    expect(await screen.findByText('Este proyecto no tiene épicas.')).toBeInTheDocument()
  })

  it('test_story_pick_reports_project_and_origin', async () => {
    /** Criterio 9: «Usar DEMO-3» entrega el proyecto y la HU como origen. */
    signIn()
    const onPick = vi.fn()
    render(<ChooseInJira initialProject="DEMO" onCancel={vi.fn()} onPick={onPick} />)
    await userEvent.click(await screen.findByRole('option', { name: 'DEMO-1 Préstamo digital' }))
    await userEvent.click(await screen.findByRole('option', { name: 'DEMO-3 Renovar un préstamo' }))
    await userEvent.click(screen.getByRole('button', { name: 'Usar DEMO-3' }))
    await waitFor(() =>
      expect(onPick).toHaveBeenCalledWith({
        project: { key: 'DEMO', name: 'Biblioteca' },
        origin: { key: 'DEMO-3', summary: 'Renovar un préstamo', issue_type: 'Story', status: 'Abierta' },
      }),
    )
  })

  it('test_without_initial_project_uses_preselected', async () => {
    /** Criterio 9 (límite): sin proyecto de Inicio parte del último usado. */
    signIn()
    mockDb.projects.preselected = 'SOCI'
    render(<ChooseInJira onCancel={vi.fn()} onPick={vi.fn()} />)
    expect(await screen.findByRole('listbox', { name: 'Épicas de SOCI' })).toBeInTheDocument()
  })

  it('test_jira_texts_rendered_as_text', async () => {
    /** Criterio 9 (seguridad): los títulos de Jira se pintan como texto. */
    mockServer.use(
      http.get('/api/v1/projects/:project/epics', () =>
        HttpResponse.json([{ key: 'DEMO-1', summary: '<img src=x onerror=alert(1)>', issue_type: 'Epic', status: 'Abierta' }]),
      ),
    )
    const { dialog } = await openFromHome()
    expect(within(dialog).getByRole('option', { name: 'DEMO-1 <img src=x onerror=alert(1)>' })).toBeInTheDocument()
    expect(dialog.querySelector('img')).toBeNull()
  })
})

describe('Elegir en Jira: teclado en las listas', () => {
  it('test_keyboard_selects_epic_then_story_and_uses_it', async () => {
    /** Criterio 9: con el teclado se elige épica y HU, y se usa la HU. */
    const { dialog } = await openFromHome()
    const epics = within(dialog).getByRole('listbox', { name: 'Épicas de DEMO' })
    epics.focus()
    await userEvent.keyboard('{Enter}')
    expect(within(epics).getByRole('option', { name: 'DEMO-1 Préstamo digital' })).toHaveAttribute('aria-selected', 'true')
    const stories = await within(dialog).findByRole('listbox', { name: 'HU de DEMO-1' })
    stories.focus()
    await userEvent.keyboard('{End}')
    expect(within(stories).getByRole('option', { name: /DEMO-4/ })).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{Home}')
    expect(within(stories).getByRole('option', { name: /DEMO-2/ })).toHaveAttribute('aria-selected', 'true')
    expect(stories.getAttribute('aria-activedescendant')).toBe(within(stories).getByRole('option', { name: /DEMO-2/ }).id)
    await userEvent.tab()
    expect(within(dialog).getByRole('button', { name: 'Cancelar' })).toHaveFocus()
  })

  it('test_listboxes_are_reachable_with_tab', async () => {
    /** Criterio 9: cada lista es un único punto de tabulación (no una parada por opción). */
    const { dialog } = await openFromHome()
    await userEvent.tab()
    expect(within(dialog).getByRole('listbox', { name: 'Proyectos' })).toHaveFocus()
    await userEvent.tab()
    expect(within(dialog).getByRole('listbox', { name: 'Épicas de DEMO' })).toHaveFocus()
  })

  it('test_arrow_up_at_first_project_stays', async () => {
    /** Criterio 9 (límite): flecha arriba en el primer proyecto no sale de la lista ni cambia. */
    const { dialog } = await openFromHome()
    const projects = within(dialog).getByRole('listbox', { name: 'Proyectos' })
    projects.focus()
    await userEvent.keyboard('{ArrowUp}')
    expect(within(projects).getByRole('option', { name: 'DEMO Biblioteca' })).toHaveAttribute('aria-selected', 'true')
    expect(projects).toHaveFocus()
  })
})
