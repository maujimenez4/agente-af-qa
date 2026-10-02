import { render, screen } from '@testing-library/react'
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
  it('se pliega y se vuelve a mostrar', async () => {
    render(
      <SidePanel title="Antes de generar" footer={<button type="button">Generar propuesta</button>}>
        Fuentes
      </SidePanel>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Plegar panel' }))
    expect(screen.queryByRole('complementary')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Mostrar el panel «Antes de generar»' }))
    expect(screen.getByRole('complementary', { name: 'Antes de generar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generar propuesta' })).toBeInTheDocument()
  })
})
