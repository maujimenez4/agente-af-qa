// PA-347 + PA-334 · huecos de `InlineMarkdown` con `plain` (pulido 2 de T-56): el texto sale tal cual, sin buscar
// marcas y sin interpretar HTML (una etiqueta del modelo es texto), también en un extracto o una Estrategia que
// pasan de INLINE_MAX_TOTAL. Sin reloj. Solo texto ficticio.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { TestSuite } from '../../api/types.ts'
import { StrategyView } from '../Suite/SuiteViews.tsx'
import { InlineMarkdown } from './InlineMarkdown.tsx'
import { INLINE_MAX_TOTAL } from './inlineMarkdown.ts'
import { MarkdownBlocks } from './MarkdownBlocks.tsx'

const TAGGED = 'Riesgo <b>ficticio</b> con <img src="x" onerror="alert(1)"> y **marca**'

/** Repite `line` hasta pasar del tope total. */
function over(line: string): string {
  return Array.from({ length: Math.ceil(INLINE_MAX_TOTAL / (line.length + 1)) + 1 }, () => line).join('\n')
}

describe('InlineMarkdown · plain (PA-347, pulido 2)', () => {
  it('test_plain_does_not_interpret_html_tags', () => {
    /** PA-347 + PA-334: con `plain`, `<b>` y `<img>` salen como texto: no se crean elementos. */
    const { container } = render(
      <p>
        <InlineMarkdown plain text={TAGGED} />
      </p>,
    )
    expect(container.querySelector('b, img, strong, em, code')).toBeNull()
    expect(container.textContent).toBe(TAGGED)
  })

  it('test_plain_keeps_markdown_marks_as_typed', () => {
    /** PA-347: con `plain` no se buscan marcas: `**`, `*` y las comillas invertidas se ven tal cual. */
    const text = '**negrita** *cursiva* `codigo`'
    const { container } = render(
      <p>
        <InlineMarkdown plain text={text} />
      </p>,
    )
    expect(container.querySelector('strong, em, code')).toBeNull()
    expect(container.textContent).toBe(text)
  })

  it('test_without_plain_html_tags_still_text_but_marks_rendered', () => {
    /** PA-334 (control): sin `plain`, `**marca**` es negrita y `<b>` sigue siendo texto, nunca HTML. */
    const { container } = render(
      <p>
        <InlineMarkdown text={TAGGED} />
      </p>,
    )
    expect(container.querySelector('b, img')).toBeNull()
    expect(container.querySelector('strong')).toHaveTextContent('marca')
    expect(container.textContent).toContain('<b>ficticio</b>')
  })

  it('test_plain_empty_text_renders_nothing', () => {
    /** PA-347 (límite): con `plain` y texto vacío no se pinta nada (ni falla). */
    const { container } = render(
      <p>
        <InlineMarkdown plain text="" />
      </p>,
    )
    expect(container.textContent).toBe('')
  })

  it('test_excerpt_over_total_shows_html_tags_as_text', () => {
    /** PA-347: un extracto de más de INLINE_MAX_TOTAL con etiquetas las muestra como texto (sin <b> ni <img>). */
    const text = over(`- ${TAGGED}`)
    expect(text.length).toBeGreaterThan(INLINE_MAX_TOTAL)
    const { container } = render(<MarkdownBlocks text={text} />)
    expect(container.querySelector('b, img, strong')).toBeNull()
    expect(screen.getAllByText(/<b>ficticio<\/b>/).length).toBeGreaterThan(0)
  })

  it('test_excerpt_table_over_total_is_plain_in_header_and_cells', () => {
    /** PA-347: en una tabla de un extracto que pasa del tope, cabecera y celdas salen sin marcas. */
    const rows = over('| **celda** ficticia | `valor` <b>x</b> |')
    const text = `| **Cabecera** | Otra |\n| --- | --- |\n${rows}`
    const { container } = render(<MarkdownBlocks text={text} />)
    expect(container.querySelector('table')).not.toBeNull()
    expect(container.querySelector('strong, code, b')).toBeNull()
    expect(screen.getByRole('columnheader', { name: '**Cabecera**' })).toBeInTheDocument()
  })

  it('test_strategy_over_total_shows_html_tags_as_text', () => {
    /** PA-347: una Estrategia de más de INLINE_MAX_TOTAL con etiquetas las muestra como texto. */
    const strategy = `## Alcance <b>ficticio</b>\n${over(`- ${TAGGED}`)}`
    const suite = { story_jira_key: 'DEMO-3', cases: [], strategy_md: strategy, sources: [] } as unknown as TestSuite
    const { container } = render(<StrategyView suite={suite} />)
    expect(container.querySelector('b, img, strong')).toBeNull()
    expect(screen.getAllByText(/<b>ficticio<\/b>/).length).toBeGreaterThan(1)
  })
})
