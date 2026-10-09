import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Rail, type RailProps } from './Rail.tsx'
import { usageDash } from './railItems.ts'

function renderRail(props: Partial<RailProps> = {}) {
  const onNavigate = vi.fn()
  const onLogout = vi.fn()
  render(
    <Rail userRole="functional" username="af-demo" active="work" onNavigate={onNavigate} onLogout={onLogout} onHome={vi.fn()} {...props} />,
  )
  return { onNavigate, onLogout }
}

function zoneNames(): string[] {
  const nav = screen.getByRole('navigation', { name: 'Zonas' })
  // La etiqueta visible de cada zona (la primera línea del botón).
  return within(within(nav).getByRole('list'))
    .getAllByRole('button')
    .map((button) => button.querySelector('span')?.textContent ?? '')
}

describe('Rail', () => {
  it('la analista funcional solo ve Trabajo y Memoria', () => {
    renderRail({ userRole: 'functional' })
    expect(zoneNames()).toEqual(['Trabajo', 'Memoria'])
  })

  it('QA solo ve Trabajo y Memoria', () => {
    renderRail({ userRole: 'qa', username: 'qa-demo' })
    expect(zoneNames()).toEqual(['Trabajo', 'Memoria'])
  })

  it('admin ve Memoria, Historial y Ajustes, y no Trabajo (decisión 16, PA-329)', () => {
    renderRail({ userRole: 'admin', username: 'admin-demo', active: 'history' })
    expect(zoneNames()).toEqual(['Memoria', 'Historial', 'Ajustes'])
    expect(screen.queryByRole('button', { name: 'Trabajo' })).toBeNull()
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
    // PA-478: la Q es el botón a Inicio, con nombre «FAQ · Inicio».
    renderRail()
    expect(screen.getByRole('button', { name: 'FAQ · Inicio' })).toBeInTheDocument()
  })

  it('sin dato de consumo no pinta el anillo (PA-305)', () => {
    renderRail()
    expect(screen.queryByRole('img', { name: /Consumo de tokens de hoy/ })).toBeNull()
  })

  it('con dato pinta el consumo total de hoy respecto al umbral de aviso, con el mismo title que el nombre', () => {
    renderRail({ usage: { tokens_today: 42000, warning_threshold: 180000 } })
    const ring = screen.getByRole('img', {
      name: 'Consumo de tokens de hoy de todas las personas que usan FAQ: 42.000 de 180.000, 23 % del umbral de aviso',
    })
    expect(ring).toHaveTextContent('23 %consumo total')
    expect(ring.getAttribute('title')).toBe(ring.getAttribute('aria-label'))
    expect(ring.querySelector('[data-warning]')).toBeNull()
  })

  it('avisa al llegar al umbral', () => {
    renderRail({ usage: { tokens_today: 180000, warning_threshold: 180000 } })
    const ring = screen.getByRole('img', { name: /100 % del umbral de aviso/ })
    expect(ring.querySelector('[data-warning]')).not.toBeNull()
  })

  it('por encima del umbral se acota a 100 % y sigue avisando', () => {
    renderRail({ usage: { tokens_today: 250000, warning_threshold: 180000 } })
    expect(screen.getByRole('img', { name: /250.000 de 180.000, 100 % del umbral/ })).toBeInTheDocument()
  })
})

describe('usageDash', () => {
  it('es proporcional al porcentaje', () => {
    expect(usageDash(0)).toBe('0.0 94.2')
    expect(usageDash(50)).toBe('47.1 94.2')
    expect(usageDash(100)).toBe('94.2 94.2')
  })
})
