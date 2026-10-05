// Versión «Jira» del selector de Iterar (PA-316): `ConversationOut.jira_baseline`. Datos sintéticos.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut

async function openFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

const panel = () => screen.getByRole('complementary', { name: 'Propuesta de HU' })
const versions = () => within(panel()).getByRole('group', { name: 'Versiones' })
const criteria = () => within(panel()).getByRole('list', { name: 'Criterios de aceptación' })

describe('Iterar · versión «Jira» (PA-316)', () => {
  it('«Jira» va delante de v1…vN y muestra la HU tal como está en Jira, sin pestañas ni marcas', async () => {
    await openFromList()
    expect(within(versions()).getAllByRole('button').map((button) => button.textContent)).toEqual(['Jira', 'v2'])
    await userEvent.click(within(versions()).getByRole('button', { name: 'Versión de Jira' }))
    expect(within(versions()).getByRole('button', { name: 'Versión de Jira' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel()).getByText('Así está la HU en Jira ahora. Elige una versión para ver qué cambia.')).toBeInTheDocument()
    expect(within(panel()).queryByRole('tablist')).toBeNull()
    // La simulada no tiene el CA-02, que es nuevo frente a Jira.
    expect(within(criteria()).getByText('CA-01')).toBeInTheDocument()
    expect(within(criteria()).queryByText('CA-02')).toBeNull()
    expect(within(panel()).queryByText(/Cambiado en|Nueva/)).toBeNull()
  })

  it('volver a una versión recupera las pestañas, y la primera se marca frente a Jira', async () => {
    await openFromList()
    await userEvent.click(within(versions()).getByRole('button', { name: 'Versión de Jira' }))
    await userEvent.click(within(versions()).getByRole('button', { name: 'Versión 2' }))
    expect(within(panel()).getByRole('tablist')).toBeInTheDocument()
    // v2 es la primera de esta conversación: se compara con Jira y el CA-02 sale como «Nueva».
    const ca02 = within(criteria()).getByText('CA-02').closest('li') as HTMLElement
    expect(within(ca02).getByText('Nueva')).toBeInTheDocument()
  })

  it('el botón «Abrir en el panel» de un mensaje sale de la versión «Jira» y abre la suya', async () => {
    await openFromList()
    await userEvent.click(within(versions()).getByRole('button', { name: 'Versión de Jira' }))
    const log = screen.getByRole('log', { name: 'Conversación' })
    await userEvent.click(within(log).getByRole('button', { name: /Propuesta de HU, versión 2/ }))
    expect(within(versions()).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(panel()).getByRole('tablist')).toBeInTheDocument()
  })

  it('sin jira_baseline (HU nueva o QA) no hay versión «Jira»', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json({ ...EXAMPLE, flow: 'need', jira_baseline: null })))
    await openFromList()
    expect(within(versions()).queryByRole('button', { name: 'Versión de Jira' })).toBeNull()
  })

  it('tras pedir un cambio, la versión «Jira» sigue siendo la de partida', async () => {
    await openFromList()
    await userEvent.type(screen.getByRole('textbox', { name: 'Pide un cambio a la propuesta (Intro para enviar, Mayús+Intro para nueva línea)' }), 'Cambio ficticio')
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await within(panel()).findByRole('button', { name: 'Versión 3' })
    expect(within(versions()).getAllByRole('button').map((button) => button.textContent)).toEqual(['Jira', 'v2', 'v3'])
    await userEvent.click(within(versions()).getByRole('button', { name: 'Versión de Jira' }))
    expect(within(criteria()).queryByText(/revisado en v3/)).toBeNull()
  })
})
