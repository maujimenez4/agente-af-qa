// Huecos de prueba del panel de la suite (UI.md §6.3, QA 3): teclado en el Gherkin desplegable, estados vacíos,
// límites de los textos y contenido del LLM pintado como texto (nunca HTML). Datos sintéticos (DEMO-3, «(ficticio)»).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { TestCase, TestSuite } from '../../api/types.ts'
import { mockSuite } from '../../mocks/qaSuite.ts'
import { CasesView, CoverageView, DataRisksView, StrategyView } from './SuiteViews.tsx'
import { coverageMatrix, newCaseIds, strategyBlocks, suiteSummary, verifiesLabel } from './suiteText.ts'

const SUITE = mockSuite('DEMO-3')
const firstCase = SUITE.cases[0] as TestCase
const caseItems = () =>
  within(screen.getByRole('list', { name: 'Casos de prueba' }))
    .getAllByRole('listitem')
    .filter((item) => item.parentElement?.getAttribute('aria-label') === 'Casos de prueba')

const testCase = (overrides: Partial<TestCase>): TestCase => ({ ...firstCase, ...overrides })

describe('suiteText · límites', () => {
  it('test_suite_summary_omits_risk_when_suite_has_no_risks', () => {
    // UI.md §6.3: «Suite lista: 4 casos y todos los CA cubiertos. Riesgo: …» (el riesgo solo si lo hay).
    expect(suiteSummary({ ...SUITE, risks: [] }, 1, undefined, { kind: 'complete' })).toBe('Suite lista: 4 casos y todos los CA cubiertos.')
  })

  it('test_suite_summary_omits_risk_and_coverage_when_suite_has_no_risks_and_coverage_is_unknown', () => {
    // PA-326: sin `uncovered`, el resumen no afirma la cobertura; sin riesgos, no hay «Riesgo:».
    expect(suiteSummary({ ...SUITE, risks: [] }, 1, undefined, { kind: 'unknown' })).toBe('Suite lista: 4 casos.')
  })

  it('test_suite_summary_strips_final_dot_of_risk_and_uses_singular', () => {
    // UI.md §6.3: resumen del asistente; un solo caso es «1 caso» y el punto del riesgo no se duplica.
    const one = { ...SUITE, cases: [firstCase], risks: ['Riesgo ficticio con punto.'] }
    expect(suiteSummary(one, 1, undefined, { kind: 'complete' })).toBe('Suite lista: 1 caso y todos los CA cubiertos. Riesgo: Riesgo ficticio con punto.')
    expect(suiteSummary(one, 1, undefined, { kind: 'unknown' })).toBe('Suite lista: 1 caso. Riesgo: Riesgo ficticio con punto.')
  })

  it('test_suite_summary_lists_every_added_case_when_several_are_new', () => {
    // UI.md §6.3: la versión siguiente dice qué casos añadió.
    const next = {
      ...SUITE,
      cases: [...SUITE.cases, testCase({ internal_id: 'CP-05', type: 'negativo' }), testCase({ internal_id: 'CP-06', type: 'alterno' })],
    }
    expect(suiteSummary(next, 2, SUITE, { kind: 'complete' })).toBe('Versión 2: añadí el CP-05 (negativo), el CP-06 (alterno). 6 casos; la cobertura sigue completa.')
    expect(suiteSummary(next, 2, SUITE, { kind: 'unknown' })).toBe('Versión 2: añadí el CP-05 (negativo), el CP-06 (alterno). 6 casos.')
  })

  it('test_new_case_ids_is_empty_when_a_case_was_only_removed', () => {
    // UI.md §6.3: «nuevo en v2» solo para casos que no estaban; quitar uno no marca nada.
    expect(newCaseIds({ ...SUITE, cases: SUITE.cases.slice(1) }, SUITE).size).toBe(0)
  })

  it('test_verifies_label_with_only_rules', () => {
    // UI.md §6.3: «Verifica CA-xx, RN-yy»; sin CA, solo las RN.
    expect(verifiesLabel(testCase({ criterion_ids: [], rule_ids: ['RN-02'] }))).toBe('Verifica RN-02')
  })

  it('test_coverage_matrix_sorts_numerically_and_puts_rules_after_criteria', () => {
    // RF-24 · UI.md §6.3: matriz CA/RN × CP; CA-10 va después de CA-2 y las RN detrás de los CA.
    const suite = {
      ...SUITE,
      cases: [testCase({ internal_id: 'CP-01', criterion_ids: ['CA-10', 'CA-2'], rule_ids: ['RN-1'] })],
    }
    expect(coverageMatrix(suite).rows.map((row) => row.id)).toEqual(['CA-2', 'CA-10', 'RN-1'])
  })

  it('test_coverage_matrix_is_empty_without_cases', () => {
    // RF-24: sin casos no hay filas ni columnas.
    expect(coverageMatrix({ ...SUITE, cases: [] })).toEqual({ cases: [], rows: [] })
  })

  it('test_strategy_blocks_ignore_blank_lines_and_keep_numbered_lists_as_text', () => {
    // RF-26 · UI.md §6.3: la estrategia llega en Markdown y se pinta como texto; las listas numeradas, como párrafos.
    expect(strategyBlocks('\n\n   \n1. Primero\n#   Título con espacios  ')).toEqual([
      { kind: 'paragraph', text: '1. Primero' },
      { kind: 'heading', text: 'Título con espacios' },
    ])
    expect(strategyBlocks('')).toEqual([])
  })
})

