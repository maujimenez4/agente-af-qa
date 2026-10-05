import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Chip } from './Chip.tsx'

describe('Chip', () => {
  it('una sugerencia es un botón que avisa al pulsarlo', async () => {
    const onClick = vi.fn()
    render(<Chip onClick={onClick}>Añade un criterio de error</Chip>)
    await userEvent.click(screen.getByRole('button', { name: 'Añade un criterio de error' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('un reciente muestra la clave delante del título', () => {
    render(
      <Chip variant="recent" issueKey="DEMO-3">
        Renovar un préstamo
      </Chip>,
    )
    expect(screen.getByRole('button', { name: 'DEMO-3 Renovar un préstamo' })).toBeInTheDocument()
  })

  it('muestra el título como texto, nunca como HTML', () => {
    const { container } = render(<Chip variant="recent">{'<b>DEMO</b>'}</Chip>)
    expect(container.querySelector('b')).toBeNull()
    expect(screen.getByRole('button')).toHaveTextContent('<b>DEMO</b>')
  })
})
