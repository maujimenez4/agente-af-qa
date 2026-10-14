import type { EditCheck } from './storyValidation.ts'

/** Lo que el pie de Editar a mano necesita de un editor (HU o suite, PA-158). */
export interface EditorCore<T> {
  /** El contenido tal como se enviaría. */
  content: T
  check: EditCheck
  /** Algo cambió respecto a la versión revisada (también la nota). */
  dirty: boolean
  note: string
  setNote: (value: string) => void
}
