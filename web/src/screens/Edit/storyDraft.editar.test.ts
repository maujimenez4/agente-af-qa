// Editar a mano, parte A (T-56, RF-32): borrador de la HU y vuelta a `UserStory`. Datos del ejemplo del contrato
// (DEMO-3, sintéticos).
import { describe, expect, it } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { example } from '../../mocks/examples.ts'
import { fromDraft, LIST_FIELDS, move, newCriterion, newRule, nextId, PRIORITIES, splitLines, toDraft, type UserStory } from './storyDraft.ts'

const story = (): UserStory =>
  example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200').review?.artifact.content as UserStory

describe('storyDraft · ida y vuelta', () => {
  it('fromDraft(toDraft(s), s) devuelve la misma HU del ejemplo del contrato', () => {
    /** Ida y vuelta sin cambios: igual a `review.artifact.content` del ejemplo GET /conversations/{id} 200. */
    const original = story()
    expect(fromDraft(toDraft(original), original)).toEqual(original)
  })

  it('toDraft pone una línea por elemento en los pasos y en las listas', () => {
    /** Listas con una línea por elemento. */
    const draft = toDraft(story())
    expect(draft.criteria[0]?.given).toBe('un préstamo activo con menos de 2 renovaciones\nsin reservas pendientes')
    expect(draft.lists.scope_includes).toBe('Renovación desde la ficha del préstamo\nRenovación desde la app')
    expect(Object.keys(draft.lists).sort()).toEqual([...LIST_FIELDS].sort())
    expect(draft.rules.map((rule) => rule.id)).toEqual(['RN-01', 'RN-02'])
  })

  it('cada criterio y regla del borrador tiene una clave distinta que no se envía', () => {
    /** La clave es solo para React: no aparece en el contenido enviado. */
    const original = story()
    const draft = toDraft(original)
    const keys = [...draft.criteria, ...draft.rules].map((item) => item.key)
    expect(new Set(keys).size).toBe(keys.length)
    const content = fromDraft(draft, original)
    expect(JSON.stringify(content)).not.toMatch(/"key"/)
  })

  it('conserva los campos no editables aunque el borrador cambie', () => {
    /** jira_key, internal_id, sources, changes_from_previous, related_requirements y open_questions se conservan. */
    const original = { ...story(), related_requirements: ['RF-ficticio-1'], open_questions: ['¿Pregunta ficticia?'] }
    const draft = toDraft(original)
    const content = fromDraft({ ...draft, title: 'Título editado' }, original)
    expect(content.title).toBe('Título editado')
    expect(content.jira_key).toBe('DEMO-3')
    expect(content.internal_id).toBe('HU-02')
    expect(content.sources).toEqual(original.sources)
    expect(content.changes_from_previous).toEqual(original.changes_from_previous)
    expect(content.related_requirements).toEqual(['RF-ficticio-1'])
    expect(content.open_questions).toEqual(['¿Pregunta ficticia?'])
  })

  it('las líneas vacías o solo con espacios de pasos y listas no se envían', () => {
    /** Líneas vacías o solo espacios no se envían. */
    const original = story()
    const draft = toDraft(original)
    const criteria = draft.criteria.map((item, index) => (index === 0 ? { ...item, given: 'paso uno\n\n   \npaso dos\n', then: '  \n' } : item))
    const content = fromDraft({ ...draft, criteria, lists: { ...draft.lists, assumptions: '\n \n', constraints: 'a\r\n\r\nb' } }, original)
    expect(content.acceptance_criteria[0]?.given).toEqual(['paso uno', 'paso dos'])
    expect(content.acceptance_criteria[0]?.then).toEqual([])
    expect(content.assumptions).toEqual([])
    expect(content.constraints).toEqual(['a', 'b'])
  })

  it('el orden del borrador manda en el contenido', () => {
    /** Reordenar CA en el borrador cambia el orden enviado. */
    const original = story()
    const draft = toDraft(original)
    const content = fromDraft({ ...draft, criteria: move(draft.criteria, 1, -1) }, original)
    expect(content.acceptance_criteria.map((item) => item.id)).toEqual(['CA-02', 'CA-01'])
  })
})

