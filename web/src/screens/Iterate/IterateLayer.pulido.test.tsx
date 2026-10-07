// Editar a mano en capa (PA-335), pulido final (T-56, PA-344): la pregunta «¿Descartar los cambios?» abierta desde Esc
// o *Cerrar* lleva el foco a «Seguir editando», también después de que la capa enfoque su primer control.
// `ResizeObserver` simulado. Datos sintéticos (DEMO-3, af-demo).
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../../App.tsx'
import { PANEL_LAYER_BELOW } from '../../components/Workspace/Workspace.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

/** Doble de `ResizeObserver` (como en IterateLayer.parteB.test.tsx): el ancho del área lo decide la prueba. */
function fakeResizeObserver() {
  const callbacks = new Set<ResizeObserverCallback>()
  class FakeResizeObserver {
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
  }
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  return {
    resize(width: number) {
      const entry = { contentRect: { width } } as ResizeObserverEntry
      act(() => {
        for (const callback of [...callbacks]) callback([entry], {} as ResizeObserver)
      })
    },
  }
}

let observer: ReturnType<typeof fakeResizeObserver>

beforeEach(() => {
  observer = fakeResizeObserver()
})

afterEach(() => {
  vi.unstubAllGlobals()
  mockServer.resetHandlers()
})

const dialog = () => screen.getByRole('dialog', { name: 'Editar a mano' })
const titleInput = () => within(dialog()).getByLabelText('Título')

async function editInLayerWithChange() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  observer.resize(PANEL_LAYER_BELOW - 1)
  await userEvent.click(screen.getByRole('button', { name: 'Mostrar el panel' }))
  const layer = screen.getByRole('dialog', { name: 'Propuesta de HU' })
  await userEvent.click(within(layer).getByRole('button', { name: 'Editar a mano' }))
  await userEvent.clear(titleInput())
  await userEvent.type(titleInput(), 'Renovar un préstamo ficticio')
}

describe('Editar a mano en capa · foco de la pregunta (PA-344)', () => {
  it('test_escape_moves_focus_to_keep_editing_inside_layer_when_dirty', async () => {
    /** PA-344 + PA-335: Esc con cambios abre la pregunta y el foco va a «Seguir editando», dentro de la capa. */
    await editInLayerWithChange()
    await userEvent.keyboard('{Escape}')
    const keep = within(dialog()).getByRole('button', { name: 'Seguir editando' })
    await waitFor(() => expect(keep).toHaveFocus())
  })

  it('test_close_button_moves_focus_to_keep_editing_when_dirty', async () => {
    /** PA-344 + PA-335: *Cerrar* con cambios abre la pregunta con el foco en «Seguir editando», no en *Cerrar*. */
    await editInLayerWithChange()
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cerrar' }))
    const keep = within(dialog()).getByRole('button', { name: 'Seguir editando' })
    await waitFor(() => expect(keep).toHaveFocus())
    // Enter sobre el botón enfocado vuelve al editor sin perder nada.
    await userEvent.keyboard('{Enter}')
    expect(screen.queryByRole('group', { name: 'Descartar los cambios' })).toBeNull()
    expect(titleInput()).toHaveValue('Renovar un préstamo ficticio')
  })
})
