import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { changeMarks, fieldLabel, versionSummary, type ImpactAnalysis, type UserStory } from './proposalText.ts'
import { ChangesView, ImpactView, SourcesView, StoryView, VersionSelector } from './ProposalViews.tsx'
import { Tabs } from './Tabs.tsx'

const conversation = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const story = conversation.review?.artifact.content as UserStory
const impact = conversation.review?.impact as ImpactAnalysis

describe('textos de la propuesta', () => {
  it('v1 (sin versión anterior): marca como nuevo un CA sin «before» y como cambiado uno con «before»', () => {
    const marks = changeMarks(story, undefined, [
      { field: 'acceptance_criteria.CA-02', before: null, after: 'x' },
      { field: 'business_rules.RN-01', before: 'a', after: 'b' },
      { field: 'acceptance_criteria.CA-09', before: 'a', after: null },
      { field: 'description', before: 'a', after: 'b' },
    ])
    expect([...marks]).toEqual([
      ['CA-02', 'new'],
      ['RN-01', 'changed'],
    ])
  })

  it('con versión anterior marca solo lo que cambió en esta versión, aunque los diffs acumulen frente a Jira', () => {
    const previous = structuredClone(story)
    const current = structuredClone(story)
    const [first, second] = current.acceptance_criteria
    if (!first || !second) throw new Error('El ejemplo necesita dos CA')
    first.then = [...first.then, 'se avisa por correo']
    current.acceptance_criteria.push({ ...second, id: 'CA-09', title: 'Nuevo en esta versión' })
    // Diffs acumulados frente a Jira: el segundo CA cambió en una versión anterior.
    const diffs = [
      { field: `acceptance_criteria.${second.id}`, before: 'antes', after: 'después' },
      { field: `acceptance_criteria.${first.id}`, before: 'antes', after: 'después' },
    ]
    expect([...changeMarks(current, previous, diffs)]).toEqual([
      [first.id, 'changed'],
      ['CA-09', 'new'],
    ])
  })

  it('una versión igual a la anterior no marca nada', () => {
    expect(changeMarks(story, structuredClone(story), [{ field: 'acceptance_criteria.CA-01', before: 'a', after: 'b' }]).size).toBe(0)
  })

  it.each([
    [0, ''],
    [1, 'Queda 1 pregunta abierta.'],
    [2, 'Quedan 2 preguntas abiertas.'],
  ])('preguntas abiertas: %i → «%s»', (count, text) => {
    const withQuestions = { ...story, open_questions: Array.from({ length: count }, (_, index) => `Pregunta ${index + 1}`) }
    const summary = versionSummary(withQuestions, 1, null)
    if (text) expect(summary).toContain(text)
    else expect(summary).not.toMatch(/pregunta/)
  })

  it('en una HU nueva la pestaña Cambios no compara con Jira', () => {
    render(<ChangesView diffs={[]} againstJira={false} />)
    expect(screen.getByText('Es una HU nueva: no hay una versión en Jira con la que compararla.')).toBeInTheDocument()
  })

  it.each([
    ['acceptance_criteria.CA-02', 'CA-02'],
    ['business_rules.RN-01', 'RN-01'],
    ['description', 'Descripción'],
    ['sources[DOC-01]', 'Fuentes (DOC-01)'],
    ['otro_campo', 'otro_campo'],
  ])('%s → «%s»', (field, label) => {
    expect(fieldLabel(field)).toBe(label)
  })

  it('el resumen de la versión dice qué cambió y a qué afecta, sin LLM', () => {
    expect(versionSummary(story, 2, impact)).toBe(
      'Versión 2 lista. CA-02: se añade el aviso de reservas pendientes (fuente DOC-01). Afecta también a DEMO-2 (comparte la regla de reservas).',
    )
  })
})

describe('StoryView (pestaña Propuesta)', () => {
  it('pinta como/quiero/para, los CA en Gherkin y las RN', () => {
    render(<StoryView story={story} version={2} diffs={impact.diffs} />)
    expect(screen.getByText(/persona socia de la biblioteca/)).toHaveTextContent(
      'Como persona socia de la biblioteca quiero renovar un préstamo activo desde la web o la app para no tener que acudir al mostrador para ampliar el plazo.',
    )
    expect(within(screen.getByRole('list', { name: 'Criterios de aceptación' })).getAllByText(/^CA-\d+$/)).toHaveLength(2)
    const first = screen.getByText('Renovación permitida').closest('li') as HTMLElement
    expect(first).toHaveTextContent('Dado un préstamo activo con menos de 2 renovaciones')
    expect(first).toHaveTextContent('Y sin reservas pendientes')
    expect(first).toHaveTextContent('Cuando la persona socia pulsa «Renovar»')
    expect(first).toHaveTextContent('Entonces el vencimiento se amplía 21 días')
    expect(within(screen.getByRole('list', { name: 'Reglas de negocio' })).getByText('Máximo 2 renovaciones por préstamo.')).toBeInTheDocument()
  })

  it('marca el CA nuevo de esta versión', () => {
    render(<StoryView story={story} version={2} diffs={impact.diffs} />)
    const changed = screen.getByText('Renovación rechazada por reservas').closest('li') as HTMLElement
    expect(within(changed).getByText('Nueva')).toBeInTheDocument()
    expect(changed).toHaveAttribute('data-mark', 'new')
    const unchanged = screen.getByText('Renovación permitida').closest('li') as HTMLElement
    expect(unchanged).not.toHaveAttribute('data-mark')
  })

  it('muestra el texto del LLM como texto, nunca como HTML', () => {
    render(<StoryView story={{ ...story, title: '<img src=x onerror=alert(1)>' }} version={1} diffs={[]} />)
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })
})

