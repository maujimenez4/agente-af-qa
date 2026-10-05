// Entrar en el flujo de QA como en la entrega (por roles): QA escribe la clave de la HU, elige «Preparar pruebas de
// DEMO-3» y genera la suite. Sin el flujo unido HU → QA (`QA_HANDOFF_ENABLED`). Datos sintéticos (DEMO-3, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from '../App.tsx'
import { mockDb } from '../mocks/node.ts'

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
