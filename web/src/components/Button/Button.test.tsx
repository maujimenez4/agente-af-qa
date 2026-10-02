import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import buttonCss from './Button.module.css?raw'
import { Button, IconButton } from './Button.tsx'

describe('Button', () => {
  it.each(['primary', 'secondary', 'ghost', 'danger'] as const)('variante %s: botón con su texto', (variant) => {
    render(<Button variant={variant}>Revisar y aprobar</Button>)
    expect(screen.getByRole('button', { name: 'Revisar y aprobar' })).toBeInTheDocument()
  })

  it('es type="button" por defecto, para no enviar formularios sin querer', () => {
    render(<Button>Descartar</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button')
  })

  it('avisa al pulsarlo', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Generar propuesta</Button>)
    await userEvent.click(screen.getByRole('button', { name: 'Generar propuesta' }))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('desactivado no responde', async () => {
    const onClick = vi.fn()
    render(
      <Button variant="primary" disabled onClick={onClick}>
        Aprobar y publicar
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Aprobar y publicar' })
    expect(button).toBeDisabled()
    await userEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('el icono es decorativo y no cambia el nombre accesible', () => {
    const { container } = render(<Button icon="new">Nueva conversación</Button>)
    expect(screen.getByRole('button', { name: 'Nueva conversación' })).toBeInTheDocument()
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('el primario lleva texto navy sobre naranja (contraste del lienzo)', () => {
    expect(buttonCss).toMatch(/\.primary\s*\{[^}]*background: var\(--color-primary\);[^}]*color: var\(--color-text\);/)
  })

  it('al pulsar baja el brillo un 6 % (UI.md §8)', () => {
    expect(buttonCss).toMatch(/:active:not\(:disabled\)\s*\{\s*filter: brightness\(0\.94\);/)
  })
})

describe('IconButton', () => {
  it('tiene nombre accesible aunque no tenga texto', async () => {
    const onClick = vi.fn()
    render(<IconButton icon="close" label="Cerrar" onClick={onClick} />)
    const button = screen.getByRole('button', { name: 'Cerrar' })
    expect(button).toHaveTextContent('')
    await userEvent.click(button)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('puede ser primario (enviar)', () => {
    render(<IconButton icon="send" label="Enviar" variant="primary" />)
    expect(screen.getByRole('button', { name: 'Enviar' })).toBeInTheDocument()
  })
})
