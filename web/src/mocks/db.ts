// Estado en memoria de la API simulada (MSW). Solo datos sintéticos: proyecto DEMO de la biblioteca
// ficticia de Villaficticia, usuarios af-demo, qa-demo y admin-demo. Parte de los ejemplos del contrato.
import type {
  AdminModelsOut,
  ConnectionsTestOut,
  ConversationOut,
  ConversationSummary,
  HandoffOut,
  MemoryOut,
  MemorySummary,
  IssueCard,
  IssueSummary,
  ProgressStep,
  ProjectsOut,
  Role,
  SettingsOut,
  UsageTodayOut,
} from '../api/types.ts'
import type { ForcedCoverage } from './qaSuite.ts'
import { mockMemoryDetails, mockMemorySummaries } from './memories.ts'
import { example } from './examples.ts'
import { seedQualityReviews, type MockQualityReview } from './quality.ts'

// Permisos de core/permissions.py (ROLE_PERMISSIONS).
const PERMISSIONS: Record<Role, string[]> = {
  functional: ['view_context', 'generate_story', 'publish_story', 'view_memory'],
  qa: ['view_context', 'generate_tests', 'publish_tests', 'view_memory'],
  admin: ['view_context', 'view_memory', 'manage_documents', 'manage_models', 'manage_connections', 'manage_users'],
}

/** Contraseña de la API simulada para los tres usuarios demo. Ficticia: no existe fuera de MSW. */
export const DEMO_PASSWORD = 'demo'

export const DEMO_USERS: Record<string, Role> = {
  'af-demo': 'functional',
  'qa-demo': 'qa',
  'admin-demo': 'admin',
}

export function permissionsOf(role: Role): string[] {
  return [...PERMISSIONS[role]]
}

// Jira simulado: los ejemplos del contrato (DEMO) más un segundo proyecto sintético (SOCI).
const EPICS: Record<string, IssueSummary[]> = {
  DEMO: example<IssueSummary[]>('GET /api/v1/projects/{project}/epics 200'),
  SOCI: [{ key: 'SOCI-1', summary: 'Alta de personas socias en línea', issue_type: 'Epic', status: 'Abierta' }],
}

const STORIES: Record<string, IssueSummary[]> = {
  'DEMO-1': [
    ...example<IssueSummary[]>('GET /api/v1/epics/{key}/stories 200'),
    { key: 'DEMO-4', summary: 'Consultar el historial de préstamos de 12 meses', issue_type: 'Story', status: 'Abierta' },
  ],
  'SOCI-1': [
    { key: 'SOCI-2', summary: 'Alta de persona socia en línea', issue_type: 'Story', status: 'Abierta' },
    { key: 'SOCI-3', summary: 'Renovar el carné de persona socia', issue_type: 'Story', status: 'Por hacer' },
  ],
}

export function epicsOf(project: string): IssueSummary[] {
  return structuredClone(EPICS[project] ?? [])
}

export function storiesOf(epicKey: string): IssueSummary[] {
  return structuredClone(STORIES[epicKey] ?? [])
}

function projectOf(key: string): string {
  return key.split('-')[0] ?? ''
}

function epicOf(storyKey: string): string | undefined {
  return Object.entries(STORIES).find(([, stories]) => stories.some((story) => story.key === storyKey))?.[0]
}

function normalize(text: string): string {
  return text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}

/** Búsqueda por texto o clave en un proyecto; sin texto, las recientes (HU y épicas). */
export function searchIssues(project: string, query: string): IssueSummary[] {
  const issues = [...(EPICS[project] ?? []), ...(EPICS[project] ?? []).flatMap((epic) => STORIES[epic.key] ?? [])]
  const needle = normalize(query.trim())
  const found = needle ? issues.filter((issue) => normalize(`${issue.key} ${issue.summary}`).includes(needle)) : issues
  return structuredClone(found)
}

export function issueCard(key: string): IssueCard | undefined {
  const all = Object.values(EPICS).flat().concat(Object.values(STORIES).flat())
  const issue = all.find((item) => item.key === key.toUpperCase())
  if (!issue) return undefined
  return {
    ...issue,
    project: projectOf(issue.key),
    epic_key: issue.issue_type === 'Epic' ? null : (epicOf(issue.key) ?? null),
    criteria_count: issue.issue_type === 'Epic' ? 0 : 2,
    rules_count: issue.issue_type === 'Epic' ? 0 : 2,
    // PA-104: subtareas CP en Jira y si la publicó el agente (como el ejemplo del contrato: ninguna, no).
    test_cases: issue.issue_type === 'Epic' ? null : 0,
    published_by_agent: issue.issue_type === 'Epic' ? null : false,
  }
}

