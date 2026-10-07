// PA-335: `useLayer` (patrón dialog de WAI-ARIA para la lista y el panel en capa). Datos sintéticos.
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useLayer } from './useLayer.ts'

function Harness({ children, onClose }: { children?: ReactNode; onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  const layerRef = useRef<HTMLDivElement>(null)
  const openerRef = useRef<HTMLButtonElement>(null)
  const onKeyDown = useLayer({
    open,
    layer: layerRef,
    opener: () => openerRef.current,
    onClose: () => {
      onClose?.()
      setOpen(false)
    },
  })
  return (
    <>
      <button ref={openerRef} type="button" onClick={() => setOpen(!open)}>
        Abrir la capa
      </button>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div ref={layerRef} role="dialog" aria-label="Capa ficticia" tabIndex={-1} hidden={!open} onKeyDown={onKeyDown}>
        {children}
      </div>
    </>
  )
}

describe('useLayer', () => {
  it('test_focus_on_layer_itself_when_no_controls: sin controles, el foco va a la propia capa', async () => {
    render(
      <Harness>
        <p>Historial ficticio</p>
      </Harness>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Abrir la capa' }))
    expect(screen.getByRole('dialog', { name: 'Capa ficticia' })).toHaveFocus()
  })

  it('test_tab_stays_on_layer_when_no_controls: sin controles, Tab no sale de la capa', async () => {
    render(
      <Harness>
        <p>Historial ficticio</p>
      </Harness>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Abrir la capa' }))
    await userEvent.tab()
    expect(screen.getByRole('dialog', { name: 'Capa ficticia' })).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(screen.getByRole('dialog', { name: 'Capa ficticia' })).toHaveFocus()
  })

  it('test_hidden_controls_skipped_when_focusing: el foco salta los controles dentro de [hidden]', async () => {
    render(
      <Harness>
        <div hidden>
          <button type="button">Oculto ficticio</button>
        </div>
        <button type="button">Visible ficticio</button>
      </Harness>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Abrir la capa' }))
    expect(screen.getByRole('button', { name: 'Visible ficticio' })).toHaveFocus()
  })

  it('test_focus_not_moved_when_rerendered_while_open: un render con la capa abierta no mueve el foco', async () => {
    render(
      <Harness>
        <button type="button">Primero ficticio</button>
        <input aria-label="Buscador ficticio" />
      </Harness>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Abrir la capa' }))
    const input = screen.getByRole('textbox', { name: 'Buscador ficticio' })
    await userEvent.click(input)
    await userEvent.type(input, 'af-demo')
    expect(input).toHaveFocus()
  })

  it('test_escape_ignored_when_closed: con la capa cerrada, Esc no llama a onClose', async () => {
    const onClose = vi.fn()
    render(
      <Harness onClose={onClose}>
        <button type="button">Primero ficticio</button>
      </Harness>,
    )
    const dialog = screen.getByRole('dialog', { hidden: true })
    dialog.focus()
    await userEvent.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('test_focus_not_stolen_when_mounted_closed: montada cerrada, no mueve el foco al botón', () => {
    render(<Harness />)
    expect(document.body).toHaveFocus()
  })

  it('test_focus_kept_outside_when_closed_from_outside: si el foco ya estaba fuera, al cerrar no lo mueve', async () => {
    render(
      <Harness>
        <button type="button">Primero ficticio</button>
      </Harness>,
    )
    const opener = screen.getByRole('button', { name: 'Abrir la capa' })
    await userEvent.click(opener)
    // El mismo botón cierra la capa: el foco queda en él (ya estaba fuera de la capa).
    await userEvent.click(opener)
    expect(opener).toHaveFocus()
    expect(screen.getByRole('dialog', { hidden: true })).toHaveAttribute('hidden')
  })

  it('test_escape_closes_and_focus_returns_when_open: Esc cierra y el foco vuelve al botón', async () => {
    const onClose = vi.fn()
    render(
      <Harness onClose={onClose}>
        <button type="button">Primero ficticio</button>
      </Harness>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Abrir la capa' }))
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Abrir la capa' })).toHaveFocus()
  })

  it('test_layer_closes_when_focus_leaves: si el foco sale de la capa (clic fuera del velo), la capa se cierra', async () => {
    const onClose = vi.fn()
    render(
      <>
        <Harness onClose={onClose}>
          <button type="button">Dentro</button>
        </Harness>
        <button type="button">Aprobar ficticio</button>
      </>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Abrir la capa' }))
    expect(screen.getByRole('button', { name: 'Dentro' })).toHaveFocus()
    act(() => screen.getByRole('button', { name: 'Aprobar ficticio' }).focus())
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog', { name: 'Capa ficticia' })).toBeNull()
  })

  it('test_focus_on_opener_keeps_layer_open: el foco en su propio botón no la cierra (lo hace su clic)', async () => {
    const onClose = vi.fn()
    render(
      <Harness onClose={onClose}>
        <button type="button">Dentro</button>
      </Harness>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Abrir la capa' }))
    act(() => screen.getByRole('button', { name: 'Abrir la capa' }).focus())
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog', { name: 'Capa ficticia' })).toBeInTheDocument()
  })
})
