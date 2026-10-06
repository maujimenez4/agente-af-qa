// Mixta 4 · Resultado (UI.md §4.7): simulada, publicada y en parte. Datos sintéticos.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { PARTIAL_ERROR } from '../../mocks/handlers.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { approvedLine, hasResult, outcomeOf } from './resultText.ts'

const SIMULATED = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as ConversationOut
const RESULT = SIMULATED.result as PublishOutcome

async function approveFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
  const operations = await screen.findByRole('group', { name: /Qué se hará en Jira/ })
  for (const box of within(operations).getAllByRole('checkbox')) await userEvent.click(box)
  await userEvent.click(screen.getByRole('button', { name: 'Aprobar y publicar' }))
  return screen.findByRole('region', { name: /Publicación simulada|Publicado en Jira|Publicada en parte/ }, { timeout: 4000 })
}

describe('textos del resultado', () => {
  it.each([
    [{ ...RESULT, simulated: true }, 'simulated'],
    [{ ...RESULT, simulated: false }, 'published'],
    [{ ...RESULT, simulated: false, errors: ['Fallo ficticio'] }, 'partial'],
    [{ ...RESULT, simulated: false, failed_ids: ['CP-02'] }, 'partial'],
  ])('%#: %s', (result, outcome) => {
    expect(outcomeOf(result as PublishOutcome)).toBe(outcome)
  })

  it('solo hay resultado con `result` y un estado aprobado, simulado o publicado', () => {
    expect(hasResult(SIMULATED)).toBe(true)
    expect(hasResult({ ...SIMULATED, state: 'approved' })).toBe(true)
    expect(hasResult({ ...SIMULATED, state: 'discarded' })).toBe(false)
    expect(hasResult({ ...SIMULATED, result: null })).toBe(false)
  })

  it('«Versión 2 aprobada por af-demo a las HH:MM», y sin hora si la fecha no vale', () => {
    expect(approvedLine(2, RESULT)).toMatch(/^Versión 2 aprobada por af-demo a las \d{2}:\d{2}$/)
    expect(approvedLine(undefined, { ...RESULT, approved_at: 'no-es-fecha' })).toBe('Propuesta aprobada por af-demo')
  })
})

