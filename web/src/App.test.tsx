import { render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from './App.tsx'
import { mockDb } from './mocks/node.ts'

function signIn(username: 'af-demo' | 'qa-demo' | 'admin-demo', role: 'functional' | 'qa' | 'admin') {
  mockDb.session = { username, role, csrf: 'csrf-ficticio' }
}

describe('App', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/')
  })

  it('sin sesión pide iniciar sesión', async () => {
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Hola de nuevo' })).toBeInTheDocument()
  })

  it('con sesión de analista muestra el carril, sus conversaciones y la zona de trabajo', async () => {
    signIn('af-demo', 'functional')
    render(<App />)
    const nav = await screen.findByRole('navigation', { name: 'Zonas' })
    expect(within(nav).getByRole('button', { name: 'Trabajo' })).toHaveAttribute('aria-current', 'page')
    const list = screen.getByRole('complementary', { name: 'Conversaciones' })
    expect(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ })).toBeInTheDocument()
  })

  it('el carril muestra el consumo total de hoy', async () => {
    signIn('af-demo', 'functional')
    render(<App />)
    expect(await screen.findByRole('img', { name: /Consumo de tokens de hoy de todas las personas que usan FAQ: 42.000 de 180.000/ })).toBeInTheDocument()
  })

  it('admin ve los Ajustes (Administración mínima) y no tiene lista de conversaciones', async () => {
    signIn('admin-demo', 'admin')
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Ajustes' })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Conversaciones' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Ajustes' })).toHaveAttribute('aria-current', 'page')
  })

  it('cerrar sesión vuelve a pedirla', async () => {
    signIn('qa-demo', 'qa')
    render(<App />)
    const logout = await screen.findByRole('button', { name: 'Cerrar sesión' })
    logout.click()
    expect(await screen.findByRole('heading', { name: 'Hola de nuevo' })).toBeInTheDocument()
  })

  it('en desarrollo, ?catalogo abre el catálogo del sistema de diseño (PA-309)', async () => {
    window.history.replaceState(null, '', '/?catalogo')
    render(<App />)
    expect(await screen.findByRole('heading', { level: 1, name: 'Sistema de diseño · Propuesta mixta' })).toBeInTheDocument()
  })
})
