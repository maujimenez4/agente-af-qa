// Panel de la suite (UI.md §6.3, QA 3): textos y vistas de Casos, Cobertura, Datos y riesgos y Estrategia.
// Lo que llega del LLM se pinta como texto. Datos sintéticos (DEMO-3).
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { TestSuite } from '../../api/types.ts'
import { mockSuite } from '../../mocks/qaSuite.ts'
import { CasesView, CoverageView, DataRisksView, StrategyView } from './SuiteViews.tsx'
import { coverageMatrix, dataColumns, newCaseIds, strategyBlocks, suiteSummary, verifiesLabel, type SuiteCoverage } from './suiteText.ts'

const SUITE = mockSuite('DEMO-3')
const COMPLETE: SuiteCoverage = { kind: 'complete' }
const UNKNOWN: SuiteCoverage = { kind: 'unknown' }
const withCase = (suite: TestSuite): TestSuite => ({
  ...suite,
  cases: [
    ...suite.cases,
    { internal_id: 'CP-05', title: 'Aviso tras renovar', type: 'positivo', priority: 'Should', criterion_ids: ['CA-04'], rule_ids: [], preconditions: [], steps: [{ action: 'Renovar', expected: 'Aviso' }], gherkin: null },
  ],
})

describe('suiteText', () => {
  it('suiteSummary v1: casos, todos los CA cubiertos y el primer riesgo', () => {
    expect(suiteSummary(SUITE, 1, undefined, COMPLETE)).toBe(
      'Suite lista: 4 casos y todos los CA cubiertos. Riesgo: El catálogo puede no responder al renovar.',
    )
  })

  it('suiteSummary v1 con cobertura desconocida: casos y riesgo, sin afirmar la cobertura (PA-326)', () => {
    expect(suiteSummary(SUITE, 1, undefined, UNKNOWN)).toBe('Suite lista: 4 casos. Riesgo: El catálogo puede no responder al renovar.')
    expect(suiteSummary(SUITE, 1, undefined)).toBe('Suite lista: 4 casos. Riesgo: El catálogo puede no responder al renovar.')
  })

  it('suiteSummary v2: dice qué casos añadió y cuántos hay', () => {
    expect(suiteSummary(withCase(SUITE), 2, SUITE, COMPLETE)).toBe('Versión 2: añadí el CP-05 (positivo). 5 casos; la cobertura sigue completa.')
    expect(suiteSummary(SUITE, 3, SUITE, COMPLETE)).toBe('Versión 3: revisé los casos. 4 casos; la cobertura sigue completa.')
  })

  it('suiteSummary v2 con cobertura desconocida: no dice que la cobertura siga completa (PA-326)', () => {
    expect(suiteSummary(withCase(SUITE), 2, SUITE, UNKNOWN)).toBe('Versión 2: añadí el CP-05 (positivo). 5 casos.')
    expect(suiteSummary(SUITE, 3, SUITE)).toBe('Versión 3: revisé los casos. 4 casos.')
  })

  it('verifiesLabel y newCaseIds', () => {
    expect(verifiesLabel(SUITE.cases[0] as TestSuite['cases'][number])).toBe('Verifica CA-01, RN-01')
    expect(verifiesLabel({ ...(SUITE.cases[0] as TestSuite['cases'][number]), criterion_ids: [], rule_ids: [] })).toBeUndefined()
    expect([...newCaseIds(withCase(SUITE), SUITE)]).toEqual(['CP-05'])
    expect(newCaseIds(SUITE, undefined).size).toBe(0)
  })

  it('coverageMatrix: primero los CA y después las RN, en orden numérico, con los casos que los verifican', () => {
    const { cases, rows } = coverageMatrix(withCase(SUITE))
    expect(cases).toEqual(['CP-01', 'CP-02', 'CP-03', 'CP-04', 'CP-05'])
    expect(rows.map((row) => row.id)).toEqual(['CA-01', 'CA-02', 'CA-04', 'RN-01', 'RN-02'])
    expect([...(rows.find((row) => row.id === 'CA-01')?.covered ?? [])]).toEqual(['CP-01', 'CP-03', 'CP-04'])
  })

  it('dataColumns: la unión de las claves en orden de aparición', () => {
    expect(dataColumns([{ a: '1' }, { b: '2', a: '3' }])).toEqual(['a', 'b'])
  })

  it('strategyBlocks: títulos, puntos y párrafos; las etiquetas HTML se quedan como texto', () => {
    expect(strategyBlocks('## Alcance\nRenovación.\n\n- Web\n* App\n<b>sin HTML</b>')).toEqual([
      { kind: 'heading', text: 'Alcance' },
      { kind: 'paragraph', text: 'Renovación.' },
      { kind: 'item', text: 'Web' },
      { kind: 'item', text: 'App' },
      { kind: 'paragraph', text: '<b>sin HTML</b>' },
    ])
  })
})

