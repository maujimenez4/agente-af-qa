// Bloque B · SoonButton (DESIGN-DECISIONS.md §4 bis): acción «disponible pronto» enfocable,
// con su descripción y sin efecto (`aria-disabled`, no `disabled`).
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SOON_TEXT, SoonButton } from './index.ts'

describe('SoonButton', () => {
  it('lleva `aria-disabled`, no `disabled`, y es de tipo button', () => {
    render(<SoonButton label="Ver la memoria" />)
    const button = screen.getByRole('button', { name: 'Ver la memoria' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).not.toBeDisabled()
    expect(button).toHaveAttribute('type', 'button')
  })

  it('sin `note` se describe con el texto común; con `note`, con el motivo concreto', () => {
    render(
      <>
        <SoonButton label="Ir al historial" />
        <SoonButton label="Abrir DEMO-3 en Jira" note="Motivo ficticio concreto." />
      </>,
    )
    expect(screen.getByRole('button', { name: 'Ir al historial' })).toHaveAccessibleDescription(SOON_TEXT)
    expect(screen.getByRole('button', { name: 'Abrir DEMO-3 en Jira' })).toHaveAccessibleDescription('Motivo ficticio concreto.')
  })

  it('cada botón apunta a su propia descripción (ids distintos) y la descripción no se ve', () => {
    render(
      <>
        <SoonButton label="Uno" />
        <SoonButton label="Dos" />
      </>,
    )
    const ids = screen.getAllByRole('button').map((button) => button.getAttribute('aria-describedby'))
    expect(new Set(ids).size).toBe(2)
    for (const id of ids) expect(document.getElementById(id ?? '')).toHaveClass('visually-hidden')
  })

  it('se enfoca con Tab y ni el clic, ni Intro, ni Espacio hacen nada (tampoco enviar un formulario)', async () => {
    const onSubmit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault())
    render(
      <form onSubmit={onSubmit}>
        <SoonButton label="Pedir sus pruebas a QA" variant="primary" />
      </form>,
    )
    const button = screen.getByRole('button', { name: 'Pedir sus pruebas a QA' })
    await userEvent.tab()
    expect(button).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    await userEvent.keyboard(' ')
    await userEvent.click(button)
    fireEvent.click(button)
    expect(onSubmit).not.toHaveBeenCalled()
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('button', { name: 'Pedir sus pruebas a QA' })).toBe(button)
  })
})
