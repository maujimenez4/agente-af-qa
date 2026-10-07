// PA-335: el panel derecho en capa con el área de trabajo de menos de 680 px y los títulos recortados
// (DESIGN-DECISIONS.md §4 bis, «Plegar el panel derecho»; UI.md §2, «Ventanas estrechas»). Datos sintéticos (DEMO-3).
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PANEL_LAYER_BELOW, SidePanel, Workspace } from './Workspace.tsx'

/** Doble de `ResizeObserver`: el ancho del área lo decide la prueba con `resize`. */
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

function renderWorkspace(panelBody: ReactNode = <p>Contenido ficticio</p>, headerActions?: ReactNode) {
  return render(
    <Workspace
      title="Evolucionar DEMO-3"
      phase={2}
      panel={
        <SidePanel title="Propuesta de HU" headerActions={headerActions}>
          {panelBody}
        </SidePanel>
      }
    >
      <p>Mensajes</p>
    </Workspace>,
  )
}

const panel = () => document.querySelector('aside') as HTMLElement
const showButton = () => screen.getByRole('button', { name: 'Mostrar el panel' })

async function openLayer() {
  await userEvent.click(showButton())
  return screen.getByRole('dialog', { name: 'Propuesta de HU' })
}

let observer: ReturnType<typeof fakeResizeObserver>