describe('Casos · Gherkin desplegable con el teclado', () => {
  it('test_gherkin_toggle_opens_and_closes_with_enter_and_space', async () => {
    // UI.md §6.3: «su Gherkin desplegable»; se abre y se cierra con el teclado.
    render(<CasesView suite={SUITE} version={1} previous={undefined} />)
    const first = caseItems()[0] as HTMLElement
    const toggle = within(first).getByRole('button', { name: 'Ver el Gherkin' })
    const gherkin = within(first).getByText(/Dado un préstamo activo sin renovaciones ni reservas/, { selector: 'pre' })
    toggle.focus()
    await userEvent.keyboard('{Enter}')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveAccessibleName('Ocultar el Gherkin')
    expect(gherkin).toBeVisible()
    await userEvent.keyboard(' ')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(gherkin).not.toBeVisible()
  })

  it('test_gherkin_toggle_is_reachable_with_tab_and_controls_its_own_block', async () => {
    // UI.md §6.3: cada caso lleva su Gherkin; el botón dice qué bloque controla y se llega con Tab.
    render(<CasesView suite={SUITE} version={1} previous={undefined} />)
    const [first, second] = caseItems() as [HTMLElement, HTMLElement]
    const firstToggle = within(first).getByRole('button', { name: 'Ver el Gherkin' })
    const secondToggle = within(second).getByRole('button', { name: 'Ver el Gherkin' })
    await userEvent.tab()
    expect(firstToggle).toHaveFocus()
    await userEvent.tab()
    expect(secondToggle).toHaveFocus()
    const firstId = firstToggle.getAttribute('aria-controls')
    const secondId = secondToggle.getAttribute('aria-controls')
    expect(firstId).toBeTruthy()
    expect(firstId).not.toBe(secondId)
    expect(document.getElementById(firstId ?? '')).toHaveTextContent('Dado un préstamo activo sin renovaciones ni reservas')
    expect(document.getElementById(secondId ?? '')).toHaveTextContent('Dado un préstamo activo con reservas pendientes')
    // Abrir el segundo no abre el primero.
    await userEvent.keyboard('{Enter}')
    expect(secondToggle).toHaveAttribute('aria-expanded', 'true')
    expect(firstToggle).toHaveAttribute('aria-expanded', 'false')
  })
})

