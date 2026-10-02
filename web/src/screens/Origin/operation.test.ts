import { describe, expect, it } from 'vitest'
import type { IssueSummary, SourcePreview, StartOption } from '../../api/types.ts'
import { createBody, fixedTitle, operationFromIssue, operationFromOption, sourceDetail } from './operation.ts'

const STORY: IssueSummary = { key: 'DEMO-3', summary: 'Renovar un préstamo', issue_type: 'Story', status: 'Abierta' }
const EPIC: IssueSummary = { key: 'DEMO-1', summary: 'Préstamo digital', issue_type: 'Epic', status: 'Abierta' }

describe('operación desde una opción del arranque guiado', () => {
  it.each([
    ['evolve', 'evolve'],
    ['tests', 'tests'],
    ['new_story_in_epic', 'need'],
    ['new_need', 'need'],
  ] as const)('%s → flujo %s (el contrato admite need con need o epic; evolve y tests con story)', (kind, flow) => {
    const option: StartOption = { kind, label: 'x', origin: { kind: 'story', key: 'DEMO-3' } }
    expect(operationFromOption(option, 'DEMO').flow).toBe(flow)
  })

  it('completa el proyecto del origen si la opción no lo trae', () => {
    const option: StartOption = { kind: 'new_need', label: 'Crear HU nueva', origin: { kind: 'need', text: 'Necesidad ficticia' } }
    expect(operationFromOption(option, 'DEMO').origin).toEqual({ kind: 'need', key: null, text: 'Necesidad ficticia', project: 'DEMO' })
  })
})

describe('operación desde un origen elegido en Jira', () => {
  it('una HU se evoluciona', () => {
    expect(operationFromIssue(STORY, 'DEMO', 'need', '')).toMatchObject({
      kind: 'evolve',
      flow: 'evolve',
      origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' },
      label: 'Evolucionar DEMO-3',
    })
  })

  it('una épica crea una HU nueva dentro de ella, con el texto escrito', () => {
    expect(operationFromIssue(EPIC, 'DEMO', 'evolve', 'Renovación en la app')).toMatchObject({
      kind: 'new_story_in_epic',
      flow: 'need',
      origin: { kind: 'epic', key: 'DEMO-1', project: 'DEMO', text: 'Renovación en la app' },
    })
  })

  it('en el flujo de QA, una HU prepara su suite', () => {
    expect(operationFromIssue(STORY, 'DEMO', 'tests', '')).toMatchObject({ kind: 'tests', flow: 'tests', label: 'Preparar pruebas de DEMO-3' })
  })
})

describe('textos de la operación fijada (UI.md §4.3 y §6.1)', () => {
  it.each([
    [operationFromIssue(STORY, 'DEMO', 'evolve', ''), 'Operación fijada: evolucionar DEMO-3'],
    [operationFromIssue(STORY, 'DEMO', 'tests', ''), 'Operación fijada: suite de pruebas de DEMO-3'],
    [operationFromIssue(EPIC, 'DEMO', 'need', ''), 'Operación fijada: HU nueva en la épica DEMO-1'],
  ])('%#: «%s»', (operation, title) => {
    expect(fixedTitle(operation)).toBe(title)
  })
})

describe('cuerpo de POST /conversations', () => {
  it('al evolucionar, las restricciones van como primer feedback', () => {
    const body = createBody(operationFromIssue(STORY, 'DEMO', 'evolve', ''), '  Mismas reglas que en la web.  ', ['DOC-20'])
    expect(body).toEqual({
      flow: 'evolve',
      origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' },
      excluded_sources: ['DOC-20'],
      feedback: ['Mismas reglas que en la web.'],
    })
  })

  it('en una necesidad nueva, las restricciones se añaden al texto', () => {
    const option: StartOption = { kind: 'new_need', label: 'Crear HU nueva', origin: { kind: 'need', text: 'Renovar desde la app', project: 'DEMO' } }
    const body = createBody(operationFromOption(option, 'DEMO'), 'Solo socios con carné', [])
    expect(body.feedback).toEqual([])
    expect(body.origin.text).toBe('Renovar desde la app\n\nRestricciones: Solo socios con carné')
  })

  it('sin restricciones no añade nada', () => {
    expect(createBody(operationFromIssue(STORY, 'DEMO', 'evolve', ''), '   ', []).feedback).toEqual([])
  })
})

describe('línea de cada fuente', () => {
  const source = (overrides: Partial<SourcePreview>): SourcePreview => ({ ref: 'DOC-01', kind: 'rag', title: 'x', category: 'politicas', required: false, ...overrides })

  it.each([
    [source({}), true, 'DOC-01 · Políticas y reglas operativas'],
    [source({ category: 'documentacion', ref: 'DOC-08' }), true, 'DOC-08 · Documentación funcional y técnica'],
    [source({ kind: 'memory', ref: 'memoria-DEMO-2' }), true, 'memoria-DEMO-2 · Memoria, prioritaria'],
    [source({ kind: 'jira', ref: 'DEMO-3', required: true }), true, 'DEMO-3 · Jira, obligatoria'],
    [source({ ref: 'DOC-20' }), false, 'DOC-20 · No influirá en la propuesta'],
    [source({ category: 'otra' }), true, 'DOC-01 · otra'],
  ])('%#: «%s»', (value, included, text) => {
    expect(sourceDetail(value, included as boolean)).toBe(text)
  })
})
