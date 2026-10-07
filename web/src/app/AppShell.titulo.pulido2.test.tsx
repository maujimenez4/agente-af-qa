// PA-317 · huecos del título antiguo (pulido 2 de T-56): una conversación guardada antes de PA-317 («Nueva HU en
// DEMO-1») se muestra normalizada («HU nueva en la épica DEMO-1») también al retomarla terminada (descartada) o
// generando, no solo en revisión. El SSE se retiene (PA-127, sin reloj). Datos sintéticos (DEMO, af-demo).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse, type JsonBodyType } from 'msw'
import { describe, expect, it } from 'vitest'
import { App } from '../App.tsx'
import type { ConversationOut } from '../api/types.ts'
import { example } from '../mocks/examples.ts'
import { mockDb, mockServer } from '../mocks/node.ts'
import { holdNextEventStream } from '../test/sse.ts'

const OLD_TITLE = 'Nueva HU en DEMO-1'
const SHOWN = 'HU nueva en la épica DEMO-1'

/** Pone el título antiguo a la primera conversación de la lista y hace que la API la devuelva en `state`. */
function seedOldTitle(state: ConversationOut['state']): string {
  const summary = mockDb.conversations[0]
  if (!summary) throw new Error('La API simulada no tiene conversaciones')
  Object.assign(summary, { title: OLD_TITLE, origin_kind: 'epic', origin_key: 'DEMO-1', mode: 'story', review_state: null })
  const base = example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200')
  const conversation: ConversationOut = { ...base, id: summary.thread_id, title: OLD_TITLE, state, review: state === 'in_review' ? base.review : null }
  mockServer.use(http.get(`/api/v1/conversations/${summary.thread_id}`, () => HttpResponse.json(conversation as unknown as JsonBodyType)))
  return summary.thread_id
}

async function openOldFromList() {
  mockDb.session = { username: 'af-demo', role: 'functional', csrf: 'csrf-ficticio' }
  render(<App />)
  const list = await screen.findByRole('complementary', { name: 'Conversaciones' })
  const item = await within(list).findByRole('button', { name: new RegExp(SHOWN) })
  expect(within(list).queryByText(OLD_TITLE)).toBeNull()
  await userEvent.click(item)
}

describe('Título antiguo normalizado al retomar (PA-317, pulido 2)', () => {
  it('test_discarded_old_title_shown_normalized_in_heading_and_list', async () => {
    /** PA-317: una conversación descartada con título antiguo se titula «HU nueva en la épica DEMO-1». */
    seedOldTitle('discarded')
    await openOldFromList()
    expect(await screen.findByRole('heading', { level: 1, name: SHOWN })).toBeInTheDocument()
    expect(screen.getByText('Propuesta descartada: no se publicó nada en Jira.')).toBeInTheDocument()
    expect(screen.queryByText(new RegExp(OLD_TITLE))).toBeNull()
  })

  it('test_error_old_title_shown_normalized_in_heading', async () => {
    /** PA-317: una conversación en error con título antiguo también se titula normalizada (tarjeta de error). */
    seedOldTitle('error')
    await openOldFromList()
    expect(await screen.findByRole('heading', { level: 1, name: SHOWN })).toBeInTheDocument()
    expect(screen.queryByText(new RegExp(OLD_TITLE))).toBeNull()
  })

  it('test_generating_old_title_shown_normalized_in_header_and_chat', async () => {
    /** PA-317: retomada generando, la cabecera y el evento «Generar propuesta · …» usan el título normalizado. */
    seedOldTitle('generating')
    holdNextEventStream()
    await openOldFromList()
    expect(await screen.findByRole('heading', { level: 1, name: SHOWN })).toBeInTheDocument()
    expect(screen.getByText(`Generar propuesta · ${SHOWN}`)).toBeInTheDocument()
    expect(screen.queryByText(new RegExp(OLD_TITLE))).toBeNull()
  })
})
