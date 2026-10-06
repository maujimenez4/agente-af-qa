import { useId, useState, type ReactNode } from 'react'
import { Button } from '../../components/Button/index.ts'
import { countLabel } from '../../text/plural.ts'
import styles from './Editor.module.css'
import { LIST_FIELDS, LIST_LABELS, PRIORITIES, type Priority } from './storyDraft.ts'
import { NOTE_MAX, type EditIssue } from './storyValidation.ts'
import type { StoryEditor } from './useStoryEditor.ts'

// Editar a mano (RF-32, PA-340): el formulario de la HU va en el cuerpo del panel derecho, en lugar de la pestaña
// Propuesta, y las acciones en su pie. Todo es texto: nada de lo que llega de la API se pinta como HTML.

interface FieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  issue?: EditIssue
  /** Un aviso no bloquea: no marca el campo como inválido y va en ámbar. */
  warning?: boolean
  hint?: string
  multiline?: boolean
  rows?: number
}

function Field({ label, value, onChange, issue, warning = false, hint, multiline = false, rows = 2 }: FieldProps) {
  const id = useId()
  const describedBy = [hint ? `${id}-hint` : '', issue ? `${id}-issue` : ''].filter(Boolean).join(' ') || undefined
  const common = {
    id,
    value,
    className: styles.input,
    'aria-invalid': issue && !warning ? true : undefined,
    'aria-describedby': describedBy,
  } as const
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      {hint && (
        <span id={`${id}-hint`} className={styles.hint}>
          {hint}
        </span>
      )}
      {multiline ? (
        <textarea {...common} rows={rows} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input {...common} type="text" onChange={(event) => onChange(event.target.value)} />
      )}
      {issue && (
        <span id={`${id}-issue`} className={warning ? styles.warning : styles.issue}>
          {issue.message}
        </span>
      )}
    </div>
  )
}

