import { describe, expect, it } from 'vitest'
import { loadingProgress, type StepEvent } from './loadingProgress.ts'

describe('loadingProgress (PA-303)', () => {
  it('sin eventos, la Q está vacía', () => {
    expect(loadingProgress([], false)).toEqual({ done: 0, running: false })
  })

  it('cada nodo de generación hecho llena un cuarto', () => {
    const events: StepEvent[] = [
      { node: 'load_origin', state: 'done' },
      { node: 'retrieve_context', state: 'done' },
    ]
    expect(loadingProgress(events, false)).toEqual({ done: 2, running: false })
  })

  it('con «generate» en running se anima dentro de su cuarto', () => {
    const events: StepEvent[] = [
      { node: 'load_origin', state: 'done' },
      { node: 'retrieve_context', state: 'done' },
      { node: 'generate', state: 'running' },
    ]
    expect(loadingProgress(events, false)).toEqual({ done: 2, running: true })
  })

  it('solo «generate» anima la Q: otro nodo en running no', () => {
    expect(loadingProgress([{ node: 'retrieve_context', state: 'running' }], false).running).toBe(false)
  })

  it('para cada nodo vale el último estado recibido', () => {
    const events: StepEvent[] = [
      { node: 'generate', state: 'running' },
      { node: 'generate', state: 'done' },
    ]
    expect(loadingProgress(events, false)).toEqual({ done: 1, running: false })
  })

  it('review_ready llena el último cuarto y para la animación', () => {
    const events: StepEvent[] = [
      { node: 'load_origin', state: 'done' },
      { node: 'retrieve_context', state: 'done' },
      { node: 'generate', state: 'done' },
    ]
    expect(loadingProgress(events, true)).toEqual({ done: 4, running: false })
  })

  it('publish y memorize no cuentan para la Q de generación', () => {
    const events: StepEvent[] = [
      { node: 'publish', state: 'done' },
      { node: 'memorize', state: 'done' },
    ]
    expect(loadingProgress(events, false)).toEqual({ done: 0, running: false })
  })
})
