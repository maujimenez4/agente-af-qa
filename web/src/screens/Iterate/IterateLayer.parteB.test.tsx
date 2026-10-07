// Editar a mano, parte B (T-56, RF-32) con el panel en capa (PA-335, área de menos de 680 px): Esc, el velo y *Cerrar*
// piden confirmación si hay cambios sin guardar. `ResizeObserver` simulado. Datos sintéticos (DEMO-3, af-demo).
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../../App.tsx'
import { PANEL_LAYER_BELOW } from '../../components/Workspace/Workspace.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const NEW_TITLE = 'Renovar un préstamo ficticio'

/** Doble de `ResizeObserver` (como en Workspace.pa335.test.tsx): el ancho del área lo decide la prueba. */
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

const showButton = () => screen.getByRole('button', { name: 'Mostrar el panel' })
/** El panel del editor, plegado o no (plegado lleva `hidden` y no tiene rol accesible). */
const editorAside = () => screen.getByRole('heading', { level: 2, name: 'Editar a mano', hidden: true }).closest('aside') as HTMLElement
const dialog = () => screen.getByRole('dialog', { name: 'Editar a mano' })
const titleInput = () => within(dialog()).getByLabelText('Título')
const confirmGroup = () => screen.queryByRole('group', { name: 'Descartar los cambios' })

/** Abre DEMO-3, estrecha el área a capa, muestra el panel y abre el editor dentro de la capa. */
async function editInLayer() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  observer.resize(PANEL_LAYER_BELOW - 1)
  await userEvent.click(showButton())
  const layer = screen.getByRole('dialog', { name: 'Propuesta de HU' })
  await userEvent.click(within(layer).getByRole('button', { name: 'Editar a mano' }))
  expect(dialog()).toHaveAttribute('aria-modal', 'true')
  return dialog()
}

async function makeChange() {
  await userEvent.clear(titleInput())
  await userEvent.type(titleInput(), NEW_TITLE)
}

