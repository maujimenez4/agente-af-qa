// PA-343 · huecos de `inertBehind` en `useLayer` (pulido 2 de T-56): no pisa un `inert` ajeno, no marca lo que
// contiene la propia capa, ignora huecos (`null`/`undefined`), lo quita si la capa se desmonta abierta y antes de
// devolver el foco al botón, también cuando el botón es un `IconButton` con `ref`. Sin reloj. Datos sintéticos.
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { describe, expect, it } from 'vitest'
import { IconButton } from '../components/Button/index.ts'
import { useLayer } from './useLayer.ts'

interface HarnessProps {
  /** El área tapada ya era `inert` antes de abrir (p. ej. la marcó otra capa). */
  preInert?: boolean
  /** Qué devuelve `inertBehind`: el área de detrás, el contenedor de la capa, la propia capa o huecos. */
  behind?: 'area' | 'container' | 'self' | 'holes'
  /** El botón que abre la capa queda dentro del área tapada (como «Mostrar el panel» en Workspace). */
  openerInside?: boolean
}

let focusSeenInert: boolean[] = []

function Harness({ preInert = false, behind = 'area', openerInside = false }: HarnessProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const areaRef = useRef<HTMLElement>(null)
  const layerRef = useRef<HTMLDivElement>(null)
  const openerRef = useRef<HTMLButtonElement>(null)
  const onKeyDown = useLayer({
    open,
    layer: layerRef,
    opener: () => openerRef.current,
    onClose: () => setOpen(false),
    inertBehind: () => {
      if (behind === 'container') return [containerRef.current, areaRef.current]
      if (behind === 'self') return [layerRef.current]
      if (behind === 'holes') return [null, undefined, areaRef.current]
      return [areaRef.current]
    },
  })
  const opener = (
    <IconButton
      ref={openerRef}
      icon="panelRight"
      label="Abrir la capa ficticia"
      // Al recibir el foco, ¿seguía `inert` algo que lo contiene? (no debería: se quita antes de devolverlo).
      onFocus={(event) => focusSeenInert.push(event.currentTarget.closest('[inert]') !== null)}
      onClick={() => setOpen(!open)}
    />
  )
  return (
    <div ref={containerRef} data-testid="contenedor">
      {!openerInside && opener}
      <section ref={areaRef} data-testid="detras" inert={preInert || undefined}>
        {openerInside && opener}
        <button type="button">Acción ficticia de detrás</button>
      </section>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <div ref={layerRef} role="dialog" aria-label="Capa ficticia" tabIndex={-1} hidden={!open} onKeyDown={onKeyDown}>
        <button type="button">Dentro ficticio</button>
      </div>
    </div>
  )
}

const behindArea = () => screen.getByTestId('detras')
const opener = () => screen.getByRole('button', { name: 'Abrir la capa ficticia' })

async function openLayer() {
  await userEvent.click(opener())
  expect(screen.getByRole('button', { name: 'Dentro ficticio' })).toHaveFocus()
}

describe('useLayer · inertBehind (PA-343, pulido 2)', () => {
  it('test_preexisting_inert_kept_after_close', async () => {
    /** PA-343: un `inert` que ya estaba (ajeno a la capa) no se toma como propio: al cerrar sigue ahí. */
    render(<Harness preInert />)
    expect(behindArea()).toHaveAttribute('inert')
    await openLayer()
    expect(behindArea()).toHaveAttribute('inert')
    await userEvent.keyboard('{Escape}')
    expect(document.querySelector('[aria-label="Capa ficticia"]')).toHaveAttribute('hidden')
    expect(behindArea()).toHaveAttribute('inert')
  })

  it('test_container_of_layer_not_marked_but_area_is', async () => {
    /** PA-343: un elemento que contiene la propia capa no se marca (la dejaría inservible); el resto, sí. */
    render(<Harness behind="container" />)
    await openLayer()
    expect(screen.getByTestId('contenedor')).not.toHaveAttribute('inert')
    expect(behindArea()).toHaveAttribute('inert')
    expect(screen.getByRole('button', { name: 'Dentro ficticio' }).closest('[inert]')).toBeNull()
  })

  it('test_layer_itself_not_marked_when_listed', async () => {
    /** PA-343 (límite): si `inertBehind` devuelve la propia capa, no se marca (`contains` de sí misma). */
    render(<Harness behind="self" />)
    await openLayer()
    expect(screen.getByRole('dialog', { name: 'Capa ficticia' })).not.toHaveAttribute('inert')
  })

  it('test_null_and_undefined_entries_ignored', async () => {
    /** PA-343 (límite): los huecos (`null`, `undefined`) se ignoran sin fallar y lo demás se marca. */
    render(<Harness behind="holes" />)
    await openLayer()
    expect(behindArea()).toHaveAttribute('inert')
    await userEvent.keyboard('{Escape}')
    expect(behindArea()).not.toHaveAttribute('inert')
  })

  it('test_inert_removed_when_unmounted_open', async () => {
    /** PA-343: si la capa se desmonta abierta (p. ej. cambia la pantalla), el `inert` que puso no se queda. */
    const area = document.createElement('section')
    document.body.append(area)
    function Outer() {
      const layerRef = useRef<HTMLDivElement>(null)
      useLayer({ open: true, layer: layerRef, opener: () => null, onClose: () => {}, inertBehind: () => [area] })
      return (
        <div ref={layerRef} role="dialog" aria-label="Capa ficticia desmontable" tabIndex={-1}>
          <button type="button">Dentro ficticio</button>
        </div>
      )
    }
    const { unmount } = render(<Outer />)
    expect(area).toHaveAttribute('inert')
    unmount()
    expect(area).not.toHaveAttribute('inert')
    area.remove()
  })

  it('test_inert_removed_before_focus_returns_to_icon_button_opener', async () => {
    /** PA-343: con el botón (`IconButton` con `ref`) dentro de lo tapado, al cerrar el foco le llega ya sin `inert`. */
    focusSeenInert = []
    render(<Harness openerInside />)
    await openLayer()
    expect(behindArea()).toHaveAttribute('inert')
    expect(opener().closest('[inert]')).toBe(behindArea())
    focusSeenInert = []
    await userEvent.keyboard('{Escape}')
    expect(behindArea()).not.toHaveAttribute('inert')
    expect(opener()).toHaveFocus()
    expect(focusSeenInert).toEqual([false])
  })

  it('test_inert_marked_again_on_reopen', async () => {
    /** PA-343: abrir, cerrar y volver a abrir marca de nuevo (no se queda en la primera vez). */
    render(<Harness />)
    await openLayer()
    await userEvent.keyboard('{Escape}')
    expect(behindArea()).not.toHaveAttribute('inert')
    await openLayer()
    expect(behindArea()).toHaveAttribute('inert')
  })

  it('test_icon_button_ref_points_to_native_button', () => {
    /** PA-343 (b): `IconButton` también acepta `ref` y llega al <button> (lo usa `useLayer` como `opener`). */
    let seen: HTMLButtonElement | null = null
    render(<IconButton ref={(element) => void (seen = element)} icon="close" label="Cerrar ficticio" />)
    expect(seen).toBe(screen.getByRole('button', { name: 'Cerrar ficticio' }))
  })

  it('test_no_inert_while_closed', () => {
    /** PA-343: cerrada (también al montar), no se marca nada. */
    render(<Harness />)
    act(() => undefined)
    expect(behindArea()).not.toHaveAttribute('inert')
  })
})
