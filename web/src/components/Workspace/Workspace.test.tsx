import { render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SidePanel, Workspace } from './Workspace.tsx'

describe('Workspace', () => {
  it('pinta el título como H1 y la Q de su fase', () => {
    render(
      <Workspace title="Renovar un préstamo desde la app" phase={1}>
        <p>Mensajes</p>
      </Workspace>,
    )
    expect(screen.getByRole('heading', { level: 1, name: 'Renovar un préstamo desde la app' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Avance: fase 1 de 4, Contexto' })).toBeInTheDocument()
  })

  it('pinta el compositor y el panel que le dan', () => {
    render(
      <Workspace title="x" phase={2} composer={<p>Compositor</p>} panel={<SidePanel title="Antes de generar">Contenido</SidePanel>}>
        <p>Mensajes</p>
      </Workspace>,
    )
    expect(screen.getByText('Compositor')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Antes de generar' })).toHaveTextContent('Contenido')
  })
})

describe('SidePanel', () => {
  function Tabs() {
    const [tab, setTab] = useState('Propuesta')
    return (
      <button type="button" onClick={() => setTab('Cambios')}>
        Pestaña {tab}
      </button>
    )
  }

  function renderWorkspace() {
    render(
      <Workspace
        title="Evolucionar DEMO-3"
        phase={2}
        panel={
          <SidePanel title="Antes de generar" footer={<button type="button">Generar propuesta</button>}>
            <Tabs />
          </SidePanel>
        }
      >
        <p>Mensajes</p>
      </Workspace>,
    )
  }

  it('el botón para plegarlo está en la cabecera de la conversación, con texto visible', () => {
    renderWorkspace()
    const header = screen.getByRole('heading', { level: 1, name: 'Evolucionar DEMO-3' }).closest('header')
    expect(header).not.toBeNull()
    const toggle = within(header as HTMLElement).getByRole('button', { name: 'Ocultar el panel' })
    expect(toggle).toHaveTextContent('Ocultar el panel')
    expect(toggle).toHaveAttribute('aria-controls', screen.getByRole('complementary', { name: 'Antes de generar' }).id)
  })

  it('se pliega y se vuelve a mostrar desde el mismo botón, sin perder su estado', async () => {
    renderWorkspace()
    await userEvent.click(screen.getByRole('button', { name: 'Pestaña Propuesta' }))
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    expect(screen.queryByRole('complementary')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Generar propuesta' })).toBeNull()

    const toggle = screen.getByRole('button', { name: 'Mostrar el panel' })
    expect(toggle).toHaveFocus()
    await userEvent.click(toggle)
    expect(screen.getByRole('complementary', { name: 'Antes de generar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pestaña Cambios' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ocultar el panel' })).toHaveFocus()
  })

  it('se pliega con el teclado', async () => {
    renderWorkspace()
    screen.getByRole('button', { name: 'Ocultar el panel' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(screen.queryByRole('complementary')).toBeNull()
    await userEvent.keyboard(' ')
    expect(screen.getByRole('complementary', { name: 'Antes de generar' })).toBeInTheDocument()
  })

  it('sin panel no hay botón para plegarlo', () => {
    render(
      <Workspace title="x" phase={1}>
        <p>Mensajes</p>
      </Workspace>,
    )
    expect(screen.queryByRole('button', { name: /panel/ })).toBeNull()
  })

  it('fuera de un Workspace se pinta siempre abierto', () => {
    render(<SidePanel title="Antes de generar">Fuentes</SidePanel>)
    expect(screen.getByRole('complementary', { name: 'Antes de generar' })).toBeVisible()
  })
})
