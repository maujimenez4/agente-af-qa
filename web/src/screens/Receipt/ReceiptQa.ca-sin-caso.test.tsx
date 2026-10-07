// T-56 · pulido final, bloque 2: un CA sin caso bloquea *Aprobar y publicar* en el recibo de la suite (QA 4, UI.md
// §6.4). Las RN sin caso no bloquean; con `uncovered` null o todo cubierto se aprueba; si el backend rechaza igualmente,
// su `review.error` se muestra tal cual. Sin reloj (PA-127). Datos sintéticos (DEMO-3, qa-demo, af-demo).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from '../../api/client.ts'
import type { ConversationOut, ReviewPayload } from '../../api/types.ts'
import { example } from '../../mocks/examples.ts'
import { uncoveredCriteriaRejection } from '../../mocks/handlers.ts'
import { mockDb, mockServer } from '../../mocks/node.ts'
import { mockSuiteConversation } from '../../mocks/qaSuite.ts'
import { openSuiteInReview } from '../../test/qaFlow.tsx'
import { ReceiptScreen } from './ReceiptScreen.tsx'
import { MISSING_CASES_REASON } from './receiptText.ts'

const CSRF = 'csrf-ficticio'

const receipt = (version = 1) => screen.getByRole('region', { name: `Suite, versión ${version} lista para revisar` })
const operations = () => within(receipt()).getByRole('group', { name: /Qué se hará en Jira/ })
const approveButton = () => within(receipt()).getByRole('button', { name: 'Aprobar y publicar' })
const missingNotice = () => within(receipt()).queryByText(/Faltan? (un caso|casos) para/)

/** Cuenta los POST /approve que salen de la pantalla. */
function countApprovals(): { count: number } {
  const seen = { count: 0 }
  mockServer.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && request.url.endsWith('/approve')) seen.count += 1
  })
  return seen
}

function renderReceipt(conversation: ConversationOut) {
  const props = { onBack: vi.fn(), onDone: vi.fn(), onDiscarded: vi.fn(), onRestart: vi.fn() }
  render(<ReceiptScreen conversation={conversation} {...props} />)
  return props
}

/**
 * Suite de DEMO-3 en revisión en la API simulada (sesión qa-demo), sin recorrer QA 1 a QA 3. `server` fija el
 * `uncovered` de la revisión del servidor (lo que decide la aprobación); la conversación devuelta es la del GET.
 */
async function suiteFromApi(server?: ReviewPayload['uncovered']): Promise<ConversationOut> {
  mockDb.session = { username: 'qa-demo', role: 'qa', csrf: CSRF }
  setCsrfToken(CSRF)
  const url = (path: string) => new URL(`/api/v1${path}`, window.location.origin)
  const created = await fetch(url('/conversations'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF },
    body: JSON.stringify({ origin: { kind: 'story', key: 'DEMO-3', project: 'DEMO' }, flow: 'tests', excluded_sources: [], feedback: [] }),
  })
  const { id } = (await created.json()) as { id: string }
  await (await fetch(url(`/conversations/${id}/events`))).text()
  const review = mockDb.runs.get(id)?.conversation.review
  if (review && server !== undefined) review.uncovered = server
  return (await (await fetch(url(`/conversations/${id}`))).json()) as ConversationOut
}

afterEach(() => mockServer.events.removeAllListeners())

