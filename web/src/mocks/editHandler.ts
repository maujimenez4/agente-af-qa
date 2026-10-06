// Editar a mano en la API simulada (`POST /conversations/{id}/edit`, RF-32), como `_edit` de core/graph/nodes.py:
// versión siguiente sin llamar al modelo, con huella nueva y `edited: true`; una edición inválida no es un error
// HTTP sino `review.error` con la misma revisión. Registrado en `createHandlers` (parte B), que le pasa su `runFor`.
// Solo datos ficticios.
import { http, HttpResponse, type JsonBodyType } from 'msw'
import type { components } from '../api/schema'
import type { ApiError, ConversationOut, ErrorCode } from '../api/types.ts'
import type { MockDb, MockRun } from './db.ts'
import { FINGERPRINT_MISMATCH } from './handlers.ts'

type UserStory = components['schemas']['UserStory']
type StoryDiff = components['schemas']['StoryDiff']
type EditIn = components['schemas']['EditIn']

const API = '/api/v1'

/** Como `MAX_REVIEW_REJECTIONS` (core/graph/nodes.py): rechazos que admite una misma revisión. */
export const MAX_EDIT_REJECTIONS = 20
export const TOO_MANY_REJECTIONS = 'Demasiadas respuestas rechazadas en esta revisión: empieza una conversación nueva.'
export const UNCHANGED = 'La edición no cambia nada respecto a la versión revisada.'

const CRITERION_ID = /^CA-\d+$/
const RULE_ID = /^RN-\d+$/

function error(status: number, code: ErrorCode, message: string) {
  const body: { error: ApiError } = { error: { code, message, retry_after: null } }
  return HttpResponse.json(body, { status })
}

/** Campos que no casan con `UserStory` (schemas/user_story.py), como los lista `_edit`: «acceptance_criteria.0.given». */
export function invalidStoryFields(value: unknown): string[] {
  if (!value || typeof value !== 'object') return ['contenido']
  const story = value as Partial<UserStory>
  const bad: string[] = []
  const text = (v: unknown, min = 0) => typeof v === 'string' && v.length >= min
  const list = (v: unknown, min = 0) => Array.isArray(v) && v.length >= min && v.every((item) => typeof item === 'string')
  if (!text(story.title, 1)) bad.push('title')
  for (const field of ['role', 'action', 'benefit', 'description', 'business_goal'] as const) if (!text(story[field])) bad.push(field)
  const criteria = Array.isArray(story.acceptance_criteria) ? story.acceptance_criteria : undefined
  if (!criteria || criteria.length === 0) bad.push('acceptance_criteria')
  criteria?.forEach((item, index) => {
    if (!text(item?.id) || !CRITERION_ID.test(item.id)) bad.push(`acceptance_criteria.${index}.id`)
    if (!text(item?.title, 1)) bad.push(`acceptance_criteria.${index}.title`)
    for (const part of ['given', 'when', 'then'] as const) if (!list(item?.[part], 1)) bad.push(`acceptance_criteria.${index}.${part}`)
  })
  const rules = Array.isArray(story.business_rules) ? story.business_rules : undefined
  if (!rules) bad.push('business_rules')
  rules?.forEach((item, index) => {
    if (!text(item?.id) || !RULE_ID.test(item.id)) bad.push(`business_rules.${index}.id`)
    if (!text(item?.description, 1)) bad.push(`business_rules.${index}.description`)
  })
  const ids = [...(criteria ?? []).map((item) => item?.id), ...(rules ?? []).map((item) => item?.id)]
  if (new Set(ids).size !== ids.length) bad.push('ids')
  if (!['Must', 'Should', 'Could', "Won't"].includes(String(story.priority))) bad.push('priority')
  return bad.sort()
}

const sorted = (value: unknown): unknown =>
  Array.isArray(value)
    ? value.map(sorted)
    : value && typeof value === 'object'
      ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sorted((value as Record<string, unknown>)[key])]))
      : value
const same = (a: unknown, b: unknown) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b))

// Como `_criterion_text` y `_rule_text` (core/impact/diff.py): el CA entero, con sus pasos; la RN, su descripción.
const criterionText = (item: UserStory['acceptance_criteria'][number]) =>
  [item.title, ...item.given.map((s) => `Dado ${s}`), ...item.when.map((s) => `Cuando ${s}`), ...item.then.map((s) => `Entonces ${s}`)].join('\n')
const ruleText = (item: UserStory['business_rules'][number]) => item.description
const idNumber = (id: string) => Number(/(\d+)$/.exec(id)?.[1] ?? 0)
const LIST_DIFF_FIELDS = ['scope_includes', 'scope_excludes', 'assumptions', 'constraints', 'dependencies', 'alternate_flows', 'exceptions', 'related_features'] as const

/**
 * Diff acumulado frente a la versión de Jira, como `diff_stories` (core/impact/diff.py): los campos de texto, las
 * listas, y los CA (enteros) y RN por id, en orden. Con el nombre de campo del ejemplo del contrato
 * (`acceptance_criteria.CA-02`), que es el que usa el resto de la API simulada (la API real usa `[CA-02]`, PA-341).
 */
