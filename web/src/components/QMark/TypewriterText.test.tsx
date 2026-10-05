import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { charsPerTick, MAX_DURATION_MS, TICK_MS } from './qGeometry.ts'
import { TypewriterText } from './TypewriterText.tsx'

function stubReducedMotion(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  )
}

function visibleText(container: HTMLElement): string {
  return container.querySelector('[aria-hidden="true"]')?.textContent ?? ''
}

const REPLY = 'Versión 2 lista. Cambió el CA-03 y añadió la RN-02.'

describe('TypewriterText', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('escribe 2 caracteres cada 35 ms con caret mientras escribe', () => {
    const { container } = render(<TypewriterText text={REPLY} />)
    expect(visibleText(container)).toBe('')
    act(() => {
      vi.advanceTimersByTime(TICK_MS)
    })
    expect(visibleText(container)).toBe('Ve')
    expect(container.querySelector('[data-caret]')).not.toBeNull()
  })

  it('termina, quita el caret y avisa una sola vez', () => {
    const onDone = vi.fn()
    const { container } = render(<TypewriterText text={REPLY} onDone={onDone} />)
    act(() => {
      vi.advanceTimersByTime(MAX_DURATION_MS + TICK_MS)
    })
    expect(visibleText(container)).toBe(REPLY)
    expect(container.querySelector('[data-caret]')).toBeNull()
    act(() => {
      vi.advanceTimersByTime(MAX_DURATION_MS)
    })
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('una respuesta larga no tarda más de 1,5 s', () => {
    const long = 'Texto sintético de prueba. '.repeat(200)
    const { container } = render(<TypewriterText text={long} />)
    act(() => {
      vi.advanceTimersByTime(MAX_DURATION_MS + TICK_MS)
    })
    expect(visibleText(container)).toBe(long)
  })

  it('el texto completo está desde el principio para los lectores de pantalla', () => {
    const { container } = render(<TypewriterText text={REPLY} />)
    expect(container.querySelector('.visually-hidden')).toHaveTextContent(REPLY)
  })

  it('muestra el texto de la API como texto, nunca como HTML', () => {
    const html = '<b>negrita</b><img src=x onerror=alert(1)>'
    const { container } = render(<TypewriterText text={html} />)
    act(() => {
      vi.advanceTimersByTime(MAX_DURATION_MS + TICK_MS)
    })
    expect(visibleText(container)).toBe(html)
    expect(container.querySelector('b, img')).toBeNull()
  })

  it('con «reducir movimiento» aparece entero de inmediato, sin caret', () => {
    stubReducedMotion(true)
    const onDone = vi.fn()
    const { container } = render(<TypewriterText text={REPLY} onDone={onDone} />)
    expect(visibleText(container)).toBe(REPLY)
    expect(container.querySelector('[data-caret]')).toBeNull()
    expect(onDone).toHaveBeenCalledTimes(1)
  })
})

describe('charsPerTick', () => {
  it('son 2 caracteres por paso para respuestas cortas', () => {
    expect(charsPerTick(20)).toBe(2)
  })

  it('crece con la longitud para no pasar de 1,5 s', () => {
    const length = 5000
    const ticks = Math.ceil(length / charsPerTick(length))
    expect(ticks * TICK_MS).toBeLessThanOrEqual(MAX_DURATION_MS)
  })
})