function Group({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  const id = useId()
  return (
    <section className={styles.group} aria-labelledby={id}>
      <h3 id={id} className={styles.groupTitle}>
        {title}
      </h3>
      {children}
      {actions}
    </section>
  )
}

function ItemTools({ label, index, count, onMove, onRemove }: { label: string; index: number; count: number; onMove: (step: -1 | 1) => void; onRemove: () => void }) {
  return (
    <span className={styles.tools}>
      <Button variant="ghost" size="sm" disabled={index === 0} aria-label={`Subir ${label}`} onClick={() => onMove(-1)}>
        Subir
      </Button>
      <Button variant="ghost" size="sm" disabled={index === count - 1} aria-label={`Bajar ${label}`} onClick={() => onMove(1)}>
        Bajar
      </Button>
      <Button variant="ghost" size="sm" aria-label={`Quitar ${label}`} onClick={onRemove}>
        Quitar
      </Button>
    </span>
  )
}

const LINES_HINT = 'Una línea por paso.'

/** El cuerpo del editor: la HU por grupos, con el motivo de la API arriba si rechazó la última edición. */
export function StoryEditorFields({ editor, reviewError }: { editor: StoryEditor; reviewError?: string | null }) {
  const { draft, check } = editor
  const issue = (path: string) => check.errors.find((item) => item.path === path)
  // Para los campos que solo pueden dar aviso: `issue` o, si no hay error, el aviso.
  const notice = (path: string) => {
    const found = issue(path)
    if (found) return { issue: found }
    const warned = check.warnings.find((item) => item.path === path)
    return warned ? { issue: warned, warning: true } : {}
  }
  const priorityId = useId()
  const fixed = [editor.original.jira_key ? `Clave en Jira: ${editor.original.jira_key}` : undefined, countLabel(editor.original.sources.length, 'fuente', 'fuentes')]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className={styles.editor}>
      {reviewError && (
        <p className={styles.rejected} role="alert">
          <b>No se guardó la edición.</b> {reviewError}
        </p>
      )}
      <p className={styles.fixed}>{fixed}. La clave, las fuentes y los cambios frente a la versión anterior no se editan.</p>

      <Group title="Historia">
        <Field label="Título" value={draft.title} onChange={(value) => editor.setField('title', value)} {...notice('title')} />
        <Field label="Como" value={draft.role} onChange={(value) => editor.setField('role', value)} {...notice('role')} />
        <Field label="Quiero" value={draft.action} onChange={(value) => editor.setField('action', value)} {...notice('action')} multiline />
        <Field label="Para" value={draft.benefit} onChange={(value) => editor.setField('benefit', value)} {...notice('benefit')} multiline />
        <Field label="Descripción" value={draft.description} onChange={(value) => editor.setField('description', value)} {...notice('description')} multiline rows={3} />
        <Field label="Objetivo de negocio" value={draft.business_goal} onChange={(value) => editor.setField('business_goal', value)} multiline />
        <div className={styles.field}>
          <label htmlFor={priorityId} className={styles.label}>
            Prioridad
          </label>
          <select id={priorityId} className={styles.input} value={draft.priority} onChange={(event) => editor.setField('priority', event.target.value as Priority)}>
            {PRIORITIES.map((priority) => (
              <option key={priority} value={priority}>
                {priority}
              </option>
            ))}
          </select>
        </div>
      </Group>

      <Group
        title="Criterios de aceptación"
        actions={
          <Button size="sm" onClick={editor.addCriterion}>
            Añadir un criterio
          </Button>
        }
      >
        {issue('criteria') && <p className={styles.issue}>{issue('criteria')?.message}</p>}
        <ol className={styles.items}>
          {draft.criteria.map((item, index) => (
            <li key={item.key} className={styles.item} aria-label={item.id}>
              <span className={styles.itemHead}>
                <span className={styles.itemId}>{item.id}</span>
                <ItemTools
                  label={item.id}
                  index={index}
                  count={draft.criteria.length}
                  onMove={(step) => editor.moveCriterion(item.key, step)}
                  onRemove={() => editor.removeCriterion(item.key)}
                />
              </span>
              <Field label={`Título de ${item.id}`} value={item.title} onChange={(title) => editor.updateCriterion(item.key, { title })} issue={issue(`criteria.${index}.title`)} />
              <Field label="Dado" hint={LINES_HINT} value={item.given} onChange={(given) => editor.updateCriterion(item.key, { given })} issue={issue(`criteria.${index}.given`)} multiline />
              <Field label="Cuando" hint={LINES_HINT} value={item.when} onChange={(when) => editor.updateCriterion(item.key, { when })} issue={issue(`criteria.${index}.when`)} multiline />
              <Field label="Entonces" hint={LINES_HINT} value={item.then} onChange={(then) => editor.updateCriterion(item.key, { then })} issue={issue(`criteria.${index}.then`)} multiline />
            </li>
          ))}
        </ol>
      </Group>

      <Group
        title="Reglas de negocio"
        actions={
          <Button size="sm" onClick={editor.addRule}>
            Añadir una regla
          </Button>
        }
      >
        {draft.rules.length === 0 && <p className={styles.hint}>Sin reglas de negocio.</p>}
        <ol className={styles.items}>
          {draft.rules.map((item, index) => (
            <li key={item.key} className={styles.item} aria-label={item.id}>
              <span className={styles.itemHead}>
                <span className={styles.itemId}>{item.id}</span>
                <ItemTools label={item.id} index={index} count={draft.rules.length} onMove={(step) => editor.moveRule(item.key, step)} onRemove={() => editor.removeRule(item.key)} />
              </span>
              <Field label={`Descripción de ${item.id}`} value={item.description} onChange={(description) => editor.updateRule(item.key, description)} issue={issue(`rules.${index}.description`)} multiline />
            </li>
          ))}
        </ol>
      </Group>

      <details className={styles.more}>
        <summary className={styles.moreSummary}>Más campos (alcance, supuestos, restricciones…)</summary>
        <div className={styles.moreBody}>
          {LIST_FIELDS.map((field) => (
            <Field key={field} label={LIST_LABELS[field]} hint="Una línea por elemento." value={draft.lists[field]} onChange={(value) => editor.setList(field, value)} multiline />
          ))}
        </div>
      </details>
    </div>
  )
}