describe('storyDraft · splitLines', () => {
  it('separa por saltos de línea Unix', () => {
    /** Una línea por elemento. */
    expect(splitLines('uno\ndos')).toEqual(['uno', 'dos'])
  })

  it('quita el \\r de los saltos CRLF', () => {
    /** CRLF: sin el retorno de carro final. */
    expect(splitLines('uno\r\ndos\r\n')).toEqual(['uno', 'dos'])
  })

  it('descarta líneas vacías y las que solo tienen espacios', () => {
    /** Vacías o solo espacios no se envían. */
    expect(splitLines('\n  \n\t\nuno\n\n')).toEqual(['uno'])
  })

  it('sin texto da una lista vacía', () => {
    /** Límite: cadena vacía. */
    expect(splitLines('')).toEqual([])
  })

  it('conserva los espacios interiores y de los extremos de una línea con texto', () => {
    /** Solo se descartan líneas vacías; el texto de una línea no se recorta. */
    expect(splitLines('  con espacios  ')).toEqual(['  con espacios  '])
  })
})

describe('storyDraft · nextId', () => {
  it('CA-01 y CA-02 → CA-03', () => {
    /** Siguiente número libre. */
    expect(nextId('CA', ['CA-01', 'CA-02'])).toBe('CA-03')
  })

  it('CA-9 → CA-10 (ancho mínimo 2)', () => {
    /** Ancho de los existentes, mínimo 2. */
    expect(nextId('CA', ['CA-9'])).toBe('CA-10')
  })

  it('sin ids → CA-01 y RN-01', () => {
    /** Sin ids, el primero. */
    expect(nextId('CA', [])).toBe('CA-01')
    expect(nextId('RN', [])).toBe('RN-01')
  })

  it('respeta el ancho de los existentes (CA-001 → CA-002)', () => {
    /** Mismo ancho que los existentes. */
    expect(nextId('CA', ['CA-001'])).toBe('CA-002')
  })

  it('usa el máximo, no el siguiente al último ni el primer hueco', () => {
    /** Siguiente número libre tras el mayor. */
    expect(nextId('CA', ['CA-05', 'CA-02'])).toBe('CA-06')
  })

  it('ignora los ids de otro prefijo y los que no siguen el patrón', () => {
    /** Solo cuentan los del prefijo pedido con el patrón PREFIJO-número. */
    expect(nextId('RN', ['CA-07', 'RN-01', 'RN-x', 'RN-'])).toBe('RN-02')
    expect(nextId('CA', ['RN-09'])).toBe('CA-01')
  })

  it('newCriterion y newRule nacen vacíos con el siguiente id', () => {
    /** Añadir un CA o una RN. */
    expect(newCriterion(['CA-01', 'CA-02', 'RN-01'])).toMatchObject({ id: 'CA-03', title: '', given: '', when: '', then: '' })
    expect(newRule(['CA-01', 'RN-01', 'RN-02'])).toMatchObject({ id: 'RN-03', description: '' })
    expect(newCriterion([]).key).not.toBe(newCriterion([]).key)
  })
})

describe('storyDraft · move', () => {
  const items = ['a', 'b', 'c'] as const

  it('sube y baja una posición', () => {
    /** Subir/Bajar. */
    expect(move(items, 1, -1)).toEqual(['b', 'a', 'c'])
    expect(move(items, 1, 1)).toEqual(['a', 'c', 'b'])
  })

  it('fuera de rango devuelve la misma lista (copia)', () => {
    /** Fuera de rango, igual. */
    expect(move(items, 0, -1)).toEqual(['a', 'b', 'c'])
    expect(move(items, 2, 1)).toEqual(['a', 'b', 'c'])
    expect(move(items, -1, 1)).toEqual(['a', 'b', 'c'])
    expect(move(items, 5, -1)).toEqual(['a', 'b', 'c'])
    expect(move(items, 0, -1)).not.toBe(items)
  })

  it('no modifica la lista original', () => {
    /** Función pura. */
    const list = ['a', 'b']
    move(list, 0, 1)
    expect(list).toEqual(['a', 'b'])
  })

  it('con un único elemento no hace nada', () => {
    /** Límite: lista de uno. */
    expect(move(['solo'], 0, 1)).toEqual(['solo'])
  })
})

describe('storyDraft · constantes', () => {
  it('PRIORITIES son las del contrato', () => {
    /** Priority de schemas/common.py. */
    expect(PRIORITIES).toEqual(['Must', 'Should', 'Could', "Won't"])
  })

  it('LIST_FIELDS son las 8 listas editables', () => {
    /** «Más campos» con las 8 listas. */
    expect(LIST_FIELDS).toHaveLength(8)
  })
})
