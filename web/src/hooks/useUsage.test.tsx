import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockDb } from '../mocks/node.ts'
import { useUsage } from './useUsage.ts'

describe('useUsage (PA-305)', () => {
  it('trae el consumo de hoy de la instalación', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    const { result } = renderHook(() => useUsage())
    await waitFor(() => expect(result.current).toEqual({ tokens_today: 42000, warning_threshold: 180000, scope: 'global' }))
  })

  it('con 503 no hay dato y el anillo no se pinta', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    mockDb.usage = 'unavailable'
    const { result } = renderHook(() => useUsage())
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(result.current).toBeUndefined()
  })

  it('desactivado no pide nada', async () => {
    const { result } = renderHook(() => useUsage(false))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(result.current).toBeUndefined()
  })
})
