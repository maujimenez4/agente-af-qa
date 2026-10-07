// QA 3 · Iterar la suite con un CA sin caso (bloquea la aprobación en el recibo): aviso en el panel, *Revisar y
// aprobar* sigue activo con el aviso como descripción, y una sugerencia que pide el caso. Las RN sin caso no lo
// provocan. Datos sintéticos (DEMO-3, qa-demo, CA-03 y RN-03 ficticios).
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { mockDb } from '../../mocks/node.ts'
import { MOCK_UNCOVERED } from '../../mocks/qaSuite.ts'
import { openSuiteInReview } from '../../test/qaFlow.tsx'
import { addCasesSuggestion, MISSING_CASES_ITERATE_REASON, QA_SUGGESTIONS } from './iterateText.ts'

const panel = () => screen.getByRole('complementary', { name: 'Suite de pruebas' })
const suggestions = () => screen.getByRole('list', { name: 'Cambios sugeridos' })
const NOTICE = `Falta un caso para CA-03. ${MISSING_CASES_ITERATE_REASON}`

describe('QA 3 · un CA sin caso', () => {
  it('test_iterate_warns_missing_case_and_keeps_review_enabled_with_description', async () => {
    mockDb.forceCoverage = 'gaps'
    await openSuiteInReview()
    const notice = within(panel()).getByRole('note')
    expect(notice).toHaveTextContent(NOTICE)
    // En todas las pestañas: va encima del contenido.
    await userEvent.click(within(panel()).getByRole('tab', { name: 'Estrategia' }))
    expect(within(panel()).getByRole('note')).toHaveTextContent('Falta un caso para CA-03.')
    const review = within(panel()).getByRole('button', { name: 'Revisar y aprobar' })
    expect(review).toBeEnabled()
    expect(review).toHaveAccessibleDescription(NOTICE)
  })

  it('test_iterate_suggestion_fills_composer_with_missing_case_request', async () => {
    mockDb.forceCoverage = 'gaps'
    await openSuiteInReview()
    const items = within(suggestions()).getAllByRole('button').map((item) => item.textContent)
    expect(items).toEqual(['Añade un caso para CA-03', ...QA_SUGGESTIONS])
    await userEvent.click(within(suggestions()).getByRole('button', { name: 'Añade un caso para CA-03' }))
    expect(screen.getByRole('textbox', { name: /Pide un cambio a la suite/ })).toHaveValue('Añade un caso para CA-03')
  })

  it('test_iterate_without_missing_criteria_has_no_notice_nor_suggestion', async () => {
    // Todo cubierto (el ejemplo del contrato): ni aviso ni sugerencia; *Revisar y aprobar* sin descripción.
    await openSuiteInReview()
    expect(within(panel()).queryByRole('note')).not.toBeInTheDocument()
    expect(within(suggestions()).getAllByRole('button').map((item) => item.textContent)).toEqual([...QA_SUGGESTIONS])
    expect(within(panel()).getByRole('button', { name: 'Revisar y aprobar' })).not.toHaveAttribute('aria-describedby')
  })

  it('test_iterate_unknown_coverage_has_no_notice', async () => {
    mockDb.forceCoverage = 'unknown'
    await openSuiteInReview()
    expect(within(panel()).queryByRole('note')).not.toBeInTheDocument()
    expect(within(suggestions()).getAllByRole('button')).toHaveLength(QA_SUGGESTIONS.length)
  })
})

describe('addCasesSuggestion', () => {
  it('test_add_cases_suggestion_singular_plural_and_none', () => {
    expect(addCasesSuggestion([])).toBeUndefined()
    expect(addCasesSuggestion(['CA-02'])).toBe('Añade un caso para CA-02')
    expect(addCasesSuggestion(['CA-02', 'CA-03'])).toBe('Añade casos para CA-02 y CA-03')
    expect(addCasesSuggestion(['CA-01', 'CA-02', 'CA-03'])).toBe('Añade casos para CA-01, CA-02 y CA-03')
  })

  it('test_mock_uncovered_has_one_criterion_and_one_rule', () => {
    // Las pruebas de arriba dependen de que `?simular=sin-cubrir` dé CA-03 (bloquea) y RN-03 (solo avisa).
    expect(MOCK_UNCOVERED).toEqual({ criteria: ['CA-03'], rules: ['RN-03'] })
  })
})
