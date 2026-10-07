// PA-343 (a): con la lista en capa, lo que queda bajo el velo (el área de trabajo) es `inert`; la franja con su
// botón no. Al cerrar se quita y el foco vuelve al botón. Datos sintéticos (DEMO).
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEMO_CONVERSATIONS, DEMO_NOW } from '../../fixtures/conversations.ts'
import { ConversationList, NARROW_QUERY } from './ConversationList.tsx'

function narrowMatchMedia() {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({ matches: query === NARROW_QUERY, media: query, addEventListener: () => {}, removeEventListener: () => {} })),
  )
}

function renderWithWorkArea() {
  render(
    <div>
      <ConversationList id="convs" conversations={DEMO_CONVERSATIONS} onNew={vi.fn()} onSelect={vi.fn()} now={DEMO_NOW} />
      <main data-testid="trabajo">
        <button type="button">Acción ficticia del área de trabajo</button>
      </main>
    </div>,
  )
}

const toggle = () => screen.getByRole('button', { name: 'Conversaciones' })

afterEach(() => vi.unstubAllGlobals())

describe('PA-343: inert detrás de la lista en capa', () => {
  it('test_work_area_inert_while_list_layer_open_and_restored_on_close', async () => {
    narrowMatchMedia()
    renderWithWorkArea()
    const work = screen.getByTestId('trabajo')
    expect(work).not.toHaveAttribute('inert')
    await userEvent.click(toggle())
    expect(screen.getByRole('dialog', { name: 'Conversaciones' })).toBeInTheDocument()
    expect(work).toHaveAttribute('inert')
    // La franja con su botón queda fuera del velo: no se toca y sigue cerrando la capa.
    expect(toggle()).not.toHaveAttribute('inert')
    expect(toggle().closest('[inert]')).toBeNull()
    await userEvent.keyboard('{Escape}')
    expect(work).not.toHaveAttribute('inert')
    expect(toggle()).toHaveFocus()
  })

  it('test_click_on_toggle_still_closes_layer_and_removes_inert', async () => {
    narrowMatchMedia()
    renderWithWorkArea()
    await userEvent.click(toggle())
    await userEvent.click(toggle())
    expect(screen.queryByRole('dialog', { name: 'Conversaciones' })).not.toBeInTheDocument()
    expect(screen.getByTestId('trabajo')).not.toHaveAttribute('inert')
  })

  it('test_no_inert_when_list_is_not_a_layer', () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {} })))
    renderWithWorkArea()
    expect(screen.getByTestId('trabajo')).not.toHaveAttribute('inert')
  })
})
