import type { ProgressStep, StepNode } from '../../api/types.ts'

/** `ProgressStep` del contrato: nodo, texto del paso y estado. */
export type ProgressEvent = ProgressStep

/** Un paso por nodo, en el orden en que apareció, con su último estado y texto. */
export function latestSteps(events: readonly ProgressEvent[]): ProgressEvent[] {
  const steps = new Map<StepNode, ProgressEvent>()
  for (const event of events) steps.set(event.node, event)
  return [...steps.values()]
}
