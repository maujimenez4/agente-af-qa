// Criterio 5 (T-56, días 2-4): huecos de Rail.test.tsx y Rail.criteria.test.tsx, sobre todo con la app
// entera contra MSW: anillo global, aviso al umbral, 503 sin anillo, Historial «disponible pronto» y zona de admin.
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../../App.tsx'
import { USAGE_REFRESH_MS } from '../../hooks/useUsage.ts'
import { mockDb } from '../../mocks/node.ts'
import { Rail } from './Rail.tsx'
import { usageView } from './railItems.ts'

const RING = /Consumo de tokens de hoy de todas las personas que usan el agente/

function signIn(role: 'functional' | 'qa' | 'admin') {
  const username = { functional: 'af-demo', qa: 'qa-demo', admin: 'admin-demo' }[role]
  mockDb.session = { username, role, csrf: 'csrf-ficticio' }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('Rail en la app: anillo de consumo (decisión 17, PA-305)', () => {
  it('test_ring_name_says_everyone_not_own_consumption', async () => {
    /** Criterio 5: el nombre accesible y el texto visible hablan del consumo de todas las personas, no del propio. */
    signIn('qa')
    render(<App />)
    const ring = await screen.findByRole('img', { name: RING })
    expect(ring).toHaveAccessibleName('Consumo de tokens de hoy de todas las personas que usan el agente: 42.000 de 180.000, 23 % del umbral de aviso')
    expect(ring).toHaveTextContent('consumo total')
    // El tooltip (`title`) dice lo mismo que el nombre accesible.
    expect(ring).toHaveAttribute('title', 'Consumo de tokens de hoy de todas las personas que usan el agente: 42.000 de 180.000, 23 % del umbral de aviso')
    // «todas las personas» sí; nada que suene al consumo propio («tu», «tus», «tuyo», «persona», «usuario»).
    expect(ring.getAttribute('aria-label')).not.toMatch(/\btus?\b|\btuyo\b|\bpersona\b|\busuario\b/i)
  })

  it('test_ring_warns_at_threshold_from_api', async () => {
    /** Criterio 5: con tokens_today = warning_threshold el anillo avisa. */
    signIn('functional')
    mockDb.usage = { tokens_today: 50000, warning_threshold: 50000, scope: 'global' }
    render(<App />)
    const ring = await screen.findByRole('img', { name: /50.000 de 50.000, 100 % del umbral de aviso/ })
    expect(ring.querySelector('[data-warning]')).not.toBeNull()
  })

  it.each([89, 90, 99])('test_ring_no_warning_below_threshold_%i_percent', (percent) => {
    /** Criterio 5 (límite): por debajo del umbral no avisa, ni al 90 % (decisión 17: «aviso desde warning_threshold»). */
    render(
      <Rail
        userRole="functional"
        username="af-demo"
        active="work"
        onNavigate={vi.fn()}
        onLogout={vi.fn()}
        usage={{ tokens_today: percent * 10, warning_threshold: 1000 }}
      />,
    )
    expect(usageView({ tokens_today: percent * 10, warning_threshold: 1000 })?.warning).toBe(false)
    expect(screen.getByRole('img', { name: RING }).querySelector('[data-warning]')).toBeNull()
  })

  it('test_ring_absent_when_usage_503', async () => {
    /** Criterio 5 (error): con 503 en /settings/usage no hay anillo, pero el carril sí. */
    signIn('functional')
    mockDb.usage = 'unavailable'
    render(<App />)
    await screen.findByRole('navigation', { name: 'Zonas' })
    await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(screen.queryByRole('img', { name: RING })).toBeNull()
    expect(screen.queryByText(/NaN|undefined/)).toBeNull()
  })

  it('test_ring_disappears_when_refresh_fails', async () => {
    /** Criterio 5 (error): si al refrescar el consumo la API da 503, el anillo deja de pintarse. */
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    signIn('functional')
    render(<App />)
    expect(await screen.findByRole('img', { name: RING })).toBeInTheDocument()
    mockDb.usage = 'unavailable'
    await act(async () => {
      vi.advanceTimersByTime(USAGE_REFRESH_MS)
    })
    await waitFor(() => expect(screen.queryByRole('img', { name: RING })).toBeNull())
  })

  it('test_ring_updates_on_refresh', async () => {
    /** Criterio 5: el anillo se actualiza con el siguiente refresco. */
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    signIn('functional')
    render(<App />)
    await screen.findByRole('img', { name: /42.000 de 180.000/ })
    mockDb.usage = { tokens_today: 90000, warning_threshold: 180000, scope: 'global' }
    await act(async () => {
      vi.advanceTimersByTime(USAGE_REFRESH_MS)
    })
    expect(await screen.findByRole('img', { name: /90.000 de 180.000, 50 %/ })).toBeInTheDocument()
  })
})

describe('Rail en la app: zonas por rol', () => {
  it('test_admin_enters_settings_and_history_is_soon', async () => {
    /** Criterio 5: admin entra por Ajustes; Historial está desactivado con «Disponible pronto» como descripción. */
    signIn('admin')
    render(<App />)
    const nav = await screen.findByRole('navigation', { name: 'Zonas' })
    expect(within(nav).getByRole('button', { name: 'Ajustes' })).toHaveAttribute('aria-current', 'page')
    const history = within(nav).getByRole('button', { name: 'Historial' })
    expect(history).toHaveAttribute('aria-disabled', 'true')
    expect(history).toHaveAccessibleDescription('Disponible pronto')
    expect(within(nav).queryByRole('button', { name: 'Trabajo' })).toBeNull()
  })

  it('test_history_soon_keyboard_does_nothing_and_stays_focusable', async () => {
    /** Criterio 5: Historial sigue en el orden de tabulación (aria-disabled) pero Intro y Espacio no navegan. */
    const onNavigate = vi.fn()
    render(<Rail userRole="admin" username="admin-demo" active="settings" onNavigate={onNavigate} onLogout={vi.fn()} />)
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Memoria' })).toHaveFocus()
    await userEvent.tab()
    const history = screen.getByRole('button', { name: 'Historial' })
    expect(history).toHaveFocus()
    expect(history).not.toBeDisabled()
    await userEvent.keyboard('{Enter}[Space]')
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('test_history_visual_soon_badge_is_hidden_from_screen_readers', () => {
    /** Criterio 5: la etiqueta visual «Pronto» no se lee pegada al nombre. */
    render(<Rail userRole="admin" username="admin-demo" active="settings" onNavigate={vi.fn()} onLogout={vi.fn()} />)
    const badge = within(screen.getByRole('button', { name: 'Historial' })).getByText('Pronto')
    expect(badge).toHaveAttribute('aria-hidden', 'true')
  })

  it('test_admin_settings_click_keeps_admin_screen', async () => {
    /** Criterio 5 y T-29: pulsar Ajustes (zona activa) deja a admin en la pantalla de Administración. */
    signIn('admin')
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Ajustes' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Ajustes' })).toBeInTheDocument()
  })

  it.each(['functional', 'qa'] as const)('test_%s_enters_work_zone', async (role) => {
    /** Criterio 5: analista y QA entran por Trabajo. */
    signIn(role)
    render(<App />)
    const nav = await screen.findByRole('navigation', { name: 'Zonas' })
    expect(within(nav).getByRole('button', { name: 'Trabajo' })).toHaveAttribute('aria-current', 'page')
  })
})
