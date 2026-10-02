// Criterio 7: el hook vale false sin matchMedia y reacciona a los eventos «change» de la media query.
import { act, render, renderHook, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { usePrefersReducedMotion } from './usePrefersReducedMotion.ts'

const QUERY = '(prefers-reduced-motion: reduce)'

/** Doble de MediaQueryList con oyentes reales, para disparar «change» como el navegador. */
function fakeMatchMedia(initial: boolean) {
  const listeners = new Set<() => void>()
  const media = {
    matches: initial,
    media: QUERY,
    addEventListener: vi.fn((_type: string, listener: () => void) => {
      listeners.add(listener)
    }),
    removeEventListener: vi.fn((_type: string, listener: () => void) => {
      listeners.delete(listener)
    }),
  }
  const matchMedia = vi.fn(() => media)
  vi.stubGlobal('matchMedia', matchMedia)
  return {
    media,
    matchMedia,
    listeners,
    change(matches: boolean) {
      media.matches = matches
      for (const listener of [...listeners]) listener()
    },
  }
}

function Probe() {
  return <span data-testid="probe">{usePrefersReducedMotion() ? 'reducir' : 'animar'}</span>
}

describe('usePrefersReducedMotion', () => {
  it('vale false si el navegador no tiene matchMedia', () => {
    vi.stubGlobal('matchMedia', undefined)
    const { result } = renderHook(() => usePrefersReducedMotion())
    expect(result.current).toBe(false)
  })

  it('vale false si matchMedia no es una función', () => {
    vi.stubGlobal('matchMedia', 'no es una función')
    const { result } = renderHook(() => usePrefersReducedMotion())
    expect(result.current).toBe(false)
  })

  it('consulta exactamente la media query de «reducir movimiento»', () => {
    const fake = fakeMatchMedia(false)
    renderHook(() => usePrefersReducedMotion())
    expect(fake.matchMedia).toHaveBeenCalledWith(QUERY)
  })

  it('vale true si el sistema pide reducir movimiento', () => {
    fakeMatchMedia(true)
    const { result } = renderHook(() => usePrefersReducedMotion())
    expect(result.current).toBe(true)
  })

  it('vale false si el sistema no lo pide', () => {
    fakeMatchMedia(false)
    const { result } = renderHook(() => usePrefersReducedMotion())
    expect(result.current).toBe(false)
  })

  it('se suscribe a «change» y se vuelve a pintar al activar y al desactivar', () => {
    const fake = fakeMatchMedia(false)
    render(<Probe />)
    expect(screen.getByTestId('probe')).toHaveTextContent('animar')
    expect(fake.media.addEventListener).toHaveBeenCalledWith('change', expect.any(Function))

    act(() => fake.change(true))
    expect(screen.getByTestId('probe')).toHaveTextContent('reducir')

    act(() => fake.change(false))
    expect(screen.getByTestId('probe')).toHaveTextContent('animar')
  })

  it('se da de baja de «change» al desmontarse, con el mismo oyente', () => {
    const fake = fakeMatchMedia(false)
    const { unmount } = render(<Probe />)
    const added = fake.media.addEventListener.mock.calls.at(-1)?.[1]
    expect(fake.listeners.size).toBe(1)

    unmount()
    expect(fake.media.removeEventListener).toHaveBeenCalledWith('change', added)
    expect(fake.listeners.size).toBe(0)
  })

  it('tras desmontarse, un cambio de la preferencia no hace nada', () => {
    const fake = fakeMatchMedia(false)
    const { unmount } = render(<Probe />)
    unmount()
    expect(() => act(() => fake.change(true))).not.toThrow()
    expect(screen.queryByTestId('probe')).toBeNull()
  })
})
