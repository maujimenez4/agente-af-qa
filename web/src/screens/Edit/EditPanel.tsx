import { useEffect, useRef, useState, type RefObject } from 'react'
import { SidePanel } from '../../components/Workspace/index.ts'
import type { UserStory } from './storyDraft.ts'
import { StoryEditorActions, StoryEditorFields } from './StoryEditor.tsx'
import { useStoryEditor } from './useStoryEditor.ts'

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
   * La pantalla la pasa a `Workspace` (`onPanelCloseRequest`): con cambios sin guardar, Esc, el velo o *Cerrar* del
   * panel en capa (PA-335) abren «¿Descartar los cambios?» en lugar de plegarlo.
   */
  closeGuardRef: RefObject<(() => boolean) | null>
  /** Plegar el panel: tras «Sí, descartar» pedido desde Esc o *Cerrar*, el panel se pliega como se pidió. */
  onClosePanel: () => void
}

// Editar a mano (RF-32, parte B) en el panel de Iterar: el editor de la parte A con su pie, en el ancho de la suite (540 px).
export function EditPanel({ title, story, version, reviewError, busy, onSave, onCancel, closeGuardRef, onClosePanel }: EditPanelProps) {
  const editor = useStoryEditor(story)
  const [confirming, setConfirming] = useState(false)
  // La confirmación vino de cerrar el panel (Esc o *Cerrar*): al descartar, además se pliega.
  const closeAfter = useRef(false)
  const dirty = editor.dirty
  // Al abrirse, el foco va al primer campo: el botón «Editar a mano» desaparece con la propuesta y, en capa (PA-335),
  // el foco quedaría fuera del panel (Esc no llegaría y Tab saldría de la capa).
  const bodyRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bodyRef.current?.querySelector<HTMLElement>('input, textarea')?.focus()
  }, [])

  useEffect(() => {
    closeGuardRef.current = () => {
      if (busy) return false // guardando: ni plegar ni descartar
      if (!dirty) return true
      closeAfter.current = true
      setConfirming(true)
      return false
    }
    return () => {
      closeGuardRef.current = null
    }
  }, [closeGuardRef, dirty, busy])

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
            if (!next) closeAfter.current = false
            setConfirming(next)
          }}
          onSave={onSave}
          onCancel={() => {
            onCancel()
            if (closeAfter.current) onClosePanel()
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
