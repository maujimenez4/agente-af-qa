// T-56: huecos de Proposal.test.tsx sobre UI.md §4.5 (panel de Iterar: marcas «Cambiado en vN» / «Nueva»,
// pestañas vacías) y DESIGN-DECISIONS.md §4 bis. Datos sintéticos del ejemplo del contrato.
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { versionSummary, type ImpactAnalysis, type UserStory } from './proposalText.ts'
import { ChangesView, ImpactView, SourcesView, StoryView } from './ProposalViews.tsx'

const conversation = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const story = conversation.review?.artifact.content as UserStory

describe('marcas de la versión nueva (UI.md §4.5)', () => {
  it('una RN cambiada lleva «Cambiado en vN» con el número de la versión abierta', () => {
    render(<StoryView story={story} version={4} diffs={[{ field: 'business_rules.RN-01', before: 'Antes ficticio', after: 'Ahora ficticio' }]} />)
    const rules = screen.getByRole('list', { name: 'Reglas de negocio' })
    const rule = within(rules).getByText('RN-01').closest('li') as HTMLElement
    expect(within(rule).getByText('Cambiado en v4')).toBeInTheDocument()
    expect(rule).toHaveAttribute('data-mark', 'changed')
  })

  it('un CA cambiado lleva «Cambiado en vN» y no «Nueva»', () => {
    render(<StoryView story={story} version={3} diffs={[{ field: 'acceptance_criteria.CA-01', before: 'Renovación', after: 'Renovación permitida' }]} />)
    const item = screen.getByText('Renovación permitida').closest('li') as HTMLElement
    expect(within(item).getByText('Cambiado en v3')).toBeInTheDocument()
    expect(within(item).queryByText('Nueva')).toBeNull()
  })

  it('un CA eliminado no marca nada en la propuesta y sale como «Eliminado» en Cambios', () => {
    const diffs = [{ field: 'acceptance_criteria.CA-02', before: 'Renovación rechazada por reservas', after: null }]
    render(<StoryView story={story} version={3} diffs={diffs} />)
    expect(screen.queryByText(/Cambiado en v|Nueva/)).toBeNull()
    render(<ChangesView diffs={diffs} />)
    const change = within(screen.getByRole('list', { name: 'Cambios' })).getByRole('listitem')
    expect(change).toHaveTextContent('CA-02Eliminado')
    expect(change).toHaveTextContent('Antes: Renovación rechazada por reservas')
    expect(change).not.toHaveTextContent('Ahora:')
  })
})

describe('pestañas sin contenido', () => {
  it('Impacto sin HU afectadas ni notas dice «No afecta a otras HU.»', () => {
    render(<ImpactView impact={null} />)
    expect(screen.getByText('No afecta a otras HU.')).toBeInTheDocument()
  })

  it('Fuentes sin citas dice «La propuesta no cita fuentes.»', () => {
    render(<SourcesView sources={[]} />)
    expect(screen.getByText('La propuesta no cita fuentes.')).toBeInTheDocument()
  })
})

describe('resumen del asistente (UI.md §4.5)', () => {
  it('nombra varias HU afectadas y las preguntas abiertas', () => {
    const text = versionSummary(
      { ...story, changes_from_previous: [], open_questions: ['¿Pregunta ficticia 1?', '¿Pregunta ficticia 2?'] },
      2,
      {
        diffs: [],
        regression_notes: [],
        affected: [
          { jira_key: 'DEMO-2', kind: 'rule', reason: 'Comparte la regla de reservas' },
          { jira_key: 'DEMO-4', kind: 'story', reason: 'Usa el mismo aviso' },
        ],
      } satisfies ImpactAnalysis,
    )
    expect(text).toBe(
      'Versión 2 lista. Afecta también a DEMO-2 (comparte la regla de reservas), DEMO-4 (usa el mismo aviso). Quedan 2 preguntas abiertas.',
    )
  })
})
