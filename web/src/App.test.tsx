import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from './App.tsx'

describe('App', () => {
  it('muestra el catálogo del sistema de diseño en español', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Sistema de diseño · Propuesta mixta' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Colores' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Tipografía · DM Sans' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Iconos' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'La Q animada' })).toBeInTheDocument()
  })
})
