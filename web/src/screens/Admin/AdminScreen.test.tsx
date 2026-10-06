// Administración mínima (T-29; HANDOFF.md, ronda 4 bloque 1): solo admin; probar conexiones (todas bien, una
// caída, 429 con cuenta atrás), modelos por tarea y modo de publicación, de solo lectura. Datos sintéticos.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../../App.tsx'
import examples from '../../api/examples.json'
import { setCsrfToken } from '../../api/client.ts'
import type { ConnectionsTestOut } from '../../api/types.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { AdminScreen } from './AdminScreen.tsx'
import { PUBLISH_SIMULATION_NOTICE } from './adminText.ts'

const CONNECTIONS = '/api/v1/admin/connections/test'

function signIn(role: 'functional' | 'qa' | 'admin') {
  const username = { functional: 'af-demo', qa: 'qa-demo', admin: 'admin-demo' }[role]
  mockDb.session = { username, role, csrf: 'csrf-ficticio' }
}

async function openAdmin() {
  signIn('admin')
  render(<App />)
  return screen.findByRole('heading', { level: 1, name: 'Ajustes' })
}

const connectionsCard = () => screen.getByRole('region', { name: 'Conexiones' })
const testButton = () => within(connectionsCard()).getByRole('button', { name: 'Probar conexiones' })

afterEach(() => {
  vi.useRealTimers()
  mockServer.events.removeAllListeners()
})

