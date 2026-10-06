// PA-326 (T-56): qué CA y RN quedan sin caso (`ReviewPayload.uncovered`) en los textos de la suite y en la pestaña
// Cobertura, con la descarga de la matriz (`coverage_md`). Datos sintéticos (DEMO-3, CA-03/RN-03 ficticios).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReviewPayload } from '../../api/types.ts'
import { mockCoverageMd, mockSuite } from '../../mocks/qaSuite.ts'
import * as download from '../../security/download.ts'
import { CoverageView } from './SuiteViews.tsx'
import { coverageBadge, coverageMatrix, coverageNote, suiteCoverage, suiteSummary, uncoveredLabel, UNKNOWN_COVERAGE, type SuiteCoverage } from './suiteText.ts'

const SUITE = mockSuite('DEMO-3')
const MATRIX = mockCoverageMd(SUITE)
const GAPS: SuiteCoverage = { kind: 'gaps', criteria: ['CA-03'], rules: ['RN-03'] }
const asUncovered = (value: unknown) => value as ReviewPayload['uncovered']

afterEach(() => vi.restoreAllMocks())

describe('suiteCoverage', () => {
  it('test_suite_coverage_is_unknown_when_uncovered_is_null_or_missing', () => {
    /** PA-326: null o sin el campo → no se sabe. */
    expect(suiteCoverage(null)).toEqual({ kind: 'unknown' })
    expect(suiteCoverage(undefined)).toEqual({ kind: 'unknown' })
  })

  it('test_suite_coverage_is_complete_when_both_lists_are_empty', () => {
    /** PA-326: listas vacías → todo cubierto. */
    expect(suiteCoverage({ criteria: [], rules: [] })).toEqual({ kind: 'complete' })
  })

  it('test_suite_coverage_lists_gaps_when_there_are_items', () => {
    /** PA-326: con elementos → los CA y RN sin caso, en su orden. */
    expect(suiteCoverage({ criteria: ['CA-03', 'CA-04'], rules: ['RN-03'] })).toEqual({ kind: 'gaps', criteria: ['CA-03', 'CA-04'], rules: ['RN-03'] })
    expect(suiteCoverage({ criteria: [], rules: ['RN-03'] })).toEqual({ kind: 'gaps', criteria: [], rules: ['RN-03'] })
    expect(suiteCoverage({ criteria: ['CA-03'], rules: [] })).toEqual({ kind: 'gaps', criteria: ['CA-03'], rules: [] })
  })

  it.each([
    ['un objeto vacío', {}],
    ['sin rules', { criteria: [] }],
    ['sin criteria', { rules: [] }],
    ['criteria no es una lista', { criteria: 'CA-03', rules: [] }],
    ['rules es null', { criteria: [], rules: null }],
    ['rules es un objeto', { criteria: [], rules: { 0: 'RN-03' } }],
    ['una cadena', 'CA-03'],
    ['un número', 0],
    ['una lista', ['CA-03']],
  ])('test_suite_coverage_is_unknown_when_malformed_%s', (_name, value) => {
    /** PA-326: lo mal formado no se toma por «todo cubierto». */
    expect(suiteCoverage(asUncovered(value))).toEqual({ kind: 'unknown' })
  })

  it('test_suite_coverage_filters_non_string_and_empty_items', () => {
    /** PA-326: solo cadenas no vacías; si al filtrar no queda nada, es «completo». */
    expect(suiteCoverage(asUncovered({ criteria: ['CA-03', 3, null, '', { id: 'CA-9' }], rules: [true, 'RN-03'] }))).toEqual({
      kind: 'gaps',
      criteria: ['CA-03'],
      rules: ['RN-03'],
    })
    expect(suiteCoverage(asUncovered({ criteria: [1, null], rules: [''] }))).toEqual({ kind: 'complete' })
  })
})

