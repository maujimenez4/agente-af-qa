// Pulido final (T-56, revisión general): un `SidePanel` con `bodyLabel` (cuerpo enfocable, p. ej. el informe de calidad)
// dentro del panel en capa (PA-335). Al abrir la capa, el foco sigue yendo a su primer control (*Cerrar*), no al cuerpo;
// el cuerpo es la siguiente parada y Tab no sale de la capa. `ResizeObserver` simulado. Datos sintéticos (DEMO-3).
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PANEL_LAYER_BELOW, SidePanel, Workspace } from './Workspace.tsx'

const BODY_LABEL = 'Contenido del informe de calidad'

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
})

function renderReportInLayer() {
  render(
    <Workspace
      title="Calidad de DEMO-3"
      phase={2}
      panel={
        <SidePanel title="Informe de calidad" subtitle="DEMO-3" bodyLabel={BODY_LABEL}>
          <p>Informe ficticio sin controles.</p>
        </SidePanel>
      }
    >
      <p>Mensajes ficticios</p>
    </Workspace>,
  )
  observer.resize(PANEL_LAYER_BELOW - 1)
}

async function openLayer() {
  await userEvent.click(screen.getByRole('button', { name: 'Mostrar el panel' }))
  return screen.getByRole('dialog', { name: 'Informe de calidad' })
}

describe('SidePanel con bodyLabel en capa (PA-335, pulido)', () => {
  it('test_first_focus_goes_to_close_not_body_when_layer_opens', async () => {
    /** bodyLabel + PA-335: al abrir la capa, el foco va a *Cerrar* (primer control), no al cuerpo enfocable. */
    renderReportInLayer()
    const layer = await openLayer()
    expect(within(layer).getByRole('button', { name: 'Cerrar' })).toHaveFocus()
    expect(within(layer).getByRole('region', { name: BODY_LABEL })).not.toHaveFocus()
  })

  it('test_body_is_next_tab_stop_and_tab_wraps_inside_layer', async () => {
    /** bodyLabel + PA-335: Tab lleva al cuerpo y, desde él (la última parada), vuelve a *Cerrar* sin salir de la capa. */
    renderReportInLayer()
    const layer = await openLayer()
    const body = within(layer).getByRole('region', { name: BODY_LABEL })
    await userEvent.tab()
    expect(body).toHaveFocus()
    await userEvent.tab()
    expect(within(layer).getByRole('button', { name: 'Cerrar' })).toHaveFocus()
  })

  it('test_shift_tab_from_close_goes_to_body_when_layer_open', async () => {
    /** bodyLabel + PA-335 (límite): Mayús+Tab desde *Cerrar* da la vuelta al cuerpo, la última parada de la capa. */
    renderReportInLayer()
    const layer = await openLayer()
    await userEvent.tab({ shift: true })
    expect(within(layer).getByRole('region', { name: BODY_LABEL })).toHaveFocus()
  })
})
