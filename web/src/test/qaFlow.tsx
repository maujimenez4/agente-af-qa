// Entrar en el flujo de QA como en la entrega (por roles): QA escribe la clave de la HU, elige «Preparar pruebas de
// DEMO-3» y genera la suite. Sin el flujo unido HU → QA (`QA_HANDOFF_ENABLED`). Datos sintéticos (DEMO-3, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ConversationCreateIn } from '../api/types.ts'
import { App } from '../App.tsx'
import { mockDb } from '../mocks/node.ts'
import { CASE_TYPES, EXTRAS, qaFeedback } from '../screens/Origin/qaOptions.ts'

/** Hasta Generando de la suite de DEMO-3 (QA 1 → QA 2). */
export async function generateSuiteForDemo3(): Promise<void> {
  mockDb.session = { username: 'qa-demo', role: 'qa', csrf: 'csrf-ficticio' }
  render(<App />)
  await screen.findByRole('button', { name: /Proyecto de Jira: DEMO/ })
  await userEvent.click(screen.getAllByRole('textbox')[0] as HTMLElement)
  await userEvent.paste('DEMO-3')
  await userEvent.click(screen.getByRole('button', { name: 'Continuar' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Preparar pruebas de DEMO-3' }))
  const panel = screen.getByRole('complementary', { name: 'Antes de generar' })
  await within(panel).findByRole('checkbox', { name: /HU de origen/ })
  await userEvent.click(within(panel).getByRole('button', { name: 'Generar la suite' }))
}

/** Hasta QA 3 · Iterar la suite. */
export async function openSuiteForDemo3(): Promise<void> {
  await generateSuiteForDemo3()
  await userEvent.click(await screen.findByRole('button', { name: 'Ver la suite' }))
  await screen.findByRole('complementary', { name: 'Suite de pruebas' })
}

/**
 * PA-127: QA 3 · Iterar la suite sin recorrer QA 1 y QA 2. La suite de DEMO-3 se genera con la propia API simulada
 * (el mismo cuerpo que envía Origen con las opciones por defecto) y se abre desde la lista de conversaciones: mismo
 * estado que tras «Ver la suite», sin depender de la interfaz para llegar.
 */
export async function openSuiteInReview(): Promise<void> {
  const csrf = 'csrf-ficticio'
  mockDb.session = { username: 'qa-demo', role: 'qa', csrf }
  const body: ConversationCreateIn = {
    origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' },
    flow: 'tests',
    excluded_sources: [],
    feedback: qaFeedback(new Set(CASE_TYPES.map((item) => item.id)), new Set(EXTRAS.map((item) => item.id))),
  }
  const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)
  const created = await fetch(url('/conversations'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body),
  })
  const { id } = (await created.json()) as { id: string }
  // El SSE simulado termina la generación: la suite queda en revisión.
  await (await fetch(url(`/conversations/${id}/events`))).text()
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Preparar pruebas de DEMO-3/ }))
  await screen.findByRole('complementary', { name: 'Suite de pruebas' })
}
