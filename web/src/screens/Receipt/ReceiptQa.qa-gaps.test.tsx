// Huecos de prueba de QA 4 · Recibo (UI.md §6.4 y contrato §5): `review.error` en el recibo de una suite, versión
// siguiente tras iterar, contador, descartar, `approval_rejected`, plan vacío y publicación en curso.
// Datos sintéticos (DEMO-3, qa-demo, «(ficticio)»).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApproveIn, ConversationOut } from '../../api/types.ts'
import { FINGERPRINT_MISMATCH } from '../../mocks/handlers.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { mockSuiteConversation } from '../../mocks/qaSuite.ts'
import { openSuiteForDemo3 } from '../../test/qaFlow.tsx'
import { openEventStream } from '../../test/sse.ts'
import { ReceiptScreen } from './ReceiptScreen.tsx'
import { aiNotice } from './receiptText.ts'

const QA_REVIEW = mockSuiteConversation('DEMO-3')

const receipt = (version = 1) => screen.getByRole('region', { name: `Suite, versión ${version} lista para revisar` })
const operations = () => within(receipt()).getByRole('group', { name: /Qué se hará en Jira/ })
const approveButton = () => within(receipt()).getByRole('button', { name: 'Aprobar y publicar' })

function recordApprovals(): ApproveIn[] {
  const bodies: ApproveIn[] = []
  mockServer.events.on('request:start', async ({ request }) => {
    if (request.method === 'POST' && request.url.endsWith('/approve')) bodies.push((await request.clone().json()) as ApproveIn)
  })
  return bodies
}

async function openReceipt() {
  await openSuiteForDemo3()
  await userEvent.click(await screen.findByRole('button', { name: 'Revisar y aprobar' }))
  await screen.findByRole('region', { name: /^Suite, versión \d+ lista para revisar$/ })
}

function renderReceipt(conversation: ConversationOut) {
  const props = { onBack: vi.fn(), onDone: vi.fn(), onDiscarded: vi.fn(), onRestart: vi.fn() }
  render(<ReceiptScreen conversation={conversation} {...props} />)
  return props
}

afterEach(() => mockServer.events.removeAllListeners())

