// Cómo avanza la Q de carga con los eventos SSE de T-55 (DESIGN-DECISIONS.md §3, PA-303).

import type { ProgressStep, StepNode, StepState } from '../../api/types.ts'

export type { StepNode, StepState }

/** Lo que usa la Q de un `ProgressStep` del contrato (`docs/api/openapi.yaml`). */
export type StepEvent = Pick<ProgressStep, 'node' | 'state'>

export interface LoadingProgress {
  /** Cuartos llenos (0 a 4). */
  done: number
  /** `generate` está en curso: la Q se anima dentro de su cuarto. */
  running: boolean
}

const GENERATION_NODES: readonly StepNode[] = ['load_origin', 'retrieve_context', 'generate']

/**
 * Cada nodo de generación hecho llena un cuarto y `review_ready` llena el último.
 * Los eventos llegan en orden: para cada nodo vale el último estado recibido.
 * `review_ready` significa que la generación terminó: la Q se llena aunque se perdiera
 * algún `progress` (por ejemplo, al reconectar el SSE).
 */
export function loadingProgress(events: readonly StepEvent[], reviewReady: boolean): LoadingProgress {
  if (reviewReady) return { done: 4, running: false }

  const latest = new Map<StepNode, StepState>()
  for (const event of events) latest.set(event.node, event.state)

  const doneNodes = GENERATION_NODES.filter((node) => latest.get(node) === 'done').length
  return { done: doneNodes, running: latest.get('generate') === 'running' }
}