describe('Administración · acceso', () => {
  it('test_admin_lands_on_settings_without_flow_cards', async () => {
    /** D-01: admin entra en Ajustes, sin Trabajo ni tarjetas de flujo; Historial sigue «disponible pronto». */
    await openAdmin()
    const nav = screen.getByRole('navigation', { name: 'Zonas' })
    expect(within(nav).getByRole('button', { name: 'Ajustes' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('button', { name: 'Historial' })).toHaveAttribute('aria-disabled', 'true')
    expect(screen.queryByRole('group', { name: 'Qué quieres hacer' })).toBeNull()
  })

  it.each(['functional', 'qa'] as const)('test_%s_does_not_see_settings', async (role) => {
    /** Los otros roles no tienen la zona de Ajustes en el carril. */
    signIn(role)
    render(<App />)
    const nav = await screen.findByRole('navigation', { name: 'Zonas' })
    expect(within(nav).queryByRole('button', { name: 'Ajustes' })).toBeNull()
    expect(screen.queryByRole('heading', { level: 1, name: 'Ajustes' })).toBeNull()
  })

  it('test_non_admin_gets_forbidden_card_from_the_api', async () => {
    /** Si otro rol llegara a la pantalla, la API responde 403 y se pinta «Sin permiso», sin reintentar. */
    signIn('functional')
    setCsrfToken('csrf-ficticio')
    render(<AdminScreen />)
    const models = screen.getByRole('region', { name: 'Modelos por tarea' })
    const alert = await within(models).findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Sin permiso' })).toBeInTheDocument()
    expect(within(alert).getByText('No tienes permiso para realizar esta acción.')).toBeInTheDocument()
    expect(within(alert).queryByRole('button')).toBeNull()

    await userEvent.click(testButton())
    const denied = await within(connectionsCard()).findByRole('alert')
    expect(within(denied).getByRole('heading', { name: 'Sin permiso' })).toBeInTheDocument()
    expect(within(denied).queryByRole('button')).toBeNull()
  })
})

describe('Administración · conexiones', () => {
  it('test_connections_are_not_tested_on_entry', async () => {
    /** Entrar no llama a servicios externos: la prueba solo se lanza con el botón. */
    const posts: string[] = []
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST') posts.push(new URL(request.url).pathname)
    })
    await openAdmin()
    await screen.findByRole('table')
    expect(within(connectionsCard()).getByText(/Aún no has probado las conexiones/)).toBeInTheDocument()
    expect(posts).not.toContain(CONNECTIONS)
  })

  it('test_all_connections_ok_with_detail_and_time', async () => {
    /** Todas bien: una fila por servicio con «Conectado», el detalle y el tiempo; la prueba lleva CSRF. */
    const headers: (string | null)[] = []
    mockServer.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname === CONNECTIONS) headers.push(request.headers.get('X-CSRF-Token'))
    })
    await openAdmin()
    await userEvent.click(testButton())

    const rows = await within(connectionsCard()).findAllByRole('listitem')
    expect(rows).toHaveLength(4)
    const jira = rows[0] as HTMLElement
    expect(within(jira).getByText('Jira')).toBeInTheDocument()
    expect(within(jira).getByText('Conectado')).toBeInTheDocument()
    expect(within(jira).getByText('Conexión correcta con api.atlassian.com.')).toBeInTheDocument()
    expect(within(jira).getByText('412 ms')).toBeInTheDocument()
    expect(within(connectionsCard()).queryByText('Con problemas')).toBeNull()
    expect(headers).toEqual(['csrf-ficticio'])
  })

  it('test_one_connection_down_shows_its_detail', async () => {
    /** Un servicio caído (ejemplo del contrato): «Con problemas» y su detalle; los demás, «Conectado». */
    mockDb.connections = examples['POST /api/v1/admin/connections/test 200'] as unknown as ConnectionsTestOut
    await openAdmin()
    await userEvent.click(testButton())

    const models = await within(connectionsCard()).findByText('Modelos · ollama')
    const row = models.closest('li') as HTMLElement
    expect(within(row).getByText('Con problemas')).toBeInTheDocument()
    expect(within(row).getByText('Faltan modelos: qwen3:8b.')).toBeInTheDocument()
    expect(within(connectionsCard()).getAllByText('Conectado')).toHaveLength(3)
  })

  it('test_detail_is_rendered_as_text_never_html', async () => {
    /** El detalle se pinta tal cual como texto, aunque traiga marcas. */
    mockDb.connections = { checks: [{ service: 'Jira', ok: false, detail: '<b>Sin configurar.</b><img src=x>', duration_ms: 3 }] }
    await openAdmin()
    await userEvent.click(testButton())

    expect(await within(connectionsCard()).findByText('<b>Sin configurar.</b><img src=x>')).toBeInTheDocument()
    expect(connectionsCard().querySelector('b, img')).toBeNull()
  })

  it('test_second_test_within_10s_is_rate_limited_with_countdown', async () => {
    /** Una prueba cada 10 s: la segunda da 429 y la tarjeta cuenta atrás con el botón desactivado. */
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    await openAdmin()
    await userEvent.click(testButton())
    await within(connectionsCard()).findAllByRole('listitem')

    await userEvent.click(testButton())
    const alert = await within(connectionsCard()).findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'Límite de uso alcanzado' })).toBeInTheDocument()
    expect(within(alert).getByText('Espera unos segundos antes de volver a probar las conexiones.')).toBeInTheDocument()
    expect(within(alert).getByText(/Reintento disponible en (9|10) s/)).toBeInTheDocument()
    const retry = within(alert).getByRole('button', { name: 'Reintentar' })
    expect(retry).toBeDisabled()
    // Los resultados anteriores siguen a la vista.
    expect(within(connectionsCard()).getAllByRole('listitem')).toHaveLength(4)

    act(() => vi.advanceTimersByTime(10_000))
    expect(retry).toBeEnabled()
    mockDb.lastConnectionsTest = undefined // han pasado los 10 s también para la API simulada
    await userEvent.click(retry)
    await waitFor(() => expect(within(connectionsCard()).queryByRole('alert')).toBeNull())
    expect(testButton()).toBeEnabled()
  })

  it('test_rate_limited_example_uses_retry_after_from_the_contract', async () => {
    /** El 429 del contrato (`retry_after: 10`) se cuenta tal cual. */
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    mockServer.use(
      http.post(CONNECTIONS, () => HttpResponse.json(examples['POST /api/v1/admin/connections/test 429'], { status: 429 })),
    )
    await openAdmin()
    await userEvent.click(testButton())
    const alert = await within(connectionsCard()).findByRole('alert')
    expect(within(alert).getByText('Reintento disponible en 10 s')).toBeInTheDocument()
    expect(within(alert).getByText('Podrás reintentar dentro de 10 segundos.')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(4_000))
    expect(within(alert).getByText('Reintento disponible en 6 s')).toBeInTheDocument()
  })
})

