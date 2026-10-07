// Editar a mano, parte A (T-56, RF-32): validación en el navegador. Errores = lo que el backend rechaza seguro
// (contrato UserStory, schemas/user_story.py, `_edit`, EditIn.feedback); avisos = lo demás. Datos sintéticos (DEMO-3).
import { describe, expect, it } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { example } from '../../mocks/examples.ts'
import type { UserStory } from './storyDraft.ts'
import { checkStory, NOTE_MAX, sameStory, type EditIssue } from './storyValidation.ts'

const original = (): UserStory =>
  example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200').review?.artifact.content as UserStory

/** La HU del ejemplo con un cambio (título) para que no salte `unchanged`, más los cambios pedidos. */
function edited(changes: (story: UserStory) => void = () => {}): UserStory {
  const story = original()
  story.title = 'Renovar un préstamo (editado)'
  changes(story)
  return story
}

const byPath = (issues: EditIssue[], path: string) => issues.find((issue) => issue.path === path)

const CONTRACT = 'Contrato (UserStory)'
const SCHEMA = 'schemas/user_story.py'
const EDIT = 'core/graph/nodes.py · _edit'
const EDIT_IN = 'Contrato (EditIn.feedback)'

describe('checkStory · sin problemas', () => {
  it('una HU válida con un cambio no tiene errores ni avisos', () => {
    /** Línea base: nada bloquea Guardar. */
    expect(checkStory(edited(), original(), '')).toEqual({ errors: [], warnings: [] })
  })
})

describe('checkStory · errores (bloquean Guardar)', () => {
  it.each<[string, (story: UserStory) => void, string, string]>([
    ['título vacío', (s) => (s.title = ''), 'title', CONTRACT],
    ['sin CA', (s) => (s.acceptance_criteria = []), 'criteria', CONTRACT],
    ['id de CA sin el patrón', (s) => (s.acceptance_criteria[0]!.id = 'CA-x'), 'criteria.0.id', CONTRACT],
    ['id de CA en minúsculas', (s) => (s.acceptance_criteria[1]!.id = 'ca-02'), 'criteria.1.id', CONTRACT],
    ['CA sin título', (s) => (s.acceptance_criteria[0]!.title = ''), 'criteria.0.title', SCHEMA],
    ['CA sin given', (s) => (s.acceptance_criteria[0]!.given = []), 'criteria.0.given', SCHEMA],
    ['CA sin when', (s) => (s.acceptance_criteria[1]!.when = []), 'criteria.1.when', SCHEMA],
    ['CA sin then', (s) => (s.acceptance_criteria[1]!.then = []), 'criteria.1.then', SCHEMA],
    ['id de RN sin el patrón', (s) => (s.business_rules[1]!.id = 'RN 02'), 'rules.1.id', CONTRACT],
    ['RN sin descripción', (s) => (s.business_rules[0]!.description = ''), 'rules.0.description', SCHEMA],
    ['id de CA repetido', (s) => (s.acceptance_criteria[1]!.id = 'CA-01'), 'ids', SCHEMA],
    ['id de RN repetido', (s) => (s.business_rules[1]!.id = 'RN-01'), 'ids', SCHEMA],
    ['jira_key cambiada', (s) => (s.jira_key = 'DEMO-99'), 'jira_key', EDIT],
    ['jira_key quitada', (s) => (s.jira_key = null), 'jira_key', EDIT],
    ['internal_id cambiado', (s) => (s.internal_id = 'HU-99'), 'internal_id', EDIT],
  ])('%s → error en «%s»', (_name, change, path, source) => {
    /** Errores con su path y source: lo que el backend rechaza seguro. */
    const check = checkStory(edited(change), original(), '')
    const found = byPath(check.errors, path)
    expect(found, JSON.stringify(check.errors)).toBeDefined()
    expect(found?.source).toBe(source)
    expect(found?.message.length).toBeGreaterThan(0)
    expect(byPath(check.warnings, path)).toBeUndefined()
  })

  it('un id repetido sale una sola vez aunque esté tres veces', () => {
    /** Ids repetidos (CA y RN juntos): un error por id. */
    const story = edited((s) => {
      const ca = s.acceptance_criteria[0]!
      s.acceptance_criteria = [ca, { ...ca }, { ...ca }]
    })
    const repeated = checkStory(story, original(), '').errors.filter((issue) => issue.path === 'ids')
    expect(repeated).toHaveLength(1)
    expect(repeated[0]?.message).toContain('CA-01')
  })

  it('sin cambios → error «unchanged» de _edit', () => {
    /** Sin cambios: unchanged. */
    const check = checkStory(original(), original(), '')
    expect(byPath(check.errors, 'unchanged')).toMatchObject({ source: EDIT })
    expect(check.errors).toHaveLength(1)
  })

  it('solo una nota no cuenta como cambio del contenido', () => {
    /** La nota no es contenido: sigue «unchanged». */
    expect(byPath(checkStory(original(), original(), 'nota ficticia').errors, 'unchanged')).toBeDefined()
  })

  it('una nota de 1000 caracteres es válida y una de 1001 no', () => {
    /** NOTE_MAX = 1000 (EditIn.feedback). */
    expect(NOTE_MAX).toBe(1000)
    expect(byPath(checkStory(edited(), original(), 'n'.repeat(1000)).errors, 'note')).toBeUndefined()
    expect(byPath(checkStory(edited(), original(), 'n'.repeat(1001)).errors, 'note')).toMatchObject({ source: EDIT_IN })
  })

  it('la longitud de la nota se mide tras recortar los espacios', () => {
    /** Nota > 1000 tras trim. */
    const padded = `   ${'n'.repeat(1000)}   `
    expect(byPath(checkStory(edited(), original(), padded).errors, 'note')).toBeUndefined()
  })

  it('un CA válido añadido (CA-03) no da errores', () => {
    /** Añadir un CA bien formado. */
    const story = edited((s) => s.acceptance_criteria.push({ id: 'CA-03', title: 'Caso ficticio', given: ['algo'], when: ['pasa'], then: ['ocurre'] }))
    expect(checkStory(story, original(), '').errors).toEqual([])
  })

  it('sin reglas de negocio no es un error', () => {
    /** business_rules puede estar vacía (contrato). */
    expect(checkStory(edited((s) => (s.business_rules = [])), original(), '').errors).toEqual([])
  })
})