export interface MockRun {
  conversation: ConversationOut
  /** Pasos del SSE que quedan por emitir (DESIGN-DECISIONS.md §3). */
  script: ProgressStep[]
  /** Al iterar: la conversación en revisión de la que parte la versión nueva y el cambio pedido. */
  previous?: ConversationOut
  pendingFeedback?: string
  /** QA: la HU de la que se preparan las pruebas (la suite sintética la usa como `story_jira_key`). */
  storyKey?: string
  /** POST /cancel: el SSE se detiene antes del siguiente paso (PA-314). */
  cancel?: boolean
  /** POST /approve: la revisión aprobada y la huella recibida; el SSE da `result` o `review_ready` con error. */
  approving?: { reviewing: ConversationOut; fingerprint: string }
}

/** Respuestas de POST /approve que la pantalla no puede provocar por sí sola. */
export type ForcedApproval = 'fingerprint' | 'approval_rejected' | 'not_in_review' | 'published' | 'partial'

const FORCED_APPROVALS: Record<string, ForcedApproval> = {
  huella: 'fingerprint',
  'aprobacion-rechazada': 'approval_rejected',
  'no-en-revision': 'not_in_review',
  publicado: 'published',
  // Publica de verdad pero sin dejar memoria: *Ver la memoria* da 404 (PA-329).
  'memoria-no-encontrada': 'published',
  parcial: 'partial',
}

/** `?simular=huella|aprobacion-rechazada|no-en-revision|publicado|parcial` → la respuesta forzada; otro valor, ninguna. */
export function forcedApprovalFrom(search: string): ForcedApproval | undefined {
  const value = new URLSearchParams(search).get('simular')
  return value && Object.hasOwn(FORCED_APPROVALS, value) ? FORCED_APPROVALS[value] : undefined
}

const FORCED_COVERAGE: Record<string, ForcedCoverage> = { 'sin-cubrir': 'gaps', 'cobertura-desconocida': 'unknown' }

/** `?simular=sin-cubrir|cobertura-desconocida` → cómo llega `uncovered` en la suite (PA-326); otro valor, el del ejemplo. */
export function forcedCoverageFrom(search: string): ForcedCoverage | undefined {
  const value = new URLSearchParams(search).get('simular')
  return value && Object.hasOwn(FORCED_COVERAGE, value) ? FORCED_COVERAGE[value] : undefined
}

/** `?simular=memoria-no-encontrada`: al publicar una HU no se genera su memoria (404 en *Ver la memoria*). */
export function memoryMissingFrom(search: string): boolean {
  return new URLSearchParams(search).get('simular') === 'memoria-no-encontrada'
}

/** `?simular=sin-memorias`: la lista de memorias vacía (solo en el navegador). */
export function noMemoriesFrom(search: string): boolean {
  return new URLSearchParams(search).get('simular') === 'sin-memorias'
}

/** `?simular=conexion-caida`: al probar las conexiones, un servicio falla (el ejemplo del contrato). */
export function connectionDownFrom(search: string): boolean {
  return new URLSearchParams(search).get('simular') === 'conexion-caida'
}

/** Prueba de conexiones del ejemplo del contrato, con todos los servicios bien (el caso normal en la demo). */
export function connectionsAllOk(): ConnectionsTestOut {
  const result = example<ConnectionsTestOut>('POST /api/v1/admin/connections/test 200')
  return {
    checks: result.checks.map((check) => (check.ok ? check : { ...check, ok: true, detail: 'Modelos disponibles.' })),
  }
}

/** Modelos por tarea: el ejemplo del contrato más una tarea con respaldo y otra que la sesión cambió. */
export function mockAdminModels(): AdminModelsOut {
  const models = example<AdminModelsOut>('GET /api/v1/admin/models 200')
  const ollama = { provider: 'ollama', model: 'qwen3:1.7b', host: 'ollama:11434' }
  const fallback = { provider: 'ollama', model: 'phi4-mini', host: 'ollama:11434' }
  models.tasks.push(
    { task: 'generate_story', chain: [ollama, fallback] },
    { task: 'generate_tests', chain: [ollama, fallback], override: { provider: 'ollama', model: 'phi4-mini' } },
  )
  return models
}

