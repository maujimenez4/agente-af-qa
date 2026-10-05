// Bloque A (T-56): el compositor con `onStop` y `stopping` (PA-314, DESIGN-DECISIONS.md §4 bis, Generando: Detener).
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Composer } from './Composer.tsx'

const PLACEHOLDER = 'Espera a la propuesta para pedir cambios'

function renderStop({ stopping = false, disabled = false, canSubmit = true } = {}) {
  const onStop = vi.fn()
  const onSubmit = vi.fn()
  render(
    <Composer
      placeholder={PLACEHOLDER}
      value="Cambio ficticio"
      onChange={vi.fn()}
      onSubmit={onSubmit}
      canSubmit={canSubmit}
      disabled={disabled}
      submitLabel="Enviar"
      onStop={onStop}
      stopping={stopping}
    />,
  )
  return { onStop, onSubmit }
}

describe('Composer con onStop (bloque A)', () => {
  it('«Detener la generación» sustituye al botón de enviar', () => {
    /** §4 bis: mientras genera, el botón de enviar pasa a «Detener la generación». */
    renderStop()
    expect(screen.getByRole('button', { name: 'Detener la generación' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Enviar' })).toBeNull()
  })

  it('el botón de detener no es de envío: pulsarlo no envía el formulario', async () => {
    const { onStop, onSubmit } = renderStop()
    const button = screen.getByRole('button', { name: 'Detener la generación' })
    expect(button).toHaveAttribute('type', 'button')
    await userEvent.click(button)
    expect(onStop).toHaveBeenCalledTimes(1)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('con onStop, Ctrl + Intro no envía aunque haya texto y canSubmit', async () => {
    /** §4 bis (negativo): mientras genera no se puede pedir otro cambio, tampoco con el atajo. */
    const { onSubmit, onStop } = renderStop({ disabled: true })
    const box = screen.getByRole('textbox')
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    expect(onSubmit).not.toHaveBeenCalled()
    expect(onStop).not.toHaveBeenCalled()
  })

  it('con el teclado: Intro y Espacio sobre «Detener la generación» detienen', async () => {
    /** Accesibilidad: *Detener* se usa con el teclado igual que con el ratón. */
    const { onStop, onSubmit } = renderStop({ disabled: true })
    const button = screen.getByRole('button', { name: 'Detener la generación' })
    await userEvent.tab()
    expect(button).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    await userEvent.keyboard(' ')
    expect(onStop).toHaveBeenCalledTimes(2)
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('con stopping el botón dice «Deteniendo la generación…», queda desactivado y no vuelve a detener', async () => {
    /** §4 bis: al pulsarlo queda desactivado con «Deteniendo la generación…». */
    const { onStop } = renderStop({ stopping: true })
    const button = screen.getByRole('button', { name: 'Deteniendo la generación…' })
    expect(button).toBeDisabled()
    await userEvent.click(button)
    expect(onStop).not.toHaveBeenCalled()
  })

  it('stopping sin onStop no cambia el botón de enviar', () => {
    /** Límite: `stopping` solo tiene efecto con `onStop`. */
    render(<Composer placeholder={PLACEHOLDER} value="x" onChange={vi.fn()} onSubmit={vi.fn()} canSubmit submitLabel="Enviar" stopping />)
    expect(screen.getByRole('button', { name: 'Enviar' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /Deten/ })).toBeNull()
  })
})