export function diffAgainst(baseline: UserStory, story: UserStory): StoryDiff[] {
  const diffs: StoryDiff[] = []
  for (const field of ['title', 'role', 'action', 'benefit', 'description', 'business_goal', 'priority'] as const) {
    if (baseline[field] !== story[field]) diffs.push({ field, before: baseline[field], after: story[field] })
  }
  for (const field of LIST_DIFF_FIELDS) {
    const before = baseline[field].join('\n')
    const after = story[field].join('\n')
    if (before !== after) diffs.push({ field, before, after })
  }
  const byId = <T extends { id: string }>(name: string, before: T[], after: T[], render: (item: T) => string) => {
    const old = new Map(before.map((item) => [item.id, render(item)]))
    const now = new Map(after.map((item) => [item.id, render(item)]))
    for (const id of [...new Set([...old.keys(), ...now.keys()])].sort((a, b) => idNumber(a) - idNumber(b) || a.localeCompare(b))) {
      if (old.get(id) !== now.get(id)) diffs.push({ field: `${name}.${id}`, before: old.get(id) ?? null, after: now.get(id) ?? null })
    }
  }
  byId('acceptance_criteria', baseline.acceptance_criteria, story.acceptance_criteria, criterionText)
  byId('business_rules', baseline.business_rules, story.business_rules, ruleText)
  return diffs
}

const randomFingerprint = () => Array.from(crypto.getRandomValues(new Uint8Array(32)), (byte) => byte.toString(16).padStart(2, '0')).join('')

/**
 * Handlers de Editar a mano sobre el mismo estado que `createHandlers`. `findRun` es su `runFor`: así también se
 * edita una conversación de la lista que aún no se había abierto (se crea con el ejemplo del contrato).
 */
export function editHandlers(db: MockDb, findRun: (id: string) => MockRun | undefined = (id) => db.runs.get(id)) {
  const rejections = new Map<string, number>()
  return [
    http.post<{ id: string }>(`${API}/conversations/:id/edit`, async ({ request, params }) => {
      if (!db.session) return error(401, 'unauthenticated', 'Inicia sesión para continuar.')
      if (request.headers.get('X-CSRF-Token') !== db.session.csrf) return error(403, 'forbidden', 'No tienes permiso para realizar esta acción.')
      const run = findRun(params.id)
      if (!run) return error(404, 'not_found', 'No existe esa conversación o no es tuya.')
      const reviewing = run.conversation
      const review = reviewing.review
      if (reviewing.state !== 'in_review' || !review) {
        return error(409, 'not_in_review', 'La conversación no tiene una propuesta en revisión (está generando o ya terminó).')
      }
      const body = (await request.json().catch(() => null)) as Partial<EditIn> | null
      if (!body || typeof body.fingerprint !== 'string' || !/^[0-9a-f]{64}$/.test(body.fingerprint) || !body.content) {
        return error(422, 'invalid_request', 'La petición no es válida: revisa fingerprint y content.')
      }
      if (body.feedback !== undefined && body.feedback !== null && (typeof body.feedback !== 'string' || body.feedback.length < 1 || body.feedback.length > 1000)) {
        return error(422, 'invalid_request', 'La petición no es válida: revisa feedback.')
      }

      // Rechazos como `_edit`: la revisión sigue con su huella y el motivo en `review.error`.
      const reject = (message: string) => {
        const count = (rejections.get(params.id) ?? 0) + 1
        rejections.set(params.id, count)
        if (count > MAX_EDIT_REJECTIONS) return error(409, 'restart', TOO_MANY_REJECTIONS)
        run.conversation = { ...reviewing, review: { ...review, error: message } }
        return HttpResponse.json(run.conversation as JsonBodyType)
      }
      if (body.fingerprint !== review.fingerprint) return reject(FINGERPRINT_MISMATCH)
      if (review.artifact.type !== 'user_story') return reject('Editar la suite a mano aún no está disponible en la API simulada.')
      const bad = invalidStoryFields(body.content)
      if (bad.length > 0) return reject(`El contenido editado no es válido; revisa: ${bad.slice(0, 8).join(', ')}.`)
      const original = review.artifact.content as UserStory
      const content = body.content as UserStory
      for (const field of ['jira_key', 'internal_id'] as const) {
        if ((content[field] ?? null) !== (original[field] ?? null)) return reject(`El campo ${field} no se puede cambiar al editar.`)
      }
      if (same(content, original)) return reject(UNCHANGED)

      const version = review.version + 1
      const baseline = reviewing.jira_baseline
      const impact = review.impact && baseline ? { ...review.impact, diffs: diffAgainst(baseline, content) } : review.impact
      const artifact = { ...review.artifact, version, content, impact }
      const conversation: ConversationOut = {
        ...reviewing,
        review: { ...review, version, artifact, impact, fingerprint: randomFingerprint(), error: null },
        versions: [...reviewing.versions, { artifact, created_at: new Date().toISOString(), edited: true, version }],
        updated_at: new Date().toISOString(),
      }
      rejections.delete(params.id)
      run.conversation = conversation
      const summary = db.conversations.find((item) => item.thread_id === params.id)
      if (summary) Object.assign(summary, { status: 'in_review', version, updated_at: conversation.updated_at })
      return HttpResponse.json(conversation as JsonBodyType)
    }),
  ]
}
