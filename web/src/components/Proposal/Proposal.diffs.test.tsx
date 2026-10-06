// PA-341: la API real nombra los diffs de CA y RN «acceptance_criteria[CA-02]» (core/impact/diff.py, `_diff_by_id`) y el
// ejemplo del contrato, «acceptance_criteria.CA-02». La web acepta los dos: pestaña Cambios, marcas «Nueva» y
// «Cambiado en vN» y el recibo. Datos sintéticos del ejemplo del contrato.
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { receiptOperations } from '../../screens/Receipt/receiptText.ts'
import { changeMarks, fieldLabel, type ImpactAnalysis, type StoryDiff, type UserStory } from './proposalText.ts'
import { ChangesView, StoryView } from './ProposalViews.tsx'

const conversation = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const story = conversation.review?.artifact.content as UserStory

/** Los mismos diffs con el formato del contrato y con el de la API real. */
const FORMATS = {
  'contrato (acceptance_criteria.CA-02)': (base: string, id: string) => `${base}.${id}`,
  'API real (acceptance_criteria[CA-02])': (base: string, id: string) => `${base}[${id}]`,
} as const

describe.each(Object.entries(FORMATS))('formato del %s', (_name, name) => {
  const added: StoryDiff = { field: name('acceptance_criteria', 'CA-02'), before: null, after: 'Renovación rechazada por reservas' }
  const changed: StoryDiff = { field: name('business_rules', 'RN-01'), before: 'Antes ficticio', after: 'Máximo 2 renovaciones por préstamo.' }
  const removed: StoryDiff = { field: name('acceptance_criteria', 'CA-09'), before: 'Quitado ficticio', after: null }

  it('fieldLabel da el id del CA o la RN', () => {
    expect(fieldLabel(added.field)).toBe('CA-02')
    expect(fieldLabel(changed.field)).toBe('RN-01')
  })

  it('las marcas de la v1 salen de los diffs: «Nueva» sin «before», «Cambiado» con él; un quitado no marca', () => {
    expect([...changeMarks(story, undefined, [added, changed, removed])]).toEqual([
      ['CA-02', 'new'],
      ['RN-01', 'changed'],
    ])
  })

  it('en la propuesta, CA-02 lleva «Nueva» y RN-01 «Cambiado en v1»', () => {
    render(<StoryView story={story} version={1} diffs={[added, changed]} />)
    const criterion = screen.getByText('Renovación rechazada por reservas').closest('li') as HTMLElement
    expect(within(criterion).getByText('Nueva')).toBeInTheDocument()
    const rule = within(screen.getByRole('list', { name: 'Reglas de negocio' })).getByText('RN-01').closest('li') as HTMLElement
    expect(within(rule).getByText('Cambiado en v1')).toBeInTheDocument()
  })

  it('la pestaña Cambios nombra cada cambio por su id, nunca con el nombre técnico del campo', () => {
    render(<ChangesView diffs={[added, changed, removed]} />)
    const items = within(screen.getByRole('list', { name: 'Cambios' })).getAllByRole('listitem')
    expect(items.map((item) => item.querySelector('b')?.textContent)).toEqual(['CA-02', 'RN-01', 'CA-09'])
    expect(screen.queryByText(/acceptance_criteria|business_rules/)).toBeNull()
  })

  it('el recibo dice qué cambia con el id', () => {
    const impact: ImpactAnalysis = { diffs: [added, changed, removed], affected: [], regression_notes: [] }
    const [update] = receiptOperations([{ op: 'update_story', key: 'DEMO-3' }], 2, story.title, impact)
    expect(update?.detail).toBe('Cambia: CA-02 (nuevo), RN-01, CA-09 (se quita).')
  })
})

describe('nombres que no son de un CA o una RN', () => {
  it.each([
    ['description', 'Descripción'],
    ['sources[DOC-01]', 'Fuentes (DOC-01)'],
    ['sources.DOC-01', 'Fuentes (DOC-01)'],
  ])('«%s» → «%s»', (field, label) => {
    expect(fieldLabel(field)).toBe(label)
  })

  it.each(['acceptance_criteria[CA-02', 'acceptance_criteria[ca-02]', 'otro_campo[CA-02]', 'acceptance_criteria.CA-02]'])('«%s» no se toma por un CA', (field) => {
    expect(fieldLabel(field)).not.toBe('CA-02')
    expect(changeMarks(story, undefined, [{ field, before: null, after: 'x' }]).size).toBe(0)
  })
})

describe('nombres heredados de Object.prototype', () => {
  it.each(['constructor', 'toString', '__proto__', 'constructor[CA-02]', 'hasOwnProperty.x'])('«%s» se muestra tal cual, como texto', (field) => {
    const label = fieldLabel(field)
    expect(typeof label).toBe('string')
    expect(label.startsWith(field.split(/[.[]/)[0] ?? '')).toBe(true)
  })
})
