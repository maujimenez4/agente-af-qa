// Memoria (PA-329) · *Ver la memoria* en el Resultado: con la HU publicada (o en parte) y `onOpenMemory`, es un
// botón que abre Memoria con la clave; en simulado y en QA no está; sin `onOpenMemory` o sin clave, «disponible
// pronto». En la app, publicar DEMO-3 deja su memoria y *Ver la memoria* la abre; con `?simular=memoria-no-encontrada`
// (`skipPublishedMemory`) no la deja y se ve la tarjeta 404 dentro de Memoria.
// Solo datos sintéticos (DEMO-3, af-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut, PublishOutcome } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb } from '../../mocks/node.ts'
import { ResultScreen } from './ResultScreen.tsx'

const SIMULATED = examples['POST /api/v1/conversations/{conversation_id}/approve 202'] as unknown as ConversationOut & { result: PublishOutcome }
const RESULT = SIMULATED.result
const SOON_MEMORY = 'No hay una HU publicada con clave de la que abrir la memoria.'
const REGION = /Publicación simulada|Publicado en Jira|Suite publicada en Jira|Publicada en parte/

function renderResult(result: Partial<PublishOutcome>, extra: Partial<ConversationOut> = {}, onOpenMemory?: (key: string) => void) {
  const conversation = { ...SIMULATED, ...extra, result: { ...RESULT, ...result } } as ConversationOut & { result: PublishOutcome }
  render(<ResultScreen conversation={conversation} onOpenMemory={onOpenMemory} />)
  return screen.getByRole('region', { name: REGION })
}