describe('Administración · modelos y modo de publicación', () => {
  it('test_models_per_task_with_fallback_host_override_and_embeddings', async () => {
    /** Solo lectura: tarea, principal y respaldo con su host; el cambio de la sesión y los embeddings. */
    await openAdmin()
    const table = await screen.findByRole('table')
    const story = within(table).getByRole('row', { name: /Crear una HU/ })
    expect(within(story).getByText('ollama · qwen3:1.7b')).toBeInTheDocument()
    expect(within(story).getByText('ollama · phi4-mini')).toBeInTheDocument()
    expect(within(story).getAllByText('ollama:11434')).toHaveLength(2)

    const tests = within(table).getByRole('row', { name: /Preparar las pruebas/ })
    expect(within(tests).getByText('Esta sesión usa ollama · phi4-mini')).toBeInTheDocument()

    // Tarea del ejemplo del contrato sin nombre conocido: se muestra tal cual y sin respaldo.
    const unknown = within(table).getByRole('row', { name: /functional/ })
    expect(within(unknown).getByText('Sin respaldo')).toBeInTheDocument()

    const embeddings = within(table).getByRole('row', { name: /Embeddings/ })
    expect(within(embeddings).getByText('ollama · bge-m3')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cambiar|Guardar/ })).toBeNull()
  })

  it('test_models_error_can_be_retried', async () => {
    /** Un 503 al leer los modelos se reintenta desde su tarjeta. */
    let fail = true
    mockServer.use(
      http.get('/api/v1/admin/models', () =>
        fail ? HttpResponse.json(examples['GET /api/v1/admin/models 503'], { status: 503 }) : undefined,
      ),
    )
    await openAdmin()
    const models = screen.getByRole('region', { name: 'Modelos por tarea' })
    const alert = await within(models).findByRole('alert')
    fail = false
    await userEvent.click(within(alert).getByRole('button', { name: 'Reintentar' }))
    expect(await within(models).findByRole('table')).toBeInTheDocument()
  })

  it('test_publish_mode_simulation_notice', async () => {
    /** `publish_mode` de GET /settings, solo lectura, con el aviso de simulación. */
    await openAdmin()
    const card = screen.getByRole('region', { name: 'Modo de publicación' })
    expect(await within(card).findByText('Simulación')).toBeInTheDocument()
    expect(within(card).getByRole('note')).toHaveTextContent(PUBLISH_SIMULATION_NOTICE)
  })

  it('test_publish_mode_live_has_no_simulation_notice', async () => {
    /** En modo real no sale el aviso de simulación. */
    mockDb.settings = { ...mockDb.settings, publish_mode: 'live' }
    await openAdmin()
    const card = screen.getByRole('region', { name: 'Modo de publicación' })
    expect(await within(card).findByText('Real')).toBeInTheDocument()
    expect(within(card).queryByRole('note')).toBeNull()
  })

  it('test_users_and_documents_are_soon', async () => {
    /** Usuarios y documentos, «disponible pronto»: enfocables, sin efecto y con su descripción. */
    await openAdmin()
    for (const name of ['Elegir archivos', 'Gestionar usuarios']) {
      const button = screen.getByRole('button', { name })
      expect(button).toHaveAttribute('aria-disabled', 'true')
      expect(button).toHaveAccessibleDescription(/Disponible pronto/)
    }
  })
})
