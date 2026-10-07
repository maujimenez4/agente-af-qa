import { useEffect, useRef, useState, type RefObject } from 'react'
import { SidePanel } from '../../components/Workspace/index.ts'
import type { UserStory } from './storyDraft.ts'
import { StoryEditorActions, StoryEditorFields } from './StoryEditor.tsx'
import { useStoryEditor } from './useStoryEditor.ts'

/**
 * Antes de salir del editor (PA-344): con cambios sin guardar abre «¿Descartar los cambios?» y devuelve `false`; al
 * confirmar, sale del editor y hace `after` (sin `after`, pliega el panel: Esc, el velo o *Cerrar* en capa). Sin
 * cambios devuelve `true` y quien llama sigue. Guardando, `false` y no pregunta.
 */
export type EditCloseGuard = (after?: () => void) => boolean

export interface EditPanelProps {
  /** Título de la conversación (subtítulo del panel). */
  title: string
  /** La HU de la versión en revisión, que se edita entera. */
  story: UserStory
  version: number
  /** Motivo con el que la API rechazó la última edición (`review.error`), tal cual. */
  reviewError?: string | null
  /** Guardando (la API aún no ha respondido). */
  busy: boolean
  onSave: (content: UserStory, note: string | null) => void
  /** Salir del editor sin guardar (la versión se queda como está). */
  onCancel: () => void
  /**
   * La pantalla lo usa en `Workspace` (`onPanelCloseRequest`) y antes de *Actualizar* o de abrir otra versión desde la
   * conversación (PA-335, PA-344).
   */
  closeGuardRef: RefObject<EditCloseGuard | null>
  /**
   * Guardar lo que hay ahora en el editor, para *Reintentar* tras un error HTTP al guardar (PA-344): nunca la copia
   * del primer intento. Devuelve `false` si el editor no se puede guardar tal como está.
   */
  saveRef?: RefObject<(() => boolean) | null>
  /** Plegar el panel: tras «Sí, descartar» pedido desde Esc o *Cerrar*, el panel se pliega como se pidió. */
  onClosePanel: () => void
}

// Editar a mano (RF-32, parte B) en el panel de Iterar: el editor de la parte A con su pie, en el ancho de la suite (540 px).
export function EditPanel({ title, story, version, reviewError, busy, onSave, onCancel, closeGuardRef, saveRef, onClosePanel }: EditPanelProps) {
  const editor = useStoryEditor(story)
  const [confirming, setConfirming] = useState(false)
  // Lo que se hace tras «Sí, descartar» si la pregunta vino de fuera del pie (cerrar el panel, Actualizar, otra versión).
  const afterDiscard = useRef<(() => void) | null>(null)
  const dirty = editor.dirty
  // Al abrirse, el foco va al primer campo: el botón «Editar a mano» desaparece con la propuesta y, en capa (PA-335),
  // el foco quedaría fuera del panel (Esc no llegaría y Tab saldría de la capa).
  const bodyRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bodyRef.current?.querySelector<HTMLElement>('input, textarea')?.focus()
  }, [])

  useEffect(() => {
    closeGuardRef.current = (after) => {
      if (busy) return false // guardando: ni plegar ni descartar
      if (!dirty) return true
      afterDiscard.current = after ?? onClosePanel
      setConfirming(true)
      return false
    }
    return () => {
      closeGuardRef.current = null
    }
  }, [closeGuardRef, dirty, busy, onClosePanel])

  const canSave = !busy && editor.check.errors.length === 0
  const note = editor.note.trim()
  useEffect(() => {
    if (!saveRef) return
    saveRef.current = () => {
      if (!canSave) return false
      onSave(editor.content, note ? note : null)
      return true
    }
    return () => {
      saveRef.current = null
    }
  }, [saveRef, canSave, onSave, editor.content, note])

  return (
    <SidePanel
      title="Editar a mano"
      subtitle={`${title} · versión ${version}`}
      size="lg"
      footer={
        <StoryEditorActions
          editor={editor}
          version={version}
          busy={busy}
          confirming={confirming}
          onConfirmingChange={(next) => {
            if (!next) afterDiscard.current = null
            setConfirming(next)
          }}
          onSave={onSave}
          onCancel={() => {
            const after = afterDiscard.current
            afterDiscard.current = null
            onCancel()
            after?.()
          }}
        />
      }
    >
      <div ref={bodyRef}>
        <StoryEditorFields editor={editor} reviewError={reviewError} />
      </div>
    </SidePanel>
  )
}
