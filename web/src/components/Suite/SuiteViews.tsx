import { useId, useState } from 'react'
import type { TestCase, TestSuite } from '../../api/types.ts'
import { Badge, CaseKindBadge } from '../Badge/index.ts'
import { DownloadButton } from '../Download/index.ts'
import p from '../Proposal/Proposal.module.css'
import styles from './Suite.module.css'
import {
  CASE_KIND,
  coverageMatrix,
  dataColumns,
  newCaseIds,
  strategyBlocks,
  UNKNOWN_COVERAGE,
  verifiesLabel,
  type SuiteCoverage,
} from './suiteText.ts'

// Pestañas del panel de la suite (UI.md §6.3, lienzo QaIterar). Lo que llega del LLM se pinta como texto.

function CaseItem({ item, isNew, version, index }: { item: TestCase; isNew: boolean; version: number; index: number }) {
  const [open, setOpen] = useState(false)
  const gherkinId = useId()
  const verifies = verifiesLabel(item)
  return (
    <li className={`${p.item} ${p.rise}`} style={{ animationDelay: `${Math.min(index, 6) * 0.06}s` }} data-mark={isNew ? '' : undefined}>
      <span className={p.itemHead}>
        <span className={p.id}>{item.internal_id}</span>
        <b className={styles.caseTitle}>{item.title}</b>
      </span>
      <span className={styles.badges}>
        <CaseKindBadge kind={CASE_KIND[item.type]} />
        <Badge tone="plain">{item.priority}</Badge>
        {isNew && <Badge tone="new">Nuevo en v{version}</Badge>}
      </span>
      {verifies && <span className={p.muted}>{verifies}</span>}
      {item.preconditions.length > 0 && (
        <span className={p.muted}>
          <b>Precondiciones:</b> {item.preconditions.join(' · ')}
        </span>
      )}
      <ol className={styles.steps} aria-label={`Pasos de ${item.internal_id}`}>
        {item.steps.map((step, stepIndex) => (
          <li key={`${stepIndex}-${step.action}`}>
            {step.action}
            {step.data && <span className={p.muted}> · Datos: {step.data}</span>}
            <span className={styles.expected}>→ {step.expected}</span>
          </li>
        ))}
      </ol>
      {item.gherkin && (
        <>
          <button type="button" className={styles.toggle} aria-expanded={open} aria-controls={gherkinId} onClick={() => setOpen((value) => !value)}>
            {open ? 'Ocultar el Gherkin' : 'Ver el Gherkin'}
          </button>
          <pre id={gherkinId} className={styles.gherkin} hidden={!open}>
            {item.gherkin}
          </pre>
        </>
      )}
    </li>
  )
}

export function CasesView({ suite, version, previous }: { suite: TestSuite; version: number; previous: TestSuite | undefined }) {
  if (suite.cases.length === 0) return <p className={p.empty}>La suite no tiene casos.</p>
  const added = newCaseIds(suite, previous)
  return (
    <ol className={p.list} aria-label="Casos de prueba">
      {suite.cases.map((item, index) => (
        <CaseItem key={item.internal_id} item={item} isNew={added.has(item.internal_id)} version={version} index={index} />
      ))}
    </ol>
  )
}

export interface CoverageViewProps {
  suite: TestSuite
  /** CA y RN sin caso (`ReviewPayload.uncovered`, PA-326); por defecto, «no se sabe». */
  coverage?: SuiteCoverage
  /** `ReviewPayload.coverage_md`: la matriz que se adjunta en Jira. Sin ella, no hay descarga. */
  coverageMd?: string | null
}

