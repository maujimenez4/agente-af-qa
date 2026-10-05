// Estado en memoria de la API simulada (MSW). Solo datos sintéticos: proyecto DEMO de la biblioteca
// ficticia de Villaficticia, usuarios af-demo, qa-demo y admin-demo. Parte de los ejemplos del contrato.
import type {
  ConversationOut,
  ConversationSummary,
  IssueCard,
  IssueSummary,
  ProgressStep,
  ProjectsOut,
  Role,
  SettingsOut,
  UsageTodayOut,
} from '../api/types.ts'
import { example } from './examples.ts'

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
  }
}

export interface MockRun {
  conversation: ConversationOut
  /** Pasos del SSE que quedan por emitir (DESIGN-DECISIONS.md §3). */
  script: ProgressStep[]
  /** Al iterar: la conversación en revisión de la que parte la versión nueva y el cambio pedido. */
  previous?: ConversationOut
  pendingFeedback?: string
  /** POST /cancel: el SSE se detiene antes del siguiente paso (PA-314). */
  cancel?: boolean
}

export interface MockDb {
  session: { username: string; role: Role; csrf: string } | null
  projects: ProjectsOut
  settings: SettingsOut
  usage: UsageTodayOut | 'unavailable'
  conversations: ConversationSummary[]
  runs: Map<string, MockRun>
  /** Milisegundos entre eventos del SSE simulado (0 en las pruebas). */
  stepDelayMs: number
}

export function createMockDb(options: { stepDelayMs?: number } = {}): MockDb {
  return {
    session: null,
    projects: example<ProjectsOut>('GET /api/v1/projects 200'),
    settings: example<SettingsOut>('GET /api/v1/settings 200'),
    usage: example<UsageTodayOut>('GET /api/v1/settings/usage 200'),
    conversations: example<ConversationSummary[]>('GET /api/v1/conversations 200'),
    runs: new Map(),
    stepDelayMs: options.stepDelayMs ?? 900,
  }
}
