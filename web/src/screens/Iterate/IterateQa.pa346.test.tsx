// PA-346 y PA-158: en QA, «Editar a mano» mostraba el distintivo «Disponible pronto» y su motivo; desde PA-158 la suite
// se edita a mano, así que ni en QA ni en la HU queda el distintivo. Datos sintéticos (DEMO-3, qa-demo, af-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb } from '../../mocks/node.ts'
import { openSuiteInReview } from '../../test/qaFlow.tsx'
import { SOON_BADGE } from '../Admin/adminText.ts'

/** El motivo que se mostraba antes de PA-158. */
const QA_EDIT_SOON = 'Editar la suite a mano llegará más adelante; por ahora, pide los cambios en la conversación.'

describe('Iterar · Editar a mano «disponible pronto» (PA-346)', () => {
  it('test_qa_footer_has_no_soon_badge_since_pa158', async () => {
    // PA-158: en QA ya no hay distintivo ni motivo; *Editar a mano* es un botón normal.
    await openSuiteInReview()
    const panel = screen.getByRole('complementary', { name: 'Suite de pruebas' })
    expect(within(panel).queryByText(QA_EDIT_SOON)).not.toBeInTheDocument()
    expect(within(panel).queryByText(SOON_BADGE)).not.toBeInTheDocument()
    const button = within(panel).getByRole('button', { name: 'Editar a mano' })
    expect(button).not.toHaveAttribute('aria-disabled')
    expect(button).toBeEnabled()
    expect(button).not.toHaveAccessibleDescription(`${SOON_BADGE}: ${QA_EDIT_SOON}`)
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
