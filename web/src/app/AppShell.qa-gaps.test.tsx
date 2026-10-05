// Huecos de prueba del flujo de QA vistos desde la app (UI.md §4.5–§4.7 y §6): el recorrido de la HU no cambia con
// los textos de la suite, y el flujo unido HU → QA está fuera de la entrega (QA_HANDOFF_ENABLED = false).
// Datos sintéticos (DEMO-3, af-demo, qa-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '../App.tsx'
import { mockDb, mockServer } from '../mocks/node.ts'
import { OUTCOME_TEXTS } from '../screens/Result/resultText.ts'
import { QA_HANDOFF_ENABLED } from './features.ts'

async function openStoryFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  return screen.findByRole('complementary', { name: 'Propuesta de HU' })
}

describe('El recorrido de la HU no cambia con el flujo de QA', () => {
  it('test_story_iterate_keeps_story_tabs_texts_and_suggestions', async () => {
    // UI.md §4.5: Mixta 3 sigue con Propuesta, Cambios, Impacto y Fuentes; nada de la suite.
    const panel = await openStoryFromList()
    const tabs = within(panel).getAllByRole('tab').map((item) => item.textContent ?? '')
    expect(tabs[0]).toBe('Propuesta')
    expect(tabs.slice(1).map((label) => label.replace(/ \(\d+\)$/, ''))).toEqual(['Cambios', 'Impacto', 'Fuentes'])
    expect(within(panel).getByRole('tab', { name: 'Propuesta' })).toHaveAttribute('aria-selected', 'true')
    expect(within(panel).queryByText('Todos los CA cubiertos')).toBeNull()
    expect(within(panel).getByRole('group', { name: 'Versiones' })).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Cambios sugeridos' })).getAllByRole('button').map((item) => item.textContent)).toEqual([
      'Añade un criterio de error',
      'Aclara el alcance',
      'Revisa INVEST',
    ])
    expect(screen.getByRole('textbox', { name: /^Pide un cambio a la propuesta/ })).toBeEnabled()
    expect(screen.getByRole('heading', { level: 1 }).textContent).not.toMatch(/^Pruebas de/)
    expect(screen.queryByText(/cobertura validada/)).toBeNull()
  })

  it('test_story_receipt_and_simulated_result_keep_story_texts', async () => {
    // UI.md §4.6 y §4.7: recibo y resultado de la HU con sus textos (no los de la suite) y sin pedir pruebas tras simular.
    const panel = await openStoryFromList()
    await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
    const receipt = await screen.findByRole('region', { name: /^Versión \d+ lista para revisar$/ })
    expect(within(receipt).getByRole('button', { name: 'Volver a la propuesta' })).toBeInTheDocument()
    expect(within(receipt).queryByRole('button', { name: 'Volver a la suite' })).toBeNull()
    expect(within(receipt).getByText(/^Generado con IA a partir de \d+ fuentes?\. Revisa cada operación antes de aprobar\.$/)).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: 'Historial de la HU' })).toBeInTheDocument()
    expect(within(receipt).queryByText(/caso-prueba/)).toBeNull()
    for (const box of within(receipt).getAllByRole('checkbox')) await userEvent.click(box)
    await userEvent.click(within(receipt).getByRole('button', { name: 'Aprobar y publicar' }))
    const result = await screen.findByRole('region', { name: 'Publicación simulada' })
    expect(within(result).getByText(OUTCOME_TEXTS.simulated.note)).toBeInTheDocument()
    expect(within(result).getByRole('button', { name: 'Ir al historial' })).toBeInTheDocument()
    expect(within(result).getByText(/^Versión \d+ aprobada por af-demo/)).toBeInTheDocument()
    // Flujo unido fuera de la entrega y, además, tras una simulación no sale.
    expect(QA_HANDOFF_ENABLED).toBe(false)
    expect(within(result).queryByRole('button', { name: 'Pedir sus pruebas a QA' })).toBeNull()
  })

  it('test_story_published_offers_handoff_only_as_soon', async () => {
    // features.ts: con QA_HANDOFF_ENABLED = false, *Pedir sus pruebas a QA* es «disponible pronto» y no llama a la API.
    mockDb.forceApprove = 'published'
    let handoffPosts = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/handoff')) handoffPosts += 1
    })
    const panel = await openStoryFromList()
    await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
    const receipt = await screen.findByRole('region', { name: /^Versión \d+ lista para revisar$/ })
    for (const box of within(receipt).getAllByRole('checkbox')) await userEvent.click(box)
    await userEvent.click(within(receipt).getByRole('button', { name: 'Aprobar y publicar' }))
    const result = await screen.findByRole('region', { name: 'Publicado en Jira' })
    const handoff = within(result).getByRole('button', { name: 'Pedir sus pruebas a QA' })
    expect(handoff).toHaveAttribute('aria-disabled', 'true')
    await userEvent.click(handoff)
    expect(handoffPosts).toBe(0)
    mockServer.events.removeAllListeners()
  })
})
