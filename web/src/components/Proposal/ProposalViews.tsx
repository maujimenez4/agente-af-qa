import type { CSSProperties } from 'react'
import { Badge } from '../Badge/index.ts'
import styles from './Proposal.module.css'
import {
  changeMarks,
  fieldLabel,
  IMPACT_KIND,
  type ImpactAnalysis,
  type SourceRef,
  type StoryDiff,
  type UserStory,
} from './proposalText.ts'
import { useJiraBrowseUrl } from '../../hooks/useJiraBrowseUrl.ts'
import { JiraKeyLink } from '../Jira/index.ts'

/** Valor de `selected` para la versión «Jira» (la HU tal como está en Jira, PA-316). */
export const JIRA_VERSION = 0

export interface VersionSelectorProps {
  versions: readonly number[]
  selected: number
  /** Añade «Jira» delante de v1 (solo al evolucionar una HU, con `jira_baseline`). */
  jira?: boolean
  onSelect: (version: number) => void
}

// Versiones de la propuesta (lienzo .ver): Jira, v1, v2… La activa con aria-pressed.
export function VersionSelector({ versions, selected, jira = false, onSelect }: VersionSelectorProps) {
  return (
    <div className={styles.versions} role="group" aria-label="Versiones">
      {jira && (
        <button
          type="button"
          className={styles.version}
          aria-pressed={selected === JIRA_VERSION}
          aria-label="Versión de Jira"
          onClick={() => onSelect(JIRA_VERSION)}
        >
          Jira
        </button>
      )}
      {versions.map((version) => (
        <button
          key={version}
          type="button"
          className={styles.version}
          aria-pressed={version === selected}
          aria-label={`Versión ${version}`}
          onClick={() => onSelect(version)}
        >
          v{version}
        </button>
      ))}
    </div>
  )
}

const delay = (index: number): CSSProperties => ({ animationDelay: `${Math.min(index, 7) * 0.08}s` })

function Lines({ keyword, lines }: { keyword: string; lines: readonly string[] }) {
  return (
    <>
      {lines.map((line, index) => (
        <li key={`${keyword}-${index}`}>
          <span className={styles.keyword}>{index === 0 ? keyword : 'Y'}</span> {line}
        </li>
      ))}
    </>
  )
}

function Bullets({ title, items }: { title: string; items: readonly string[] }) {
  if (items.length === 0) return null
  return (
    <>
      <h4 className={styles.sectionTitle}>{title}</h4>
      <ul className={styles.bullets}>
        {items.map((item, index) => (
          <li key={`${index}-${item}`}>{item}</li>
        ))}
      </ul>
    </>
  )
}

export interface StoryViewProps {
  story: UserStory
  version: number
  /** La versión anterior (vN-1), para marcar lo que cambió en esta. */
  previous?: UserStory
  diffs: readonly StoryDiff[]
}

// Pestaña Propuesta (UI.md §4.5): como/quiero/para, CA en Gherkin y RN, con la marca de lo cambiado.
export function StoryView({ story, version, previous, diffs }: StoryViewProps) {
  const marks = changeMarks(story, previous, diffs)
  const markLabel = (id: string) => {
    const mark = marks.get(id)
    if (!mark) return null
    return <Badge tone="new">{mark === 'new' ? 'Nueva' : `Cambiado en v${version}`}</Badge>
  }

  return (
    <>
      <h3 className={styles.story}>
        <b>{story.title}</b>
      </h3>
      <p className={`${styles.story} ${styles.rise}`}>
        <b>Como</b> {story.role} <b>quiero</b> {story.action} <b>para</b> {story.benefit}.
      </p>
      {story.description && <p className={styles.muted}>{story.description}</p>}

      <h4 className={styles.sectionTitle}>Criterios de aceptación</h4>
      <ol className={styles.list} aria-label="Criterios de aceptación">
        {story.acceptance_criteria.map((criterion, index) => (
          <li
            key={criterion.id}
            className={`${styles.item} ${styles.rise}`}
            style={delay(index + 1)}
            data-mark={marks.get(criterion.id)}
          >
            <span className={styles.itemHead}>
              <span className={styles.id}>{criterion.id}</span>
              <b>{criterion.title}</b>
              {markLabel(criterion.id)}
            </span>
            <ul className={styles.gherkin}>
              <Lines keyword="Dado" lines={criterion.given} />
              <Lines keyword="Cuando" lines={criterion.when} />
              <Lines keyword="Entonces" lines={criterion.then} />
            </ul>
          </li>
        ))}
      </ol>

      {story.business_rules.length > 0 && (
        <>
          <h4 className={styles.sectionTitle}>Reglas de negocio</h4>
          <ol className={styles.list} aria-label="Reglas de negocio">
            {story.business_rules.map((rule, index) => (
              <li key={rule.id} className={`${styles.item} ${styles.rise}`} style={delay(index + 2)} data-mark={marks.get(rule.id)}>
                <span className={styles.itemHead}>
                  <span className={styles.id}>{rule.id}</span>
                  {markLabel(rule.id)}
                </span>
                <span>{rule.description}</span>
              </li>
            ))}
          </ol>
        </>
      )}

      <Bullets title="Alcance incluido" items={story.scope_includes} />
      <Bullets title="Alcance excluido" items={story.scope_excludes} />
      <Bullets title="Preguntas abiertas" items={story.open_questions} />
      <p className={styles.muted}>Prioridad: {story.priority}</p>
    </>
  )
}