describe('coverageBadge y uncoveredLabel', () => {
  it('test_coverage_badge_by_kind', () => {
    /** PA-326: distintivo del panel; si no se sabe, ninguno. */
    expect(coverageBadge({ kind: 'complete' })).toEqual({ tone: 'success', text: 'Todos los CA cubiertos' })
    expect(coverageBadge({ kind: 'gaps', criteria: ['CA-03', 'CA-04'], rules: ['RN-03'] })).toEqual({ tone: 'warning', text: '2 CA y 1 RN sin caso' })
    expect(coverageBadge(UNKNOWN_COVERAGE)).toBeUndefined()
  })

  it('test_uncovered_label_omits_the_empty_part', () => {
    /** PA-326: «2 CA y 1 RN sin caso», «1 RN sin caso», «1 CA sin caso». */
    expect(uncoveredLabel(['CA-03', 'CA-04'], ['RN-03'])).toBe('2 CA y 1 RN sin caso')
    expect(uncoveredLabel([], ['RN-03'])).toBe('1 RN sin caso')
    expect(uncoveredLabel(['CA-03'], [])).toBe('1 CA sin caso')
  })
})

describe('suiteSummary con cobertura (PA-326)', () => {
  it('test_suite_summary_v1_with_gaps_names_them_and_never_says_all_covered', () => {
    const text = suiteSummary(SUITE, 1, undefined, GAPS)
    expect(text).toBe('Suite lista: 4 casos. Sin ningún caso: CA-03, RN-03. Riesgo: El catálogo puede no responder al renovar.')
    expect(text).not.toMatch(/todos los CA cubiertos/)
  })

  it('test_suite_summary_next_version_with_gaps_names_them_and_never_says_complete', () => {
    const text = suiteSummary(SUITE, 2, SUITE, GAPS)
    expect(text).toBe('Versión 2: revisé los casos. 4 casos. Sin ningún caso: CA-03, RN-03.')
    expect(text).not.toMatch(/sigue completa/)
  })
})

describe('coverageMatrix con no cubiertos', () => {
  it('test_coverage_matrix_adds_empty_rows_for_uncovered_in_order', () => {
    /** PA-326: una fila vacía por cada CA o RN sin caso; CA antes que RN, en orden numérico. */
    const { rows } = coverageMatrix(SUITE, ['RN-03', 'CA-03'])
    expect(rows.map((row) => row.id)).toEqual(['CA-01', 'CA-02', 'CA-03', 'RN-01', 'RN-02', 'RN-03'])
    expect(rows.find((row) => row.id === 'CA-03')?.covered.size).toBe(0)
    expect(rows.find((row) => row.id === 'RN-03')?.covered.size).toBe(0)
  })

  it('test_coverage_matrix_uncovered_id_that_has_cases_keeps_them', () => {
    /** Límite: si `uncovered` nombra un id que sí tiene casos, se pintan sus casos (no se vacía). */
    const { rows } = coverageMatrix(SUITE, ['CA-01'])
    expect([...(rows.find((row) => row.id === 'CA-01')?.covered ?? [])]).toEqual(['CP-01', 'CP-03', 'CP-04'])
  })
})

