// PA-347: un texto entero de más de INLINE_MAX_TOTAL caracteres (la Estrategia o un extracto) se pinta sin buscar
// marcas, porque cada una de sus líneas pasaría por inlineParts. Por debajo, igual que antes. Solo texto ficticio.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { TestSuite } from '../../api/types.ts'
import { StrategyView } from '../Suite/SuiteViews.tsx'
import { INLINE_MAX_TOTAL } from './inlineMarkdown.ts'
import { MarkdownBlocks } from './MarkdownBlocks.tsx'

const LINE = '- **Riesgo ficticio** con `dato` y relleno ' + 'x'.repeat(60)

/** Tantas líneas como hagan falta para pasar (o no) del tope total, cada una muy por debajo del tope por línea. */
function linesOver(total: number): string {
  return Array.from({ length: Math.ceil(total / (LINE.length + 1)) + 1 }, () => LINE).join('\n')
}

function suiteWith(strategy: string): TestSuite {
  return { story_jira_key: 'DEMO-3', cases: [], strategy_md: strategy, sources: [] } as unknown as TestSuite
}

describe('PA-347 · tope del texto entero', () => {
  it('test_strategy_over_total_is_plain_text_with_marks_as_typed', () => {
    const strategy = linesOver(INLINE_MAX_TOTAL)
    expect(strategy.length).toBeGreaterThan(INLINE_MAX_TOTAL)
    const { container } = render(<StrategyView suite={suiteWith(strategy)} />)
    expect(container.querySelector('strong, code, em')).toBeNull()
    expect(screen.getAllByText(/\*\*Riesgo ficticio\*\* con `dato`/).length).toBeGreaterThan(0)
  })

  it('test_strategy_under_total_keeps_marks', () => {
    const { container } = render(<StrategyView suite={suiteWith(`${LINE}\n${LINE}`)} />)
    expect(container.querySelectorAll('strong')).toHaveLength(2)
    expect(container.querySelectorAll('code')).toHaveLength(2)
  })

  it('test_excerpt_over_total_is_plain_text', () => {
    const { container } = render(<MarkdownBlocks text={linesOver(INLINE_MAX_TOTAL)} />)
    expect(container.querySelector('strong, code, em')).toBeNull()
  })

  it('test_excerpt_exactly_at_total_with_short_lines_keeps_marks', () => {
    // Justo en el tope (no por encima) y en líneas cortas: se buscan las marcas como siempre.
    const lines = Array.from({ length: 150 }, () => LINE)
    const text = lines.join('\n') + 'z'.repeat(INLINE_MAX_TOTAL - lines.join('\n').length)
    expect(text).toHaveLength(INLINE_MAX_TOTAL)
    const { container } = render(<MarkdownBlocks text={text} />)
    expect(container.querySelectorAll('strong').length).toBeGreaterThan(0)
  })
})