// Pestaña Cambios: un elemento por campo cambiado, con lo de antes tachado y lo nuevo (StoryDiff).
export function ChangesView({ diffs, againstJira = true }: { diffs: readonly StoryDiff[]; againstJira?: boolean }) {
  if (!againstJira) return <p className={styles.empty}>Es una HU nueva: no hay una versión en Jira con la que compararla.</p>
  if (diffs.length === 0) return <p className={styles.empty}>Esta versión no cambia nada frente a Jira.</p>
  return (
    <ol className={styles.list} aria-label="Cambios">
      {diffs.map((diff) => (
        <li key={diff.field} className={styles.item}>
          <span className={styles.itemHead}>
            <b>{fieldLabel(diff.field)}</b>
            {diff.before == null && <Badge tone="new">Nuevo</Badge>}
            {diff.after === null && <Badge tone="error">Eliminado</Badge>}
          </span>
          {diff.before != null && (
            <span>
              <span className="visually-hidden">Antes: </span>
              <span className={styles.before}>{diff.before}</span>
            </span>
          )}
          {diff.after !== null && (
            <span>
              <span className="visually-hidden">Ahora: </span>
              <span className={styles.after}>{diff.after}</span>
            </span>
          )}
        </li>
      ))}
    </ol>
  )
}

// Pestaña Impacto: HU y reglas afectadas, y notas de regresión (ImpactAnalysis).
export function ImpactView({ impact }: { impact: ImpactAnalysis | null | undefined }) {
  const affected = impact?.affected ?? []
  const notes = impact?.regression_notes ?? []
  // PA-325: cada HU afectada enlaza a Jira con `jira_browse_url`; sin él, la clave va como texto.
  const browseUrl = useJiraBrowseUrl(affected.length > 0)
  if (affected.length === 0 && notes.length === 0) return <p className={styles.empty}>No afecta a otras HU.</p>
  return (
    <>
      {affected.length > 0 && (
        <ol className={styles.list} aria-label="Afectadas">
          {affected.map((item) => (
            <li key={`${item.jira_key}-${item.kind}`} className={styles.item}>
              <span className={styles.itemHead}>
                <b>
                  <JiraKeyLink jiraKey={item.jira_key} browseUrl={browseUrl} />
                </b>
                <Badge>{IMPACT_KIND[item.kind]}</Badge>
              </span>
              <span>{item.reason}</span>
            </li>
          ))}
        </ol>
      )}
      <Bullets title="Notas de regresión" items={notes} />
    </>
  )
}

const SOURCE_KIND: Record<SourceRef['kind'], string> = { jira: 'Jira', rag: 'Documento', memory: 'Memoria' }

// Pestaña Fuentes: las citadas en la propuesta (UserStory.sources), con su extracto.
export function SourcesView({ sources }: { sources: readonly SourceRef[] }) {
  if (sources.length === 0) return <p className={styles.empty}>La propuesta no cita fuentes.</p>
  return (
    <ol className={styles.list} aria-label="Fuentes citadas">
      {sources.map((source) => (
        <li key={`${source.kind}-${source.ref}`} className={styles.item}>
          <span className={styles.itemHead}>
            <Badge tone="cite">{source.ref}</Badge>
            <span className={styles.muted}>{SOURCE_KIND[source.kind]}</span>
          </span>
          {source.excerpt && <span className={styles.excerpt}>«{source.excerpt}»</span>}
        </li>
      ))}
    </ol>
  )
}
