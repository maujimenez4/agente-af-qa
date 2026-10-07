// PA-346: en QA, «Editar a mano» (aún no disponible para la suite) muestra el distintivo «Disponible pronto» y su
// motivo a la vista, como Ajustes (PA-431); en la HU no sale. Datos sintéticos (DEMO-3, qa-demo, af-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb } from '../../mocks/node.ts'
import { openSuiteInReview } from '../../test/qaFlow.tsx'
import { SOON_BADGE } from '../Admin/adminText.ts'
import { QA_EDIT_SOON } from './iterateText.ts'

describe('Iterar · Editar a mano «disponible pronto» (PA-346)', () => {
  it('test_qa_footer_shows_soon_badge_and_visible_reason', async () => {
    await openSuiteInReview()
    const panel = screen.getByRole('complementary', { name: 'Suite de pruebas' })
    const note = within(panel).getByText(QA_EDIT_SOON)
    // Visible (no `visually-hidden`) y con el distintivo al lado.
    expect(note.closest('.visually-hidden')).toBeNull()
    expect(within(note.closest('p') as HTMLElement).getByText(SOON_BADGE)).toBeInTheDocument()
    const button = within(panel).getByRole('button', { name: 'Editar a mano' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAccessibleDescription(`${SOON_BADGE}: ${QA_EDIT_SOON}`)
  })

  it('test_story_footer_has_no_soon_note', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
    expect(within(panel).queryByText(QA_EDIT_SOON)).not.toBeInTheDocument()
    expect(within(panel).queryByText(SOON_BADGE)).not.toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: 'Editar a mano' })).not.toHaveAttribute('aria-disabled')
  })
})