describe('ResultScreen · Ver la memoria', () => {
  it.each<[string, Partial<PublishOutcome>, ConversationOut['state']]>([
    ['publicada', { simulated: false, published_keys: ['DEMO-3'] }, 'published'],
    ['en parte', { simulated: false, errors: ['Fallo ficticio.'], published_keys: ['DEMO-3'] }, 'approved'],
  ])('test_view_memory_is_button_that_opens_key_when_%s', async (_name, result, state) => {
    /** HU publicada o en parte con `onOpenMemory`: botón activo que avisa con la clave DEMO-3. */
    const onOpenMemory = vi.fn()
    const region = renderResult(result, { state }, onOpenMemory)
    const button = within(region).getByRole('button', { name: 'Ver la memoria' })
    expect(button).not.toHaveAttribute('aria-disabled')
    expect(button).toBeEnabled()
    expect(button).not.toHaveAccessibleDescription(SOON_MEMORY)
    await userEvent.click(button)
    expect(onOpenMemory).toHaveBeenCalledTimes(1)
    expect(onOpenMemory).toHaveBeenCalledWith('DEMO-3')
  })

  it('test_view_memory_opens_with_keyboard', async () => {
    /** Se llega con Tab y se abre con Intro. */
    const onOpenMemory = vi.fn()
    const region = renderResult({ simulated: false, published_keys: ['DEMO-3'] }, { state: 'published' }, onOpenMemory)
    const button = within(region).getByRole('button', { name: 'Ver la memoria' })
    while (document.activeElement !== button) await userEvent.tab()
    await userEvent.keyboard('{Enter}')
    expect(onOpenMemory).toHaveBeenCalledWith('DEMO-3')
  })

  it('test_view_memory_absent_when_simulated', () => {
    /** En una simulación no hay *Ver la memoria* (no se ha publicado nada), aunque haya `onOpenMemory`. */
    const onOpenMemory = vi.fn()
    const region = renderResult({ simulated: true }, {}, onOpenMemory)
    expect(within(region).queryByRole('button', { name: 'Ver la memoria' })).toBeNull()
  })

  it('test_view_memory_absent_in_qa_suite', () => {
    /** En el resultado de una suite de QA no hay *Ver la memoria*. */
    const onOpenMemory = vi.fn()
    const plan = [{ op: 'publish_suite', project: 'DEMO', story: 'DEMO-3', cases: '3' }]
    const region = renderResult({ simulated: false, plan, published_keys: ['DEMO-3'] }, { state: 'published' }, onOpenMemory)
    expect(within(region).queryByRole('button', { name: 'Ver la memoria' })).toBeNull()
    expect(onOpenMemory).not.toHaveBeenCalled()
  })

  it('test_view_memory_absent_in_qa_mode', () => {
    /** Con la conversación en modo QA tampoco. */
    const region = renderResult({ simulated: false, published_keys: ['DEMO-3'] }, { state: 'published', mode: 'qa' } as Partial<ConversationOut>, vi.fn())
    expect(within(region).queryByRole('button', { name: 'Ver la memoria' })).toBeNull()
  })

  it('test_view_memory_soon_without_on_open_memory', async () => {
    /** Sin `onOpenMemory`: «disponible pronto» con su motivo, y pulsarlo no cambia nada. */
    const region = renderResult({ simulated: false, published_keys: ['DEMO-3'] }, { state: 'published' })
    const button = within(region).getByRole('button', { name: 'Ver la memoria' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAccessibleDescription(SOON_MEMORY)
    const before = region.innerHTML
    await userEvent.click(button)
    expect(region.innerHTML).toBe(before)
  })

  it('test_view_memory_soon_without_key', async () => {
    /** Sin clave (ni `update_story` en el plan ni claves publicadas): «disponible pronto» y no avisa. */
    const onOpenMemory = vi.fn()
    const region = renderResult({ simulated: false, plan: [{ op: 'create_story', project: 'DEMO' }], published_keys: [] }, { state: 'published' }, onOpenMemory)
    const button = within(region).getByRole('button', { name: 'Ver la memoria' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    expect(button).toHaveAccessibleDescription(SOON_MEMORY)
    await userEvent.click(button)
    expect(onOpenMemory).not.toHaveBeenCalled()
  })
})

/** Como `ResultScreen.test.tsx`: abre DEMO-3, aprueba todas las operaciones y espera al resultado. */
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
  return screen.findByRole('region', { name: REGION }, { timeout: 4000 })
}

const zones = () => screen.getByRole('navigation', { name: 'Zonas' })

describe('Resultado en la app · Ver la memoria abre Memoria', () => {
  it('test_published_view_memory_opens_memory_with_404_card_and_rail_still_works', async () => {
    /** `?simular=memoria-no-encontrada`: DEMO-3 se publica sin dejar memoria. Memoria se abre con la tarjeta
     * «No se encuentra»; el carril sigue funcionando y al volver a Trabajo sigue el resultado. */
    mockDb.forceApprove = 'published'
    mockDb.skipPublishedMemory = true
    mockDb.settings = { ...mockDb.settings, jira_browse_url: null }
    const region = await approveFromList()
    await userEvent.click(within(region).getByRole('button', { name: 'Ver la memoria' }))
    expect(within(zones()).getByRole('button', { name: 'Memoria' })).toHaveAttribute('aria-current', 'page')
    const main = await screen.findByRole('main', { name: 'Memoria elegida' })
    const alert = await within(main).findByRole('alert')
    expect(within(alert).getByRole('heading', { name: 'No se encuentra' })).toBeInTheDocument()
    expect(alert).toHaveTextContent('No existe esa memoria o no la puedes ver.')
    // La lista se ve igualmente.
    const list = screen.getByRole('complementary', { name: 'Memorias' })
    expect(await within(list).findByRole('button', { name: /DEMO-9001/ })).toBeInTheDocument()

    await userEvent.click(within(zones()).getByRole('button', { name: 'Trabajo' }))
    expect(screen.getByRole('region', { name: 'Publicado en Jira' })).toBeInTheDocument()
    expect(screen.queryByRole('complementary', { name: 'Memorias' })).toBeNull()

    await userEvent.click(within(zones()).getByRole('button', { name: 'Memoria' }))
    expect(await screen.findByText('Elige una memoria')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it.each(['published', 'partial'] as const)('test_%s_hu_leaves_its_memory_and_view_memory_opens_it', async (forced) => {
    /** Como `memorize`: publicar DEMO-3 (entera o con un vínculo fallido) deja su memoria, indexada y con el contenido de
     * la HU publicada; *Ver la memoria* la abre con su detalle y la marca en la lista, la primera. */
    mockDb.forceApprove = forced
    const region = await approveFromList()
    expect(mockDb.memories[0]).toMatchObject({ key: 'DEMO-3', project: 'DEMO', version: 2, indexed: true })
    await userEvent.click(within(region).getByRole('button', { name: 'Ver la memoria' }))
    const article = await screen.findByRole('article', { name: 'DEMO-3 · Memoria v2' })
    expect(within(article).getByText('Indexada')).toBeInTheDocument()
    expect(within(article).getByText(/^Renovar un préstamo./)).toBeInTheDocument()
    expect(within(article).getByText(/^CA-02: Renovación rechazada por reservas$/)).toBeInTheDocument()
    expect(within(article).getByRole('button', { name: 'Descargar la memoria' })).toBeInTheDocument()
    const list = screen.getByRole('complementary', { name: 'Memorias' })
    const rows = await within(list).findAllByRole('button', { name: /DEMO-/ })
    expect(rows[0]).toHaveTextContent('DEMO-3')
    expect(rows[0]).toHaveAttribute('aria-current', 'true')
    expect(within(list).getByRole('button', { name: /DEMO-9001/ })).toBeInTheDocument()
  })

  it('test_simulated_result_leaves_no_memory', async () => {
    /** Una simulación no escribe en Jira ni genera memoria. */
    await approveFromList()
    expect(mockDb.memories.map((item) => item.key)).toEqual(['DEMO-9001', 'DEMO-9002'])
  })

  it('test_simulated_result_in_app_has_no_view_memory', async () => {
    /** En la app, tras una simulación (por defecto) no hay *Ver la memoria*. */
    const region = await approveFromList()
    expect(within(region).queryByRole('button', { name: 'Ver la memoria' })).toBeNull()
  })
})