describe('QA 4 · un CA sin caso bloquea Aprobar y publicar', () => {
  it('test_simulated_uncovered_shows_notice_and_keeps_approve_disabled', async () => {
    /** Criterio 1: con ?simular=sin-cubrir, aviso «Falta un caso para CA-03.», *Aprobar* desactivado y sin POST /approve. */
    mockDb.forceCoverage = 'gaps'
    const approvals = countApprovals()
    await openSuiteInReview()
    await userEvent.click(screen.getByRole('button', { name: 'Revisar y aprobar' }))
    await screen.findByRole('region', { name: 'Suite, versión 1 lista para revisar' })
    const notice = within(receipt()).getByRole('note')
    expect(notice).toHaveTextContent(`Falta un caso para CA-03. ${MISSING_CASES_REASON}`)
    await userEvent.click(within(operations()).getByRole('checkbox'))
    expect(operations()).toHaveTextContent('Todo revisado')
    expect(approveButton()).toBeDisabled()
    await userEvent.click(approveButton())
    expect(approvals.count).toBe(0)
    // Sigue en el recibo, sin rechazo ni publicación.
    expect(within(receipt()).queryByRole('alert')).toBeNull()
    expect(within(receipt()).queryByText('Aprobando y publicando…')).toBeNull()
  })

  it('test_disabled_approve_is_described_by_the_missing_cases_notice', async () => {
    /** Criterio 1: la descripción accesible de *Aprobar y publicar* incluye el aviso. */
    renderReceipt(mockSuiteConversation('DEMO-3', 'gaps'))
    await userEvent.click(within(operations()).getByRole('checkbox'))
    expect(approveButton()).toBeDisabled()
    expect(approveButton()).toHaveAccessibleDescription(`Falta un caso para CA-03. ${MISSING_CASES_REASON}`)
    const describedBy = approveButton().getAttribute('aria-describedby') ?? ''
    expect(document.getElementById(describedBy)).toContainElement(within(receipt()).getByRole('note'))
  })

  it('test_notice_is_visible_before_checking_and_stays_after_unchecking', async () => {
    /** Criterio 1 (límite): el aviso no depende de las casillas; *Aprobar* nunca se activa. */
    renderReceipt(mockSuiteConversation('DEMO-3', 'gaps'))
    expect(missingNotice()).toHaveTextContent('Falta un caso para CA-03.')
    expect(approveButton()).toBeDisabled()
    const box = within(operations()).getByRole('checkbox')
    await userEvent.click(box)
    await userEvent.click(box)
    await userEvent.click(box)
    expect(missingNotice()).toBeInTheDocument()
    expect(approveButton()).toBeDisabled()
  })

  it('test_several_uncovered_criteria_are_listed_in_the_notice', async () => {
    /** Criterio 1 y 6: con dos CA sin caso, «Faltan casos para CA-02 y CA-03.». */
    const conversation = mockSuiteConversation('DEMO-3')
    if (conversation.review) conversation.review.uncovered = { criteria: ['CA-02', 'CA-03'], rules: ['RN-03'] }
    renderReceipt(conversation)
    await userEvent.click(within(operations()).getByRole('checkbox'))
    expect(within(receipt()).getByRole('note')).toHaveTextContent('Faltan casos para CA-02 y CA-03.')
    expect(approveButton()).toHaveAccessibleDescription(/^Faltan casos para CA-02 y CA-03\./)
    expect(approveButton()).toBeDisabled()
  })

  it('test_keyboard_cannot_approve_with_uncovered_criterion', async () => {
    /** Criterio 1 (negativo): ni con el teclado sale un POST /approve. */
    const approvals = countApprovals()
    renderReceipt(mockSuiteConversation('DEMO-3', 'gaps'))
    within(operations()).getByRole('checkbox').focus()
    await userEvent.keyboard(' ')
    await userEvent.tab()
    await userEvent.keyboard('{Enter}')
    expect(approvals.count).toBe(0)
  })
})