beforeEach(() => {
  observer = fakeResizeObserver()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PA-335: panel derecho en capa con menos de 680 px', () => {
  it('test_panel_starts_folded_when_area_narrow: con 679 px el panel empieza plegado', () => {
    renderWorkspace()
    expect(screen.getByRole('button', { name: 'Ocultar el panel' })).toHaveAttribute('aria-expanded', 'true')
    observer.resize(PANEL_LAYER_BELOW - 1)
    expect(showButton()).toHaveAttribute('aria-expanded', 'false')
    expect(panel()).toHaveAttribute('hidden')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('test_panel_opens_as_dialog_with_focus_when_show_clicked: diálogo modal con el foco en su primer control', async () => {
    renderWorkspace(<button type="button">Acción ficticia</button>)
    observer.resize(500)
    const dialog = await openLayer()
    expect(screen.getByRole('button', { name: 'Ocultar el panel' })).toHaveAttribute('aria-expanded', 'true')
    expect(dialog).toBe(panel())
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('tabindex', '-1')
    // «Cerrar» va en la cabecera, antes del cuerpo: es el primer control.
    expect(screen.getByRole('button', { name: 'Cerrar' })).toHaveFocus()
  })

  it('test_focus_goes_to_first_header_action_when_present: el foco entra en el primer control (acciones de la cabecera)', async () => {
    renderWorkspace(<p>Contenido ficticio</p>, <button type="button">Versión 2</button>)
    observer.resize(500)
    await openLayer()
    expect(screen.getByRole('button', { name: 'Versión 2' })).toHaveFocus()
  })

  it('test_close_button_folds_panel_and_returns_focus_when_clicked: «Cerrar» pliega y devuelve el foco', async () => {
    renderWorkspace()
    observer.resize(500)
    await openLayer()
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar' }))
    expect(panel()).toHaveAttribute('hidden')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(showButton()).toHaveAttribute('aria-expanded', 'false')
    expect(showButton()).toHaveFocus()
  })

  it('test_panel_folds_and_focus_returns_when_escape: Esc pliega el panel', async () => {
    renderWorkspace(<button type="button">Acción ficticia</button>)
    observer.resize(500)
    await openLayer()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Acción ficticia' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(panel()).toHaveAttribute('hidden')
    expect(showButton()).toHaveFocus()
  })

  it('test_panel_folds_when_backdrop_clicked: un clic en el velo pliega el panel', async () => {
    renderWorkspace()
    observer.resize(500)
    const dialog = await openLayer()
    const backdrop = dialog.previousElementSibling as HTMLElement
    expect(backdrop).toHaveAttribute('aria-hidden', 'true')
    await userEvent.click(backdrop)
    expect(panel()).toHaveAttribute('hidden')
    expect(showButton()).toHaveAttribute('aria-expanded', 'false')
    expect(showButton()).toHaveFocus()
  })

  it('test_focus_stays_inside_when_tab_and_shift_tab: Tab y Mayús+Tab no salen del panel', async () => {
    renderWorkspace(<button type="button">Acción ficticia</button>)
    observer.resize(500)
    const dialog = await openLayer()
    const close = screen.getByRole('button', { name: 'Cerrar' })
    const action = screen.getByRole('button', { name: 'Acción ficticia' })
    await userEvent.tab()
    expect(action).toHaveFocus()
    await userEvent.tab()
    expect(close).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(action).toHaveFocus()
    for (let step = 0; step < 4; step += 1) {
      await userEvent.tab({ shift: step % 2 === 0 })
      expect(dialog).toContainElement(document.activeElement as HTMLElement)
    }
  })

  it('test_shift_tab_from_panel_itself_goes_to_last_control: desde el propio panel, Mayús+Tab va al último control', async () => {
    renderWorkspace(<button type="button">Acción ficticia</button>)
    observer.resize(500)
    const dialog = await openLayer()
    act(() => dialog.focus())
    await userEvent.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Acción ficticia' })).toHaveFocus()
  })

  it('test_panel_restored_open_when_area_widens: al volver a 680 px el panel vuelve abierto, sin capa ni «Cerrar»', () => {
    renderWorkspace()
    observer.resize(500)
    expect(panel()).toHaveAttribute('hidden')
    observer.resize(PANEL_LAYER_BELOW)
    expect(panel()).not.toHaveAttribute('hidden')
    expect(screen.getByRole('button', { name: 'Ocultar el panel' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cerrar' })).toBeNull()
    expect(panel()).not.toHaveAttribute('tabindex')
  })

  it('test_panel_restored_open_when_widened_with_layer_open: abierta en capa, al ensanchar sigue abierto y sin diálogo', async () => {
    renderWorkspace()
    observer.resize(500)
    await openLayer()
    observer.resize(900)
    expect(panel()).not.toHaveAttribute('hidden')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cerrar' })).toBeNull()
  })

  it('test_panel_restored_folded_when_area_widens: plegado antes de la capa, sigue plegado al ensanchar', async () => {
    renderWorkspace()
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    observer.resize(500)
    await openLayer()
    observer.resize(1000)
    expect(panel()).toHaveAttribute('hidden')
    expect(showButton()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('test_no_layer_when_area_wide: con 680 px o más, ni capa ni «Cerrar»', async () => {
    renderWorkspace()
    observer.resize(PANEL_LAYER_BELOW)
    expect(panel()).not.toHaveAttribute('hidden')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cerrar' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    await userEvent.click(showButton())
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cerrar' })).toBeNull()
  })

  it('test_no_layer_when_resize_observer_missing: sin ResizeObserver nunca hay capa', async () => {
    vi.stubGlobal('ResizeObserver', undefined)
    renderWorkspace()
    expect(panel()).not.toHaveAttribute('hidden')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Cerrar' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Ocultar el panel' }))
    await userEvent.click(showButton())
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('test_focus_kept_in_control_when_rerendering_open_layer: escribir en el panel no lleva el foco al primer control', async () => {
    function Typing() {
      const [text, setText] = useState('')
      return (
        <label>
          Nota ficticia
          <input value={text} onChange={(event) => setText(event.target.value)} />
        </label>
      )
    }
    renderWorkspace(<Typing />)
    observer.resize(500)
    await openLayer()
    const input = screen.getByRole('textbox', { name: 'Nota ficticia' })
    await userEvent.click(input)
    await userEvent.type(input, 'DEMO-3')
    expect(input).toHaveValue('DEMO-3')
    expect(input).toHaveFocus()
  })

  // Regresión (PA-335): Workspace avisaba a la pantalla (`onPanelOpenChange`) durante su render al entrar o salir de la
  // capa y React lo marcaba como error (IterateScreen controla el panel así). Ahora lo hace desde el observador.
  it('test_parent_notified_without_warning_when_controlled: controlado, pasar a capa no da errores de React', () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    function Controlled() {
      const [open, setOpen] = useState(true)
      return (
        <Workspace
          title="Evolucionar DEMO-3"
          phase={2}
          panelOpen={open}
          onPanelOpenChange={setOpen}
          panel={<SidePanel title="Propuesta de HU">Contenido ficticio</SidePanel>}
        >
          <p>Mensajes</p>
        </Workspace>
      )
    }
    render(<Controlled />)
    observer.resize(500)
    expect(panel()).toHaveAttribute('hidden')
    observer.resize(900)
    expect(panel()).not.toHaveAttribute('hidden')
    expect(errors).not.toHaveBeenCalled()
  })
})

describe('PA-335: títulos recortados', () => {
  it('test_h1_has_full_title_when_rendered: el h1 lleva title con el texto completo', () => {
    const title = 'Evolucionar DEMO-3 · Renovar un préstamo desde la app con un título ficticio muy largo'
    render(
      <Workspace title={title} phase={2}>
        <p>Mensajes</p>
      </Workspace>,
    )
    expect(screen.getByRole('heading', { level: 1 })).toHaveAttribute('title', title)
  })

  it('test_header_note_has_full_text_when_no_phase: la nota sin fases lleva title', () => {
    render(
      <Workspace title="Revisar la calidad de af-demo" phaseName="Revisar la calidad · solo lectura">
        <p>Mensajes</p>
      </Workspace>,
    )
    expect(screen.getByText('Revisar la calidad · solo lectura')).toHaveAttribute('title', 'Revisar la calidad · solo lectura')
    expect(screen.getByRole('heading', { level: 1 })).toHaveAttribute('title', 'Revisar la calidad de af-demo')
  })
})
