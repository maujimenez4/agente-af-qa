// Validación de Editar a mano en el navegador. **El backend decide**: aquí solo se bloquea *Guardar* con lo que el
// contrato o `_edit` (core/graph/nodes.py) rechazan seguro; lo demás es un aviso y se envía igual. La procedencia de
// cada regla está en `source` y en web/DESIGN-DECISIONS.md («Editar a mano»).
import type { UserStory } from './storyDraft.ts'

/** Campo al que se refiere un problema: «title», «criteria.2.then», «rules.0.description», «note»… */
export type IssuePath = string

export interface EditIssue {
  path: IssuePath
  message: string
  /** De dónde sale la regla (contrato, schemas/user_story.py o `_edit`). */
  source: string
}

export interface EditCheck {
  /** Bloquean *Guardar*: el backend los rechazaría. */
  errors: EditIssue[]
  /** No bloquean: el backend no los exige (o no consta), pero conviene revisarlos. */
  warnings: EditIssue[]
}

/** `EditIn.feedback`: entre 1 y 1000 caracteres (vacía, no se envía). */
export const NOTE_MAX = 1000

const CONTRACT = 'Contrato (UserStory)'
const SCHEMA = 'schemas/user_story.py'
const EDIT = 'core/graph/nodes.py · _edit'
const EDIT_IN = 'Contrato (EditIn.feedback)'

const CRITERION_ID = /^CA-\d+$/
const RULE_ID = /^RN-\d+$/

function repeated(ids: readonly string[]): Set<string> {
  const seen = new Set<string>()
  const twice = new Set<string>()
  for (const id of ids) (seen.has(id) ? twice : seen).add(id)
  return twice
}

/** Igualdad estructural de dos HU (como compara `_edit` el contenido editado con el revisado). */
export function sameStory(a: UserStory, b: UserStory): boolean {
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b))
}

// Mismo orden de claves en los dos lados: el orden de un objeto no cuenta como cambio.
function normalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalize)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .map((key) => [key, normalize((value as Record<string, unknown>)[key])]),
    )
  }
  return value
}

export function checkStory(edited: UserStory, original: UserStory, note: string): EditCheck {
  const errors: EditIssue[] = []
  const warnings: EditIssue[] = []
  const error = (path: IssuePath, message: string, source: string) => errors.push({ path, message, source })
  const warning = (path: IssuePath, message: string, source: string) => warnings.push({ path, message, source })

  // Contrato y schemas/user_story.py: lo que la API rechaza al validar el contenido.
  if (edited.title.length === 0) error('title', 'La HU necesita un título.', CONTRACT)
  if (edited.acceptance_criteria.length === 0) error('criteria', 'La HU necesita al menos un criterio de aceptación.', CONTRACT)
  edited.acceptance_criteria.forEach((item, index) => {
    const label = item.id || `El criterio ${index + 1}`
    if (!CRITERION_ID.test(item.id)) error(`criteria.${index}.id`, `${label}: el identificador debe ser «CA-» y un número.`, CONTRACT)
    if (item.title.length === 0) error(`criteria.${index}.title`, `${label} necesita un título.`, SCHEMA)
    if (item.given.length === 0) error(`criteria.${index}.given`, `${label} necesita al menos un «Dado».`, SCHEMA)
    if (item.when.length === 0) error(`criteria.${index}.when`, `${label} necesita al menos un «Cuando».`, SCHEMA)
    if (item.then.length === 0) error(`criteria.${index}.then`, `${label} necesita al menos un «Entonces».`, SCHEMA)
  })
  edited.business_rules.forEach((item, index) => {
    const label = item.id || `La regla ${index + 1}`
    if (!RULE_ID.test(item.id)) error(`rules.${index}.id`, `${label}: el identificador debe ser «RN-» y un número.`, CONTRACT)
    if (item.description.length === 0) error(`rules.${index}.description`, `${label} necesita una descripción.`, SCHEMA)
  })
  for (const id of repeated([...edited.acceptance_criteria.map((item) => item.id), ...edited.business_rules.map((item) => item.id)])) {
    error('ids', `El identificador ${id} está repetido.`, SCHEMA)
  }

  // `_edit`: campos que atan la HU a su origen y edición sin cambios.
  if (edited.jira_key !== original.jira_key) error('jira_key', 'La clave de Jira no se puede cambiar al editar.', EDIT)
  if (edited.internal_id !== original.internal_id) error('internal_id', 'El identificador interno no se puede cambiar al editar.', EDIT)
  if (sameStory(edited, original)) error('unchanged', 'No has cambiado nada respecto a la versión revisada.', EDIT)

  if (note.trim().length > NOTE_MAX) error('note', `La nota no puede pasar de ${NOTE_MAX} caracteres.`, EDIT_IN)

  // Avisos: el contrato admite estos campos vacíos, pero una HU así suele estar incompleta.
  const blank = (text: string) => text.trim().length === 0
  if (blank(edited.role)) warning('role', '«Como» está vacío.', 'Aviso (el contrato lo admite)')
  if (blank(edited.action)) warning('action', '«Quiero» está vacío.', 'Aviso (el contrato lo admite)')
  if (blank(edited.benefit)) warning('benefit', '«Para» está vacío.', 'Aviso (el contrato lo admite)')
  if (blank(edited.description)) warning('description', 'La descripción está vacía.', 'Aviso (el contrato lo admite)')
  if (edited.title.length > 0 && blank(edited.title)) warning('title', 'El título solo tiene espacios.', 'Aviso (el contrato lo admite)')
  else if (!blank(edited.title) && edited.title !== edited.title.trim()) warning('title', 'El título empieza o acaba con espacios.', 'Aviso')
  return { errors, warnings }
}
