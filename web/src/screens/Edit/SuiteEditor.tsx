import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/Button/index.ts'
import { CASE_KIND } from '../../components/Suite/suiteText.ts'
import { countLabel } from '../../text/plural.ts'
import { Field, Group, ItemTools } from './EditorParts.tsx'
import styles from './Editor.module.css'
import { PRIORITIES } from './storyDraft.ts'
import { CASE_TYPES, nextCaseId, SUITE_LIST_FIELDS, SUITE_LIST_LABELS, type CaseDraft, type CasePriority, type CaseType } from './suiteDraft.ts'
import { liveCoverageText } from './suiteValidation.ts'
import type { SuiteEditor } from './useSuiteEditor.ts'

// Editar a mano la suite de QA (PA-158, UI.md §6.3): el formulario va en el cuerpo del panel derecho, por grupos (casos,
// datos y riesgos, estrategia), y las acciones en el pie común. Todo es texto: nada se pinta como HTML.

const LINES_HINT = 'Una línea por elemento.'

/** Nombre de un caso en los botones y avisos: su id o, si aún no lo tiene, su posición. */
const caseLabel = (item: CaseDraft, index: number) => item.internal_id || `caso ${index + 1}`

/**
 * Tras subir, bajar o quitar, el foco no se pierde (el botón puede quedar desactivado o desaparecer): va al botón que
 * se indique por su nombre accesible, y un aviso de estado dice lo que ha pasado.
 */
function useFocusAfter() {
  const rootRef = useRef<HTMLDivElement>(null)
  const pending = useRef<string[] | null>(null)
  const [announcement, setAnnouncement] = useState('')
  useEffect(() => {
    const names = pending.current
    if (!names || !rootRef.current) return
    pending.current = null
    // Por su nombre accesible: `aria-label`, su etiqueta o su texto.
    const controls = [...rootRef.current.querySelectorAll<HTMLButtonElement | HTMLInputElement>('button, input')]
    const nameOf = (control: HTMLButtonElement | HTMLInputElement) => control.getAttribute('aria-label') ?? control.labels?.[0]?.textContent ?? control.textContent
    for (const name of names) {
      const target = controls.find((control) => nameOf(control) === name && !control.disabled)
      if (target) {
        target.focus()
        return
      }
    }
  })
  return {
    rootRef,
    announcement,
    after: (message: string, ...focus: string[]) => {
      pending.current = focus
      setAnnouncement(message)
    },
  }
}