describe('Vistas de la suite', () => {
  it('Casos: id, título, tipo, prioridad, qué verifica, pasos y el Gherkin desplegable', async () => {
    render(<CasesView suite={SUITE} version={1} previous={undefined} />)
    const items = within(screen.getByRole('list', { name: 'Casos de prueba' })).getAllByRole('listitem', { name: '' }).filter((item) => item.parentElement?.getAttribute('aria-label') === 'Casos de prueba')
    expect(items).toHaveLength(4)
    const first = items[0] as HTMLElement
    expect(first).toHaveTextContent('CP-01')
    expect(first).toHaveTextContent('Renovar un préstamo sin reservas ni renovaciones previas')
    expect(first).toHaveTextContent('Positivo')
    expect(first).toHaveTextContent('Must')
    expect(first).toHaveTextContent('Verifica CA-01, RN-01')
    expect(within(first).getByRole('list', { name: 'Pasos de CP-01' })).toHaveTextContent('→ El vencimiento se amplía 21 días')
    const toggle = within(first).getByRole('button', { name: 'Ver el Gherkin' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(within(first).getByText(/Dado un préstamo activo sin renovaciones ni reservas/, { selector: 'pre' })).not.toBeVisible()
    await userEvent.click(toggle)
    expect(within(first).getByRole('button', { name: 'Ocultar el Gherkin' })).toHaveAttribute('aria-expanded', 'true')
    expect(within(first).getByText(/Dado un préstamo activo sin renovaciones ni reservas/, { selector: 'pre' })).toBeVisible()
  })

  it('Casos: sin Gherkin, sin botón para desplegarlo', () => {
    // En el ejemplo del contrato todos los casos traen Gherkin: el CP-03 se queda sin él para la prueba.
    const suite = { ...SUITE, cases: SUITE.cases.map((item) => (item.internal_id === 'CP-03' ? { ...item, gherkin: null } : item)) }
    render(<CasesView suite={suite} version={1} previous={undefined} />)
    const items = within(screen.getByRole('list', { name: 'Casos de prueba' }))
      .getAllByRole('listitem')
      .filter((item) => item.parentElement?.getAttribute('aria-label') === 'Casos de prueba')
    expect(within(items[2] as HTMLElement).queryByRole('button', { name: /Gherkin/ })).toBeNull()
    expect(within(items[0] as HTMLElement).getByRole('button', { name: 'Ver el Gherkin' })).toBeInTheDocument()
  })

  it('Casos: el nuevo frente a la versión anterior lleva «Nuevo en v2»', () => {
    render(<CasesView suite={withCase(SUITE)} version={2} previous={SUITE} />)
    expect(screen.getAllByText('Nuevo en v2')).toHaveLength(1)
    expect(screen.getByText('Nuevo en v2').closest('li')).toHaveTextContent('CP-05')
  })

  it('Cobertura: tabla CA/RN × CP con cabeceras y «Lo verifica» para los lectores de pantalla', () => {
    render(<CoverageView suite={SUITE} coverage={COMPLETE} />)
    expect(screen.getByText('Matriz de cobertura CA/RN ↔ CP (RF-24) · se adjunta como matriz-DEMO-3.md')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Qué casos verifican cada CA y cada RN' })
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['CA / RN', 'CP-01', 'CP-02', 'CP-03', 'CP-04'])
    const row = within(table).getByRole('row', { name: /^CA-02/ })
    expect(within(row).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['No lo verifica', '✓Lo verifica', 'No lo verifica', 'No lo verifica'])
    expect(screen.getByText('Cada CA y cada RN de la HU tiene al menos un caso.')).toBeInTheDocument()
    expect(screen.queryByText(/Si no fuera así, la suite no se podría aprobar/)).toBeNull()
  })

  it('Cobertura sin referencias: lo dice y no afirma que cada CA tenga un caso', () => {
    render(<CoverageView suite={{ ...SUITE, cases: SUITE.cases.map((item) => ({ ...item, criterion_ids: [], rule_ids: [] })) }} />)
    expect(screen.getByText('Los casos no dicen qué CA o RN verifican.')).toBeInTheDocument()
    expect(screen.queryByText(/Cada CA y cada RN tiene al menos un caso/)).toBeNull()
  })

  it('Datos y riesgos: tabla de datos ficticios, riesgos, dependencias y áreas de impacto', () => {
    render(<DataRisksView suite={SUITE} />)
    const table = screen.getByRole('table', { name: 'Datos sintéticos de la suite' })
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['prestamo', 'renovaciones', 'reservas'])
    expect(within(table).getAllByRole('row')).toHaveLength(4)
    expect(screen.getByText('El catálogo puede no responder al renovar.')).toBeInTheDocument()
    expect(screen.getByText('DEMO-2')).toBeInTheDocument()
    expect(screen.getByText('Reservas')).toBeInTheDocument()
  })

  it('Datos y riesgos vacíos lo dicen', () => {
    render(<DataRisksView suite={{ ...SUITE, synthetic_data: [], risks: [], dependencies: [], impact_areas: [] }} />)
    expect(screen.getByText('La suite no trae datos de prueba.')).toBeInTheDocument()
    expect(screen.getByText('Sin riesgos señalados.')).toBeInTheDocument()
  })

  it('Estrategia: el Markdown como texto, sin HTML', () => {
    const { container } = render(<StrategyView suite={{ ...SUITE, strategy_md: '## Alcance\n<img src=x onerror=alert(1)>\n- Web' }} />)
    expect(screen.getByText('Estrategia de pruebas (RF-26) · se adjunta como estrategia-DEMO-3.md')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Alcance' })).toBeInTheDocument()
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText('• Web')).toBeInTheDocument()
  })
})
