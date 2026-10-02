import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from './App.tsx'

describe('App', () => {
  it('muestra el catálogo del sistema de diseño mientras no hay pantallas', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Sistema de diseño · Propuesta mixta' })).toBeInTheDocument()
  })
})