describe('ChangesView, ImpactView y SourcesView', () => {
  it('los cambios muestran el campo, lo de antes y lo nuevo', () => {
    render(<ChangesView diffs={[{ field: 'description', before: 'Texto viejo', after: 'Texto nuevo' }, ...impact.diffs]} />)
    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('DescripciónAntes: Texto viejoAhora: Texto nuevo')
    expect(items[1]).toHaveTextContent('CA-02Nuevo')
  })

  it('sin cambios lo dice', () => {
    render(<ChangesView diffs={[]} />)
    expect(screen.getByText('Esta versión no cambia nada frente a Jira.')).toBeInTheDocument()
  })

  it('el impacto lista las HU afectadas con su tipo y las notas de regresión', () => {
    render(<ImpactView impact={impact} />)
    expect(screen.getByText('DEMO-2')).toBeInTheDocument()
    expect(screen.getByText('Regla compartida')).toBeInTheDocument()
    expect(screen.getByText('Revisar el flujo de reservas.')).toBeInTheDocument()
  })

  it('las fuentes citadas llevan su referencia, tipo y extracto', () => {
    render(<SourcesView sources={story.sources} />)
    expect(screen.getByText('DOC-01')).toBeInTheDocument()
    // PA-428: el extracto se pinta como bloques de Markdown (sin «»: puede ser una tabla o una lista).
    expect(screen.getByText('Cada préstamo admite hasta 2 renovaciones.')).toBeInTheDocument()
    expect(screen.getAllByText('Documento')).toHaveLength(1)
  })
})

describe('VersionSelector', () => {
  it('marca la versión abierta y avisa al elegir otra', async () => {
    const onSelect = vi.fn()
    render(<VersionSelector versions={[1, 2]} selected={2} onSelect={onSelect} />)
    expect(screen.getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Versión 1' }))
    expect(onSelect).toHaveBeenCalledWith(1)
  })
})

describe('Tabs', () => {
  function Demo() {
    const [selected, setSelected] = useState<'a' | 'b' | 'c'>('a')
    return (
      <Tabs
        label="Contenido del panel"
        tabs={[
          { id: 'a', label: 'Propuesta' },
          { id: 'b', label: 'Cambios (1)' },
          { id: 'c', label: 'Fuentes (2)' },
        ]}
        selected={selected}
        onSelect={setSelected}
      >
        <p>Contenido {selected}</p>
      </Tabs>
    )
  }

  it('una sola pestaña activa en el orden de Tab y su panel enlazado', () => {
    render(<Demo />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.getAttribute('tabindex'))).toEqual(['0', '-1', '-1'])
    expect(screen.getByRole('tabpanel', { name: 'Propuesta' })).toHaveTextContent('Contenido a')
  })

  it('las flechas, Inicio y Fin cambian de pestaña y mueven el foco', async () => {
    render(<Demo />)
    screen.getByRole('tab', { name: 'Propuesta' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Cambios (1)' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Cambios (1)' })).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Contenido c')
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Propuesta' })).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Fuentes (2)' })).toHaveFocus()
  })
})

describe('detalles de texto', () => {
  it('cada cambio del resumen es una frase con su punto', () => {
    const text = versionSummary({ ...story, changes_from_previous: ['CA-01: debe hablar de la app', 'RN-02: aclarada.'] }, 3, null)
    expect(text).toBe('Versión 3 lista. CA-01: debe hablar de la app. RN-02: aclarada.')
  })

  it('«cambio» en singular y «cambios» en plural', async () => {
    const { changesLabel } = await import('./proposalText.ts')
    expect(changesLabel(1)).toBe('1 cambio frente a Jira')
    expect(changesLabel(0)).toBe('0 cambios frente a Jira')
    expect(changesLabel(3)).toBe('3 cambios frente a Jira')
  })
})
