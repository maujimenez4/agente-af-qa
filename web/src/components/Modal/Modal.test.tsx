import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Modal } from './Modal.tsx'

function Opener({ onClose = vi.fn() }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Elegir en Jira
      </button>
      {open && (
        <Modal
          title="Elegir en Jira"
          onClose={() => {
            onClose()
            setOpen(false)
          }}
          footer={<button type="button">Usar DEMO-3</button>}
        >
          <input aria-label="Buscar en Jira" data-autofocus />
        </Modal>
      )}
    </>
  )
}

describe('Modal', () => {
  it('es un diálogo modal con su título y pone el foco en el campo marcado', async () => {
    render(<Opener />)
    await userEvent.click(screen.getByRole('button', { name: 'Elegir en Jira' }))
    const dialog = screen.getByRole('dialog', { name: 'Elegir en Jira' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByLabelText('Buscar en Jira')).toHaveFocus()
  })

  it('Esc cierra y el foco vuelve a quien lo abrió', async () => {
    const onClose = vi.fn()
    render(<Opener onClose={onClose} />)
    const opener = screen.getByRole('button', { name: 'Elegir en Jira' })
    await userEvent.click(opener)
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(opener).toHaveFocus()
  })

  it('el botón «Cerrar» también cierra', async () => {
    const onClose = vi.fn()
    render(<Opener onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Elegir en Jira' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('Tab no sale del diálogo', async () => {
    render(<Opener />)
    await userEvent.click(screen.getByRole('button', { name: 'Elegir en Jira' }))
    // El foco empieza en el buscador; el orden es Cerrar (cabecera), buscador y Usar DEMO-3 (pie).
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Usar DEMO-3' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Cerrar' })).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Usar DEMO-3' })).toHaveFocus()
  })
})