describe('QA 4 · review.error en el recibo de una suite (contrato §5.3)', () => {
  it('test_fingerprint_mismatch_shows_reason_and_resets_the_checkbox', async () => {
    // UI.md §5.3: respuesta rechazada → la revisión vuelve con `error`, que se muestra junto al recibo; se revisa entera de nuevo.
    mockDb.forceApprove = 'fingerprint'
    await openReceipt()
    await userEvent.click(within(operations()).getByRole('checkbox'))
    await userEvent.click(approveButton())
    const rejected = await within(receipt()).findByRole('alert')
    expect(rejected).toHaveTextContent('No se aprobó')
    expect(rejected).toHaveTextContent(FINGERPRINT_MISMATCH)
    expect(within(operations()).getByRole('checkbox')).not.toBeChecked()
    expect(operations()).toHaveTextContent('0 de 1 revisada')
    expect(approveButton()).toBeDisabled()
    // Sigue siendo el recibo de la suite.
    expect(screen.getByRole('heading', { level: 1, name: 'Pruebas de DEMO-3' })).toBeInTheDocument()
    expect(within(receipt()).getByRole('button', { name: 'Volver a la suite' })).toBeEnabled()
  })

  it('test_after_rejection_approving_again_sends_the_fingerprint_of_the_last_payload', async () => {
    // UI.md §5.4: la UI devuelve exactamente la huella del último `interrupt`; tras corregir, la suite se aprueba.
    mockDb.forceApprove = 'fingerprint'
    const bodies = recordApprovals()
    await openReceipt()
    await userEvent.click(within(operations()).getByRole('checkbox'))
    await userEvent.click(approveButton())
    await within(receipt()).findByRole('alert')
    mockDb.forceApprove = undefined
    await userEvent.click(within(operations()).getByRole('checkbox'))
    await userEvent.click(approveButton())
    expect(await screen.findByRole('region', { name: 'Publicación simulada' })).toBeInTheDocument()
    const fingerprint = QA_REVIEW.review?.fingerprint
    expect(fingerprint).toBe('7c'.repeat(32))
    expect(bodies).toEqual([{ fingerprint }, { fingerprint }])
  })

  it('test_review_error_with_html_is_shown_as_text', () => {
    // UI.md §5.3 y §7: el motivo llega del grafo y se muestra tal cual, como texto.
    const hostile = '<img src=x onerror=alert(1)> motivo ficticio'
    const conversation = structuredClone(QA_REVIEW)
    if (conversation.review) conversation.review.error = hostile
    const { container } = render(
      <ReceiptScreen conversation={conversation} onBack={vi.fn()} onDone={vi.fn()} onDiscarded={vi.fn()} onRestart={vi.fn()} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(hostile)
    expect(container.querySelector('img')).toBeNull()
  })
})

describe('QA 4 · versión, contador e historial', () => {
  it('test_receipt_after_iterating_shows_version_2_and_new_case_count', async () => {
    // UI.md §6.4: cabecera «versión 2 lista para revisar», «Crear N subtareas…» y el historial con las dos versiones.
    await openSuiteForDemo3()
    await userEvent.click(screen.getByRole('button', { name: 'Añade un caso de excepción' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await screen.findByText(/^Versión 2: añadí el CP-05/)
    await userEvent.click(screen.getByRole('button', { name: 'Revisar y aprobar' }))
    const region = await screen.findByRole('region', { name: 'Suite, versión 2 lista para revisar' })
    expect(within(region).getByRole('group', { name: /Qué se hará en Jira/ })).toHaveTextContent('Crear 5 subtareas en DEMO-3 con la etiqueta «caso-prueba»')
    const history = within(screen.getByRole('complementary', { name: 'Historial de la suite' })).getByRole('list', { name: 'Versiones de la suite' })
    const items = within(history).getAllByRole('listitem')
    expect(items.map((item) => item.querySelector('b')?.textContent)).toEqual(['Versión 2 generada', 'Versión 1 generada'])
    expect(items[0]).toHaveTextContent('5 casos · cobertura validada')
    // PA-326: la cobertura solo se conoce para la versión en revisión; la anterior, solo sus casos.
    expect(items[1]).toHaveTextContent('4 casos')
    expect(items[1]).not.toHaveTextContent(/cobertura validada|sin caso/)
  })

  it('test_back_to_suite_keeps_both_versions', async () => {
    // UI.md §6.4: *Volver a la suite* (iterate) vuelve a QA 3 con las versiones que había.
    await openSuiteForDemo3()
    await userEvent.click(screen.getByRole('button', { name: 'Añade un caso de excepción' }))
    await userEvent.click(screen.getByRole('button', { name: 'Enviar' }))
    await screen.findByText(/^Versión 2: añadí el CP-05/)
    await userEvent.click(screen.getByRole('button', { name: 'Revisar y aprobar' }))
    await userEvent.click(within(await screen.findByRole('region', { name: 'Suite, versión 2 lista para revisar' })).getByRole('button', { name: 'Volver a la suite' }))
    const panel = await screen.findByRole('complementary', { name: 'Suite de pruebas' })
    expect(within(within(panel).getByRole('group', { name: 'Versiones' })).getAllByRole('button').map((item) => item.textContent)).toEqual(['v1', 'v2'])
    expect(within(panel).getByRole('tab', { name: 'Casos (5)' })).toBeInTheDocument()
  })

  it('test_counter_and_approve_follow_the_single_checkbox', async () => {
    // UI.md §6.4 y §5.5: contador «N de M revisadas» y *Aprobar y publicar* solo con todas las casillas.
    renderReceipt(QA_REVIEW)
    expect(operations()).toHaveTextContent('0 de 1 revisada')
    expect(approveButton()).toBeDisabled()
    const box = within(operations()).getByRole('checkbox')
    await userEvent.click(box)
    expect(operations()).toHaveTextContent('Todo revisado')
    expect(approveButton()).toBeEnabled()
    await userEvent.click(box)
    expect(operations()).toHaveTextContent('0 de 1 revisada')
    expect(approveButton()).toBeDisabled()
  })

  it('test_checkbox_toggles_with_the_keyboard', async () => {
    // UI.md §6.4: marcar cada operación también con el teclado.
    renderReceipt(QA_REVIEW)
    const box = within(operations()).getByRole('checkbox')
    box.focus()
    await userEvent.keyboard(' ')
    expect(box).toBeChecked()
    expect(approveButton()).toBeEnabled()
  })

  it('test_receipt_phase_is_3_review', () => {
    // UI.md §6.4: «Fase 3 de 4».
    renderReceipt(QA_REVIEW)
    expect(screen.getByRole('img', { name: 'Avance: fase 3 de 4, Revisión' })).toBeInTheDocument()
  })

  it('test_ai_notice_in_qa_uses_singular_and_never_promises_retry', () => {
    // UI.md §6.4 y RNF-13: aviso de IA; sin «podrás reintentar solo esa» hasta PA-05.
    expect(aiNotice(1, true)).toBe('Generado con IA a partir de la HU y 1 fuente. Revisa cada operación antes de aprobar. Si una subtarea falla, las demás se mantienen.')
    expect(aiNotice(0, true)).not.toMatch(/reintentar/)
  })

  it('test_suite_with_empty_plan_has_nothing_to_approve', () => {
    // UI.md §5.5: sin operaciones no hay nada que aprobar.
    const conversation = structuredClone(QA_REVIEW)
    if (conversation.review) conversation.review.plan = []
    renderReceipt(conversation)
    expect(screen.getByText('Esta suite no tiene operaciones de Jira que aprobar.')).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()
  })
})

describe('QA 4 · descartar, approval_rejected y publicación en curso', () => {
  it('test_discard_from_qa_receipt_confirms_with_suite_text_and_returns_home', async () => {
    // UI.md §6.4: *Descartar* (discard) con confirmación que habla de la suite.
    await openReceipt()
    await userEvent.click(within(receipt()).getByRole('button', { name: 'Descartar' }))
    expect(within(receipt()).getByRole('group', { name: 'Confirmar el descarte' })).toHaveTextContent(
      '¿Descartar la suite? No se publicará nada en Jira y la conversación terminará.',
    )
    await userEvent.click(within(receipt()).getByRole('button', { name: 'Sí, descartar' }))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('test_approval_rejected_in_qa_offers_restart', async () => {
    // UI.md §5.3: rechazo del registro de aprobaciones → falla cerrado y se ofrece empezar de nuevo.
    mockDb.forceApprove = 'approval_rejected'
    await openReceipt()
    await userEvent.click(within(operations()).getByRole('checkbox'))
    await userEvent.click(approveButton())
    const card = await within(receipt()).findByRole('alert')
    expect(card).toHaveTextContent('La aprobación no corresponde a la versión revisada; empieza de nuevo.')
    await userEvent.click(within(card).getByRole('button'))
    expect(await screen.findByRole('heading', { level: 1, name: '¿En qué trabajamos hoy?' })).toBeInTheDocument()
  })

  it('test_while_publishing_the_suite_actions_are_disabled', async () => {
    // UI.md §6.4 y §5: mientras `publish` trabaja no se puede volver, descartar ni aprobar otra vez.
    await openReceipt()
    mockServer.use(http.get('/api/v1/conversations/:id/events', openEventStream))
    await userEvent.click(within(operations()).getByRole('checkbox'))
    await userEvent.click(approveButton())
    expect(await within(receipt()).findByText('Aprobando y publicando…')).toBeInTheDocument()
    expect(within(receipt()).getByRole('button', { name: 'Volver a la suite' })).toBeDisabled()
    expect(within(receipt()).getByRole('button', { name: 'Descartar' })).toBeDisabled()
    expect(approveButton()).toBeDisabled()
    expect(within(operations()).getByRole('checkbox')).toBeDisabled()
  })
})