export function CoverageView({ suite, coverage = UNKNOWN_COVERAGE, coverageMd }: CoverageViewProps) {
  const gaps = coverage.kind === 'gaps' ? [...coverage.criteria, ...coverage.rules] : []
  const missing = new Set(gaps)
  const { cases, rows } = coverageMatrix(suite, gaps)
  const fileName = `matriz-${suite.story_jira_key}.md`
  return (
    <div className={styles.section}>
      <div className={styles.coverageHead}>
        <p className={p.muted}>Matriz de cobertura CA/RN ↔ CP (RF-24) · se adjunta como {fileName}</p>
        <DownloadButton label="Descargar la matriz" fileName={fileName} text={coverageMd} />
      </div>
      {coverage.kind === 'gaps' && (
        <p className={styles.gaps}>
          <b>Sin ningún caso:</b> {gaps.join(', ')}.
        </p>
      )}
      {rows.length === 0 ? (
        <p className={p.empty}>Los casos no dicen qué CA o RN verifican.</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className="visually-hidden">Qué casos verifican cada CA y cada RN</caption>
            <thead>
              <tr>
                <th scope="col">CA / RN</th>
                {cases.map((id) => (
                  <th key={id} scope="col">
                    {id}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} data-uncovered={missing.has(row.id) ? '' : undefined}>
                  <th scope="row">
                    {row.id}
                    {missing.has(row.id) && <span className={styles.noCase}> · Sin caso</span>}
                  </th>
                  {cases.map((id) => (
                    <td key={id} className={styles.cell}>
                      {row.covered.has(id) ? (
                        <>
                          <span aria-hidden="true">✓</span>
                          <span className="visually-hidden">Lo verifica</span>
                        </>
                      ) : (
                        <span className="visually-hidden">No lo verifica</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {coverage.kind === 'complete' && <p className={p.muted}>Cada CA y cada RN de la HU tiene al menos un caso.</p>}
      {coverage.kind === 'unknown' && (
        <p className={p.muted}>No se ha podido comprobar qué CA y RN de la HU quedan sin caso: la matriz solo muestra lo que dicen los casos.</p>
      )}
    </div>
  )
}

function Bullets({ title, items, empty }: { title: string; items: readonly string[]; empty: string }) {
  return (
    <>
      <h4 className={p.sectionTitle}>{title}</h4>
      {items.length === 0 ? (
        <p className={p.empty}>{empty}</p>
      ) : (
        <ul className={p.bullets}>
          {items.map((item, index) => (
            <li key={`${index}-${item}`}>{item}</li>
          ))}
        </ul>
      )}
    </>
  )
}

export function DataRisksView({ suite }: { suite: TestSuite }) {
  const columns = dataColumns(suite.synthetic_data)
  return (
    <div className={styles.section}>
      <h4 className={p.sectionTitle}>Datos sintéticos (RF-25) · ficticios</h4>
      {suite.synthetic_data.length === 0 ? (
        <p className={p.empty}>La suite no trae datos de prueba.</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className="visually-hidden">Datos sintéticos de la suite</caption>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {suite.synthetic_data.map((row, index) => (
                <tr key={index}>
                  {columns.map((column) => (
                    // Solo propiedades propias: una clave como «constructor» no lee nada heredado.
                    <td key={column}>{Object.hasOwn(row, column) ? String(row[column]) : ''}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Bullets title="Riesgos (RF-27)" items={suite.risks} empty="Sin riesgos señalados." />
      <Bullets title="Dependencias" items={suite.dependencies} empty="Sin dependencias señaladas." />
      <Bullets title="Áreas de impacto" items={suite.impact_areas} empty="Sin áreas de impacto señaladas." />
    </div>
  )
}

export function StrategyView({ suite }: { suite: TestSuite }) {
  const blocks = strategyBlocks(suite.strategy_md)
  return (
    <div className={styles.section}>
      <p className={p.muted}>Estrategia de pruebas (RF-26) · se adjunta como estrategia-{suite.story_jira_key}.md</p>
      {blocks.length === 0 ? (
        <p className={p.empty}>La suite no trae estrategia.</p>
      ) : (
        <div className={styles.strategy}>
          {blocks.map((block, index) =>
            block.kind === 'heading' ? (
              <h4 key={index} className={p.sectionTitle}>
                {block.text}
              </h4>
            ) : block.kind === 'item' ? (
              <p key={index} className={styles.strategyItem}>
                • {block.text}
              </p>
            ) : (
              <p key={index} className={p.story}>
                {block.text}
              </p>
            ),
          )}
        </div>
      )}
    </div>
  )
}
