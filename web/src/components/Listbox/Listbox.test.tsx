import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Listbox, type ListboxItem } from './Listbox.tsx'

const ITEMS: ListboxItem[] = [
  { id: 'DEMO-2', itemKey: 'DEMO-2', label: 'Reservar un libro' },
  { id: 'DEMO-3', itemKey: 'DEMO-3', label: 'Renovar un préstamo' },
  { id: 'DEMO-4', itemKey: 'DEMO-4', label: 'Consultar el historial' },
]

function Controlled({ onSelect = vi.fn(), items = ITEMS }: { onSelect?: (id: string) => void; items?: ListboxItem[] }) {
  const [selected, setSelected] = useState<string | undefined>()
  return (
    <Listbox
      label="HU de DEMO-1"
      heading="HU de DEMO-1 (3)"
      items={items}
      selectedId={selected}
      onSelect={(id) => {
        setSelected(id)
        onSelect(id)
      }}
      emptyText="Esta épica no tiene HU."
    />
  )
}

describe('Listbox', () => {
  it('es una lista con su nombre y una opción por elemento', () => {
    render(<Controlled />)
    const list = screen.getByRole('listbox', { name: 'HU de DEMO-1' })
    expect(list).toHaveAttribute('tabindex', '0')
    expect(screen.getAllByRole('option')).toHaveLength(3)
  })

  it('al pulsar una opción la elige', async () => {
    const onSelect = vi.fn()
    render(<Controlled onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('option', { name: 'DEMO-3 Renovar un préstamo' }))
    expect(onSelect).toHaveBeenCalledWith('DEMO-3')
    expect(screen.getByRole('option', { name: 'DEMO-3 Renovar un préstamo' })).toHaveAttribute('aria-selected', 'true')
  })

  it('con el teclado: flechas, Inicio y Fin mueven y eligen, y aria-activedescendant sigue a la activa', async () => {
    const onSelect = vi.fn()
    render(<Controlled onSelect={onSelect} />)
    const list = screen.getByRole('listbox')
    list.focus()
    await userEvent.keyboard('{ArrowDown}')
    expect(onSelect).toHaveBeenLastCalledWith('DEMO-3')
    expect(list.getAttribute('aria-activedescendant')).toBe(screen.getByRole('option', { name: /DEMO-3/ }).id)
    await userEvent.keyboard('{End}')
    expect(onSelect).toHaveBeenLastCalledWith('DEMO-4')
    await userEvent.keyboard('{ArrowDown}')
    expect(onSelect).toHaveBeenLastCalledWith('DEMO-4')
    await userEvent.keyboard('{Home}')
    expect(onSelect).toHaveBeenLastCalledWith('DEMO-2')
  })

  it('sin elementos muestra el texto vacío en lugar de la lista', () => {
    render(<Controlled items={[]} />)
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('Esta épica no tiene HU.')
  })

  it('los textos de la API se pintan como texto', () => {
    render(<Controlled items={[{ id: 'X-1', itemKey: 'X-1', label: '<img src=x onerror=alert(1)>' }]} />)
    expect(screen.getByRole('option')).toHaveTextContent('<img src=x onerror=alert(1)>')
    expect(document.querySelector('[role="option"] img')).toBeNull()
  })
})