/** El cuerpo del editor de la suite, con el motivo de la API arriba si rechazó la última edición. */
export function SuiteEditorFields({ editor, reviewError }: { editor: SuiteEditor; reviewError?: string | null }) {
  const { draft, check } = editor
  const issue = (path: string) => check.errors.find((item) => item.path === path)
  const notice = (path: string) => {
    const found = issue(path)
    if (found) return { issue: found }
    const warned = check.warnings.find((item) => item.path === path)
    return warned ? { issue: warned, warning: true } : {}
  }
  const { rootRef, announcement, after } = useFocusAfter()
  const typesId = useId()
  const typesIssue = issue('types')
  const coverage = liveCoverageText(editor.coverage)
  const refsHint = editor.refs
    ? `Separados por comas. En la HU: ${[...editor.refs.criteria, ...editor.refs.rules].join(', ')}.`
    : 'Separados por comas, por ejemplo «CA-01, RN-02». No se sabe qué CA y RN tiene la HU: FAQ lo comprobará al guardar.'
  const fixed = [`HU ${editor.original.story_jira_key}`, countLabel(editor.original.sources?.length ?? 0, 'fuente', 'fuentes')].join(' · ')

  return (
    <div className={`${styles.editor} ${styles.suiteEditor}`} ref={rootRef}>
      {/* Lo que ha pasado al mover, quitar o añadir. Va al principio: al final, oculto y con posición absoluta, estiraría la
          columna de la pantalla (y en ventanas estrechas, el panel pasaría a capa plegada). */}
      <span className="visually-hidden" role="status">
        {announcement}
      </span>
      {reviewError && (
        <p className={styles.rejected} role="alert">
          <b>No se guardó la edición.</b> {reviewError}
        </p>
      )}
      <p className={styles.fixed}>{fixed}. La clave de la HU y las fuentes no se editan.</p>

      {/* Cobertura en vivo, con las reglas de la pestaña Cobertura: un CA sin caso bloquea la aprobación, una RN solo avisa. */}
      <div className={styles.coverage} data-tone={coverage.tone} role="status">
        <b>Cobertura</b>
        {coverage.lines.map((line) => (
          <span key={line}>{line}</span>
        ))}
      </div>

      <Group
        title={`Casos (${draft.cases.length})`}
        actions={
          <Button
            size="sm"
            onClick={() => {
              const id = nextCaseId(draft.cases.map((item) => item.internal_id))
              editor.addCase()
              after(`${id} añadido al final.`, `Identificador de ${id}`)
            }}
          >
            Añadir un caso
          </Button>
        }
      >
        {issue('cases') && <p className={styles.issue}>{issue('cases')?.message}</p>}
        {typesIssue && (
          <p id={typesId} className={styles.issue}>
            {typesIssue.message}
          </p>
        )}
        <ol className={styles.items}>
          {draft.cases.map((item, index) => {
            const label = caseLabel(item, index)
            const at = (field: string) => `cases.${index}.${field}`
            return (
              <li key={item.key} className={styles.item} aria-label={label}>
                <span className={styles.itemHead}>
                  <span className={styles.itemId}>{label}</span>
                  <ItemTools
                    label={label}
                    index={index}
                    count={draft.cases.length}
                    onMove={(step) => {
                      editor.moveCase(item.key, step)
                      const word = step < 0 ? 'Subir' : 'Bajar'
                      const other = step < 0 ? 'Bajar' : 'Subir'
                      after(`${label} pasa a la posición ${index + 1 + step}.`, `${word} ${label}`, `${other} ${label}`)
                    }}
                    onRemove={() => {
                      editor.removeCase(item.key)
                      after(`${label} quitado.`, 'Añadir un caso')
                    }}
                  />
                </span>
                <Field label={`Identificador de ${label}`} value={item.internal_id} onChange={(internal_id) => editor.updateCase(item.key, { internal_id })} issue={issue(at('id'))} />
                <Field label={`Título de ${label}`} value={item.title} onChange={(title) => editor.updateCase(item.key, { title })} {...notice(at('title'))} />
                <span className={styles.pair}>
                  <Select
                    label="Tipo"
                    value={item.type}
                    options={CASE_TYPES.map((type) => ({ value: type, text: CASE_KIND[type] }))}
                    onChange={(type) => editor.updateCase(item.key, { type: type as CaseType })}
                    describedBy={typesIssue ? typesId : undefined}
                  />
                  <Select
                    label="Prioridad"
                    value={item.priority}
                    options={PRIORITIES.map((priority) => ({ value: priority, text: priority }))}
                    onChange={(priority) => editor.updateCase(item.key, { priority: priority as CasePriority })}
                  />
                </span>
                <Field label="Verifica (CA y RN)" hint={refsHint} value={item.refs} onChange={(refs) => editor.updateCase(item.key, { refs })} issue={issue(at('refs'))} />
                <Field label="Precondiciones" hint={LINES_HINT} value={item.preconditions} onChange={(preconditions) => editor.updateCase(item.key, { preconditions })} multiline />

                <section className={styles.steps} aria-label={`Pasos de ${label}`}>
                  <span className={styles.label}>Pasos</span>
                  {issue(at('steps')) && <p className={styles.issue}>{issue(at('steps'))?.message}</p>}
                  <ol className={styles.items}>
                    {item.steps.map((step, position) => {
                      const stepLabel = `paso ${position + 1} de ${label}`
                      const stepAt = (field: string) => `${at('steps')}.${position}.${field}`
                      return (
                        <li key={step.key} className={styles.step} aria-label={stepLabel}>
                          <span className={styles.itemHead}>
                            <span className={styles.itemId}>Paso {position + 1}</span>
                            <ItemTools
                              label={stepLabel}
                              index={position}
                              count={item.steps.length}
                              onMove={(direction) => {
                                editor.moveStep(item.key, step.key, direction)
                                const moved = `paso ${position + 1 + direction} de ${label}`
                                const word = direction < 0 ? 'Subir' : 'Bajar'
                                const other = direction < 0 ? 'Bajar' : 'Subir'
                                after(`El ${stepLabel} pasa a la posición ${position + 1 + direction}.`, `${word} ${moved}`, `${other} ${moved}`)
                              }}
                              onRemove={() => {
                                editor.removeStep(item.key, step.key)
                                after(`El ${stepLabel} se ha quitado.`, `Añadir un paso a ${label}`)
                              }}
                            />
                          </span>
                          <Field label="Acción" value={step.action} onChange={(action) => editor.updateStep(item.key, step.key, { action })} issue={issue(stepAt('action'))} multiline />
                          <Field label="Datos (opcional)" value={step.data} onChange={(data) => editor.updateStep(item.key, step.key, { data })} />
                          <Field label="Resultado esperado" value={step.expected} onChange={(expected) => editor.updateStep(item.key, step.key, { expected })} issue={issue(stepAt('expected'))} multiline />
                        </li>
                      )
                    })}
                  </ol>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Añadir un paso a ${label}`}
                    onClick={() => {
                      editor.addStep(item.key)
                      after(`Paso añadido a ${label}.`)
                    }}
                  >
                    Añadir un paso
                  </Button>
                </section>
                <Field label="Gherkin (opcional)" value={item.gherkin} onChange={(gherkin) => editor.updateCase(item.key, { gherkin })} multiline rows={3} />
              </li>
            )
          })}
        </ol>
      </Group>

      <Group title="Datos y riesgos">
        <DataTable editor={editor} after={after} />
        {SUITE_LIST_FIELDS.map((field) => (
          <Field key={field} label={SUITE_LIST_LABELS[field]} hint={LINES_HINT} value={draft.lists[field]} onChange={(value) => editor.setList(field, value)} multiline />
        ))}
      </Group>

      <Group title="Estrategia">
        <Field
          label="Estrategia de pruebas"
          hint="En Markdown: títulos con «#» y puntos con «-». Se adjunta como estrategia en Jira."
          value={draft.strategy_md}
          onChange={editor.setStrategy}
          {...notice('strategy')}
          multiline
          rows={8}
        />
      </Group>

    </div>
  )
}

function Select({
  label,
  value,
  options,
  onChange,
  describedBy,
}: {
  label: string
  value: string
  options: { value: string; text: string }[]
  onChange: (value: string) => void
  describedBy?: string
}) {
  const id = useId()
  return (
    <span className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <select id={id} className={styles.input} value={value} aria-describedby={describedBy} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.text}
          </option>
        ))}
      </select>
    </span>
  )
}

/** Datos sintéticos (RF-25): una tabla con el nombre de cada columna editable; filas y columnas se añaden y se quitan. */
function DataTable({ editor, after }: { editor: SuiteEditor; after: (message: string, ...focus: string[]) => void }) {
  const { draft, check } = editor
  const baseId = useId()
  const columnIssue = (index: number) =>
    check.errors.find((item) => item.path === `data.columns.${index}`) ?? check.warnings.find((item) => item.path === `data.columns.${index}`)
  const columnName = (index: number) => draft.columns[index]?.name.trim() || `columna ${index + 1}`
  // «la columna «reservas»» o, sin nombre, «la columna 2».
  const columnRef = (index: number) => (draft.columns[index]?.name.trim() ? `la columna «${columnName(index)}»` : `la ${columnName(index)}`)
  return (
    <div className={styles.dataField}>
      <span className={styles.label}>Datos de prueba ficticios</span>
      <span className={styles.hint}>Solo valores ficticios: FAQ rechaza al guardar lo que parezca un dato personal real.</span>
      {draft.columns.length > 0 && (
        <div className={styles.tableScroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                {draft.columns.map((column, index) => {
                  const found = columnIssue(index)
                  const blocking = found && check.errors.includes(found)
                  const issueId = `${baseId}-c${index}`
                  return (
                    <th key={column.key} scope="col">
                      <input
                        className={styles.input}
                        aria-label={`Nombre de la columna ${index + 1}`}
                        value={column.name}
                        aria-invalid={blocking ? true : undefined}
                        aria-describedby={found ? issueId : undefined}
                        onChange={(event) => editor.renameColumn(column.key, event.target.value)}
                      />
                      {found && (
                        <span id={issueId} className={blocking ? styles.issue : styles.warning}>
                          {found.message}
                        </span>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Quitar ${columnRef(index)}`}
                        onClick={() => {
                          editor.removeColumn(column.key)
                          after(`Se ha quitado ${columnRef(index)}.`, 'Añadir una columna')
                        }}
                      >
                        Quitar
                      </Button>
                    </th>
                  )
                })}
                <th scope="col">
                  <span className="visually-hidden">Acciones de la fila</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {draft.rows.map((row, rowIndex) => (
                <tr key={row.key}>
                  {draft.columns.map((column, index) => (
                    <td key={column.key}>
                      <input
                        className={styles.input}
                        aria-label={`${columnName(index)}, fila ${rowIndex + 1}`}
                        value={row.values[column.key] ?? ''}
                        onChange={(event) => editor.setCell(row.key, column.key, event.target.value)}
                      />
                    </td>
                  ))}
                  <td>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`Quitar la fila ${rowIndex + 1}`}
                      onClick={() => {
                        editor.removeRow(row.key)
                        after(`Fila ${rowIndex + 1} quitada.`, 'Añadir una fila')
                      }}
                    >
                      Quitar
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {check.warnings
        .filter((item) => item.path.startsWith('data.rows.'))
        .map((item) => (
          <span key={item.path} className={styles.warning}>
            {item.message}
          </span>
        ))}
      <span className={styles.actions}>
        <Button
          size="sm"
          disabled={draft.columns.length === 0}
          onClick={() => {
            editor.addRow()
            after('Fila añadida.')
          }}
        >
          Añadir una fila
        </Button>
        <Button
          size="sm"
          onClick={() => {
            editor.addColumn()
            after('Columna añadida.')
          }}
        >
          Añadir una columna
        </Button>
      </span>
    </div>
  )
}
