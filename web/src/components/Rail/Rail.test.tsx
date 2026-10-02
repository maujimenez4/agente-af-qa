import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Rail, type RailProps } from './Rail.tsx'
import { usageDash } from './railItems.ts'

function renderRail(props: Partial<RailProps> = {}) {
  const onNavigate = vi.fn()
  const onLogout = vi.fn()
  render(
    <Rail userRole="functional" username="af-demo" active="work" onNavigate={onNavigate} onLogout={onLogout} {...props} />,
  )
  return { onNavigate, onLogout }
}

function zoneNames(): string[] {
  const nav = screen.getByRole('navigation', { name: 'Zonas' })
  return within(nav)
    .getAllByRole('listitem')
    .map((item) => item.textContent ?? '')
}

describe('Rail', () => {
  it('la analista funcional solo ve Trabajo', () => {
    renderRail({ userRole: 'functional' })
    expect(zoneNames()).toEqual(['Trabajo'])
  })

  it('QA solo ve Trabajo', () => {
    renderRail({ userRole: 'qa', username: 'qa-demo' })
    expect(zoneNames()).toEqual(['Trabajo'])
  })

  it('admin ve Historial y Ajustes, y no Trabajo (decisión 16)', () => {
    renderRail({ userRole: 'admin', username: 'admin-demo', active: 'history' })
    expect(zoneNames()).toEqual(['Historial', 'Ajustes'])
  })

  it('marca la zona activa con aria-current="page"', () => {
    renderRail({ userRole: 'admin', username: 'admin-demo', active: 'settings' })
    expect(screen.getByRole('button', { name: 'Ajustes' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Historial' })).not.toHaveAttribute('aria-current')
  })

  it('avisa al pulsar una zona', async () => {
    const { onNavigate } = renderRail({ userRole: 'admin', username: 'admin-demo', active: 'history' })
    await userEvent.click(screen.getByRole('button', { name: 'Ajustes' }))
    expect(onNavigate).toHaveBeenCalledWith('settings')
  })

  it('cierra sesión con su botón, que tiene nombre accesible', async () => {
    const { onLogout } = renderRail()
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar sesión' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('muestra la inicial del usuario y anuncia usuario y rol', () => {
    renderRail({ userRole: 'qa', username: 'qa-demo' })
    const avatar = screen.getByRole('img', { name: 'qa-demo, QA' })
    expect(avatar).toHaveTextContent('Q')
  })

  it('tiene el logotipo con nombre accesible', () => {
    renderRail()
    expect(screen.getByRole('img', { name: 'Agente AF y QA' })).toBeInTheDocument()
  })

  it('sin dato de consumo no pinta el anillo (PA-305)', () => {
    renderRail()
    expect(screen.queryByRole('img', { name: /Consumo diario de tokens/ })).toBeNull()
  })

  it('con dato pinta el anillo y su porcentaje', () => {
    renderRail({ usagePercent: 24 })
    const ring = screen.getByRole('img', { name: 'Consumo diario de tokens: 24 %' })
    expect(ring).toHaveTextContent('24 % tokens')
    expect(ring.querySelector('[data-warning]')).toBeNull()
  })

  it('avisa desde el 90 %', () => {
    renderRail({ usagePercent: 90 })
    const ring = screen.getByRole('img', { name: 'Consumo diario de tokens: 90 %' })
    expect(ring.querySelector('[data-warning]')).not.toBeNull()
  })

  it('acota el porcentaje a 0–100', () => {
    renderRail({ usagePercent: 140 })
    expect(screen.getByRole('img', { name: 'Consumo diario de tokens: 100 %' })).toBeInTheDocument()
  })
})

describe('usageDash', () => {
  it('es proporcional al porcentaje', () => {
    expect(usageDash(0)).toBe('0.0 94.2')
    expect(usageDash(50)).toBe('47.1 94.2')
    expect(usageDash(100)).toBe('94.2 94.2')
  })
})
