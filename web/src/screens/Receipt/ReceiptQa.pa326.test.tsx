// PA-326 · historial de la suite en el recibo (QA 4, UI.md §6.4): «N casos · <coverageNote>» solo para la versión en
// revisión; con `uncovered` null, ausente o en versiones anteriores, solo «N casos». Datos sintéticos (DEMO-3).
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ConversationOut } from '../../api/types.ts'
import { mockSuiteConversation, nextSuiteVersion } from '../../mocks/qaSuite.ts'
import { ReceiptScreen } from './ReceiptScreen.tsx'

function renderReceipt(conversation: ConversationOut) {
  render(<ReceiptScreen conversation={conversation} onBack={vi.fn()} onDone={vi.fn()} onDiscarded={vi.fn()} onRestart={vi.fn()} />)
  const history = within(screen.getByRole('complementary', { name: 'Historial de la suite' })).getByRole('list', { name: 'Versiones de la suite' })
  return within(history).getAllByRole('listitem')
}

/** El texto de la línea de detalle de una versión (sin el título «Versión N generada»). */
const detail = (item: HTMLElement | undefined) => item?.querySelector('span')?.textContent ?? ''

describe('Recibo · historial de la suite con coverageNote (PA-326)', () => {
  it('test_history_complete_says_cases_and_coverage_validated', () => {
    const [only] = renderReceipt(mockSuiteConversation('DEMO-3'))
    expect(only).toHaveTextContent('4 casos · cobertura validada')
  })

  it('test_history_gaps_says_cases_and_what_has_no_case', () => {
    const [only] = renderReceipt(mockSuiteConversation('DEMO-3', 'gaps'))
    expect(only).toHaveTextContent('4 casos · 1 CA y 1 RN sin caso')
    expect(only).not.toHaveTextContent('cobertura validada')
  })

  it('test_history_unknown_says_only_the_cases', () => {
    const [only] = renderReceipt(mockSuiteConversation('DEMO-3', 'unknown'))
    expect(detail(only)).toMatch(/^4 casos(, |$)/)
    expect(only).not.toHaveTextContent(/cobertura validada|sin caso/)
  })

  it('test_history_without_uncovered_field_says_only_the_cases', () => {
    const conversation = mockSuiteConversation('DEMO-3')
    if (conversation.review) Reflect.deleteProperty(conversation.review, 'uncovered')
    const [only] = renderReceipt(conversation)
    expect(only).toHaveTextContent('4 casos')
    expect(only).not.toHaveTextContent(/cobertura validada|sin caso/)
  })

  it.each([
    ['completa', undefined, '5 casos · cobertura validada'],
    // Al iterar, la API simulada cubre el CA que faltaba; RN-03 sigue sin caso.
    ['con huecos', 'gaps', '5 casos · 1 RN sin caso'],
  ] as const)('test_history_earlier_version_has_no_note_when_review_is_%s', (_name, forced, latest) => {
    const conversation = nextSuiteVersion(mockSuiteConversation('DEMO-3', forced), 'Añade un caso negativo')
    const [v2, v1] = renderReceipt(conversation)
    expect(v2?.querySelector('b')).toHaveTextContent('Versión 2 generada')
    expect(v2).toHaveTextContent(latest)
    expect(v1?.querySelector('b')).toHaveTextContent('Versión 1 generada')
    expect(v1).toHaveTextContent('4 casos')
    expect(v1).not.toHaveTextContent(/cobertura validada|sin caso/)
  })
})
