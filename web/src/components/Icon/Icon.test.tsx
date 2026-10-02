import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Icon } from './Icon.tsx'
import { ICON_NAMES, ICONS } from './icons.ts'

describe('Icon', () => {
  it.each(ICON_NAMES)('pinta «%s» con su path del lienzo', (name) => {
    const { container } = render(<Icon name={name} />)
    const path = container.querySelector(`svg[data-icon="${name}"] path`)
    expect(path).not.toBeNull()
    expect(path?.getAttribute('d')).toBe(ICONS[name].d)
  })

  it('es decorativo por defecto: oculto a los lectores de pantalla', () => {
    const { container } = render(<Icon name="work" />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg).not.toHaveAttribute('role')
  })

  it('con etiqueta se anuncia como imagen con ese nombre', () => {
    render(<Icon name="logout" label="Cerrar sesión" />)
    const img = screen.getByRole('img', { name: 'Cerrar sesión' })
    expect(img).not.toHaveAttribute('aria-hidden')
  })

  it('usa el trazo del lienzo y hereda el color del texto', () => {
    const { container } = render(<Icon name="history" />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('viewBox', '0 0 24 24')
    expect(svg).toHaveAttribute('stroke', 'currentColor')
    expect(svg).toHaveAttribute('stroke-width', '1.75')
    expect(svg).toHaveAttribute('fill', 'none')
  })

  it('mide 18 px por defecto y acepta otro tamaño', () => {
    const { container, rerender } = render(<Icon name="send" />)
    expect(container.querySelector('svg')).toHaveAttribute('width', '18')
    rerender(<Icon name="send" size={24} />)
    expect(container.querySelector('svg')).toHaveAttribute('height', '24')
  })

  it('«detener» es un cuadrado relleno, no un trazo', () => {
    const { container } = render(<Icon name="stop" />)
    const path = container.querySelector('path')
    expect(path).toHaveAttribute('fill', 'currentColor')
    expect(path).toHaveAttribute('stroke', 'none')
  })

  it('sigue la decisión 6: enviar es la flecha hacia arriba y aviso el triángulo', () => {
    expect(ICONS.send.d).toBe('M12 19V6 M7 11l5-5 5 5')
    expect(ICONS.warning.d).toContain('M12 3l9 16H3z')
    const paths = Object.values(ICONS).map((icon) => icon.d)
    expect(paths).not.toContain('M5 12h13 M13 7l5 5-5 5')
  })
})
