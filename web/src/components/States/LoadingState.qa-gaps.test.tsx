// Huecos de prueba de PA-327 (UI.md §6.2 y §8): la Q de carga cuenta solo los tres nodos de generar y se llena con
// `review_ready`; la lista pinta un paso por nodo con su último estado. Etiquetas ficticias.
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ProgressStep } from '../../api/types.ts'
import { loadingProgress } from '../QMark/index.ts'
import { LoadingState } from './LoadingState.tsx'
import { latestSteps } from './progressSteps.ts'

const step = (node: ProgressStep['node'], state: ProgressStep['state'], label = `Paso ${node} (ficticio)`): ProgressStep => ({ node, label, state })
const qState = () => screen.getByRole('status').querySelector('[data-q-state]')?.getAttribute('data-q-state')

describe('loadingProgress · límites', () => {
  it('test_no_events_means_empty_q', () => {
    // PA-327: sin eventos, la Q empieza vacía.
    expect(loadingProgress([], false)).toEqual({ done: 0, running: false })
  })

  it('test_publish_and_memorize_done_do_not_move_the_q', () => {
    // PA-327: los pasos de publicar (y guardar la memoria) no cuentan para la Q de generar.
    expect(loadingProgress([step('publish', 'done'), step('memorize', 'done')], false)).toEqual({ done: 0, running: false })
  })

  it('test_latest_state_wins_when_generate_runs_again', () => {
    // PA-327: los eventos llegan en orden; un `generate` que vuelve a empezar (reintento) ya no cuenta como hecho.
    const events = [step('load_origin', 'done'), step('retrieve_context', 'done'), step('generate', 'done'), step('generate', 'running')]
    expect(loadingProgress(events, false)).toEqual({ done: 2, running: true })
  })

  it('test_running_is_only_for_generate', () => {
    // PA-327: solo `generate` en curso anima la Q.
    expect(loadingProgress([step('load_origin', 'running')], false).running).toBe(false)
    expect(loadingProgress([step('publish', 'running')], false).running).toBe(false)
  })

  it('test_review_ready_fills_the_q_even_without_events', () => {
    // UI.md §6.2: con la suite lista la Q se completa aunque se hayan perdido eventos `progress`.
    expect(loadingProgress([], true)).toEqual({ done: 4, running: false })
  })
})

describe('LoadingState · lista de pasos', () => {
  it('test_repeated_node_events_render_a_single_step_with_latest_label_and_state', () => {
    // PA-327: un paso por nodo, en el orden en que apareció, con su último texto y estado.
    const events = [step('load_origin', 'running', 'Leer (ficticio)'), step('retrieve_context', 'running'), step('load_origin', 'done', 'Leído (ficticio)')]
    expect(latestSteps(events).map((item) => [item.node, item.state, item.label])).toEqual([
      ['load_origin', 'done', 'Leído (ficticio)'],
      ['retrieve_context', 'running', 'Paso retrieve_context (ficticio)'],
    ])
    render(<LoadingState title="Generando la suite…" events={events} />)
    const items = within(screen.getByRole('status')).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('Leído (ficticio)')
  })

  it('test_status_is_busy_until_review_ready', () => {
    // UI.md §8: la zona de estado se anuncia ocupada mientras se genera.
    const { rerender } = render(<LoadingState title="Generando la suite…" events={[step('generate', 'running')]} />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
    expect(qState()).toBe('loading-0')
    rerender(<LoadingState title="Suite lista" events={[step('generate', 'done')]} reviewReady />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'false')
    expect(qState()).toBe('loading-4')
  })

  it('test_step_labels_with_html_render_as_text', () => {
    // UI.md §7: las etiquetas de los pasos llegan de la API (PA-307) y se pintan como texto.
    const { container } = render(<LoadingState title="Generando…" events={[step('load_origin', 'running', '<img src=x onerror=alert(1)>')]} />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
  })
})
