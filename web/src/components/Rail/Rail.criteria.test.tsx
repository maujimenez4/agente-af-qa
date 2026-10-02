// Criterio 3: zonas por rol (decisión 16), aria-current, anillo de consumo opcional (decisión 17, PA-305)
// y aviso desde el 90 % (decisión 2). Casos de límite que no cubre Rail.test.tsx.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Rail, type RailProps } from './Rail.tsx'
import { railItemsFor, ROLE_NAMES, USAGE_WARNING, usageDash, type Role } from './railItems.ts'

function renderRail(props: Partial<RailProps> = {}) {
  const onNavigate = vi.fn()
  const onLogout = vi.fn()
  const result = render(
    <Rail userRole="functional" username="af-demo" active="work" onNavigate={onNavigate} onLogout={onLogout} {...props} />,
  )
  return { ...result, onNavigate, onLogout }
}

function ring(): HTMLElement {
  return screen.getByRole('img', { name: /Consumo diario de tokens/ })
}

describe('railItemsFor (decisión 16)', () => {
  it.each([
    ['functional', ['work']],
    ['qa', ['work']],
    ['admin', ['history', 'settings']],
  ] as const)('%s → zonas %j', (role, zones) => {
    expect(railItemsFor(role).map((item) => item.zone)).toEqual(zones)
  })

  it.each(['functional', 'qa'] as const)('%s nunca ve Historial ni Ajustes', (role) => {
    const zones = railItemsFor(role).map((item) => item.zone)
    expect(zones).not.toContain('history')
    expect(zones).not.toContain('settings')
  })

  it('cada zona usa su icono del carril', () => {
    expect(railItemsFor('admin').map((item) => item.icon)).toEqual(['history', 'settings'])
    expect(railItemsFor('qa').map((item) => item.icon)).toEqual(['work'])
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
    const { container } = renderRail({ userRole: 'admin', username: 'admin-demo', active: 'history' })
    expect(container.querySelectorAll('[aria-current]')).toHaveLength(1)
  })

  it('se navega con el teclado', async () => {
    const { onNavigate } = renderRail({ userRole: 'admin', username: 'admin-demo', active: 'history' })
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Historial' })).toHaveFocus()
    await userEvent.tab()
    await userEvent.keyboard('{Enter}')
    expect(onNavigate).toHaveBeenCalledWith('settings')
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

describe('Rail: anillo de consumo de tokens (decisiones 2 y 17)', () => {
  it('el umbral del aviso es el 90 %', () => {
    expect(USAGE_WARNING).toBe(90)
  })

  it('89 % no avisa', () => {
    renderRail({ usagePercent: 89 })
    expect(ring().querySelector('[data-warning]')).toBeNull()
  })

  it.each([90, 95, 100])('%i % avisa', (percent) => {
    renderRail({ usagePercent: percent })
    expect(ring().querySelector('[data-warning]')).not.toBeNull()
  })

  it('redondea antes de decidir el aviso: 89,4 % no avisa y 89,6 % se ve y avisa como 90 %', () => {
    const { unmount } = renderRail({ usagePercent: 89.4 })
    expect(ring()).toHaveAccessibleName('Consumo diario de tokens: 89 %')
    expect(ring().querySelector('[data-warning]')).toBeNull()
    unmount()
    renderRail({ usagePercent: 89.6 })
    expect(ring()).toHaveAccessibleName('Consumo diario de tokens: 90 %')
    expect(ring().querySelector('[data-warning]')).not.toBeNull()
  })

  it('un consumo negativo se acota a 0 % y no avisa', () => {
    renderRail({ usagePercent: -5 })
    expect(ring()).toHaveAccessibleName('Consumo diario de tokens: 0 %')
    expect(ring().querySelector('[data-warning]')).toBeNull()
  })

  it('0 % sí pinta el anillo: es un dato, no la ausencia de dato', () => {
    renderRail({ usagePercent: 0 })
    expect(ring()).toHaveTextContent('0 % tokens')
  })

  it('el dasharray del anillo corresponde al porcentaje redondeado', () => {
    renderRail({ usagePercent: 49.6 })
    const value = ring().querySelector('circle[stroke-dasharray]')
    expect(value).toHaveAttribute('stroke-dasharray', usageDash(50))
  })

  it('el texto del porcentaje es decorativo y con cifras tabulares; lo anuncia el nombre del anillo', () => {
    renderRail({ usagePercent: 24 })
    const text = within(ring()).getByText(/24/)
    expect(text).toHaveAttribute('aria-hidden', 'true')
    expect(text).toHaveClass('tabular-nums')
  })

  it('usageDash acota fuera de 0–100', () => {
    expect(usageDash(-10)).toBe(usageDash(0))
    expect(usageDash(250)).toBe(usageDash(100))
  })

  it('un consumo NaN no pinta «NaN %»', () => {
    renderRail({ usagePercent: Number.NaN })
    expect(screen.queryByText(/NaN/)).toBeNull()
  })
})
