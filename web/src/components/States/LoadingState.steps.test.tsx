// PA-327: la API manda en `progress` todos sus pasos (la HU, 5 con «Guardar la memoria»; QA, 4 sin él). La lista
// pinta los que lleguen, sin un número fijo, y la Q de carga avanza con los tres nodos de generar (iguales en HU y
// QA) y se completa con `review_ready`: los pasos de publicar no la mueven. Etiquetas de ejemplo, como la API.
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ProgressStep } from '../../api/types.ts'
import { loadingProgress } from '../QMark/index.ts'
import { LoadingState } from './LoadingState.tsx'

type State = ProgressStep['state']

const HU_STEPS: Array<[ProgressStep['node'], string]> = [
  ['load_origin', 'Leer el origen en Jira'],
  ['retrieve_context', 'Recuperar el contexto (Jira, documentos y memoria)'],
  ['generate', 'Generar la propuesta, validar las citas y analizar el impacto'],
  ['publish', 'Publicar (o simular la publicación) en Jira'],
  ['memorize', 'Guardar la memoria de la HU publicada'],
]
const QA_STEPS: Array<[ProgressStep['node'], string]> = [
  ['load_origin', 'Recuperar la HU y el contexto'],
  ['retrieve_context', 'Generar casos y escenarios'],
  ['generate', 'Validar la cobertura'],
  ['publish', 'Publicar la suite en Jira'],
]

/** Los pasos con los estados dados en orden; el resto, pendientes. */
function progress(steps: Array<[ProgressStep['node'], string]>, states: State[]): ProgressStep[] {
  return steps.map(([node, label], index) => ({ node, label, state: states[index] ?? 'pending' }))
}

const qState = () => document.querySelector('[data-q-state]')?.getAttribute('data-q-state')

describe.each([
  ['HU, 5 pasos', HU_STEPS],
  ['QA, 4 pasos (PA-327)', QA_STEPS],
])('%s', (_, steps) => {
  it('la lista pinta todos los pasos que llegan, con su etiqueta y su estado', () => {
    render(<LoadingState title="Generando…" events={progress(steps, ['done', 'running'])} />)
    const items = within(screen.getByRole('status')).getAllByRole('listitem')
    expect(items).toHaveLength(steps.length)
    expect(items.map((item) => item.getAttribute('data-state'))).toEqual(['done', 'running', ...Array(steps.length - 2).fill('pending')])
    expect(items[0]).toHaveTextContent(steps[0]?.[1] ?? '')
  })

  it.each([
    [['done'], 1],
    [['done', 'done'], 2],
    [['done', 'done', 'done'], 3],
  ] as Array<[State[], number]>)('con %j, la Q va en %i cuartos: los pasos de publicar pendientes no cuentan', (states, quarters) => {
    expect(loadingProgress(progress(steps, states), false).done).toBe(quarters)
    render(<LoadingState title="Generando…" events={progress(steps, states)} />)
    expect(qState()).toBe(`loading-${quarters}`)
  })

  it('con `review_ready` la Q se llena aunque queden pasos de publicar pendientes', () => {
    render(<LoadingState title="Lista" events={progress(steps, ['done', 'done', 'done'])} reviewReady />)
    expect(qState()).toBe('loading-4')
  })

  it('`generate` en curso anima la Q dentro de su cuarto', () => {
    expect(loadingProgress(progress(steps, ['done', 'done', 'running']), false)).toEqual({ done: 2, running: true })
  })
})