export interface StoryEditorActionsProps {
  editor: StoryEditor
  /** Versión que se está editando: se guarda como la siguiente. */
  version: number
  /** Guardando (la API aún no ha respondido): no se puede volver a enviar ni cancelar. */
  busy?: boolean
  onSave: (content: StoryEditor['content'], note: string | null) => void
  onCancel: () => void
  /**
   * La pregunta «¿Descartar los cambios?», si la controla quien lo usa (p. ej. Iterar la abre también con Esc o *Cerrar*
   * del panel en capa). Sin estas dos, la lleva el propio pie.
   */
  confirming?: boolean
  onConfirmingChange?: (confirming: boolean) => void
}

/** El pie del editor: lo que falta antes de guardar, los avisos, la nota opcional y *Cancelar* / *Guardar*. */
export function StoryEditorActions({
  editor,
  version,
  busy = false,
  onSave,
  onCancel,
  confirming: controlled,
  onConfirmingChange,
}: StoryEditorActionsProps) {
  const [own, setOwn] = useState(false)
  const confirming = controlled ?? own
  const setConfirming = (next: boolean) => {
    setOwn(next)
    onConfirmingChange?.(next)
  }
  const noteId = useId()
  const summaryId = useId()
  const { errors, warnings } = editor.check
  const blocking = errors.filter((item) => item.path !== 'unchanged')
  const unchanged = errors.some((item) => item.path === 'unchanged')
  const note = editor.note.trim()

  if (confirming) {
    return (
      <div className={styles.confirm} role="group" aria-label="Descartar los cambios">
        <span>¿Descartar los cambios? La versión {version} se queda como está.</span>
        <span className={styles.actions}>
          <Button variant="danger" size="md" onClick={onCancel}>
            Sí, descartar
          </Button>
          <Button size="md" onClick={() => setConfirming(false)}>
            Seguir editando
          </Button>
        </span>
      </div>
    )
  }

  return (
    <div className={styles.footer}>
      <div id={summaryId} className={styles.summary} aria-live="polite">
        {blocking.length > 0 && (
          <div className={styles.blocking}>
            <b>Antes de guardar:</b>
            <ul>
              {blocking.map((item) => (
                <li key={`${item.path}-${item.message}`}>{item.message}</li>
              ))}
            </ul>
          </div>
        )}
        {blocking.length === 0 && unchanged && <p className={styles.hint}>Aún no has cambiado nada.</p>}
        {warnings.length > 0 && (
          <div className={styles.warnings}>
            <b>Revisa también</b> (no impide guardar):
            <ul>
              {warnings.map((item) => (
                <li key={`${item.path}-${item.message}`}>{item.message}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div className={styles.field}>
        <label htmlFor={noteId} className={styles.label}>
          Nota de la edición (opcional)
        </label>
        <textarea
          id={noteId}
          className={styles.input}
          rows={2}
          value={editor.note}
          aria-invalid={editor.note.trim().length > NOTE_MAX ? true : undefined}
          onChange={(event) => editor.setNote(event.target.value)}
        />
        <span className={`${styles.hint} tabular-nums`}>
          {editor.note.trim().length} de {NOTE_MAX}
        </span>
      </div>
      <span className={styles.actions}>
        <Button variant="ghost" disabled={busy} onClick={() => (editor.dirty ? setConfirming(true) : onCancel())}>
          Cancelar
        </Button>
        <Button
          variant="primary"
          disabled={busy || errors.length > 0}
          aria-describedby={summaryId}
          onClick={() => onSave(editor.content, note ? note : null)}
        >
          {busy ? 'Guardando…' : `Guardar la versión ${version + 1}`}
        </Button>
      </span>
    </div>
  )
}
