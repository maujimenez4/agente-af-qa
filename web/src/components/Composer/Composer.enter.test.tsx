// Compositor: Intro envía, Mayús + Intro hace un salto de línea y Ctrl/Cmd + Intro siguen enviando. No envía con el
// texto vacío, desactivado, generando ni durante una composición (acentos, IME), ni dos veces seguidas.
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Composer, COMPOSER_KEYS_HINT, type ComposerProps } from './Composer.tsx'

const PLACEHOLDER = 'Pide un cambio a la propuesta'

/** Compositor con su propio texto; `clearOnSubmit` imita a la pantalla que vacía el cuadro al enviar. */
function Controlled({ clearOnSubmit = false, initial = '', ...props }: Partial<ComposerProps> & { onSubmit: () => void; clearOnSubmit?: boolean; initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <Composer
      placeholder={PLACEHOLDER}
      value={value}
      onChange={setValue}
      canSubmit={value.trim().length > 0}
      {...props}
      onSubmit={() => {
        props.onSubmit()
        if (clearOnSubmit) setValue('')
      }}
    />
  )
}

const box = () => screen.getByRole('textbox')

describe('Compositor · Intro envía', () => {
  it('Intro envía el mensaje, igual que la flecha, sin añadir un salto de línea', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} />)
    await userEvent.type(box(), 'Añade un criterio de error{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(box()).toHaveValue('Añade un criterio de error')
  })

  it('Mayús + Intro inserta un salto de línea y no envía', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} />)
    await userEvent.type(box(), 'Uno{Shift>}{Enter}{/Shift}dos')
    expect(box()).toHaveValue('Uno\ndos')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it.each([
    ['Ctrl + Intro', '{Control>}{Enter}{/Control}'],
    ['Cmd + Intro', '{Meta>}{Enter}{/Meta}'],
  ])('%s sigue enviando', async (_, keys) => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} initial="Aclara el alcance" />)
    box().focus()
    await userEvent.keyboard(keys)
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(box()).toHaveValue('Aclara el alcance')
  })

  it.each([
    ['vacío', ''],
    ['solo espacios', '   '],
  ])('con el texto %s, Intro no envía ni añade un salto de línea', async (_, text) => {
    const onSubmit = vi.fn()
    // canSubmit a true (p. ej. con un origen adjunto): aun así, Intro sin texto no envía.
    render(<Controlled onSubmit={onSubmit} initial={text} canSubmit />)
    box().focus()
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
    expect(box()).toHaveValue(text)
  })

  it('desactivado (generando) no envía con Intro', () => {
    const onSubmit = vi.fn()
    render(<Composer placeholder="Espera a la propuesta para pedir cambios" value="Texto" onChange={vi.fn()} onSubmit={onSubmit} canSubmit disabled />)
    fireEvent.keyDown(box(), { key: 'Enter' })
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('con «Detener» (generando o deteniendo) Intro no envía', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} initial="Texto" onStop={vi.fn()} />)
    box().focus()
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('con canSubmit a false no envía aunque haya texto', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} initial="Texto" canSubmit={false} />)
    box().focus()
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it.each([
    ['isComposing', { isComposing: true }],
    ['keyCode 229', { keyCode: 229 }],
  ])('durante una composición de texto (%s) Intro no envía', (_, init) => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} initial="Pedir acentuación" />)
    fireEvent.keyDown(box(), { key: 'Enter', ...init })
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('Intro varias veces seguidas envía una sola vez', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} initial="Revisa INVEST" />)
    box().focus()
    await userEvent.keyboard('{Enter}{Enter}{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('mantener Intro pulsado (repetición) no envía otra vez', () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} initial="Revisa INVEST" />)
    fireEvent.keyDown(box(), { key: 'Enter' })
    fireEvent.keyDown(box(), { key: 'Enter', repeat: true })
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('tras enviar y escribir otro mensaje, Intro vuelve a enviar', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} clearOnSubmit />)
    await userEvent.type(box(), 'Primero{Enter}')
    await userEvent.type(box(), 'Segundo{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(2)
    expect(box()).toHaveValue('')
  })

  it('si el envío falla y el texto sigue, Intro vuelve a enviar pasado un momento', () => {
    vi.useFakeTimers()
    try {
      const onSubmit = vi.fn()
      render(<Controlled onSubmit={onSubmit} initial="Revisa INVEST" />)
      fireEvent.keyDown(box(), { key: 'Enter' })
      fireEvent.keyDown(box(), { key: 'Enter' })
      expect(onSubmit).toHaveBeenCalledTimes(1)
      vi.advanceTimersByTime(1000)
      fireEvent.keyDown(box(), { key: 'Enter' })
      expect(onSubmit).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('un doble clic en la flecha tampoco envía dos veces', async () => {
    const onSubmit = vi.fn()
    render(<Controlled onSubmit={onSubmit} initial="Revisa INVEST" />)
    await userEvent.dblClick(screen.getByRole('button', { name: 'Continuar' }))
    expect(onSubmit).toHaveBeenCalledTimes(1)
  })
})

describe('Compositor · ayuda de teclado', () => {
  it('la ayuda se ve bajo el cuadro y forma parte del nombre accesible', () => {
    render(<Controlled onSubmit={vi.fn()} />)
    expect(screen.getByText(COMPOSER_KEYS_HINT)).toBeVisible()
    expect(box()).toHaveAccessibleName(`${PLACEHOLDER} (Intro para enviar, Mayús+Intro para nueva línea)`)
  })

  it('desactivado no ofrece la ayuda: no se puede enviar', () => {
    render(<Composer placeholder="Espera a la propuesta para pedir cambios" value="" onChange={vi.fn()} onSubmit={vi.fn()} canSubmit={false} disabled />)
    expect(screen.queryByText(COMPOSER_KEYS_HINT)).toBeNull()
    expect(box()).toHaveAccessibleName('Espera a la propuesta para pedir cambios')
  })
})
