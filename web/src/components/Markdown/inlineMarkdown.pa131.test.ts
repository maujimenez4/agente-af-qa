// PA-131: una línea de más de INLINE_MAX_LINE caracteres se pinta como texto, sin buscar marcas (el análisis crece
// con el cuadrado de la línea y el texto del modelo no es de fiar). Las demás líneas conservan sus marcas.
import { describe, expect, it } from 'vitest'
import { INLINE_MAX_LINE, inlineParts, plainText } from './inlineMarkdown.ts'

const filler = (length: number) => 'a'.repeat(length)

describe('inlineParts · tope por línea (PA-131)', () => {
  it('test_line_at_the_limit_still_gets_its_marks', () => {
    const text = `**negrita** ${filler(INLINE_MAX_LINE - 12)}`
    expect(text).toHaveLength(INLINE_MAX_LINE)
    expect(inlineParts(text)[0]).toEqual({ kind: 'strong', text: 'negrita' })
  })

  it('test_line_over_the_limit_is_plain_text_with_its_marks_as_typed', () => {
    const text = `**negrita** ${filler(INLINE_MAX_LINE)}`
    expect(inlineParts(text)).toEqual([{ kind: 'text', text }])
  })

  it('test_short_lines_around_a_long_one_keep_their_marks', () => {
    const long = `[${filler(INLINE_MAX_LINE)}`
    const parts = inlineParts(`*antes* y \`código\`\n${long}\n**después**`)
    expect(parts).toEqual([
      { kind: 'em', text: 'antes' },
      { kind: 'text', text: ' y ' },
      { kind: 'code', text: 'código' },
      { kind: 'text', text: `\n${long}\n` },
      { kind: 'strong', text: 'después' },
    ])
  })

  it('test_long_text_of_short_lines_is_parsed_as_before', () => {
    // Más de INLINE_MAX_LINE en total, pero en líneas cortas: lo mismo que analizado de una vez.
    const line = `**dato** ${filler(80)}`
    const text = Array.from({ length: 60 }, () => line).join('\n')
    expect(text.length).toBeGreaterThan(INLINE_MAX_LINE)
    const parts = inlineParts(text)
    expect(parts.filter((part) => part.kind === 'strong')).toHaveLength(60)
    expect(plainText(text)).toBe(text.replaceAll('**', ''))
  })

  it('test_worst_case_unclosed_brackets_line_is_not_parsed', () => {
    // Medido antes del tope: 315 ms con 32.000 «[» en una línea. Sin medir tiempos aquí (PA-127): no se analiza.
    const text = '['.repeat(32_000)
    expect(inlineParts(text)).toEqual([{ kind: 'text', text }])
  })
})
