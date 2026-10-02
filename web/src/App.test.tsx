import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from './App.tsx'

describe('App', () => {
  it('pinta el título de la aplicación en español', () => {
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Agente AF y QA' })).toBeInTheDocument()
  })
})