/** `?simular=ya-recogida`: la HU que QA intenta recoger ya la recogió otra persona. */
export function takenFrom(search: string): boolean {
  return new URLSearchParams(search).get('simular') === 'ya-recogida'
}

/** `?simular=muchas-conversaciones`: la lista con muchas conversaciones (solo en el navegador). */
export function manyConversationsFrom(search: string): boolean {
  return new URLSearchParams(search).get('simular') === 'muchas-conversaciones'
}

const MANY_STATUSES: readonly ConversationSummary['status'][] = ['in_review', 'simulated', 'started', 'published', 'approved', 'discarded']

/**
 * `count` conversaciones sintéticas (DEMO-1…DEMO-40), cuatro por día hacia atrás desde `now`, para revisar la lista larga:
 * scroll dentro de su columna, sin «Ver más» ni paginación.
 */
export function manyConversations(base: ConversationSummary, count = 120, now = new Date()): ConversationSummary[] {
  return Array.from({ length: count }, (_, index) => {
    const key = `DEMO-${(index % 40) + 1}`
    const updated = new Date(now.getTime() - Math.floor(index / 4) * 86_400_000 - (index % 4) * 3_600_000).toISOString()
    const kind = index % 3
    return {
      ...base,
      thread_id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
      origin_kind: kind === 1 ? 'epic' : 'story',
      origin_key: kind === 1 ? 'DEMO-1' : key,
      title: kind === 1 ? 'HU nueva en la épica DEMO-1' : `Evolucionar ${key}`,
      status: MANY_STATUSES[index % MANY_STATUSES.length] ?? 'in_review',
      version: (index % 3) + 1,
      created_at: updated,
      updated_at: updated,
    }
  })
}

export interface MockDb {
  session: { username: string; role: Role; csrf: string } | null
  projects: ProjectsOut
  settings: SettingsOut
  usage: UsageTodayOut | 'unavailable'
  /** Solo para revisar en el navegador (`?simular=`): cómo responde POST /approve. */
  forceApprove?: ForcedApproval
  conversations: ConversationSummary[]
  runs: Map<string, MockRun>
  /** QA encadenada (T-54): HU pasadas a QA y aún sin recoger. */
  handoffs: HandoffOut[]
  /** Memorias (PA-329): la lista y el detalle de cada una. */
  memories: MemorySummary[]
  memoryDetails: Map<string, MemoryOut>
  /** `?simular=memoria-no-encontrada`: publicar una HU no deja memoria. */
  skipPublishedMemory?: boolean
  /** `?simular=ya-recogida`: al recoger, otra persona se adelantó (409 `handoff_unavailable`). */
  forceTaken?: boolean
  /** `?simular=sin-cubrir|cobertura-desconocida`: `uncovered` de la suite (PA-326). */
  forceCoverage?: ForcedCoverage
  /** Administración (T-29): resultado de probar las conexiones y modelos por tarea. */
  connections: ConnectionsTestOut
  adminModels: AdminModelsOut
  /** Hora (ms) de la última prueba de conexiones: una cada 10 s por persona (429 con `retry_after`). */
  lastConnectionsTest?: number
  /** Revisiones de calidad (T-48) de cada persona, guardadas. */
  qualityReviews: MockQualityReview[]
  /** `?simular=calidad-error`: la revisión acaba en `error` con `quality_failed`. */
  forceQualityError?: boolean
  /** Milisegundos entre eventos del SSE simulado (0 en las pruebas). */
  stepDelayMs: number
}

export function createMockDb(options: { stepDelayMs?: number } = {}): MockDb {
  const memories = mockMemorySummaries()
  return {
    session: null,
    projects: example<ProjectsOut>('GET /api/v1/projects 200'),
    settings: example<SettingsOut>('GET /api/v1/settings 200'),
    usage: example<UsageTodayOut>('GET /api/v1/settings/usage 200'),
    conversations: example<ConversationSummary[]>('GET /api/v1/conversations 200'),
    runs: new Map(),
    handoffs: example<HandoffOut[]>('GET /api/v1/qa/handoffs 200'),
    memories,
    memoryDetails: mockMemoryDetails(memories),
    connections: connectionsAllOk(),
    adminModels: mockAdminModels(),
    qualityReviews: seedQualityReviews(),
    stepDelayMs: options.stepDelayMs ?? 900,
  }
}
