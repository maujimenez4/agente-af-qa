import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import type { TestSuite } from '../../api/types.ts'
import { SidePanel } from '../../components/Workspace/index.ts'
import type { EditorCore } from './editorCore.ts'
import { EditorActions } from './EditorActions.tsx'
import type { UserStory } from './storyDraft.ts'
import { StoryEditorFields } from './StoryEditor.tsx'
import { SuiteEditorFields } from './SuiteEditor.tsx'
import type { StoryRefs } from './suiteValidation.ts'
import { useStoryEditor } from './useStoryEditor.ts'
import { useSuiteEditor } from './useSuiteEditor.ts'

/**
 * Antes de salir del editor (PA-344): con cambios sin guardar abre «¿Descartar los cambios?» y devuelve `false`; al
 * confirmar, sale del editor y hace `after` (sin `after`, pliega el panel: Esc, el velo o *Cerrar* en capa). Sin
 * cambios devuelve `true` y quien llama sigue. Guardando, `false` y no pregunta.
 */
export type EditCloseGuard = (after?: () => void) => boolean

interface EditPanelCommon {
  /** Título de la conversación (subtítulo del panel). */
  title: string
  version: number
  /** Motivo con el que la API rechazó la última edición (`review.error`), tal cual. */
  reviewError?: string | null
  /** Guardando (la API aún no ha respondido). */
  busy: boolean
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

export interface EditPanelProps extends EditPanelCommon {
  /** La HU de la versión en revisión, que se edita entera. */
  story: UserStory
  onSave: (content: UserStory, note: string | null) => void
}

export interface SuiteEditPanelProps extends EditPanelCommon {
  /** La suite de la versión en revisión, que se edita entera (PA-158). */
  suite: TestSuite
  /** Los CA y RN de la HU, deducidos de la revisión (`null`: no se sabe). */
  refs: StoryRefs
  onSave: (content: TestSuite, note: string | null) => void
}

// Editar a mano (RF-32, parte B) en el panel de Iterar: el editor de la parte A con su pie, en el ancho de la suite (540 px).
export function EditPanel({ story, reviewError, ...rest }: EditPanelProps) {
  const editor = useStoryEditor(story)
  return <EditPanelFrame {...rest} editor={editor} fields={<StoryEditorFields editor={editor} reviewError={reviewError} />} />
}

// Editar a mano la suite de QA (PA-158, UI.md §6.3): el mismo marco y el mismo pie que la HU.
export function SuiteEditPanel({ suite, refs, reviewError, ...rest }: SuiteEditPanelProps) {
  const editor = useSuiteEditor(suite, refs)
  return <EditPanelFrame {...rest} editor={editor} fields={<SuiteEditorFields editor={editor} reviewError={reviewError} />} />
}

interface EditPanelFrameProps<T> extends Omit<EditPanelCommon, 'reviewError'> {
  editor: EditorCore<T>
  fields: ReactNode
  onSave: (content: T, note: string | null) => void
}

/** Lo común a los dos editores: el panel, la pregunta antes de salir, *Reintentar* y el foco en el primer campo. */
function EditPanelFrame<T>({ title, version, busy, onSave, onCancel, closeGuardRef, saveRef, onClosePanel, editor, fields }: EditPanelFrameProps<T>) {
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
        <EditorActions
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
      <div ref={bodyRef}>{fields}</div>
    </SidePanel>
  )
}
