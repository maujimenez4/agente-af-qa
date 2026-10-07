// PA-343: con el panel en capa, la conversación (bajo el velo) es `inert` y el velo sigue cerrando; al cerrar se
// quita y el foco vuelve a «Mostrar el panel», que ahora llega por `ref` (Button con ref). Datos sintéticos (DEMO-3).
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Button } from '../Button/index.ts'
import { PANEL_LAYER_BELOW, SidePanel, Workspace } from './Workspace.tsx'

let resize: (width: number) => void

beforeEach(() => {
  const callbacks = new Set<ResizeObserverCallback>()
  vi.stubGlobal(
    'ResizeObserver',
    class {
      private readonly callback: ResizeObserverCallback
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback
      }
      observe() {
        callbacks.add(this.callback)
      }
      unobserve() {}
      disconnect() {
        callbacks.delete(this.callback)
      }
    },
  )
  resize = (width) =>
    act(() => {
      for (const callback of [...callbacks]) callback([{ contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver)
    })
})

afterEach(() => vi.unstubAllGlobals())

function renderWorkspace() {
  render(
    <Workspace title="Evolucionar DEMO-3" phase={2} panel={<SidePanel title="Propuesta de HU">Propuesta ficticia</SidePanel>}>
      <p>Mensajes ficticios</p>
    </Workspace>,
  )
}

const conversation = () => screen.getByRole('region', { name: 'Conversación' })

describe('PA-343 (a): inert detrás del panel en capa', () => {
  it('test_conversation_inert_while_panel_layer_open_and_focus_back_on_close', async () => {
    renderWorkspace()
    resize(PANEL_LAYER_BELOW - 1)
    const show = screen.getByRole('button', { name: 'Mostrar el panel' })
    await userEvent.click(show)
    expect(screen.getByRole('dialog', { name: 'Propuesta de HU' })).toBeInTheDocument()
    expect(conversation()).toHaveAttribute('inert')
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar' }))
    expect(conversation()).not.toHaveAttribute('inert')
    expect(screen.getByRole('button', { name: 'Mostrar el panel' })).toHaveFocus()
  })

  it('test_backdrop_still_closes_layer_while_conversation_inert', async () => {
    renderWorkspace()
    resize(PANEL_LAYER_BELOW - 1)
    await userEvent.click(screen.getByRole('button', { name: 'Mostrar el panel' }))
    const backdrop = document.querySelector('[aria-hidden="true"][class*="layerBackdrop"]') as HTMLElement
    expect(backdrop.closest('[inert]')).toBeNull()
    await userEvent.click(backdrop)
    expect(screen.queryByRole('dialog', { name: 'Propuesta de HU' })).not.toBeInTheDocument()
    expect(conversation()).not.toHaveAttribute('inert')
  })

  it('test_no_inert_when_panel_is_not_a_layer', async () => {
    renderWorkspace()
    expect(conversation()).not.toHaveAttribute('inert')
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    await userEvent.click(screen.getByRole('button', { name: 'Mostrar el panel' }))
    expect(conversation()).not.toHaveAttribute('inert')
  })
})

describe('PA-343 (b): Button reenvía ref', () => {
  it('test_button_ref_points_to_native_button', () => {
    const ref = createRef<HTMLButtonElement>()
    render(<Button ref={ref}>Acción ficticia</Button>)
    expect(ref.current).toBe(screen.getByRole('button', { name: 'Acción ficticia' }))
  })
})
