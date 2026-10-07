// Editar a mano, parte B (T-56): `useLayer` con `onFocusLeave`. Si el foco sale de la capa, se pliega sin preguntar
// (`onFocusLeave`); Esc sigue yendo a `onClose`. Datos sintéticos.
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useLayer } from './useLayer.ts'

function Harness({ onClose, onFocusLeave }: { onClose: () => void; onFocusLeave?: () => void }) {
  const [open, setOpen] = useState(false)
  const layerRef = useRef<HTMLDivElement>(null)
  const openerRef = useRef<HTMLButtonElement>(null)
  const onKeyDown = useLayer({
    open,
    layer: layerRef,
    opener: () => openerRef.current,
    onClose: () => {
      onClose()
      setOpen(false)
    },
    onFocusLeave: onFocusLeave
      ? () => {
          onFocusLeave()
          setOpen(false)
        }
      : undefined,
  })
  return (
    <>
      <button ref={openerRef} type="button" onClick={() => setOpen(!open)}>
        Abrir la capa
      </button>
      <button type="button">Fuera ficticio</button>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div ref={layerRef} role="dialog" aria-label="Capa ficticia" tabIndex={-1} hidden={!open} onKeyDown={onKeyDown}>
        <button type="button">Dentro ficticio</button>
      </div>
    </>
  )
}

const outside = () => screen.getByRole('button', { name: 'Fuera ficticio' })
const layer = () => document.querySelector('[aria-label="Capa ficticia"]') as HTMLElement

async function openLayer() {
  await userEvent.click(screen.getByRole('button', { name: 'Abrir la capa' }))
  expect(screen.getByRole('button', { name: 'Dentro ficticio' })).toHaveFocus()
}

describe('useLayer · onFocusLeave (parte B)', () => {
  it('test_on_focus_leave_called_not_on_close_when_focus_leaves', async () => {
    /** CA 9: con `onFocusLeave`, si el foco sale de la capa se llama a `onFocusLeave` y no a `onClose`. */
    const onClose = vi.fn()
    const onFocusLeave = vi.fn()
    render(<Harness onClose={onClose} onFocusLeave={onFocusLeave} />)
    await openLayer()
    act(() => outside().focus())
    expect(onFocusLeave).toHaveBeenCalledTimes(1)
    expect(onClose).not.toHaveBeenCalled()
    expect(layer()).toHaveAttribute('hidden')
    // El foco se queda donde fue la persona: no vuelve al botón de la capa.
    expect(outside()).toHaveFocus()
  })

  it('test_on_close_called_when_focus_leaves_without_on_focus_leave', async () => {
    /** CA 9: sin `onFocusLeave`, que el foco salga llama a `onClose`. */
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)
    await openLayer()
    act(() => outside().focus())
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(layer()).toHaveAttribute('hidden')
  })

  it('test_escape_calls_on_close_not_on_focus_leave_when_both_given', async () => {
    /** CA 9 (negativa): Esc sigue yendo a `onClose` aunque haya `onFocusLeave`. */
    const onClose = vi.fn()
    const onFocusLeave = vi.fn()
    render(<Harness onClose={onClose} onFocusLeave={onFocusLeave} />)
    await openLayer()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onFocusLeave).not.toHaveBeenCalled()
  })

  it('test_neither_called_when_focus_moves_inside_or_to_opener', async () => {
    /** CA 9 (límite): el foco dentro de la capa o en su botón no cuenta como salir. */
    const onClose = vi.fn()
    const onFocusLeave = vi.fn()
    render(<Harness onClose={onClose} onFocusLeave={onFocusLeave} />)
    await openLayer()
    act(() => layer().focus())
    act(() => screen.getByRole('button', { name: 'Abrir la capa' }).focus())
    expect(onFocusLeave).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('test_neither_called_when_focus_moves_while_closed', async () => {
    /** CA 9 (límite): con la capa cerrada, mover el foco no llama a nada. */
    const onClose = vi.fn()
    const onFocusLeave = vi.fn()
    render(<Harness onClose={onClose} onFocusLeave={onFocusLeave} />)
    act(() => outside().focus())
    expect(onFocusLeave).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })
})
