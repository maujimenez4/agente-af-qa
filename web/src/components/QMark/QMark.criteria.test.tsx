// Criterio 2 (DESIGN-DECISIONS.md decisión 13 y §3): casos de límite que no cubren QMark.test.tsx,
// TypewriterText.test.tsx ni loadingProgress.test.ts.
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import qCss from './QMark.module.css?raw'
import { LoadingQ } from './LoadingQ.tsx'
import { loadingProgress, type StepEvent } from './loadingProgress.ts'
import { PhaseQ } from './PhaseQ.tsx'
import { charsPerTick, MAX_DURATION_MS, offsetFor, PHASE_NAMES, QUARTER, TICK_MS } from './qGeometry.ts'
import { TypewriterText } from './TypewriterText.tsx'

function rectOf(container: HTMLElement): SVGRectElement {
  const rect = container.querySelector<SVGRectElement>('clipPath rect')
  if (!rect) throw new Error('No hay rect de recorte')
  return rect
}

function cssVar(container: HTMLElement, name: string): string {
  return rectOf(container).style.getPropertyValue(name)
}

function keyframes(name: string): string {
  return new RegExp(`@keyframes ${name}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(qCss)?.[1] ?? ''
}

describe('Q de fase: nunca se ve llena antes de tiempo (decisión 13)', () => {
  it('fase 1 al montarse anima desde vacía (326), nunca desde llena', () => {
    const { container } = render(<PhaseQ phase={1} />)
    expect(cssVar(container, '--q-from')).toBe('326px')
    expect(cssVar(container, '--q-to')).toBe('244.5px')
  })

  it.each([1, 2, 3] as const)('fase %i: ni el estado final ni el inicial son la Q llena', (phase) => {
    const { container } = render(<PhaseQ phase={phase} />)
    expect(cssVar(container, '--q-to')).not.toBe('0px')
    expect(cssVar(container, '--q-from')).not.toBe('0px')
  })

  it('solo la fase 4 queda llena', () => {
    const { container } = render(<PhaseQ phase={4} />)
    expect(cssVar(container, '--q-to')).toBe('0px')
  })

  it('al bajar de fase (p. ej., empezar de nuevo) el estado final es el de la fase nueva', () => {
    const { container, rerender } = render(<PhaseQ phase={4} />)
    rerender(<PhaseQ phase={1} />)
    expect(cssVar(container, '--q-to')).toBe('244.5px')
  })

  it('al bajar de la fase 4 a la 1 no parte de la Q llena', () => {
    const { container, rerender } = render(<PhaseQ phase={4} />)
    rerender(<PhaseQ phase={1} />)
    expect(cssVar(container, '--q-from')).not.toBe('0px')
  })

  it('el texto visible «Fase N de 4 · nombre» es decorativo; el nombre accesible lo da role="img"', () => {
    const { container } = render(<PhaseQ phase={2} />)
    const visible = container.querySelector('span[aria-hidden="true"]')
    expect(visible).toHaveTextContent('Fase 2 de 4 · Generar')
    expect(screen.getByRole('img', { name: 'Avance: fase 2 de 4, Generar' })).toBeInTheDocument()
  })

  it('los nombres de las fases son los de UI.md §2 (decisión 8: «Generar»)', () => {
    expect(PHASE_NAMES).toEqual({ 1: 'Contexto', 2: 'Generar', 3: 'Revisión', 4: 'Publicado' })
  })
})

describe('CSS de la Q con «reducir movimiento» (decisión 13)', () => {
  it('el bucle de «generate» va del inicio al final de su cuarto, no de vacía a llena', () => {
    const pulse = keyframes('q-pulse')
    expect(pulse).toContain('translateY(var(--q-from))')
    expect(pulse).toContain('translateY(var(--q-pulse-to))')
    expect(pulse).not.toMatch(/translateY\((0|326)(px)?\)/)
  })

  it('las animaciones de la Q usan solo transform (no tocan el estilo base)', () => {
    for (const name of ['q-fill', 'q-pulse', 'q-loop']) {
      const body = keyframes(name)
      expect(body, name).not.toBe('')
      expect(body.replace(/transform:[^;]+;/g, '')).not.toMatch(/[a-z-]+\s*:/)
    }
  })
})

describe('Q de carga por eventos SSE (§3)', () => {
  const SEQUENCE: ReadonlyArray<{ event: StepEvent; done: number; running: boolean }> = [
    { event: { node: 'load_origin', state: 'running' }, done: 0, running: false },
    { event: { node: 'load_origin', state: 'done' }, done: 1, running: false },
    { event: { node: 'retrieve_context', state: 'running' }, done: 1, running: false },
    { event: { node: 'retrieve_context', state: 'done' }, done: 2, running: false },
    { event: { node: 'generate', state: 'running' }, done: 2, running: true },
    { event: { node: 'generate', state: 'done' }, done: 3, running: false },
  ]

  it('avanza un cuarto por cada progress en done, en el orden de la tabla', () => {
    const received: StepEvent[] = []
    for (const step of SEQUENCE) {
      received.push(step.event)
      expect(loadingProgress(received, false), `${step.event.node} ${step.event.state}`).toEqual({
        done: step.done,
        running: step.running,
      })
    }
  })

  it('sin review_ready nunca llega al 4.º cuarto, aunque todos los nodos estén hechos', () => {
    const all = SEQUENCE.map((step) => step.event)
    expect(loadingProgress(all, false).done).toBe(3)
  })

  it('review_ready llena la Q sin ningún progress previo', () => {
    expect(loadingProgress([], true)).toEqual({ done: 4, running: false })
  })

  it('error: la Q se queda en el último cuarto hecho y deja de animarse si generate no sigue en curso', () => {
    const events: StepEvent[] = [
      { node: 'load_origin', state: 'done' },
      { node: 'retrieve_context', state: 'done' },
    ]
    const { container } = render(<LoadingQ {...loadingProgress(events, false)} />)
    expect(cssVar(container, '--q-to')).toBe(`${offsetFor(2)}px`)
    expect(rectOf(container).dataset.qMotion).not.toBe('pulse')
  })

  it('un progress repetido del mismo nodo no cuenta dos veces', () => {
    const events: StepEvent[] = [
      { node: 'load_origin', state: 'done' },
      { node: 'load_origin', state: 'done' },
    ]
    expect(loadingProgress(events, false).done).toBe(1)
  })

  it('con «generate» en curso la Q se anima dentro del 3.er cuarto: de 163 a 81,5', () => {
    const progress = loadingProgress(SEQUENCE.slice(0, 5).map((step) => step.event), false)
    const { container } = render(<LoadingQ done={progress.done} running={progress.running} />)
    expect(cssVar(container, '--q-from')).toBe('163px')
    expect(cssVar(container, '--q-pulse-to')).toBe(`${163 - QUARTER}px`)
  })

  it('con «reducir movimiento» el estilo base muestra solo los cuartos hechos, nunca el que está en curso', () => {
    const { container } = render(<LoadingQ done={2} running />)
    // El estilo base (--q-to) es lo que se ve con las animaciones anuladas.
    expect(cssVar(container, '--q-to')).toBe('163px')
    expect(container.querySelector('svg')).toHaveAttribute('data-q-offset', '163')
  })

  it('vacía y sin eventos no se anima', () => {
    const { container } = render(<LoadingQ done={0} />)
    expect(rectOf(container).dataset.qMotion).toBe('none')
    expect(cssVar(container, '--q-to')).toBe('326px')
  })

  it('al llegar review_ready rellena desde el último cuarto visto', () => {
    const { container, rerender } = render(<LoadingQ done={2} running />)
    rerender(<LoadingQ done={4} />)
    expect(rectOf(container).dataset.qMotion).toBe('fill')
    expect(cssVar(container, '--q-from')).toBe('163px')
    expect(cssVar(container, '--q-to')).toBe('0px')
  })
})

describe('escritura simulada: ritmo (§3)', () => {
  it.each([1, 2, 40, 84])('%i caracteres → 2 por paso de 35 ms', (length) => {
    expect(charsPerTick(length)).toBe(2)
  })

  it('a partir de 85 caracteres escribe más de 2 por paso para no pasar de 1,5 s', () => {
    expect(charsPerTick(85)).toBe(3)
  })

  it.each([0, 1, 84, 85, 500, 1234, 20000])('%i caracteres: nunca más de 1,5 s', (length) => {
    const ticks = length === 0 ? 0 : Math.ceil(length / charsPerTick(length))
    expect(ticks * TICK_MS).toBeLessThanOrEqual(MAX_DURATION_MS)
  })
})

function stubReducedMotion(initial: boolean) {
  const listeners = new Set<() => void>()
  const media = {
    matches: initial,
    media: '(prefers-reduced-motion: reduce)',
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  }
  vi.stubGlobal('matchMedia', vi.fn(() => media))
  return (matches: boolean) => {
    media.matches = matches
    for (const listener of [...listeners]) listener()
  }
}

function visibleText(container: HTMLElement): string {
  return container.querySelector('[aria-hidden="true"]')?.textContent ?? ''
}

const REPLY = 'Versión 3 lista. Se añadió el CA-05 sobre reservas ficticias de la biblioteca de prueba.'

describe('TypewriterText: casos de límite (§3)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('a los 1,5 s exactos el texto está entero, sea cual sea su longitud', () => {
    for (const text of [REPLY, 'x'.repeat(85), 'Texto sintético. '.repeat(300)]) {
      const { container, unmount } = render(<TypewriterText text={text} />)
      act(() => {
        vi.advanceTimersByTime(MAX_DURATION_MS)
      })
      expect(visibleText(container)).toBe(text)
      unmount()
    }
  })

  it('no escribe más rápido de 2 caracteres por paso en una respuesta corta', () => {
    const { container } = render(<TypewriterText text={REPLY.slice(0, 20)} />)
    act(() => {
      vi.advanceTimersByTime(TICK_MS * 3)
    })
    expect(visibleText(container)).toBe(REPLY.slice(0, 6))
  })

  it('una respuesta larga avanza más de 2 caracteres por paso', () => {
    const long = 'Texto sintético de prueba. '.repeat(20)
    const { container } = render(<TypewriterText text={long} />)
    act(() => {
      vi.advanceTimersByTime(TICK_MS)
    })
    expect(visibleText(container)).toBe(long.slice(0, charsPerTick(long.length)))
    expect(charsPerTick(long.length)).toBeGreaterThan(2)
  })

  it('para el temporizador al terminar', () => {
    render(<TypewriterText text="Hola" />)
    act(() => {
      vi.advanceTimersByTime(MAX_DURATION_MS)
    })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('limpia el temporizador si se desmonta a medias', () => {
    const { unmount } = render(<TypewriterText text={REPLY} />)
    act(() => {
      vi.advanceTimersByTime(TICK_MS)
    })
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('el caret está dentro de la parte decorativa (aria-hidden)', () => {
    const { container } = render(<TypewriterText text={REPLY} />)
    act(() => {
      vi.advanceTimersByTime(TICK_MS)
    })
    expect(container.querySelector('[data-caret]')?.closest('[aria-hidden="true"]')).not.toBeNull()
  })

  it('el nodo para lectores de pantalla tampoco interpreta HTML', () => {
    const html = '<script>alert(1)</script><a href="https://ejemplo.invalid">enlace</a>'
    const { container } = render(<TypewriterText text={html} />)
    const hidden = container.querySelector('.visually-hidden')
    expect(hidden?.textContent).toBe(html)
    expect(container.querySelector('script, a')).toBeNull()
  })

  it('texto vacío: termina de inmediato, sin caret, y avisa una vez', () => {
    const onDone = vi.fn()
    const { container } = render(<TypewriterText text="" onDone={onDone} />)
    expect(container.querySelector('[data-caret]')).toBeNull()
    expect(container.firstElementChild).toHaveAttribute('data-typing', 'done')
    act(() => {
      vi.advanceTimersByTime(MAX_DURATION_MS)
    })
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('con «reducir movimiento» no arranca ningún temporizador', () => {
    stubReducedMotion(true)
    const { container } = render(<TypewriterText text={REPLY} />)
    expect(vi.getTimerCount()).toBe(0)
    expect(container.firstElementChild).toHaveAttribute('data-typing', 'done')
  })

  it('si se activa «reducir movimiento» a media escritura, el texto aparece entero y sin caret', () => {
    const change = stubReducedMotion(false)
    const onDone = vi.fn()
    const { container } = render(<TypewriterText text={REPLY} onDone={onDone} />)
    act(() => {
      vi.advanceTimersByTime(TICK_MS)
    })
    expect(visibleText(container)).toBe(REPLY.slice(0, charsPerTick(REPLY.length)))

    act(() => change(true))
    expect(visibleText(container)).toBe(REPLY)
    expect(container.querySelector('[data-caret]')).toBeNull()
    expect(onDone).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })
})
