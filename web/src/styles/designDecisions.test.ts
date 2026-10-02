// Criterios de DESIGN-DECISIONS.md §1 y §2 que no cubre styles.test.ts, y las reglas de seguridad
// de web/README.md («Reglas») comprobadas sobre el código fuente.
import { describe, expect, it } from 'vitest'
import badgeCss from '../components/Badge/Badge.module.css?raw'
import buttonCss from '../components/Button/Button.module.css?raw'
import railCss from '../components/Rail/Rail.module.css?raw'
import statesCss from '../components/States/States.module.css?raw'
import baseCss from './base.css?raw'
import fontsSource from './fonts.ts?raw'
import tokensCss from './tokens.css?raw'

const allCss = import.meta.glob<string>('../**/*.css', { query: '?raw', import: 'default', eager: true })
const allSource = import.meta.glob<string>(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../test/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
})
const indexHtml = Object.values(
  import.meta.glob<string>('../../index.html', { query: '?raw', import: 'default', eager: true }),
)[0]

function declaredTokens(css: string): Map<string, string> {
  const tokens = new Map<string, string>()
  for (const match of css.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    const [, name, value] = match
    if (name && value) tokens.set(name, value.trim())
  }
  return tokens
}

function withoutComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

function ruleBody(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`${escaped}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? ''
}

const tokens = declaredTokens(tokensCss)

describe('decisiones de color (DESIGN-DECISIONS.md §1)', () => {
  it('fija el naranja del foco #FF7932 y el halo #B23E00 (decisión 12)', () => {
    expect(tokens.get('--color-primary')).toBe('#ff7932')
    expect(tokens.get('--color-primary-text')).toBe('#b23e00')
  })

  it('no usa en ningún CSS los valores descartados del lienzo (decisiones 1 y 3)', () => {
    expect(Object.keys(allCss).length).toBeGreaterThan(3)
    for (const [file, css] of Object.entries(allCss)) {
      for (const discarded of ['#fff3e0', '#f0c98a', '#6b3a00', '#14532d']) {
        expect(css.toLowerCase(), `${file} contiene ${discarded}`).not.toContain(discarded)
      }
    }
  })

  it('los módulos CSS usan solo variables, nunca colores hex sueltos', () => {
    const modules = Object.entries(allCss).filter(([file]) => file.endsWith('.module.css'))
    expect(modules.length).toBeGreaterThan(5)
    for (const [file, css] of modules) {
      expect(withoutComments(css), file).not.toMatch(/#[0-9a-f]{3,8}\b/i)
    }
  })

  it('el aviso de consumo sobre el carril navy usa --color-warn-on-dark (decisión 2)', () => {
    expect(ruleBody(railCss, ".usageValue[data-warning]")).toContain('var(--color-warn-on-dark)')
    expect(railCss).not.toMatch(/var\(--color-warn\)/)
  })

  it('el texto verde de los chips usa --color-success-text, no el sólido (decisión 3)', () => {
    expect(ruleBody(badgeCss, '.success')).toContain('color: var(--color-success-text)')
    expect(ruleBody(badgeCss, '.success')).not.toMatch(/color: var\(--color-success\);/)
  })

  it('los pasos hechos son naranja, no verdes (decisión 7)', () => {
    const done = ruleBody(statesCss, ".step[data-state='done'] .mark")
    expect(done).toContain('var(--color-primary)')
    expect(done).not.toContain('success')
  })
})

describe('decisiones de forma y medidas (DESIGN-DECISIONS.md §1)', () => {
  it('el botón usa el radio de 10 px (decisión 4)', () => {
    expect(ruleBody(buttonCss, '.button')).toContain('border-radius: var(--radius-btn)')
  })

  it('las marcas de paso miden --step-mark (22 px, decisión 5)', () => {
    const mark = ruleBody(statesCss, '.mark')
    expect(mark).toContain('width: var(--step-mark)')
    expect(mark).toContain('height: var(--step-mark)')
  })

  it('el avatar del carril tiene forma Q, 40 px y peso 700 (decisión 9)', () => {
    const avatar = ruleBody(railCss, '.avatar')
    expect(avatar).toContain('width: 40px')
    expect(avatar).toContain('height: 40px')
    expect(avatar).toContain('border-radius: var(--radius-q-md)')
    expect(avatar).toContain('font-weight: var(--weight-bold)')
    expect(tokens.get('--weight-bold')).toBe('700')
  })

  it('el carril usa --rail-width (88 px, decisión 10)', () => {
    expect(ruleBody(railCss, '.rail')).toContain('width: var(--rail-width)')
  })

  it.each([
    ['--dur-fast', '0.22s'],
    ['--dur-base', '0.32s'],
    ['--dur-slow', '0.42s'],
  ])('define la duración %s = %s (§2, Movimiento)', (name, value) => {
    expect(tokens.get(name)).toBe(value)
  })

  it('no define ningún espacio fuera de la escala normalizada', () => {
    const allowed = new Set(['4px', '8px', '12px', '16px', '20px', '24px', '32px'])
    const spaces = [...tokens].filter(([name]) => name.startsWith('--space-'))
    expect(spaces.length).toBe(7)
    for (const [name, value] of spaces) expect(allowed.has(value), name).toBe(true)
  })
})

describe('foco visible y «reducir movimiento» (decisiones 12 y 13)', () => {
  it('el foco mantiene un contorno transparente de 2 px para el alto contraste', () => {
    expect(ruleBody(baseCss, ':focus-visible')).toContain('outline: 2px solid transparent')
  })

  it('no anula el foco con outline: none en ningún CSS', () => {
    for (const [file, css] of Object.entries(allCss)) {
      expect(withoutComments(css), file).not.toMatch(/outline:\s*(none|0)\b/)
    }
  })

  it('«reducir movimiento» alcanza también a ::before y ::after (UI.md §8)', () => {
    const media = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$/.exec(baseCss.trim())?.[1] ?? ''
    expect(media).toMatch(/\*,\s*\*::before,\s*\*::after\s*\{/)
    expect(media).toContain('animation: none !important')
    expect(media).toContain('transition: none !important')
  })

  it('ofrece cifras tabulares (decisión 14)', () => {
    expect(ruleBody(baseCss, '.tabular-nums')).toContain('font-variant-numeric: tabular-nums')
  })
})

describe('fuentes (decisión 14 y §2, Tipografía)', () => {
  it('carga DM Sans 400, 500, 600 y 700 desde el paquete local', () => {
    for (const weight of ['400', '500', '600', '700']) {
      expect(fontsSource).toContain(`@fontsource/dm-sans/latin-${weight}.css`)
    }
  })

  it('no pide fuentes a Google Fonts ni usa IBM Plex Mono', () => {
    const everything = [indexHtml ?? '', ...Object.values(allCss), ...Object.values(allSource)].join('\n')
    expect(indexHtml).toBeDefined()
    expect(everything).not.toMatch(/fonts\.(googleapis|gstatic)\.com/)
    expect(everything).not.toMatch(/Plex/i)
  })
})

describe('reglas de seguridad del código fuente (web/README.md)', () => {
  const files = Object.entries(allSource)

  it('analiza el código de producción', () => {
    expect(files.length).toBeGreaterThan(20)
    expect(files.some(([file]) => file.endsWith('.test.ts') || file.endsWith('.test.tsx'))).toBe(false)
  })

  it('no inserta HTML: ni dangerouslySetInnerHTML, ni innerHTML, ni insertAdjacentHTML', () => {
    for (const [file, source] of files) {
      expect(source, file).not.toMatch(/dangerouslySetInnerHTML|\.(inner|outer)HTML\b|insertAdjacentHTML/)
    }
  })

  it('no usa localStorage ni sessionStorage', () => {
    for (const [file, source] of files) {
      expect(source, file).not.toMatch(/localStorage|sessionStorage/)
    }
  })

  it('no contiene correos ni cabeceras Authorization', () => {
    for (const [file, source] of files) {
      expect(source, file).not.toMatch(/[\w.+-]+@[\w-]+\.[a-z]{2,}/i)
      expect(source, file).not.toMatch(/Authorization|Bearer\s/)
    }
  })
})