describe('Editar a mano en capa · cambios sin guardar (parte B, PA-335)', () => {
  it('test_editor_in_layer_focuses_first_field_when_opened', async () => {
    /** CA 2 + CA 7: en capa, el editor se abre con el foco en el primer campo, dentro del diálogo. */
    await editInLayer()
    expect(titleInput()).toHaveFocus()
  })

  it('test_escape_asks_confirmation_and_keeps_open_when_dirty', async () => {
    /** CA 7: con cambios, Esc abre «¿Descartar los cambios?» y no pliega el panel. */
    await editInLayer()
    await makeChange()
    await userEvent.keyboard('{Escape}')
    expect(confirmGroup()).toBeInTheDocument()
    expect(editorAside()).not.toHaveAttribute('hidden')
    expect(screen.getByRole('button', { name: 'Ocultar el panel' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('test_backdrop_asks_confirmation_and_keeps_open_when_dirty', async () => {
    /** CA 7: con cambios, un clic en el velo abre la confirmación y no pliega. */
    await editInLayer()
    await makeChange()
    const backdrop = dialog().previousElementSibling as HTMLElement
    expect(backdrop).toHaveAttribute('aria-hidden', 'true')
    await userEvent.click(backdrop)
    expect(confirmGroup()).toBeInTheDocument()
    expect(editorAside()).not.toHaveAttribute('hidden')
  })

  it('test_close_button_asks_confirmation_and_keeps_open_when_dirty', async () => {
    /** CA 7: con cambios, *Cerrar* de la capa abre la confirmación y no pliega. */
    await editInLayer()
    await makeChange()
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cerrar' }))
    expect(confirmGroup()).toBeInTheDocument()
    expect(editorAside()).not.toHaveAttribute('hidden')
  })

  it('test_keep_editing_preserves_changes_when_confirmation_dismissed', async () => {
    /** CA 7: «Seguir editando» cierra la pregunta, el panel sigue abierto y los cambios se conservan. */
    await editInLayer()
    await makeChange()
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    expect(confirmGroup()).toBeNull()
    expect(editorAside()).not.toHaveAttribute('hidden')
    expect(titleInput()).toHaveValue(NEW_TITLE)
    expect(within(dialog()).getByRole('button', { name: 'Guardar la versión 3' })).toBeEnabled()
  })

  it('test_keep_editing_then_cancel_does_not_fold_panel', async () => {
    /** CA 7 (límite): tras «Seguir editando» desde Esc, *Cancelar* + «Sí, descartar» vuelve a la propuesta sin plegar. */
    await editInLayer()
    await makeChange()
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: 'Seguir editando' }))
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cancelar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(screen.getByRole('dialog', { name: 'Propuesta de HU' })).not.toHaveAttribute('hidden')
    expect(screen.queryByRole('heading', { name: 'Editar a mano', hidden: true })).toBeNull()
  })

  it('test_discard_leaves_editor_folds_and_focuses_show_button_when_confirmed', async () => {
    /** CA 7: «Sí, descartar» (desde Esc) sale del editor, pliega el panel y devuelve el foco a «Mostrar el panel». */
    await editInLayer()
    await makeChange()
    await userEvent.keyboard('{Escape}')
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(screen.queryByRole('heading', { name: 'Editar a mano', hidden: true })).toBeNull()
    expect(showButton()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(showButton()).toHaveFocus()
    // Al volver a abrir, la propuesta sigue en la versión 2 (no se guardó nada).
    await userEvent.click(showButton())
    const proposal = screen.getByRole('dialog', { name: 'Propuesta de HU' })
    expect(within(proposal).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('test_discard_from_close_button_folds_and_focuses_show_button', async () => {
    /** CA 7: «Sí, descartar» pedido desde *Cerrar* también pliega y devuelve el foco. */
    await editInLayer()
    await makeChange()
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cerrar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(screen.queryByRole('heading', { name: 'Editar a mano', hidden: true })).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(showButton()).toHaveFocus()
  })

  it('test_escape_folds_without_asking_when_no_changes', async () => {
    /** CA 7: sin cambios, Esc pliega sin preguntar (el editor sigue montado, oculto). */
    await editInLayer()
    await userEvent.keyboard('{Escape}')
    expect(confirmGroup()).toBeNull()
    expect(editorAside()).toHaveAttribute('hidden')
    expect(showButton()).toHaveAttribute('aria-expanded', 'false')
    expect(showButton()).toHaveFocus()
  })

  it('test_focus_leaving_layer_folds_without_asking_and_keeps_changes', async () => {
    /** CA 7 + CA 9: que el foco salga de la capa la pliega sin preguntar; al volver, los cambios siguen ahí. */
    await editInLayer()
    await makeChange()
    const outside = within(screen.getByRole('log', { name: 'Conversación' })).getByRole('button', { name: /Propuesta de HU, versión 2/ })
    act(() => outside.focus())
    expect(confirmGroup()).toBeNull()
    expect(editorAside()).toHaveAttribute('hidden')
    await userEvent.click(showButton())
    expect(titleInput()).toHaveValue(NEW_TITLE)
  })

  it('test_escape_and_close_do_not_fold_when_saving', async () => {
    /** CA 7: con el editor guardando (`busy`), ni Esc ni *Cerrar* pliegan ni preguntan. */
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    mockServer.use(
      http.post('/api/v1/conversations/:id/edit', async () => {
        await gate
        const error = { code: 'not_in_review', message: 'Revisión cerrada (ficticio).', retry_after: null }
        return HttpResponse.json({ error }, { status: 409 })
      }),
    )
    await editInLayer()
    await makeChange()
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Guardar la versión 3' }))
    expect(within(dialog()).getByRole('button', { name: 'Guardando…' })).toBeDisabled()
    act(() => titleInput().focus())
    await userEvent.keyboard('{Escape}')
    expect(editorAside()).not.toHaveAttribute('hidden')
    expect(confirmGroup()).toBeNull()
    await userEvent.click(within(dialog()).getByRole('button', { name: 'Cerrar' }))
    expect(editorAside()).not.toHaveAttribute('hidden')
    expect(confirmGroup()).toBeNull()
    release()
    await waitFor(() => expect(within(dialog()).getByRole('button', { name: 'Guardar la versión 3' })).toBeEnabled())
  })
})
