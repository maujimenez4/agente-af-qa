// Editar a mano, pulido final (T-56, PA-344): *Reintentar* tras un error HTTP al guardar usa `saveRef`. Si el editor
// no se puede guardar tal como está (un campo obligatorio vaciado) o ya se cerró, la tarjeta se cierra y no sale un
// segundo POST /edit. Con la App y la API simulada (MSW). Datos sintéticos (DEMO-3, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const NEW_TITLE = 'Renovar un préstamo ficticio'

const log = () => screen.getByRole('log', { name: 'Conversación' })
const editor = () => screen.getByRole('complementary', { name: 'Editar a mano' })
const titleInput = () => within(editor()).getByLabelText('Título')

/** Cuenta los POST /edit que llegan a la API simulada. */
function countEdits() {
  const seen = { count: 0 }
  mockServer.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname.endsWith('/edit')) seen.count += 1
  })
  return seen
}

/** Abre DEMO-3, edita el título y guarda contra un 503: queda la tarjeta con *Reintentar* y el editor abierto. */
async function editAndFailWith503() {
  mockServer.use(
    http.post(
      '/api/v1/conversations/:id/edit',
      () => HttpResponse.json({ error: { code: 'service_unavailable', message: 'Servicio ficticio caído.', retry_after: null } }, { status: 503 }),
      { once: true },
    ),
  )
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  const proposal = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(proposal).getByRole('button', { name: 'Editar a mano' }))
  await userEvent.clear(titleInput())
  await userEvent.type(titleInput(), NEW_TITLE)
  await userEvent.click(within(editor()).getByRole('button', { name: 'Guardar la versión 3' }))
  const card = await within(log()).findByRole('alert')
  expect(within(card).getByRole('heading', { name: 'Servicio no disponible' })).toBeInTheDocument()
  return card
}

afterEach(() => {
  mockServer.events.removeAllListeners()
  mockServer.resetHandlers()
})

describe('Iterar · Reintentar cuando el editor no se puede guardar (PA-344)', () => {
  it('test_retry_closes_card_without_second_post_when_required_field_emptied', async () => {
    /** PA-344 (negativa): tras un 503, con el título vaciado, *Reintentar* cierra la tarjeta y no hay segundo POST /edit. */
    const edits = countEdits()
    const card = await editAndFailWith503()
    expect(edits.count).toBe(1)
    await userEvent.clear(titleInput())
    expect(within(editor()).getAllByText('La HU necesita un título.').length).toBeGreaterThan(0)
    await userEvent.click(within(card).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(within(log()).queryByRole('alert')).toBeNull())
    expect(edits.count).toBe(1)
    // El editor sigue abierto con lo escrito (vacío) y el error a la vista: no se pierde nada.
    expect(titleInput()).toHaveValue('')
    expect(within(editor()).getByRole('button', { name: 'Guardar la versión 3' })).toBeDisabled()
  })

  it('test_retry_closes_card_without_post_when_editor_reverted_to_original', async () => {
    /** PA-344 (límite): tras un 503, si se deshace el cambio (HU igual a la versión 2), *Reintentar* no envía nada. */
    const edits = countEdits()
    const card = await editAndFailWith503()
    await userEvent.clear(titleInput())
    await userEvent.type(titleInput(), 'Renovar un préstamo')
    await userEvent.click(within(card).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(within(log()).queryByRole('alert')).toBeNull())
    expect(edits.count).toBe(1)
    expect(editor()).toBeInTheDocument()
  })

  it('test_retry_closes_card_without_post_when_editor_already_closed', async () => {
    /** PA-344: tras un 503, si se sale del editor (*Cancelar* + «Sí, descartar»), *Reintentar* solo cierra la tarjeta. */
    const edits = countEdits()
    const card = await editAndFailWith503()
    await userEvent.click(within(editor()).getByRole('button', { name: 'Cancelar' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sí, descartar' }))
    expect(screen.queryByRole('heading', { name: 'Editar a mano', hidden: true })).toBeNull()
    await userEvent.click(within(card).getByRole('button', { name: 'Reintentar' }))
    await waitFor(() => expect(within(log()).queryByRole('alert')).toBeNull())
    expect(edits.count).toBe(1)
    const proposal = screen.getByRole('complementary', { name: 'Propuesta de HU' })
    expect(within(proposal).getByRole('button', { name: 'Versión 2' })).toHaveAttribute('aria-pressed', 'true')
  })
})