describe('QA 4 · sin CA sin caso, se aprueba', () => {
  it('test_only_uncovered_rules_has_no_notice_and_approves', async () => {
    /** Criterio 2: solo RN-03 sin caso → sin aviso; *Aprobar* se activa al marcar y la suite se aprueba. */
    const approvals = countApprovals()
    const conversation = await suiteFromApi({ criteria: [], rules: ['RN-03'] })
    expect(conversation.review?.uncovered).toEqual({ criteria: [], rules: ['RN-03'] })
    const { onDone } = renderReceipt(conversation)
    expect(missingNotice()).toBeNull()
    expect(within(receipt()).queryByRole('note')).toBeNull()
    expect(approveButton()).toBeDisabled()
    await userEvent.click(within(operations()).getByRole('checkbox'))
    expect(approveButton()).toBeEnabled()
    expect(approveButton()).not.toHaveAttribute('aria-describedby')
    await userEvent.click(approveButton())
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(onDone.mock.calls[0]?.[0]).toMatchObject({ state: 'simulated', result: { simulated: true } })
    expect(approvals.count).toBe(1)
  })

  it.each([
    ['uncovered null (no se sabe)', 'unknown'],
    ['todo cubierto', undefined],
  ] as const)('test_%s_has_no_notice_and_approves', async (_name, forced) => {
    /** Criterio 3: con `uncovered` null o vacío, sin aviso y se puede aprobar. */
    mockDb.forceCoverage = forced
    const conversation = await suiteFromApi()
    expect(conversation.review?.uncovered).toEqual(forced === 'unknown' ? null : { criteria: [], rules: [] })
    const { onDone } = renderReceipt(conversation)
    expect(missingNotice()).toBeNull()
    await userEvent.click(within(operations()).getByRole('checkbox'))
    expect(approveButton()).toBeEnabled()
    await userEvent.click(approveButton())
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(onDone.mock.calls[0]?.[0]).toMatchObject({ state: 'simulated' })
  })

  it('test_uncovered_without_field_has_no_notice', async () => {
    /** Criterio 3 (límite): sin el campo `uncovered`, igual que null. */
    const conversation = mockSuiteConversation('DEMO-3')
    if (conversation.review) Reflect.deleteProperty(conversation.review, 'uncovered')
    renderReceipt(conversation)
    expect(missingNotice()).toBeNull()
    await userEvent.click(within(operations()).getByRole('checkbox'))
    expect(approveButton()).toBeEnabled()
  })

  it('test_story_receipt_never_shows_missing_cases_notice', async () => {
    /** Criterio 1 (negativo): en el recibo de una HU (no suite) nunca hay aviso aunque llegue `uncovered` con CA. */
    const conversation = example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200')
    if (conversation.review) conversation.review.uncovered = { criteria: ['CA-03'], rules: [] }
    render(<ReceiptScreen conversation={conversation} onBack={vi.fn()} onDone={vi.fn()} onDiscarded={vi.fn()} onRestart={vi.fn()} />)
    expect(screen.queryByText(/Faltan? (un caso|casos) para/)).toBeNull()
    const region = screen.getByRole('region', { name: /^Versión \d+ lista para revisar$/ })
    for (const box of within(region).getAllByRole('checkbox')) await userEvent.click(box)
    expect(within(region).getByRole('button', { name: 'Aprobar y publicar' })).toBeEnabled()
  })
})

describe('QA 4 · el backend rechaza igualmente', () => {
  it('test_backend_rejection_shows_not_approved_and_review_error_as_is', async () => {
    /**
     * Criterio 4: la web no sabe qué falta (`uncovered` null) pero el backend tiene CA-03 sin caso: responde
     * `review_ready` con `review.error`; el recibo muestra «No se aprobó» y el mensaje tal cual.
     */
    const conversation = await suiteFromApi(structuredClone({ criteria: ['CA-03'], rules: ['RN-03'] }))
    if (conversation.review) conversation.review.uncovered = null
    const { onDone } = renderReceipt(conversation)
    expect(missingNotice()).toBeNull()
    await userEvent.click(within(operations()).getByRole('checkbox'))
    await userEvent.click(approveButton())
    const rejected = await within(receipt()).findByRole('alert')
    expect(rejected).toHaveTextContent('No se aprobó')
    expect(rejected).toHaveTextContent(uncoveredCriteriaRejection(['CA-03']))
    expect(onDone).not.toHaveBeenCalled()
    // Se revisa entera de nuevo; la revisión devuelta sí trae CA-03 sin caso, así que ahora se bloquea.
    expect(within(operations()).getByRole('checkbox')).not.toBeChecked()
    expect(missingNotice()).toHaveTextContent('Falta un caso para CA-03.')
    await userEvent.click(within(operations()).getByRole('checkbox'))
    expect(approveButton()).toBeDisabled()
  })

  it('test_backend_rejection_text_is_shown_verbatim_without_html', () => {
    /** Criterio 4: `review.error` se muestra tal cual, como texto, junto al aviso del CA sin caso. */
    const hostile = '<img src=x onerror=alert(1)> CA-03 sin caso (ficticio)'
    const conversation = mockSuiteConversation('DEMO-3', 'gaps')
    if (conversation.review) conversation.review.error = hostile
    const { container } = render(
      <ReceiptScreen conversation={conversation} onBack={vi.fn()} onDone={vi.fn()} onDiscarded={vi.fn()} onRestart={vi.fn()} />,
    )
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('No se aprobó')
    expect(alert).toHaveTextContent(hostile)
    expect(container.querySelector('img')).toBeNull()
    expect(missingNotice()).toHaveTextContent('Falta un caso para CA-03.')
  })
})