describe('CoverageView (PA-326)', () => {
  it('todo cubierto pero ningún caso cita CA ni RN: solo «Los casos no dicen…», sin «Cada CA y cada RN…»', () => {
    const bare = { ...SUITE, cases: SUITE.cases.map((item) => ({ ...item, criterion_ids: [], rule_ids: [] })) }
    render(<CoverageView suite={bare} coverage={{ kind: 'complete' }} coverageMd={MATRIX} />)
    expect(screen.getByText('Los casos no dicen qué CA o RN verifican.')).toBeInTheDocument()
    expect(screen.queryByText('Cada CA y cada RN de la HU tiene al menos un caso.')).toBeNull()
  })

  const table = () => screen.getByRole('table', { name: 'Qué casos verifican cada CA y cada RN' })

  it('test_coverage_view_complete_says_every_ca_and_rn_has_a_case_and_offers_download', () => {
    render(<CoverageView suite={SUITE} coverage={{ kind: 'complete' }} coverageMd={MATRIX} />)
    expect(screen.getByText('Cada CA y cada RN de la HU tiene al menos un caso.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Descargar la matriz' })).toHaveAccessibleDescription('Descarga el archivo matriz-DEMO-3.md.')
    expect(screen.queryByText(/Sin ningún caso/)).toBeNull()
    expect(table().querySelectorAll('tr[data-uncovered]')).toHaveLength(0)
    expect(screen.queryByText(/No se ha podido comprobar/)).toBeNull()
  })

  it('test_coverage_view_gaps_lists_them_and_marks_their_rows', () => {
    render(<CoverageView suite={SUITE} coverage={GAPS} coverageMd={MATRIX} />)
    expect(screen.getByText('Sin ningún caso:').closest('p')).toHaveTextContent('Sin ningún caso: CA-03, RN-03.')
    const marked = [...table().querySelectorAll('tr[data-uncovered]')]
    expect(marked.map((row) => row.querySelector('th')?.textContent)).toEqual(['CA-03 · Sin caso', 'RN-03 · Sin caso'])
    // Las filas vacías no dicen que algún caso las verifique.
    for (const row of marked) expect(within(row as HTMLElement).queryByText('Lo verifica')).toBeNull()
    expect(within(table()).getByRole('row', { name: /^CA-01/ })).not.toHaveAttribute('data-uncovered')
    expect(screen.queryByText('Cada CA y cada RN de la HU tiene al menos un caso.')).toBeNull()
  })

  it('test_coverage_view_unknown_says_it_could_not_check', () => {
    render(<CoverageView suite={SUITE} coverage={UNKNOWN_COVERAGE} coverageMd={MATRIX} />)
    expect(screen.getByText(/^No se ha podido comprobar qué CA y RN de la HU quedan sin caso:/)).toBeInTheDocument()
    expect(screen.queryByText('Cada CA y cada RN de la HU tiene al menos un caso.')).toBeNull()
    expect(screen.queryByText(/Sin ningún caso/)).toBeNull()
  })

  it('test_coverage_view_defaults_to_unknown', () => {
    render(<CoverageView suite={SUITE} />)
    expect(screen.getByText(/^No se ha podido comprobar/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Descargar la matriz' })).toBeNull()
  })

  it.each([
    ['null', null],
    ['ausente', undefined],
    ['vacía', ''],
  ])('test_coverage_view_without_coverage_md_%s_has_no_download', (_name, coverageMd) => {
    render(<CoverageView suite={SUITE} coverage={{ kind: 'complete' }} coverageMd={coverageMd} />)
    expect(screen.getByText('Matriz de cobertura CA/RN ↔ CP (RF-24) · se adjunta como matriz-DEMO-3.md')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Descargar la matriz' })).toBeNull()
  })

  it('test_coverage_view_download_sends_the_matrix_as_is', async () => {
    const spy = vi.spyOn(download, 'downloadText').mockReturnValue(true)
    render(<CoverageView suite={SUITE} coverage={{ kind: 'complete' }} coverageMd={MATRIX} />)
    await userEvent.click(screen.getByRole('button', { name: 'Descargar la matriz' }))
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith('matriz-DEMO-3.md', MATRIX, 'text/markdown')
  })

  it('test_coverage_view_with_unsafe_story_key_has_no_download', () => {
    /** Límite: una clave que no sirve como nombre de archivo no ofrece descarga. */
    render(<CoverageView suite={{ ...SUITE, story_jira_key: '../DEMO-3' }} coverage={{ kind: 'complete' }} coverageMd={MATRIX} />)
    expect(screen.queryByRole('button', { name: 'Descargar la matriz' })).toBeNull()
  })
})

describe('coverageNote', () => {
  it('test_coverage_note_complete_says_coverage_validated', () => {
    /** PA-326: coletilla de la tarjeta y del historial solo con `uncovered` vacío. */
    expect(coverageNote({ kind: 'complete' })).toBe('cobertura validada')
  })

  it('test_coverage_note_gaps_uses_uncovered_label', () => {
    /** PA-326: con huecos, «1 CA y 1 RN sin caso» (como el distintivo), nunca «cobertura validada». */
    expect(coverageNote(GAPS)).toBe('1 CA y 1 RN sin caso')
    expect(coverageNote({ kind: 'gaps', criteria: [], rules: ['RN-03'] })).toBe('1 RN sin caso')
  })

  it('test_coverage_note_unknown_is_undefined', () => {
    /** PA-326: si no se sabe, ninguna coletilla. */
    expect(coverageNote(UNKNOWN_COVERAGE)).toBeUndefined()
    expect(coverageNote(suiteCoverage(null))).toBeUndefined()
  })

  it('test_coverage_note_is_exported_from_the_suite_index', async () => {
    const index = await import('./index.ts')
    expect(index.coverageNote).toBe(coverageNote)
  })
})
