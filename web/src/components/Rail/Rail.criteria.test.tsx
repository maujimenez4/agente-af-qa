// Criterio 3: zonas por rol (decisión 16), aria-current, anillo de consumo opcional (decisión 17, PA-305)
// y aviso desde el 90 % (decisión 2). Casos de límite que no cubre Rail.test.tsx.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Rail, type RailProps } from './Rail.tsx'
import { homeZone, railItemsFor, ROLE_NAMES, usageDash, usageView, type Role } from './railItems.ts'

function renderRail(props: Partial<RailProps> = {}) {
  const onNavigate = vi.fn()
  const onLogout = vi.fn()
  const result = render(
    <Rail userRole="functional" username="af-demo" active="work" onNavigate={onNavigate} onLogout={onLogout} onHome={vi.fn()} {...props} />,
  )
  return { ...result, onNavigate, onLogout }
}

function ring(): HTMLElement {
  return screen.getByRole('img', { name: /Consumo de tokens de hoy de todas las personas que usan FAQ/ })
}

describe('railItemsFor (decisión 16)', () => {
  it.each([
    ['functional', ['work', 'memory']],
    ['qa', ['work', 'memory']],
    ['admin', ['memory', 'history', 'settings']],
  ] as const)('%s → zonas %j', (role, zones) => {
    expect(railItemsFor(role).map((item) => item.zone)).toEqual(zones)
  })

  it.each(['functional', 'qa'] as const)('%s nunca ve Historial ni Ajustes', (role) => {
    const zones = railItemsFor(role).map((item) => item.zone)
    expect(zones).not.toContain('history')
    expect(zones).not.toContain('settings')
  })

  it('cada zona usa su icono del carril', () => {
    expect(railItemsFor('admin').map((item) => item.icon)).toEqual(['memory', 'history', 'settings'])
    expect(railItemsFor('qa').map((item) => item.icon)).toEqual(['work', 'memory'])
    expect(railItemsFor('functional').map((item) => item.icon)).toEqual(['work', 'memory'])
  })

  it('nombra los roles en español', () => {
    expect(ROLE_NAMES).toEqual({ functional: 'Analista funcional', qa: 'QA', admin: 'Administrador' })
  })
})

