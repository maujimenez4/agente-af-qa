import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Q_PATH } from '../../design/qPath.ts'
import qCss from './QMark.module.css?raw'
import { LoadingQ } from './LoadingQ.tsx'
import { PhaseQ } from './PhaseQ.tsx'
import { QLogo } from './QLogo.tsx'
import { offsetFor } from './qGeometry.ts'
import { ResultQ } from './ResultQ.tsx'
import { TypingIndicator } from './TypingIndicator.tsx'

function rectOf(container: HTMLElement): SVGRectElement {
  const rect = container.querySelector<SVGRectElement>('clipPath rect')
  if (!rect) throw new Error('No hay rect de recorte')
  return rect
}

function finalOffset(container: HTMLElement): string {
  return rectOf(container).style.getPropertyValue('--q-to')
}

describe('offsetFor', () => {
  it.each([
    [0, 326],
    [1, 244.5],
    [2, 163],
    [3, 81.5],
    [4, 0],
  ])('%i cuartos llenos → desplazamiento %d', (quarters, offset) => {
    expect(offsetFor(quarters)).toBe(offset)
  })

  it('no sale del rango 0–4', () => {
    expect(offsetFor(-1)).toBe(326)
    expect(offsetFor(9)).toBe(0)
  })
})

describe('QMark.module.css (decisión 13)', () => {
  it('el estilo base del rect es el estado final, no la Q llena', () => {
    expect(qCss).toMatch(/\.rect\s*\{\s*transform: translateY\(var\(--q-to\)\);\s*\}/)
  })

  it('la animación de relleno solo define el «desde», así que sin animación queda en --q-to', () => {
    const keyframes = /@keyframes q-fill\s*\{([\s\S]*?)\n\}/.exec(qCss)?.[1] ?? ''
    expect(keyframes).toContain('from')
    expect(keyframes).not.toMatch(/\bto\s*\{/)
  })

  it('usa la curva y duraciones del sistema', () => {
    expect(qCss).toContain('var(--ease)')
  })
})

describe('PhaseQ', () => {
  it.each([
    [1, 'Contexto', '244.5px'],
    [2, 'Generar', '163px'],
    [3, 'Revisión', '81.5px'],
    [4, 'Publicado', '0px'],
  ] as const)('fase %i: nombre accesible «%s» y Q llena hasta su cuarto', (phase, name, offset) => {
    const { container } = render(<PhaseQ phase={phase} />)
    expect(screen.getByRole('img', { name: `Avance: fase ${phase} de 4, ${name}` })).toBeInTheDocument()
    expect(finalOffset(container)).toBe(offset)
  })

  it('en la fase 1 no se ve llena aunque se anulen las animaciones', () => {
    const { container } = render(<PhaseQ phase={1} />)
    expect(finalOffset(container)).not.toBe('0px')
  })

  it('al montarse sube desde la fase anterior en 0,42 s con 0,25 s de retardo', () => {
    const { container } = render(<PhaseQ phase={2} />)
    const rect = rectOf(container)
    expect(rect.dataset.qMotion).toBe('fill')
    expect(rect.style.getPropertyValue('--q-from')).toBe('244.5px')
    expect(rect.style.getPropertyValue('--q-duration')).toBe('0.42s')
    expect(rect.style.getPropertyValue('--q-delay')).toBe('0.25s')
  })

  it('al cambiar de fase anima desde la fase que se veía', () => {
    const { container, rerender } = render(<PhaseQ phase={1} />)
    rerender(<PhaseQ phase={3} />)
    const rect = rectOf(container)
    expect(rect.style.getPropertyValue('--q-from')).toBe('244.5px')
    expect(rect.style.getPropertyValue('--q-to')).toBe('81.5px')
  })

  it('admite otro nombre de fase («Aprobada» en simulación)', () => {
    render(<PhaseQ phase={3} name="Aprobada" />)
    expect(screen.getByRole('img', { name: 'Avance: fase 3 de 4, Aprobada' })).toBeInTheDocument()
  })

  it('cada Q tiene su propio clipPath aunque haya varias en la página', () => {
    const { container } = render(
      <>
        <PhaseQ phase={1} />
        <PhaseQ phase={2} />
      </>,
    )
    const ids = [...container.querySelectorAll('clipPath')].map((clip) => clip.id)
    expect(new Set(ids).size).toBe(2)
    for (const id of ids) {
      expect(id).toMatch(/^q-clip-[a-zA-Z0-9_-]+$/)
      expect(container.querySelector(`path[clip-path="url(#${id})"]`)).not.toBeNull()
    }
  })

  it('pinta la Q con el path aislado en qPath.ts', () => {
    const { container } = render(<PhaseQ phase={1} />)
    const paths = [...container.querySelectorAll('path')].map((path) => path.getAttribute('d'))
    expect(paths).toEqual([Q_PATH, Q_PATH])
  })
})

describe('LoadingQ', () => {
  it('llena tantos cuartos como procesos hechos', () => {
    const { container } = render(<LoadingQ done={2} />)
    expect(finalOffset(container)).toBe('163px')
  })

  it('con «generate» en curso se anima dentro del cuarto siguiente', () => {
    const { container } = render(<LoadingQ done={2} running />)
    const rect = rectOf(container)
    expect(rect.dataset.qMotion).toBe('pulse')
    expect(rect.style.getPropertyValue('--q-from')).toBe('163px')
    expect(rect.style.getPropertyValue('--q-pulse-to')).toBe('81.5px')
    // Sin animación se ven solo los cuartos hechos.
    expect(finalOffset(container)).toBe('163px')
  })

  it('al terminar un proceso rellena el cuarto desde el anterior', () => {
    const { container, rerender } = render(<LoadingQ done={1} />)
    rerender(<LoadingQ done={2} />)
    const rect = rectOf(container)
    expect(rect.dataset.qMotion).toBe('fill')
    expect(rect.style.getPropertyValue('--q-from')).toBe('244.5px')
    expect(rect.style.getPropertyValue('--q-to')).toBe('163px')
  })

  it('llena no se anima', () => {
    const { container } = render(<LoadingQ done={4} running />)
    expect(rectOf(container).dataset.qMotion).toBe('none')
    expect(finalOffset(container)).toBe('0px')
  })

  it('es decorativa salvo que se le dé una etiqueta', () => {
    const { container, rerender } = render(<LoadingQ done={1} />)
    expect(screen.queryByRole('img')).toBeNull()
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    rerender(<LoadingQ done={1} label="Generando la propuesta" />)
    expect(screen.getByRole('img', { name: 'Generando la propuesta' })).toBeInTheDocument()
  })
})

describe('ResultQ', () => {
  it('publicada: se completa de vacía a llena en 1,2 s', () => {
    const { container } = render(<ResultQ outcome="published" />)
    const rect = rectOf(container)
    expect(screen.getByRole('img', { name: 'Publicado en Jira' })).toBeInTheDocument()
    expect(rect.style.getPropertyValue('--q-from')).toBe('326px')
    expect(rect.style.getPropertyValue('--q-to')).toBe('0px')
    expect(rect.style.getPropertyValue('--q-duration')).toBe('1.2s')
  })

  it('parcial: se queda en 65 sin llegar a llenarse', () => {
    const { container } = render(<ResultQ outcome="partial" />)
    expect(screen.getByRole('img', { name: 'Publicada en parte' })).toBeInTheDocument()
    expect(finalOffset(container)).toBe('65px')
  })

  it('simulada: fija en 3/4 y sin animación', () => {
    const { container } = render(<ResultQ outcome="simulated" />)
    expect(screen.getByRole('img', { name: 'Publicación simulada' })).toBeInTheDocument()
    expect(rectOf(container).dataset.qMotion).toBe('none')
    expect(finalOffset(container)).toBe('81.5px')
  })
})

describe('QLogo', () => {
  it('es la Q llena en naranja y decorativa por defecto', () => {
    const { container } = render(<QLogo />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(container.querySelector('path')).toHaveAttribute('fill', 'var(--color-primary)')
    expect(container.querySelector('path')).toHaveAttribute('d', Q_PATH)
  })

  it('con etiqueta se anuncia', () => {
    render(<QLogo label="Agente AF y QA" />)
    expect(screen.getByRole('img', { name: 'Agente AF y QA' })).toBeInTheDocument()
  })
})

describe('TypingIndicator', () => {
  it('anuncia «Escribiendo la respuesta» con una Q de 18 px en bucle', () => {
    const { container } = render(<TypingIndicator />)
    expect(screen.getByRole('status')).toHaveTextContent('Escribiendo la respuesta')
    expect(container.querySelector('svg')).toHaveAttribute('width', '18')
    expect(rectOf(container).dataset.qMotion).toBe('loop')
  })

  it('sin animación se queda a la mitad', () => {
    const { container } = render(<TypingIndicator />)
    expect(finalOffset(container)).toBe('163px')
  })
})
