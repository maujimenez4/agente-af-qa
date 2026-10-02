import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Card, FlowCard } from './Card.tsx'

describe('Card', () => {
  it('es una región con el nombre de su título', () => {
    render(
      <Card title="Antes de generar" description="Se puede cambiar solo antes de generar.">
        <p>Contenido</p>
      </Card>,
    )
    expect(screen.getByRole('region', { name: 'Antes de generar' })).toHaveTextContent('Contenido')
    expect(screen.getByRole('heading', { level: 2, name: 'Antes de generar' })).toBeInTheDocument()
  })

  it('admite un título de nivel 3', () => {
    render(<Card title="Fuentes" headingLevel={3} />)
    expect(screen.getByRole('heading', { level: 3, name: 'Fuentes' })).toBeInTheDocument()
  })
})

describe('FlowCard', () => {
  const base = {
    label: 'Evolucionar una HU',
    hint: 'Parte de una HU de Jira y propón su nueva versión con el diff.',
    icon: 'work' as const,
  }

  it('se elige con aria-pressed y avisa al pulsarla', async () => {
    const onSelect = vi.fn()
    render(<FlowCard {...base} selected={false} onSelect={onSelect} />)
    const card = screen.getByRole('button', { name: /Evolucionar una HU/ })
    expect(card).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(card)
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('seleccionada: aria-pressed="true"', () => {
    render(<FlowCard {...base} selected onSelect={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Evolucionar una HU/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('desactivada para el rol: aria-disabled, su ayuda y sin efecto al pulsar (UI.md §3)', async () => {
    const onSelect = vi.fn()
    render(
      <FlowCard {...base} selected onSelect={onSelect} disabledHint="Disponible para el rol de analista funcional." />,
    )
    const card = screen.getByRole('button', { name: /Evolucionar una HU/ })
    expect(card).toHaveAttribute('aria-disabled', 'true')
    expect(card).toHaveAttribute('aria-pressed', 'false')
    expect(card).toHaveTextContent('Disponible para el rol de analista funcional.')
    expect(card).not.toHaveTextContent(base.hint)
    await userEvent.click(card)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('desactivada sigue siendo enfocable para poder leer su ayuda', () => {
    render(<FlowCard {...base} selected={false} onSelect={vi.fn()} disabledHint="Disponible para el rol QA." />)
    expect(screen.getByRole('button', { name: /Evolucionar una HU/ })).not.toBeDisabled()
  })
})
