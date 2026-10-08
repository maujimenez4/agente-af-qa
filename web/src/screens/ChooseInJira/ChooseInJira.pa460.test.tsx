// PA-460: «Elegir en Jira» distingue «cargando» de «vacío» en cada lista (proyectos, épicas, HU y búsqueda) y lleva
// un error por cada carga, con su «Reintentar». Antes, mientras Jira respondía, salía «Este proyecto no tiene
// épicas.». Deterministas: las respuestas se retienen hasta que la prueba las suelta. Datos sintéticos (DEMO).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { SEARCH_MAX_LENGTH } from './ChooseInJira.tsx'

/** Retiene la siguiente respuesta de `path` hasta `release()`; después responde la API simulada. */
function hold(path: string) {
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  mockServer.use(
    http.get(
      path,
      async () => {
        await gate
        return undefined
      },
      { once: true },
    ),
  )
  return { release: () => release() }
}

const unavailable = (message: string) =>
  HttpResponse.json({ error: { code: 'service_unavailable', message } }, { status: 503 })

/** Cuántas peticiones a cada ruta (sin el prefijo /api/v1). */
function countRequests() {
  const counts = new Map<string, number>()
  mockServer.events.on('request:start', ({ request }) => {
    const path = new URL(request.url).pathname.replace('/api/v1', '')
    counts.set(path, (counts.get(path) ?? 0) + 1)
  })
  return (path: string) => counts.get(path) ?? 0
}

/** Abre el diálogo desde Inicio. `beforeOpen` prepara respuestas solo para el diálogo (Inicio también pide /projects). */
async function openDialog(beforeOpen?: () => void) {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const button = await screen.findByRole('button', { name: 'Elegir en Jira' })
  await waitFor(() => expect(button).toBeEnabled())
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  beforeOpen?.()
  await userEvent.click(button)
  return screen.getByRole('dialog', { name: 'Elegir en Jira' })
}

afterEach(() => {
  mockServer.events.removeAllListeners()
})

describe('Elegir en Jira · cargando frente a vacío (PA-460)', () => {
  it('épicas: mientras Jira responde dice «Cargando épicas…», nunca «no tiene épicas»; después, la lista', async () => {
    const epics = hold('/api/v1/projects/:project/epics')
    const dialog = await openDialog()
    const loading = await within(dialog).findByText('Cargando épicas…')
    expect(loading).toHaveAttribute('aria-busy', 'true')
    expect(within(dialog).queryByText('Este proyecto no tiene épicas.')).toBeNull()

    epics.release()
    expect(await within(dialog).findByRole('listbox', { name: 'Épicas de DEMO' })).toBeInTheDocument()
    expect(within(dialog).queryByText('Cargando épicas…')).toBeNull()
  })

  it('épicas vacías: «Este proyecto no tiene épicas.» solo con la respuesta ya recibida', async () => {
    mockServer.use(http.get('/api/v1/projects/:project/epics', () => HttpResponse.json([])))
    const dialog = await openDialog()
    expect(await within(dialog).findByText('Este proyecto no tiene épicas.')).toBeInTheDocument()
    expect(within(dialog).queryByText('Cargando épicas…')).toBeNull()
  })

  it('proyectos: «Cargando proyectos…» mientras llegan', async () => {
    let projects = { release: () => undefined as void }
    const dialog = await openDialog(() => {
      projects = hold('/api/v1/projects')
    })
    expect(within(dialog).getByText('Cargando proyectos…')).toBeInTheDocument()
    expect(within(dialog).queryByText('Ningún proyecto coincide.')).toBeNull()
    projects.release()
    expect(await within(dialog).findByRole('listbox', { name: 'Proyectos' })).toBeInTheDocument()
  })

  it('HU de una épica: «Cargando HU…» mientras llegan, no «Esta épica no tiene HU.»', async () => {
    const dialog = await openDialog()
    const epics = await within(dialog).findByRole('listbox', { name: 'Épicas de DEMO' })
    const stories = hold('/api/v1/epics/:key/stories')
    await userEvent.click(within(epics).getAllByRole('option')[0] as HTMLElement)
    expect(await within(dialog).findByText('Cargando HU…')).toBeInTheDocument()
    expect(within(dialog).queryByText('Esta épica no tiene HU.')).toBeNull()
    stories.release()
    await waitFor(() => expect(within(dialog).queryByText('Cargando HU…')).toBeNull())
  })

  it('búsqueda: «Buscando…» mientras llega, sin «Ninguna épica coincide.»', async () => {
    const dialog = await openDialog()
    await within(dialog).findByRole('listbox', { name: 'Épicas de DEMO' })
    const search = hold('/api/v1/projects/:project/search')
    await userEvent.type(within(dialog).getByRole('searchbox'), 'renovar')
    expect(within(dialog).getAllByText('Buscando…').length).toBeGreaterThan(0)
    expect(within(dialog).queryByText('Ninguna épica coincide.')).toBeNull()
    search.release()
    await waitFor(() => expect(within(dialog).queryByText('Buscando…')).toBeNull())
  })

  it(`el buscador admite como mucho ${SEARCH_MAX_LENGTH} caracteres (contrato)`, async () => {
    const dialog = await openDialog()
    expect(within(dialog).getByRole('searchbox')).toHaveAttribute('maxLength', String(SEARCH_MAX_LENGTH))
    expect(SEARCH_MAX_LENGTH).toBe(200)
  })
})

describe('Elegir en Jira · un error por cada carga (PA-460)', () => {
  it('si fallan las épicas, su tarjeta sale en su columna y los proyectos siguen; «Reintentar» pide solo las épicas', async () => {
    mockServer.use(http.get('/api/v1/projects/:project/epics', () => unavailable('Jira ficticio caído (épicas).'), { once: true }))
    const requests = countRequests()
    const dialog = await openDialog()
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('Jira ficticio caído (épicas).')
    expect(within(dialog).getByRole('listbox', { name: 'Proyectos' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('listbox', { name: 'Épicas de DEMO' })).toBeNull()
    const projectsBefore = requests('/projects')

    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await within(dialog).findByRole('listbox', { name: 'Épicas de DEMO' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('alert')).toBeNull()
    expect(requests('/projects')).toBe(projectsBefore) // los proyectos no se vuelven a pedir
  })

  it('si fallan las HU, las épicas siguen visibles y elegibles', async () => {
    const dialog = await openDialog()
    const epics = await within(dialog).findByRole('listbox', { name: 'Épicas de DEMO' })
    mockServer.use(http.get('/api/v1/epics/:key/stories', () => unavailable('Jira ficticio caído (HU).'), { once: true }))
    await userEvent.click(within(epics).getAllByRole('option')[0] as HTMLElement)
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('Jira ficticio caído (HU).')
    expect(within(dialog).getByRole('listbox', { name: 'Épicas de DEMO' })).toBeInTheDocument()
    expect(within(dialog).getAllByRole('alert')).toHaveLength(1)
  })

  it('si fallan los proyectos, la tarjeta sale en su columna con su «Reintentar»', async () => {
    const dialog = await openDialog(() =>
      mockServer.use(http.get('/api/v1/projects', () => unavailable('Jira ficticio caído (proyectos).'), { once: true })),
    )
    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('Jira ficticio caído (proyectos).')
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await within(dialog).findByRole('listbox', { name: 'Proyectos' })).toBeInTheDocument()
  })
})
