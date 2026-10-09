// Al llegar review_ready, la lista de conversaciones se vuelve a leer: la conversación deja de decir «En curso»
// sin esperar a *Ver la propuesta* o *Ver la suite* (HU y QA). Datos sintéticos (DEMO-3, af-demo, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../App.tsx'
import { mockDb } from '../mocks/node.ts'
import { generateSuiteForDemo3 } from '../test/qaFlow.tsx'

const list = () => screen.getByRole('complementary', { name: 'Conversaciones' })

describe('Lista de conversaciones al llegar review_ready', () => {
  it('HU: la conversación nueva pasa de «En curso» a su versión sin pulsar *Ver la propuesta*', async () => {
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
    await userEvent.click(screen.getAllByRole('textbox')[0] as HTMLElement)
    await userEvent.paste('Renovar un préstamo desde la app')
    await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Evolucionar DEMO-3' }))
    const panel = screen.getByRole('complementary', { name: 'Antes de generar' })
    await within(panel).findByRole('checkbox', { name: /HU de origen/ })
    await userEvent.click(within(panel).getByRole('button', { name: 'Generar propuesta' }))
    expect(await within(list()).findByRole('button', { name: /Evolucionar DEMO-3.*En curso/ })).toBeInTheDocument()
    await screen.findByRole('button', { name: 'Ver la propuesta de FAQ' })
    await vi.waitFor(() => expect(within(list()).queryByRole('button', { name: /En curso/ })).toBeNull())
    // Sigue en Generando: no se ha abierto la propuesta.
    expect(screen.getByRole('button', { name: 'Ver la propuesta de FAQ' })).toBeInTheDocument()
  })

  it('QA: la suite lista deja de decir «En curso» sin pulsar *Ver la suite*', async () => {
    await generateSuiteForDemo3()
    expect(await within(list()).findByRole('button', { name: /Preparar pruebas de DEMO-3.*En curso/ })).toBeInTheDocument()
    await screen.findByRole('button', { name: 'Ver la suite de FAQ' })
    await vi.waitFor(() => expect(within(list()).queryByRole('button', { name: /En curso/ })).toBeNull())
    expect(within(list()).getByRole('button', { name: /Preparar pruebas de DEMO-3.*Versión 1/ })).toBeInTheDocument()
  })
})
