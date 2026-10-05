// Seguridad del recibo (security-reviewer, bloque B): un solo POST /approve y el texto de la API como texto.
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import examples from '../../api/examples.json'
import type { ConversationOut } from '../../api/types.ts'
import { App } from '../../App.tsx'
import { mockDb, mockServer } from '../../mocks/node.ts'

const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const INJECTION = '<img src=x onerror=alert(1)> texto ficticio'

async function openReceipt() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  await userEvent.click(await within(list).findByRole('button', { name: /Evolucionar DEMO-3/ }))
  const panel = await screen.findByRole('complementary', { name: 'Propuesta de HU' })
  await userEvent.click(within(panel).getByRole('button', { name: 'Revisar y aprobar' }))
  return screen.findByRole('region', { name: /lista para revisar/ })
}

afterEach(() => mockServer.events.removeAllListeners())

describe('Recibo · seguridad', () => {
  it('un doble clic en *Aprobar y publicar* envía un solo POST /approve', async () => {
    let approvals = 0
    mockServer.events.on('request:start', ({ request }) => {
      if (new URL(request.url).pathname.endsWith('/approve')) approvals += 1
    })
    await openReceipt()
    const operations = screen.getByRole('group', { name: /Qué se hará en Jira/ })
    for (const box of within(operations).getAllByRole('checkbox')) await userEvent.click(box)
    await userEvent.dblClick(screen.getByRole('button', { name: 'Aprobar y publicar' }))
    await screen.findByText(/Publicación simulada/)
    expect(approvals).toBe(1)
  })

  it('review.error y el detalle de una operación desconocida se pintan como texto, nunca como HTML', async () => {
    const review = EXAMPLE.review
    if (!review) throw new Error('El ejemplo necesita review')
    mockServer.use(
      http.get('/api/v1/conversations/:id', () =>
        HttpResponse.json({ ...EXAMPLE, review: { ...review, error: INJECTION, plan: [{ op: 'otra_cosa', detalle: INJECTION }] } }),
      ),
    )
    const region = await openReceipt()
    expect(within(region).getByRole('alert')).toHaveTextContent(INJECTION)
    expect(within(region).getByText(`detalle: ${INJECTION}`)).toBeInTheDocument()
    expect(region.querySelector('img')).toBeNull()
  })
})