describe('Resultado tras aprobar', () => {
  it('simulación: fase 3 «Aprobada», distintivo, aviso de modo de prueba, operaciones numeradas y la aprobación vigente', async () => {
    const region = await approveFromList()
    expect(screen.getByRole('img', { name: 'Avance: fase 3 de 4, Aprobada' })).toBeInTheDocument()
    expect(within(region).getByRole('img', { name: 'Publicación simulada' })).toBeInTheDocument()
    // Flujo unido fuera de la entrega: tras una simulación no se ofrece pasar la HU a QA, ni siquiera como «disponible pronto».
    expect(within(region).queryByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeNull()
    expect(within(region).getByText('Aprobada · simulada')).toBeInTheDocument()
    expect(within(region).getByText('Modo de prueba activo: el agente no escribe en Jira. Lo cambia el administrador.')).toBeInTheDocument()
    expect(within(region).getByText('No se ha escrito nada en Jira. Esto es lo que se habría hecho, y queda en la auditoría:')).toBeInTheDocument()
    const operations = within(region).getByRole('list', { name: 'Operaciones que se habrían hecho' })
    expect(within(operations).getByText('Actualizar DEMO-3 con la versión 2')).toBeInTheDocument()
    expect(within(operations).getByText('Vincular DEMO-3 con DEMO-2')).toBeInTheDocument()
    expect(within(region).getByText(/^La aprobación sigue vigente/)).toBeInTheDocument()
    expect(within(region).getByText(/^Versión 2 aprobada por af-demo a las \d{2}:\d{2}$/)).toBeInTheDocument()
    for (const name of ['Ver el registro de auditoría', 'Ir al historial']) {
      expect(within(region).getByRole('button', { name })).toHaveAttribute('aria-disabled', 'true')
    }
  })

  it('publicada: fase 4, «Publicado en Jira», operaciones hechas, claves y acciones «disponible pronto» con su motivo', async () => {
    mockDb.forceApprove = 'published'
    // Sin dirección de Jira, *Abrir DEMO-3 en Jira* sigue «disponible pronto» pase lo que pase con /settings (sin carrera).
    mockDb.settings = { ...mockDb.settings, jira_browse_url: null }
    const region = await approveFromList()
    expect(screen.getByRole('img', { name: 'Avance: fase 4 de 4, Publicado' })).toBeInTheDocument()
    expect(within(region).getByRole('heading', { level: 2, name: 'Publicado en Jira' })).toBeInTheDocument()
    expect(within(region).getByRole('list', { name: 'Operaciones hechas en Jira' })).toBeInTheDocument()
    // PA-325: cada clave puede ser un enlace a Jira (con texto oculto); se comparan solo las claves.
    expect(within(region).getByText(/^Claves en Jira:/, { selector: 'p' }).textContent?.match(/[A-Z][A-Z0-9_]*-\d+/g)).toEqual(['DEMO-3'])
    expect(within(region).queryByText(/Modo de prueba activo/)).toBeNull()
    expect(within(region).getByRole('button', { name: 'Abrir DEMO-3 en Jira' })).toHaveAccessibleDescription('La dirección de Jira no está disponible.')
    // PA-329: con la HU publicada y su clave, *Ver la memoria* ya abre Memoria (no es «disponible pronto»).
    expect(within(region).getByRole('button', { name: 'Ver la memoria' })).not.toHaveAttribute('aria-disabled')
    // Flujo unido HU → QA fuera de la entrega (QA_HANDOFF_ENABLED = false): «disponible pronto» con su motivo.
    expect(within(region).getByRole('button', { name: 'Pedir sus pruebas a QA' })).toHaveAttribute('aria-disabled', 'true')
    expect(within(region).getByRole('button', { name: 'Pedir sus pruebas a QA' })).toHaveAccessibleDescription(
      'No entra en esta entrega: QA prepara las pruebas escribiendo la clave de la HU.',
    )
  })

  it('en parte: «Publicada en parte» con el error de la API tal cual y sin ocultar lo publicado', async () => {
    mockDb.forceApprove = 'partial'
    const region = await approveFromList()
    expect(screen.getByRole('img', { name: 'Avance: fase 4 de 4, Publicada en parte' })).toBeInTheDocument()
    expect(within(region).getByRole('heading', { level: 2, name: 'Publicada en parte' })).toBeInTheDocument()
    const failed = within(region).getByRole('alert')
    expect(failed).toHaveTextContent('Lo que no se pudo publicar')
    expect(failed).toHaveTextContent(PARTIAL_ERROR)
    const approved = within(region).getByRole('list', { name: 'Operaciones aprobadas' })
    expect(within(approved).getByText('Actualizar DEMO-3 con la versión 2')).toBeInTheDocument()
    // No se sabe qué operación falló: ninguna lleva ✓.
    expect(within(approved).queryByText('✓')).toBeNull()
  })

  it('retomar desde la lista una conversación simulada abre su resultado', async () => {
    mockServer.use(http.get('/api/v1/conversations/:id', () => HttpResponse.json(SIMULATED)))
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Publicación simulada' })).toBeInTheDocument()
  })

  it('el texto de la API se pinta como texto, nunca como HTML', async () => {
    mockServer.use(
      http.get('/api/v1/conversations/:id', () =>
        HttpResponse.json({ ...SIMULATED, state: 'approved', result: { ...RESULT, simulated: false, errors: ['<img src=x onerror=alert(1)> fallo ficticio'] } }),
      ),
    )
    mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
    render(<App />)
    const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
    await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
    const failed = await screen.findByRole('alert')
    expect(failed).toHaveTextContent('<img src=x onerror=alert(1)> fallo ficticio')
    expect(failed.querySelector('img')).toBeNull()
  })
})
