// Memoria (PA-329) · AppShell: la zona Memoria convive con Trabajo (que sigue montado y oculto, y conserva la
// conversación) y admin entra por Ajustes y puede abrir Memoria. Solo datos sintéticos (DEMO-3, af-demo, qa-demo, admin-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../App.tsx'
import { mockDb } from '../mocks/node.ts'

function signIn(role: 'functional' | 'qa' | 'admin') {
  const username = { functional: 'af-demo', qa: 'qa-demo', admin: 'admin-demo' }[role]
  mockDb.session = { username, role, csrf: 'csrf-ficticio' }
}

const zones = () => screen.getByRole('navigation', { name: 'Zonas' })

describe('AppShell · Memoria y Trabajo', () => {
  it('test_switch_to_memory_and_back_keeps_open_conversation', async () => {
    /** PA-329: con una conversación en Iterar y un mensaje a medio escribir, ir a Memoria y volver la conserva. */
    signIn('functional')
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    const draft = 'Borrador ficticio a medio escribir'
    await userEvent.type(screen.getByRole('textbox', { name: /^Pide un cambio a la propuesta/ }), draft)
    const title = screen.getByRole('heading', { level: 1 }).textContent

    await userEvent.click(within(zones()).getByRole('button', { name: 'Memoria' }))
    expect(await screen.findByRole('complementary', { name: 'Memorias' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Memoria' })).toBeInTheDocument()
    // Trabajo sigue montado pero oculto: ni sus regiones ni su textbox son accesibles.
    expect(screen.queryByRole('complementary', { name: 'Propuesta de HU' })).toBeNull()
    expect(screen.queryByRole('complementary', { name: 'Conversaciones' })).toBeNull()
    expect(screen.queryByRole('textbox', { name: /^Pide un cambio a la propuesta/ })).toBeNull()
    expect(screen.getAllByRole('main')).toHaveLength(1)
    expect(within(zones()).getByRole('button', { name: 'Memoria' })).toHaveAttribute('aria-current', 'page')
    expect(within(zones()).getByRole('button', { name: 'Trabajo' })).not.toHaveAttribute('aria-current')

    await userEvent.click(within(zones()).getByRole('button', { name: 'Trabajo' }))
    expect(screen.getByRole('complementary', { name: 'Propuesta de HU' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /^Pide un cambio a la propuesta/ })).toHaveValue(draft)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(title)
    expect(screen.queryByRole('complementary', { name: 'Memorias' })).toBeNull()
    expect(within(zones()).getByRole('button', { name: 'Trabajo' })).toHaveAttribute('aria-current', 'page')
  })

  it('test_reopening_memory_starts_fresh_without_selection', async () => {
    /** Volver a Memoria desde el carril la abre de nuevo, sin memoria elegida. */
    signIn('qa')
    render(<App />)
    await userEvent.click(within(await screen.findByRole('navigation', { name: 'Zonas' })).getByRole('button', { name: 'Memoria' }))
    const list = await screen.findByRole('complementary', { name: 'Memorias' })
    await userEvent.click(await within(list).findByRole('button', { name: /DEMO-9001/ }))
    expect(await screen.findByRole('article', { name: 'DEMO-9001 · Memoria v2' })).toBeInTheDocument()
    await userEvent.click(within(zones()).getByRole('button', { name: 'Trabajo' }))
    await userEvent.click(within(zones()).getByRole('button', { name: 'Memoria' }))
    expect(await screen.findByText('Elige una memoria')).toBeInTheDocument()
    expect(screen.queryByRole('article')).toBeNull()
  })
})

describe('AppShell · admin', () => {
  it('test_admin_enters_settings_and_can_open_memory', async () => {
    /** Decisión 16 y PA-329: admin entra por Ajustes («Disponible pronto»), sin Trabajo, y puede abrir Memoria y volver. */
    signIn('admin')
    render(<App />)
    const nav = await screen.findByRole('navigation', { name: 'Zonas' })
    expect(within(nav).getByRole('button', { name: 'Ajustes' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('heading', { level: 1, name: 'Disponible pronto' })).toBeInTheDocument()
    expect(within(nav).queryByRole('button', { name: 'Trabajo' })).toBeNull()

    await userEvent.click(within(nav).getByRole('button', { name: 'Memoria' }))
    const list = await screen.findByRole('complementary', { name: 'Memorias' })
    expect(await within(list).findByRole('button', { name: /DEMO-9001/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 1, name: 'Disponible pronto' })).toBeNull()
    expect(within(nav).getByRole('button', { name: 'Memoria' })).toHaveAttribute('aria-current', 'page')

    await userEvent.click(within(nav).getByRole('button', { name: 'Ajustes' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Disponible pronto' })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Memorias' })).toBeNull()
  })

  it('test_admin_history_soon_does_not_leave_memory', async () => {
    /** Historial sigue «disponible pronto»: pulsarlo desde Memoria no cambia de zona. */
    signIn('admin')
    render(<App />)
    const nav = await screen.findByRole('navigation', { name: 'Zonas' })
    await userEvent.click(within(nav).getByRole('button', { name: 'Memoria' }))
    await screen.findByRole('complementary', { name: 'Memorias' })
    await userEvent.click(within(nav).getByRole('button', { name: 'Historial' }))
    expect(screen.getByRole('complementary', { name: 'Memorias' })).toBeInTheDocument()
    expect(within(nav).getByRole('button', { name: 'Memoria' })).toHaveAttribute('aria-current', 'page')
  })
})
