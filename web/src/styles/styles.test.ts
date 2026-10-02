import { describe, expect, it } from 'vitest'
import { COLOR_GROUPS, LAYOUT, RADII, SPACES } from '../catalog/catalogTokens.ts'
import baseCss from './base.css?raw'
import tokensCss from './tokens.css?raw'

function declaredTokens(css: string): Map<string, string> {
  const tokens = new Map<string, string>()
  for (const match of css.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    const [, name, value] = match
    if (name && value) tokens.set(name, value.trim())
  }
  return tokens
}

const tokens = declaredTokens(tokensCss)

describe('tokens.css', () => {
  it.each([
    ['--color-warn-bg', '#fff8e6'],
    ['--color-warn-border', '#f0d48a'],
    ['--color-warn-text', '#6b4a00'],
    ['--color-success-text', '#1e5e38'],
    ['--color-success', '#1e7a46'],
    ['--color-warn-on-dark', '#ffb48a'],
    ['--color-warn', '#b35c00'],
  ])('fija %s en el valor decidido (%s)', (name, value) => {
    expect(tokens.get(name)).toBe(value)
  })

  it('no conserva los valores descartados del lienzo', () => {
    const values = [...tokens.values()]
    for (const discarded of ['#fff3e0', '#f0c98a', '#6b3a00', '#14532d']) {
      expect(values).not.toContain(discarded)
    }
  })

  it.each([
    ['--radius-btn', '10px'],
    ['--step-mark', '22px'],
    ['--rail-width', '88px'],
    ['--conversations-width', '248px'],
    ['--header-height', '64px'],
    ['--panel-sm', '420px'],
    ['--panel-md', '480px'],
    ['--panel-lg', '540px'],
    ['--chat-max', '640px'],
    ['--hero-max', '760px'],
    ['--radius-q', '16px 16px 4px 16px'],
    ['--ease', 'cubic-bezier(0.2, 0.7, 0.2, 1)'],
    ['--dur-slow', '0.42s'],
  ])('define %s = %s', (name, value) => {
    expect(tokens.get(name)).toBe(value)
  })

  it('usa solo DM Sans como fuente', () => {
    expect(tokens.get('--font-sans')).toBe("'DM Sans', system-ui, sans-serif")
    expect(tokensCss).not.toMatch(/Plex/i)
  })

  it('normaliza el espaciado a 4, 8, 12, 16, 20, 24 y 32 px', () => {
    const spaces = [...tokens].filter(([name]) => name.startsWith('--space-')).map(([, value]) => value)
    expect(spaces).toEqual(['4px', '8px', '12px', '16px', '20px', '24px', '32px'])
  })
})

describe('catálogo de colores', () => {
  const catalogColors = COLOR_GROUPS.flatMap((group) => group.colors)

  it('muestra cada color con el valor que tiene en tokens.css', () => {
    for (const color of catalogColors) {
      expect(tokens.get(color.token), color.token).toBe(color.hex)
    }
  })

  it('incluye todos los colores definidos en tokens.css', () => {
    const shown = new Set(catalogColors.map((color) => color.token))
    const defined = [...tokens.keys()].filter((name) => name.startsWith('--color-'))
    expect(defined.filter((name) => !shown.has(name))).toEqual([])
  })
})

describe('catálogo de forma y medidas', () => {
  it('muestra cada radio con su valor de tokens.css', () => {
    for (const radius of RADII) expect(tokens.get(radius.token), radius.token).toBe(radius.value)
  })

  it('incluye todos los radios definidos', () => {
    const shown = new Set(RADII.map((radius) => radius.token))
    const defined = [...tokens.keys()].filter((name) => name.startsWith('--radius-'))
    expect(defined.filter((name) => !shown.has(name))).toEqual([])
  })

  it('muestra cada medida de layout con su valor', () => {
    for (const item of LAYOUT) expect(tokens.get(item.token), item.token).toBe(item.value)
  })

  it('muestra toda la escala de espaciado', () => {
    expect(SPACES).toEqual([...tokens.keys()].filter((name) => name.startsWith('--space-')))
  })
})

describe('base.css', () => {
  it('pinta el foco visible con contorno naranja y halo #B23E00 (decisión 12)', () => {
    expect(tokens.get('--focus-ring')).toBe('var(--color-primary)')
    expect(tokens.get('--focus-halo')).toBe('var(--color-primary-text)')
    expect(baseCss).toMatch(/:focus-visible\s*\{[^}]*0 0 0 2px var\(--focus-ring\)[^}]*0 0 0 4px var\(--focus-halo\)/)
  })

  it('desactiva animaciones y transiciones con «reducir movimiento»', () => {
    expect(baseCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*animation: none !important;[\s\S]*transition: none !important;/,
    )
  })

  it('ofrece la clase .visually-hidden para textos de lectores de pantalla', () => {
    expect(baseCss).toMatch(/\.visually-hidden\s*\{/)
  })
})
