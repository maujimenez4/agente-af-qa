import { useId } from 'react'
import { Button } from '../../components/Button/index.ts'
import { countLabel } from '../../text/plural.ts'
import { EditorActions, type EditorActionsProps } from './EditorActions.tsx'
import { Field, Group, ItemTools } from './EditorParts.tsx'
import styles from './Editor.module.css'
import { LIST_FIELDS, LIST_LABELS, PRIORITIES, type Priority, type UserStory } from './storyDraft.ts'
import type { StoryEditor } from './useStoryEditor.ts'

// Editar a mano (RF-32, PA-340): el formulario de la HU va en el cuerpo del panel derecho, en lugar de la pestaña
// Propuesta, y las acciones en su pie. Todo es texto: nada de lo que llega de la API se pinta como HTML.

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

/** El pie del editor de la HU: el común de Editar a mano (`EditorActions`). */
export const StoryEditorActions = EditorActions<UserStory>
export type StoryEditorActionsProps = EditorActionsProps<UserStory>
