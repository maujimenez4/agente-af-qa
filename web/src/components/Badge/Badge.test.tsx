import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Badge, CaseKindBadge } from './Badge.tsx'

describe('Badge', () => {
  it('es texto, no un control', () => {
    render(<Badge tone="new">Cambiado en v2</Badge>)
    expect(screen.getByText('Cambiado en v2')).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it.each(['neutral', 'cite', 'new', 'success', 'warning', 'error', 'info', 'plain'] as const)(
    'admite el tono %s',
    (tone) => {
      render(<Badge tone={tone}>Etiqueta</Badge>)
      expect(screen.getByText('Etiqueta').closest('[data-tone]')).toHaveAttribute('data-tone', tone)
    },
  )

  it('el icono es decorativo', () => {
    const { container } = render(
      <Badge tone="success" size="md" icon="done">
        Todos los CA cubiertos
      </Badge>,
    )
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })
})

describe('CaseKindBadge', () => {
  it.each([
    ['Positivo', 'success'],
    ['Negativo', 'error'],
    ['Alterno', 'info'],
    ['Excepción', 'warning'],
  ] as const)('%s → tono %s', (kind, tone) => {
    render(<CaseKindBadge kind={kind} />)
    expect(screen.getByText(kind)).toHaveAttribute('data-tone', tone)
  })
})