describe('checkStory · avisos (no bloquean)', () => {
  it.each<[string, (story: UserStory) => void, string]>([
    ['role vacío', (s) => (s.role = ''), 'role'],
    ['role solo espacios', (s) => (s.role = '   '), 'role'],
    ['action vacío', (s) => (s.action = ''), 'action'],
    ['benefit vacío', (s) => (s.benefit = '  '), 'benefit'],
    ['description vacía', (s) => (s.description = ''), 'description'],
    ['título con espacio al principio', (s) => (s.title = ' Título ficticio'), 'title'],
    ['título con espacio al final', (s) => (s.title = 'Título ficticio '), 'title'],
  ])('%s → aviso en «%s», no error', (_name, change, path) => {
    /** Avisos con su path y source; NO están en errors. */
    const check = checkStory(edited(change), original(), '')
    const found = byPath(check.warnings, path)
    expect(found).toBeDefined()
    expect(found?.source).toMatch(/^Aviso/)
    expect(byPath(check.errors, path)).toBeUndefined()
    expect(check.errors).toEqual([])
  })

  it('business_goal vacío no da aviso ni error', () => {
    /** Solo role/action/benefit/description avisan. */
    expect(checkStory(edited((s) => (s.business_goal = '')), original(), '')).toEqual({ errors: [], warnings: [] })
  })
})

describe('sameStory', () => {
  it('ignora el orden de las claves', () => {
    /** Comparación estructural sin importar el orden de las claves. */
    const a = original()
    const reversed = Object.fromEntries(Object.entries(a).reverse()) as UserStory
    reversed.acceptance_criteria = a.acceptance_criteria.map((item) => Object.fromEntries(Object.entries(item).reverse()) as typeof item)
    expect(sameStory(a, reversed)).toBe(true)
    expect(byPath(checkStory(reversed, a, '').errors, 'unchanged')).toBeDefined()
  })

  it('sí tiene en cuenta el orden de las listas', () => {
    /** Reordenar CA es un cambio. */
    const a = original()
    const b = original()
    b.acceptance_criteria.reverse()
    expect(sameStory(a, b)).toBe(false)
  })

  it('distingue un cambio en un paso', () => {
    /** Comparación profunda. */
    const b = original()
    b.acceptance_criteria[0]!.then = ['otro resultado ficticio']
    expect(sameStory(original(), b)).toBe(false)
  })
})

describe('título solo con espacios', () => {
  it('no bloquea (el contrato lo admite) pero avisa', async () => {
    const { checkStory } = await import('./storyValidation.ts')
    const examples = (await import('../../api/examples.json')).default
    const original = (examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as { review: { artifact: { content: Parameters<typeof checkStory>[0] } } }).review.artifact.content
    const check = checkStory({ ...original, title: '   ' }, original, '')
    expect(check.errors.some((item) => item.path === 'title')).toBe(false)
    expect(check.warnings).toContainEqual(expect.objectContaining({ path: 'title', message: 'El título solo tiene espacios.' }))
  })
})
