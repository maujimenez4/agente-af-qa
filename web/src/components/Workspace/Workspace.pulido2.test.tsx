// PA-343 · huecos del `inert` bajo el panel en capa (pulido 2 de T-56): al ensancharse el área con la capa abierta,
// al quitar el panel, con una confirmación que impide cerrar y si la conversación ya era `inert`. Sin reloj: el
// tamaño llega por un ResizeObserver simulado. Datos sintéticos (DEMO-3).
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PANEL_LAYER_BELOW, SidePanel, Workspace, type WorkspaceProps } from './Workspace.tsx'

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

const PANEL = <SidePanel title="Propuesta de HU">Propuesta ficticia</SidePanel>

function workspace(props: Partial<WorkspaceProps> = {}) {
  return (
    <Workspace title="Evolucionar DEMO-3" phase={2} panel={PANEL} {...props}>
      <p>Mensajes ficticios</p>
    </Workspace>
  )
}

const conversation = () => screen.getByRole('region', { name: 'Conversación' })

async function openPanelLayer() {
  resize(PANEL_LAYER_BELOW - 1)
  await userEvent.click(screen.getByRole('button', { name: 'Mostrar el panel' }))
  expect(screen.getByRole('dialog', { name: 'Propuesta de HU' })).toBeInTheDocument()
  expect(conversation()).toHaveAttribute('inert')
}

describe('Workspace · inert bajo el panel en capa (PA-343, pulido 2)', () => {
  it('test_inert_removed_when_area_widens_with_layer_open', async () => {
    /** PA-343 + PA-335: al ensancharse el área con la capa abierta, el panel deja de ser capa y se quita `inert`. */
    render(workspace())
    await openPanelLayer()
    resize(PANEL_LAYER_BELOW + 200)
    expect(screen.queryByRole('dialog', { name: 'Propuesta de HU' })).not.toBeInTheDocument()
    expect(conversation()).not.toHaveAttribute('inert')
    expect(screen.getByRole('button', { name: /el panel/ }).closest('[inert]')).toBeNull()
  })

  it('test_inert_removed_when_panel_prop_goes_away_with_layer_open', async () => {
    /** PA-343: si la pantalla deja de pasar el panel con la capa abierta, la conversación no se queda `inert`. */
    const { rerender } = render(workspace())
    await openPanelLayer()
    rerender(workspace({ panel: undefined }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(conversation()).not.toHaveAttribute('inert')
  })

  it('test_inert_kept_while_close_request_is_refused', async () => {
    /** PA-343: si `onPanelCloseRequest` no deja cerrar (Esc), la capa sigue abierta y la conversación, `inert`. */
    const onPanelCloseRequest = vi.fn(() => false)
    render(workspace({ onPanelCloseRequest }))
    await openPanelLayer()
    await userEvent.keyboard('{Escape}')
    expect(onPanelCloseRequest).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('dialog', { name: 'Propuesta de HU' })).toBeInTheDocument()
    expect(conversation()).toHaveAttribute('inert')
  })

  it('test_inert_removed_and_focus_back_when_close_request_accepted_by_escape', async () => {
    /** PA-343: con la confirmación aceptada, Esc cierra, quita `inert` y el foco vuelve a «Mostrar el panel» (ref). */
    render(workspace({ onPanelCloseRequest: () => true }))
    await openPanelLayer()
    await userEvent.keyboard('{Escape}')
    expect(conversation()).not.toHaveAttribute('inert')
    expect(screen.getByRole('button', { name: 'Mostrar el panel' })).toHaveFocus()
  })

  it('test_foreign_inert_on_conversation_not_removed_on_close', async () => {
    /** PA-343: si la conversación ya era `inert` por otro motivo, cerrar la capa no se lo quita. */
    render(workspace())
    resize(PANEL_LAYER_BELOW - 1)
    conversation().setAttribute('inert', '')
    // El botón está dentro de la conversación inerte: se abre la capa con el clic programático (no con el puntero).
    act(() => screen.getByRole('button', { name: 'Mostrar el panel' }).click())
    expect(screen.getByRole('dialog', { name: 'Propuesta de HU' })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Propuesta de HU' })).not.toBeInTheDocument()
    expect(conversation()).toHaveAttribute('inert')
  })

  it('test_panel_not_inert_while_layer_open', async () => {
    /** PA-343: el panel (la capa) nunca queda dentro de algo `inert`. */
    render(workspace())
    await openPanelLayer()
    expect(screen.getByRole('dialog', { name: 'Propuesta de HU' }).closest('[inert]')).toBeNull()
  })
})
