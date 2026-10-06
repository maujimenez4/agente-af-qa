// PA-334: la pestaña Estrategia (QA) mostraba `strategy_md` con el Markdown en bruto («**Alcance**»).
// Subconjunto seguro: negrita, cursiva, código, listas, títulos y tablas como texto; nunca HTML. Datos
// sintéticos.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { TestSuite } from '../../api/types.ts'
import { StrategyView } from '../Suite/SuiteViews.tsx'
import { strategyBlocks } from '../Suite/suiteText.ts'
import { InlineMarkdown } from './InlineMarkdown.tsx'
import { inlineParts, plainText } from './inlineMarkdown.ts'

describe('inlineParts: Markdown en línea seguro (PA-334)', () => {
  it('negrita, cursiva y código salen como trozos; el resto, texto', () => {
    expect(inlineParts('Probar **la renovación** con *datos* y `DEMO-3`.')).toEqual([
      { kind: 'text', text: 'Probar ' },
      { kind: 'strong', text: 'la renovación' },
      { kind: 'text', text: ' con ' },
      { kind: 'em', text: 'datos' },
      { kind: 'text', text: ' y ' },
      { kind: 'code', text: 'DEMO-3' },
      { kind: 'text', text: '.' },
    ])
  })

  it('también __negrita__ y _cursiva_, pero no los guiones bajos dentro de una palabra', () => {
    expect(inlineParts('__Riesgo__ _alto_ en caso_de_prueba')).toEqual([
      { kind: 'strong', text: 'Riesgo' },
      { kind: 'text', text: ' ' },
      { kind: 'em', text: 'alto' },
      { kind: 'text', text: ' en caso_de_prueba' },
    ])
  })

  it('un enlace deja solo su texto (sin URL, ni siquiera javascript:)', () => {
    expect(plainText('Ver [la norma](https://ejemplo.invalid/x) y [esto](javascript:alert(1))')).toBe('Ver la norma y esto')
  })

  it('quita las barras de escape del modelo', () => {
    expect(plainText('Importe \\(ficticio\\): 10\\*2')).toBe('Importe (ficticio): 10*2')
  })

  it('las marcas sin cerrar o con espacios por dentro se quedan como texto', () => {
    expect(plainText('2 * 3 = 6 y **sin cerrar')).toBe('2 * 3 = 6 y **sin cerrar')
    expect(inlineParts('** no es negrita **')).toEqual([{ kind: 'text', text: '** no es negrita **' }])
  })

  it('el HTML del modelo sale como texto: ni elementos ni atributos', () => {
    const { container } = render(<InlineMarkdown text={'**<img src=x onerror=alert(1)>** <script>alert(1)</script>'} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('strong')?.textContent).toBe('<img src=x onerror=alert(1)>')
    expect(container.textContent).toContain('<script>alert(1)</script>')
  })
})

describe('strategyBlocks: tablas y reglas (PA-334)', () => {
  it('una tabla sale como filas de texto y sin la línea separadora; las reglas y «> » se quitan', () => {
    expect(strategyBlocks('| Nivel | Entorno |\n|---|:---:|\n| Sistema | Pruebas |\n---\n> Nota ficticia\n***')).toEqual([
      { kind: 'paragraph', text: 'Nivel · Entorno' },
      { kind: 'paragraph', text: 'Sistema · Pruebas' },
      { kind: 'paragraph', text: 'Nota ficticia' },
    ])
  })

  it('una cita vacía («>» sola) no deja un párrafo en blanco', () => {
    expect(strategyBlocks('Antes\n>\n> \nDespués')).toEqual([
      { kind: 'paragraph', text: 'Antes' },
      { kind: 'paragraph', text: 'Después' },
    ])
  })
})

describe('Estrategia (QA) con el Markdown del modelo (PA-334)', () => {
  // StrategyView solo lee la estrategia y la clave de la HU.
  const suiteWith = (strategy: string) => ({ story_jira_key: 'DEMO-3', strategy_md: strategy }) as TestSuite

  it('no muestra marcas en bruto: negritas y código como elementos, listas y títulos limpios', () => {
    const strategy = [
      '## **Alcance**',
      'La renovación desde la app (**ficticia**).',
      '- **Niveles:** sistema y aceptación',
      '* Entorno `pre` ficticio',
      '1. Primero los *casos* positivos',
    ].join('\n')
    const { container } = render(<StrategyView suite={suiteWith(strategy)} />)
    expect(container.textContent).not.toMatch(/\*\*|`|(^|\s)\*\s/)
    expect(screen.getByRole('heading', { name: 'Alcance' })).toBeInTheDocument()
    expect(container.querySelectorAll('strong').length).toBeGreaterThanOrEqual(3)
    expect(container.querySelector('code')?.textContent).toBe('pre')
    expect(container.querySelector('em')?.textContent).toBe('casos')
    const items = [...container.querySelectorAll('p')].map((item) => item.textContent)
    expect(items).toContain('• Niveles: sistema y aceptación')
  })
})
