// PA-461 en pantalla: con el token CSRF antiguo (se inició sesión en otra pestaña), la web se recupera sola si
// sigue siendo la misma persona, y vuelve al inicio de sesión con su aviso si es otra. Datos sintéticos.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../App.tsx'
import { mockDb } from '../mocks/node.ts'
import { OTHER_ACCOUNT_ERROR } from './sessionContext.ts'

/** Entra af-demo y llega a Inicio; luego «otra pestaña» inicia sesión (otro token, y si se dice, otra persona). */
async function homeThenOtherTab(next: { username: string; role: 'functional' | 'qa' }) {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio-antiguo' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  mockDb.session = { ...next, csrf: 'csrf-ficticio-nuevo' }
}

describe('Inicio con el token CSRF antiguo (PA-461)', () => {
  it('la misma persona: «Continuar» (propuesta, repetible) sale bien sin pasar por «Sin permiso»', async () => {
    await homeThenOtherTab({ username: 'af-demo', role: 'functional' })
    await userEvent.type(screen.getByRole('textbox'), 'Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    expect(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Sin permiso' })).toBeNull()
  })

  it('otra persona en la otra pestaña: vuelve al inicio de sesión con el aviso', async () => {
    await homeThenOtherTab({ username: 'qa-demo', role: 'qa' })
    await userEvent.type(screen.getByRole('textbox'), 'DEMO-3')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    expect(await screen.findByText(OTHER_ACCOUNT_ERROR.message)).toBeInTheDocument()
    expect(screen.getByLabelText('Usuario')).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Conversaciones' })).toBeNull()
  })
})
