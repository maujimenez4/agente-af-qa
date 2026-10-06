// Memoria (PA-329) · textos puros: secciones del detalle, fechas, nombre del .md y constantes de la lista.
// Solo datos sintéticos (DEMO-9001).
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { MemoryOut } from '../../api/types.ts'
import {
  INDEXED_TEXT,
  MEMORY_LIMIT,
  MEMORY_SEARCH_DEBOUNCE_MS,
  MEMORY_SECTIONS,
  memoryDate,
  memoryFileName,
  memoryShortDate,
  NO_MATCHES,
  NO_MEMORIES,
  sectionItems,
  sectionText,
  type MemoryContent,
} from './memoryText.ts'

const DETAIL = examples['GET /api/v1/memories/{key} 200'] as unknown as MemoryOut

/** El contenido del ejemplo con campos sustituidos, incluso por valores que no cumplen el tipo (la API podría fallar). */
function memoryWith(fields: Record<string, unknown>): MemoryContent {
  return { ...DETAIL.memory, ...fields } as MemoryContent
}

describe('MEMORY_SECTIONS', () => {
  it('test_sections_follow_md_order_with_their_kind', () => {
    /** Las 8 secciones del detalle, en el orden de core/memory: dos de texto y seis listas. */
    expect(MEMORY_SECTIONS.map((section) => [section.title, section.kind, section.field])).toEqual([
      ['Objetivo', 'text', 'objective'],
      ['Alcance', 'text', 'scope'],
      ['Reglas de negocio', 'list', 'business_rules'],
      ['Criterios de aceptación', 'list', 'acceptance_criteria'],
      ['Decisiones', 'list', 'decisions'],
      ['Dependencias', 'list', 'dependencies'],
      ['Cambios', 'list', 'changes'],
      ['Referencias', 'list', 'references'],
    ])
  })

  it('test_sections_fields_exist_in_contract_example', () => {
    /** Cada campo de sección existe en el `memory` del ejemplo del contrato. */
    for (const section of MEMORY_SECTIONS) expect(Object.hasOwn(DETAIL.memory, section.field)).toBe(true)
  })
})

describe('sectionText', () => {
  it('test_section_text_returns_trimmed_text', () => {
    /** Texto con espacios alrededor: se recorta. */
    expect(sectionText(memoryWith({ objective: '  Objetivo ficticio.  \n' }), 'objective')).toBe('Objetivo ficticio.')
  })

  it('test_section_text_returns_example_value_as_is', () => {
    /** El ejemplo del contrato sale tal cual. */
    expect(sectionText(DETAIL.memory, 'scope')).toBe(DETAIL.memory.scope)
  })

  it.each([
    ['vacío', ''],
    ['solo espacios', '   \n\t '],
    ['null', null],
    ['undefined', undefined],
    ['número', 42],
    ['lista', ['a']],
    ['objeto', { text: 'x' }],
  ])('test_section_text_is_empty_when_value_is_%s', (_name, value) => {
    /** Vacío o un valor que no es texto: cadena vacía (la pantalla pinta «Sin datos.»). */
    expect(sectionText(memoryWith({ objective: value }), 'objective')).toBe('')
  })
})

describe('sectionItems', () => {
  it('test_section_items_returns_example_list', () => {
    /** La lista del ejemplo del contrato sale entera y en orden. */
    expect(sectionItems(DETAIL.memory, 'business_rules')).toEqual(DETAIL.memory.business_rules)
  })

  it('test_section_items_drops_empty_and_non_string_items', () => {
    /** Solo textos no vacíos: fuera vacíos, espacios, números, null y objetos; se conserva el orden. */
    const memory = memoryWith({ decisions: ['Primera ficticia.', '', '   ', 7, null, { a: 1 }, 'Segunda ficticia.'] })
    expect(sectionItems(memory, 'decisions')).toEqual(['Primera ficticia.', 'Segunda ficticia.'])
  })

  it.each([
    ['lista vacía', []],
    ['null', null],
    ['undefined', undefined],
    ['texto', 'no es una lista'],
    ['número', 3],
  ])('test_section_items_is_empty_when_value_is_%s', (_name, value) => {
    /** Sin lista (o con algo que no es una lista): vacío (la pantalla pinta «Ninguno.»). */
    expect(sectionItems(memoryWith({ references: value }), 'references')).toEqual([])
  })
})

describe('memoryDate y memoryShortDate', () => {
  it('test_memory_date_is_long_spanish_date_in_utc', () => {
    /** «2 de octubre de 2026» para la fecha del ejemplo. */
    expect(memoryDate('2026-10-02T10:30:00Z')).toBe('2 de octubre de 2026')
  })

  it('test_memory_date_uses_utc_near_midnight', () => {
    /** Se formatea en UTC: las 23:30 Z siguen siendo el mismo día. */
    expect(memoryDate('2026-10-02T23:30:00Z')).toBe('2 de octubre de 2026')
  })

  it('test_memory_short_date_is_day_and_short_month_without_dot', () => {
    /** «2 oct» para la lista, sin punto de abreviatura. */
    expect(memoryShortDate('2026-10-02T10:30:00Z')).toBe('2 oct')
    expect(memoryShortDate('2026-09-15T00:00:00Z')).toBe('15 sept')
  })

  it.each(['no-es-fecha', '', '2026-13-45T99:99:99Z'])('test_memory_dates_are_undefined_when_invalid_%j', (value) => {
    /** Una fecha que no se puede leer no pinta «Invalid Date»: `undefined`. */
    expect(memoryDate(value)).toBeUndefined()
    expect(memoryShortDate(value)).toBeUndefined()
  })
})

describe('memoryFileName y constantes', () => {
  it.each([
    ['DEMO-9001', 'memoria-DEMO-9001.md'],
    ['DEMO-9002', 'memoria-DEMO-9002.md'],
  ])('test_memory_file_name_for_%s', (key, name) => {
    /** El .md se llama `memoria-<CLAVE>.md`. */
    expect(memoryFileName(key)).toBe(name)
  })

  it('test_list_constants_match_contract', () => {
    /** La lista se pide con el máximo del contrato (200) y el buscador espera 300 ms. */
    expect(MEMORY_LIMIT).toBe(200)
    expect(MEMORY_SEARCH_DEBOUNCE_MS).toBe(300)
  })

  it('test_empty_texts_and_indexed_labels', () => {
    /** Textos de lista vacía (con y sin filtros) distintos y los distintivos de indexado. */
    expect(NO_MEMORIES).toMatch(/^Aún no hay memorias/)
    expect(NO_MATCHES).toMatch(/^Ninguna memoria coincide/)
    expect(NO_MEMORIES).not.toBe(NO_MATCHES)
    expect(INDEXED_TEXT.true.label).toBe('Indexada')
    expect(INDEXED_TEXT.false.label).toBe('No indexada')
  })
})
