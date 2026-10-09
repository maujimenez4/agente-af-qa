// PA-444: el inicio de sesión muestra el logotipo completo de Qaracter (la Q y las letras «qaracter»), copiado
// tal cual del original del Qaracter Design System (docs/diseno/marca/). La Q sola sigue en el carril. Datos
// sintéticos (af-demo).
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { Q_PATH } from '../../design/qPath.ts'
import { mockDb } from '../../mocks/node.ts'
import { QaracterLogo } from './QaracterLogo.tsx'
// El original, con una ruta relativa a este archivo (Vite la resuelve desde aquí, no desde el directorio de trabajo).
import originalSvg from '../../../../docs/diseno/marca/logo-qaracter-oscuro.svg?raw'

function originalPaths(): { d: string; fill: string }[] {
  return [...originalSvg.matchAll(/<path d="([^"]+)" fill="(#[0-9A-Fa-f]{6})"/g)].map((match) => ({ d: match[1] ?? '', fill: match[2] ?? '' }))
}

describe('QaracterLogo (PA-444)', () => {
  it('reproduce los trazados del original tal cual: la Q (Q_PATH) en --color-primary y las letras en #233441', () => {
    const original = originalPaths()
    expect(original).toHaveLength(9)
    const { container } = render(<QaracterLogo />)
    const svg = container.querySelector('svg')
    expect(svg?.getAttribute('viewBox')).toBe('0 0 1406 331')
    const paths = [...container.querySelectorAll('path')]
    expect(paths.map((path) => path.getAttribute('d'))).toEqual(original.map((path) => path.d))
    expect(paths[0]?.getAttribute('d')).toBe(Q_PATH)
    expect(original[0]?.fill.toUpperCase()).toBe('#FF7932') // el --color-primary de tokens.css
    expect(paths[0]?.getAttribute('fill')).toBe('var(--color-primary)')
    expect(paths.slice(1).map((path) => path.getAttribute('fill'))).toEqual(original.slice(1).map((path) => path.fill))
  })

  it('es una imagen con el nombre accesible «Qaracter» y mantiene la proporción', () => {
    render(<QaracterLogo height={40} />)
    const logo = screen.getByRole('img', { name: 'Qaracter' })
    expect(logo).toHaveAttribute('height', '40')
    expect(logo).toHaveAttribute('width', String(Math.round((40 * 1406) / 331)))
  })

  it('con label={null} es decorativo', () => {
    const { container } = render(<QaracterLogo label={null} />)
    expect(screen.queryByRole('img')).toBeNull()
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('el SVG solo lleva <svg> y <path>: ni <script>, ni <image>, ni enlaces ni href', () => {
    const { container } = render(<QaracterLogo />)
    const svg = container.querySelector('svg')
    if (!svg) throw new Error('Sin SVG')
    const tags = new Set([svg, ...svg.querySelectorAll('*')].map((element) => element.tagName.toLowerCase()))
    expect([...tags].sort()).toEqual(['path', 'svg'])
    for (const element of [svg, ...svg.querySelectorAll('*')]) {
      for (const attribute of element.getAttributeNames()) expect(attribute).not.toMatch(/href|^on/i)
    }
    expect(svg.outerHTML).not.toMatch(/<script|<image|<use|<a[\s>]|<foreignObject|url\(/i)
  })
})

describe('Inicio de sesión y carril con el logotipo (PA-444)', () => {
  it('el inicio de sesión muestra el logotipo completo «Qaracter» encima del título', async () => {
    render(<App />)
    const title = await screen.findByRole('heading', { level: 1, name: 'Hola de nuevo' })
    const logo = screen.getByRole('img', { name: 'Qaracter' })
    expect(logo.querySelectorAll('path')).toHaveLength(9)
    expect(logo.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(logo).toHaveAttribute('height', '30') // PA-478: 30 px en la mitad blanca
  })

  it('el carril sigue con la Q sola (QLogo), no con el logotipo completo', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const rail = await screen.findByRole('navigation')
    const qs = [...rail.querySelectorAll('svg')].filter((svg) => svg.querySelector('path')?.getAttribute('d') === Q_PATH)
    expect(qs.length).toBeGreaterThan(0)
    for (const q of qs) expect(q.querySelectorAll('path')).toHaveLength(1)
    expect(within(rail).queryByRole('img', { name: 'Qaracter' })).toBeNull()
    expect(screen.queryByRole('img', { name: 'Qaracter' })).toBeNull()
  })
})