describe('Vistas · estados vacíos y datos parciales', () => {
  it('test_cases_view_says_so_when_suite_has_no_cases', () => {
    // UI.md §7 (estado vacío) aplicado a la pestaña Casos.
    render(<CasesView suite={{ ...SUITE, cases: [] }} version={1} previous={undefined} />)
    expect(screen.getByText('La suite no tiene casos.')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Casos de prueba' })).toBeNull()
  })

  it('test_case_shows_preconditions_and_step_data_only_when_present', () => {
    // RF-23 · UI.md §6.3: pasos con datos y resultado esperado; precondiciones si las hay.
    render(<CasesView suite={SUITE} version={1} previous={undefined} />)
    const [first, , , fourth] = caseItems() as HTMLElement[]
    expect(first).toHaveTextContent('Precondiciones: La persona socia ficticia SOC-0001 ha iniciado sesión.')
    const firstSteps = within(within(first as HTMLElement).getByRole('list', { name: 'Pasos de CP-01' })).getAllByRole('listitem')
    expect(firstSteps[0]).toHaveTextContent('· Datos: PR-0001')
    // El segundo paso del CP-01 trae `data: null`: sin «Datos:».
    expect(firstSteps[1]).not.toHaveTextContent('Datos:')
    // CP-04 no trae datos en su paso.
    expect(within(fourth as HTMLElement).getByRole('list', { name: 'Pasos de CP-04' })).not.toHaveTextContent('Datos:')
  })

  it('test_case_without_preconditions_or_references_hides_those_lines', () => {
    // UI.md §6.3: «Verifica …» solo si el caso dice qué verifica.
    render(<CasesView suite={{ ...SUITE, cases: [testCase({ preconditions: [], criterion_ids: [], rule_ids: [] })] }} version={1} previous={undefined} />)
    const [only] = caseItems() as HTMLElement[]
    expect(only).not.toHaveTextContent('Precondiciones:')
    expect(only).not.toHaveTextContent('Verifica')
  })

  it('test_case_kind_badges_for_the_four_types', () => {
    // RF-22 · UI.md §6.3: tipo de caso por caso (positivo, negativo, alterno, de excepción).
    render(<CasesView suite={SUITE} version={1} previous={undefined} />)
    const items = caseItems()
    expect(items[0]).toHaveTextContent('Positivo')
    expect(items[1]).toHaveTextContent('Negativo')
    // Ejemplo del contrato: CP-03 es de excepción y CP-04, alterno.
    expect(items[2]).toHaveTextContent('Excepción')
    expect(items[3]).toHaveTextContent('Alterno')
  })

  it('test_coverage_view_without_references_shows_empty_text', () => {
    // RF-24 · UI.md §6.3: sin CA ni RN en los casos, la matriz no se pinta.
    render(<CoverageView suite={{ ...SUITE, cases: [testCase({ criterion_ids: [], rule_ids: [] })] }} />)
    expect(screen.getByText('Los casos no dicen qué CA o RN verifican.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('test_data_view_fills_missing_columns_with_empty_cells', () => {
    // RF-25 · UI.md §6.3: tabla de datos sintéticos con la unión de columnas; lo que falta queda vacío.
    render(<DataRisksView suite={{ ...SUITE, synthetic_data: [{ socio: 'SOC-0009 (ficticio)' }, { prestamo: 'PR-0009' }] }} />)
    const table = screen.getByRole('table', { name: 'Datos sintéticos de la suite' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0] as HTMLElement).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['SOC-0009 (ficticio)', ''])
    expect(within(rows[1] as HTMLElement).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['', 'PR-0009'])
  })

  it('test_data_view_empty_dependencies_and_impact_areas_say_so', () => {
    // RF-27 · UI.md §6.3: riesgos, dependencias y áreas de impacto; vacías lo dicen.
    render(<DataRisksView suite={{ ...SUITE, dependencies: [], impact_areas: [] }} />)
    expect(screen.getByText('Sin dependencias señaladas.')).toBeInTheDocument()
    expect(screen.getByText('Sin áreas de impacto señaladas.')).toBeInTheDocument()
  })

  it('test_strategy_view_empty_says_so', () => {
    // RF-26 · UI.md §6.3: sin estrategia, se dice.
    render(<StrategyView suite={{ ...SUITE, strategy_md: '  \n ' }} />)
    expect(screen.getByText('La suite no trae estrategia.')).toBeInTheDocument()
  })

  it('test_risks_with_duplicated_text_render_every_item', () => {
    // RF-27 · UI.md §6.3: el LLM puede repetir un riesgo; la lista pinta los dos, sin perder ninguno.
    render(<DataRisksView suite={{ ...SUITE, risks: ['Riesgo ficticio repetido', 'Riesgo ficticio repetido'] }} />)
    expect(screen.getAllByText('Riesgo ficticio repetido')).toHaveLength(2)
  })
})

describe('Lo que llega del LLM se pinta como texto (nunca HTML)', () => {
  const HOSTILE = '<img src=x onerror=alert(1)><script>alert(1)</script>'

  it('test_case_fields_with_html_render_as_text', async () => {
    // UI.md §6.3 y principio de seguridad: título, pasos, precondiciones y Gherkin como texto.
    const suite = {
      ...SUITE,
      cases: [testCase({ title: HOSTILE, preconditions: [HOSTILE], steps: [{ action: HOSTILE, data: HOSTILE, expected: HOSTILE }], gherkin: HOSTILE })],
    }
    const { container } = render(<CasesView suite={suite} version={1} previous={undefined} />)
    await userEvent.click(screen.getByRole('button', { name: 'Ver el Gherkin' }))
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText(HOSTILE, { selector: 'b' })).toBeInTheDocument()
    expect(screen.getByText(HOSTILE, { selector: 'pre' })).toBeVisible()
  })

  it('test_data_and_risks_with_html_render_as_text', () => {
    // RF-25 · RF-27: datos sintéticos, riesgos, dependencias e impacto como texto.
    const suite: TestSuite = { ...SUITE, synthetic_data: [{ [HOSTILE]: HOSTILE }], risks: [HOSTILE], dependencies: [`${HOSTILE} dep`], impact_areas: [`${HOSTILE} área`] }
    const { container } = render(<DataRisksView suite={suite} />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByRole('columnheader', { name: HOSTILE })).toBeInTheDocument()
  })

  it('test_coverage_ids_with_html_render_as_text', () => {
    // RF-24: los ids de CA/RN y de CP vienen del LLM; como texto.
    const { container } = render(<CoverageView suite={{ ...SUITE, cases: [testCase({ internal_id: HOSTILE, criterion_ids: [HOSTILE], rule_ids: [] })] }} />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByRole('rowheader', { name: HOSTILE })).toBeInTheDocument()
  })

  it('test_strategy_with_script_and_link_markdown_renders_no_elements', () => {
    // RF-26 · UI.md §6.3: strategy_md como texto; ni scripts ni enlaces de Markdown.
    const { container } = render(<StrategyView suite={{ ...SUITE, strategy_md: '## <script>alert(1)</script>\n- [enlace](javascript:alert(1))' }} />)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('a')).toBeNull()
    expect(screen.getByRole('heading', { name: '<script>alert(1)</script>' })).toBeInTheDocument()
    // PA-334: un enlace de Markdown deja solo su texto; la URL no se pinta ni se puede abrir.
    expect(screen.getByText('• enlace')).toBeInTheDocument()
    expect(container.textContent).not.toContain('javascript:')
  })
})
