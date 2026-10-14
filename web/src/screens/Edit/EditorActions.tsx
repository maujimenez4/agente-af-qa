import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/Button/index.ts'
import { NARROW_QUERY } from '../../components/ConversationList/ConversationList.tsx'
import { useMediaQuery } from '../../hooks/useMediaQuery.ts'
import type { EditorCore } from './editorCore.ts'
import { NOTE_ONLY_HINT } from './editText.ts'
import styles from './Editor.module.css'
import { NOTE_MAX } from './storyValidation.ts'

// El pie de Editar a mano, el mismo para la HU y para la suite (PA-158).

export interface EditorActionsProps<T> {
  editor: EditorCore<T>
  /** Versión que se está editando: se guarda como la siguiente. */
  version: number
  /** Guardando (la API aún no ha respondido): no se puede volver a enviar ni cancelar. */
  busy?: boolean
  onSave: (content: T, note: string | null) => void
  onCancel: () => void
  /**
   * La pregunta «¿Descartar los cambios?», si la controla quien lo usa (p. ej. Iterar la abre también con Esc o *Cerrar*
   * del panel en capa). Sin estas dos, la lleva el propio pie.
   */
  confirming?: boolean
  onConfirmingChange?: (confirming: boolean) => void
}

/** El pie del editor: lo que falta antes de guardar, los avisos, la nota opcional y *Cancelar* / *Guardar*. */
export function EditorActions<T>({
  editor,
  version,
  busy = false,
  onSave,
  onCancel,
  confirming: controlled,
  onConfirmingChange,
}: EditorActionsProps<T>) {
  const [own, setOwn] = useState(false)
  const confirming = controlled ?? own
  const setConfirming = (next: boolean) => {
    setOwn(next)
    onConfirmingChange?.(next)
  }
  const noteId = useId()
  const summaryId = useId()
  // En ventanas estrechas (menos de 1024 px útiles, como PA-335) el pie ocupa media altura: la nota opcional se pliega
  // tras «Añadir una nota», salvo que ya tenga texto. Al desplegarla, el foco va a la nota.
  const narrow = useMediaQuery(NARROW_QUERY)
  const [noteOpen, setNoteOpen] = useState(false)
  const foldNote = narrow && !noteOpen && editor.note.length === 0
  const noteRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (noteOpen) noteRef.current?.focus()
  }, [noteOpen])
  // «¿Descartar los cambios?» sustituye al pie (y a *Cancelar*, que tenía el foco) o llega desde fuera (Esc, Actualizar,
  // otra versión: PA-344): el foco va a *Seguir editando*, la opción que no pierde nada. En una microtarea, para ir
  // después de `useLayer`, que al abrir la capa enfoca su primer control.
  const confirmRef = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!confirming) return
    queueMicrotask(() => confirmRef.current?.querySelector<HTMLElement>('button:last-child')?.focus())
  }, [confirming])
  const { errors, warnings } = editor.check
  // Un mismo motivo en varios campos (p. ej. un id repetido) se dice una vez en el resumen; junto a cada campo, siempre.
  const blocking = errors.filter((item, index) => item.path !== 'unchanged' && errors.findIndex((other) => other.message === item.message) === index)
  const unchanged = errors.some((item) => item.path === 'unchanged')
  const note = editor.note.trim()

  if (confirming) {
    return (
      <div className={styles.confirm} role="group" aria-label="Descartar los cambios">
        <span>¿Descartar los cambios? La versión {version} se queda como está.</span>
        <span ref={confirmRef} className={styles.actions}>
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
        {/* PA-435: la API rechaza una edición sin cambios en la HU, también con nota; se explica antes de intentarlo. */}
        {blocking.length === 0 && unchanged && <p className={styles.hint}>{note ? NOTE_ONLY_HINT : 'Aún no has cambiado nada.'}</p>}
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
      {foldNote ? (
        <button type="button" className={styles.addNote} onClick={() => setNoteOpen(true)}>
          Añadir una nota
        </button>
      ) : (
        <div className={styles.field}>
          <label htmlFor={noteId} className={styles.label}>
            Nota de la edición (opcional)
          </label>
          <textarea
            ref={noteRef}
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
      )}
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