describe('Rail: zonas y zona activa', () => {
  it.each(['functional', 'qa'] as const)('%s no tiene botón de Historial ni de Ajustes', (role: Role) => {
    renderRail({ userRole: role })
    expect(screen.queryByRole('button', { name: 'Historial' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Ajustes' })).toBeNull()
  })

  it('la zona activa de la analista lleva aria-current="page"', () => {
    renderRail({ active: 'work' })
    expect(screen.getByRole('button', { name: 'Trabajo' })).toHaveAttribute('aria-current', 'page')
  })

  it('si la zona activa no es del rol, ningún botón lleva aria-current', () => {
    renderRail({ userRole: 'functional', active: 'history' })
    const nav = screen.getByRole('navigation', { name: 'Zonas' })
    for (const button of within(nav).getAllByRole('button')) expect(button).not.toHaveAttribute('aria-current')
  })

  it('solo hay una zona con aria-current a la vez', () => {
    const { container } = renderRail({ userRole: 'admin', username: 'admin-demo', active: 'settings' })
    expect(container.querySelectorAll('[aria-current]')).toHaveLength(1)
  })

  it('se navega con el teclado', async () => {
    const { onNavigate } = renderRail({ userRole: 'admin', username: 'admin-demo', active: 'history' })
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'FAQ · Inicio' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Memoria' })).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(onNavigate).toHaveBeenLastCalledWith('memory')
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Historial' })).toHaveFocus()
    await userEvent.tab()
    await userEvent.keyboard('{Enter}')
    expect(onNavigate).toHaveBeenLastCalledWith('settings')
    expect(onNavigate).toHaveBeenCalledTimes(2)
  })

  it('pulsar la zona ya activa vuelve a avisar con la misma zona', async () => {
    const { onNavigate } = renderRail({ active: 'work' })
    await userEvent.click(screen.getByRole('button', { name: 'Trabajo' }))
    expect(onNavigate).toHaveBeenCalledWith('work')
  })

  it('los iconos de las zonas y de salir son decorativos', () => {
    const { container } = renderRail()
    const icons = container.querySelectorAll('svg[data-icon]')
    expect(icons.length).toBeGreaterThanOrEqual(2)
    for (const icon of icons) expect(icon).toHaveAttribute('aria-hidden', 'true')
  })

  it('el avatar de admin anuncia «Administrador»', () => {
    renderRail({ userRole: 'admin', username: 'admin-demo', active: 'history' })
    expect(screen.getByRole('img', { name: 'admin-demo, Administrador' })).toHaveTextContent('A')
  })

  it('el nombre de usuario se muestra como texto, nunca como HTML', () => {
    const { container } = renderRail({ username: '<img src=x onerror=alert(1)>' })
    expect(screen.getByRole('img', { name: '<img src=x onerror=alert(1)>, Analista funcional' })).toHaveTextContent('<')
    expect(container.querySelector('nav img')).toBeNull()
  })

  it('con un nombre de usuario vacío no falla y el avatar queda sin inicial', () => {
    renderRail({ username: '' })
    expect(screen.getByRole('img', { name: ', Analista funcional' }).textContent).toBe('')
  })
})

describe('Rail: anillo con el consumo total de hoy (decisión 17, PA-305)', () => {
  const usage = (tokens_today: number, warning_threshold = 1000) => ({ tokens_today, warning_threshold })

  it('el porcentaje es tokens_today / warning_threshold, redondeado', () => {
    expect(usageView(usage(244))?.percent).toBe(24)
    expect(usageView(usage(245))?.percent).toBe(25)
  })

  it('avisa desde el umbral, no antes', () => {
    expect(usageView(usage(999))?.warning).toBe(false)
    expect(usageView(usage(1000))?.warning).toBe(true)
  })

  it('acota a 0–100 % y no pinta números negativos', () => {
    expect(usageView(usage(-5))?.percent).toBe(0)
    expect(usageView(usage(-5))?.label).toContain(': 0 de 1.000')
    expect(usageView(usage(5000))?.percent).toBe(100)
  })

  it.each([
    ['sin dato', undefined],
    ['NaN', { tokens_today: Number.NaN, warning_threshold: 1000 }],
    ['umbral 0', { tokens_today: 10, warning_threshold: 0 }],
    ['umbral infinito', { tokens_today: 10, warning_threshold: Number.POSITIVE_INFINITY }],
  ])('%s: no hay anillo', (_name, value) => {
    expect(usageView(value)).toBeUndefined()
  })

  it('0 tokens sí pinta el anillo: es un dato, no la ausencia de dato', () => {
    renderRail({ usage: usage(0) })
    expect(ring()).toHaveTextContent('0 %')
  })

  it('el nombre accesible dice que es el consumo de todas las personas que usan FAQ, con cifras en español', () => {
    renderRail({ usage: { tokens_today: 12345, warning_threshold: 50000 } })
    expect(ring()).toHaveAccessibleName(
      'Consumo de tokens de hoy de todas las personas que usan FAQ: 12.345 de 50.000, 25 % del umbral de aviso',
    )
  })

  it('el dasharray del anillo corresponde al porcentaje redondeado', () => {
    renderRail({ usage: usage(496) })
    expect(ring().querySelector('circle[stroke-dasharray]')).toHaveAttribute('stroke-dasharray', usageDash(50))
  })

  it('el texto visible es decorativo y con cifras tabulares; lo anuncia el nombre del anillo', () => {
    renderRail({ usage: usage(240) })
    const text = within(ring()).getByText(/24/)
    expect(text).toHaveAttribute('aria-hidden', 'true')
    expect(text).toHaveClass('tabular-nums')
    expect(text).toHaveTextContent('consumo total')
  })

  it('usageDash acota fuera de 0–100', () => {
    expect(usageDash(-10)).toBe(usageDash(0))
    expect(usageDash(250)).toBe(usageDash(100))
  })

  it('un consumo NaN no pinta «NaN %»', () => {
    renderRail({ usage: { tokens_today: Number.NaN, warning_threshold: 1000 } })
    expect(screen.queryByText(/NaN/)).toBeNull()
  })
})

describe('Rail: Historial «disponible pronto» (decisión 16, PA-302)', () => {
  it('admin ve Historial desactivado con su descripción, y no navega', async () => {
    const { onNavigate } = renderRail({ userRole: 'admin', username: 'admin-demo', active: 'settings' })
    const history = screen.getByRole('button', { name: 'Historial' })
    expect(history).toHaveAttribute('aria-disabled', 'true')
    expect(history).toHaveAccessibleDescription('Disponible pronto')
    expect(history).not.toHaveAttribute('aria-current')
    await userEvent.click(history)
    expect(onNavigate).not.toHaveBeenCalled()
  })

  it('cada rol entra por su primera zona disponible', () => {
    expect(homeZone('functional')).toBe('work')
    expect(homeZone('qa')).toBe('work')
    expect(homeZone('admin')).toBe('settings')
  })
})
