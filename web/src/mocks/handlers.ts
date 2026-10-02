// Handlers de la API simulada (MSW) para desarrollo (VITE_API_MOCK=1) y pruebas.
// Responden con los ejemplos del contrato y un estado en memoria; el SSE emite los pasos uno a uno.
import { delay, http, HttpResponse, type JsonBodyType } from 'msw'
import type {
  ApiError,
  ChooseProjectIn,
  ConversationCreateIn,
  ConversationOut,
  ConversationSummary,
  ErrorCode,
  IssueSummary,
  IterateIn,
  LoginIn,
  ProgressStep,
  ProposeIn,
  SessionOut,
  SourcePreview,
  SourcesIn,
  StartOption,
  StartProposal,
} from '../api/types.ts'
import {
  DEMO_PASSWORD,
  DEMO_USERS,
  epicsOf,
  issueCard,
  permissionsOf,
  searchIssues,
  storiesOf,
  type MockDb,
  type MockRun,
} from './db.ts'
import type { components } from '../api/schema'

type UserStory = components['schemas']['UserStory']
import { example } from './examples.ts'

const API = '/api/v1'

// Documentos y memoria sintéticos del RAG simulado (categorías de core/rag/documents.py).
const MOCK_SOURCES: SourcePreview[] = [
  { ref: 'DOC-01', kind: 'rag', title: 'Reglamento de préstamo', category: 'politicas', required: false },
  { ref: 'DOC-08', kind: 'rag', title: 'Especificación del préstamo digital', category: 'documentacion', required: false },
  { ref: 'DOC-20', kind: 'rag', title: 'Acta de la comisión de abril', category: 'procesos', required: false },
  { ref: 'memoria-DEMO-2', kind: 'memory', title: 'Memoria validada de reservas', category: 'memoria', required: false },
]

function error(status: number, code: ErrorCode, message: string, retryAfter?: number) {
  const body: { error: ApiError } = { error: { code, message, retry_after: retryAfter ?? null } }
  return HttpResponse.json(body, { status })
}

const UNAUTHENTICATED = () => error(401, 'unauthenticated', 'Inicia sesión para continuar.')

/** Pasos de la generación (labels de `api/service.py`), en el orden en que llegan por SSE. */
const GENERATION_STEPS: ReadonlyArray<Pick<ProgressStep, 'node' | 'label'>> = [
  { node: 'load_origin', label: 'Cargar el origen' },
  { node: 'retrieve_context', label: 'Recuperar contexto' },
  { node: 'generate', label: 'Generar la propuesta, validar las citas y analizar el impacto' },
]

// Como conversation_title() de core/conversations.py: flujo y clave, sin texto libre.
function mockTitle(body: ConversationCreateIn): string {
  const { kind, key, project } = body.origin
  const flow =
    body.flow === 'tests' ? 'Preparar pruebas de' : kind === 'story' ? 'Evolucionar' : kind === 'epic' ? 'Nueva HU en' : 'Nueva necesidad'
  return key ? `${flow} ${key}` : `${flow} · ${project}`
}

function generationScript(): ProgressStep[] {
  return GENERATION_STEPS.flatMap((step) => [
    { ...step, state: 'running' as const },
    { ...step, state: 'done' as const },
  ])
}

/**
 * Versión siguiente tras pedir un cambio: la HU simulada cambia el título del primer CA y lo anota en
 * `changes_from_previous`. Como la API real, `impact.diffs` es el diff **acumulado frente a Jira**
 * (core/impact/analysis.py): un campo ya cambiado conserva su «before» de Jira.
 */
function nextVersion(previous: ConversationOut, feedback: string): ConversationOut {
  const next = structuredClone(previous)
  const review = next.review
  if (!review) return next
  const version = review.version + 1
  const story = review.artifact.content as UserStory
  const criterion = story.acceptance_criteria[0]
  const before = criterion?.title ?? null
  if (criterion) criterion.title = `${criterion.title} (revisado en v${version})`
  story.changes_from_previous = [`${criterion?.id ?? 'HU'}: ${feedback}`]
  const previousDiffs = review.impact?.diffs ?? []
  const field = criterion ? `acceptance_criteria.${criterion.id}` : undefined
  const earlier = previousDiffs.find((diff) => diff.field === field)
  const diffs = criterion
    ? [...previousDiffs.filter((diff) => diff.field !== field), { field: field as string, before: earlier ? earlier.before : before, after: criterion.title }]
    : previousDiffs
  const impact = { ...(review.impact ?? { affected: [], regression_notes: [] }), diffs }
  review.version = version
  review.fingerprint = `huella-ficticia-${crypto.randomUUID()}`
  review.impact = impact
  review.artifact = { ...review.artifact, version, impact }
  next.versions = [...previous.versions, { artifact: review.artifact, created_at: new Date().toISOString(), edited: false, version }]
  return next
}

function sse(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

export function createHandlers(db: MockDb) {
  const requireSession = () => db.session
  const csrfOk = (request: Request) => db.session !== null && request.headers.get('X-CSRF-Token') === db.session.csrf

  // Envuelve los handlers que modifican algo: sesión y X-CSRF-Token obligatorios.
  function mutation<P>(
    resolver: (args: { request: Request; params: P }) => Promise<Response> | Response,
  ): (args: { request: Request; params: P }) => Promise<Response> | Response {
    return (args) => {
      if (!requireSession()) return UNAUTHENTICATED()
      if (!csrfOk(args.request)) return error(403, 'forbidden', 'No tienes permiso para realizar esta acción.')
      return resolver(args)
    }
  }

  function query<P>(
    resolver: (args: { request: Request; params: P }) => Promise<Response> | Response,
  ): (args: { request: Request; params: P }) => Promise<Response> | Response {
    return (args) => (requireSession() ? resolver(args) : UNAUTHENTICATED())
  }

  /** Conversación en curso; las de la lista sin estado se abren con el ejemplo del contrato. */
  function runFor(id: string): MockRun | undefined {
    const existing = db.runs.get(id)
    if (existing) return existing
    const summary = db.conversations.find((item) => item.thread_id === id)
    if (!summary) return undefined
    const run: MockRun = {
      conversation: {
        ...example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200'),
        id,
        title: summary.title,
        project: summary.project_key,
      },
      script: [],
    }
    db.runs.set(id, run)
    return run
  }

  function setSummary(id: string, changes: Partial<ConversationSummary>) {
    const summary = db.conversations.find((item) => item.thread_id === id)
    if (summary) Object.assign(summary, changes, { updated_at: new Date().toISOString() })
  }

  function session(): SessionOut {
    const current = db.session
    if (!current) throw new Error('Sin sesión')
    return { user: { username: current.username, role: current.role, permissions: permissionsOf(current.role) }, csrf_token: current.csrf }
  }

  return [
    // Sesión
    http.post(`${API}/auth/login`, async ({ request }) => {
      const body = (await request.json()) as LoginIn
      const role = DEMO_USERS[body.username]
      if (!role || body.password !== DEMO_PASSWORD) {
        return error(401, 'invalid_credentials', 'Usuario o contraseña incorrectos.')
      }
      db.session = { username: body.username, role, csrf: `csrf-ficticio-${crypto.randomUUID()}` }
      return HttpResponse.json(session() as JsonBodyType)
    }),
    http.post(
      `${API}/auth/logout`,
      mutation(() => {
        db.session = null
        return new HttpResponse(null, { status: 204 })
      }),
    ),
    http.get(`${API}/auth/me`, query(() => HttpResponse.json(session() as JsonBodyType))),

    // Proyectos y Jira
    http.get(`${API}/projects`, query(() => HttpResponse.json(db.projects as JsonBodyType))),
    http.post(
      `${API}/projects/choose`,
      mutation(async ({ request }) => {
        const { project } = (await request.json()) as ChooseProjectIn
        if (!db.projects.projects.some((item) => item.key === project)) {
          return error(404, 'project_not_found', `El proyecto ${project} no existe o la conexión no tiene acceso a él.`)
        }
        db.projects.preselected = project
        return HttpResponse.json({ project })
      }),
    ),
    http.get<{ project: string }>(
      `${API}/projects/:project/epics`,
      query(({ params }) => HttpResponse.json(epicsOf(params.project))),
    ),
    http.get<{ project: string }>(
      `${API}/projects/:project/search`,
      query(({ request, params }) => {
        const q = new URL(request.url).searchParams.get('q') ?? ''
        return HttpResponse.json(searchIssues(params.project, q))
      }),
    ),
    http.get<{ key: string }>(`${API}/epics/:key/stories`, query(({ params }) => HttpResponse.json(storiesOf(params.key)))),
    http.get<{ key: string }>(
      `${API}/issues/:key`,
      query(({ params }) => {
        const card = issueCard(params.key)
        return card
          ? HttpResponse.json(card)
          : error(404, 'not_found', `La incidencia ${params.key} no existe o no tienes permiso para verla.`)
      }),
    ),

    // Arranque guiado
    http.post(
      `${API}/start/propose`,
      mutation(async ({ request }) => {
        const body = (await request.json()) as ProposeIn
        const proposal = example<StartProposal>('POST /api/v1/start/propose 200')
        const keys = [...body.text.toUpperCase().matchAll(/\b([A-Z]+-\d+)\b/g)].map((match) => match[1] ?? '')
        const recognized = keys.map((key) => issueCard(key)).filter((card) => card !== undefined)
        // Una clave de otro proyecto cambia el de la conversación (T-50, T-53).
        const project = recognized[0]?.project ?? body.project
        const summaryOf = (issue: IssueSummary): IssueSummary => ({
          key: issue.key,
          summary: issue.summary,
          issue_type: issue.issue_type,
          status: issue.status,
        })
        const words = body.text.split(/\s+/).filter((word) => word.length > 3)
        const similar =
          recognized.length > 0
            ? []
            : (words.map((word) => searchIssues(project, word)).find((found) => found.length > 0) ?? [])
                .filter((issue) => issue.issue_type !== 'Epic')
                .slice(0, 1)
        const issue = recognized[0] ? summaryOf(recognized[0]) : similar[0]
        const options: StartOption[] = []
        if (issue) {
          options.push(
            body.mode === 'qa'
              ? { kind: 'tests', label: `Preparar pruebas de ${issue.key}`, origin: { kind: 'story', key: issue.key, project }, issue }
              : { kind: 'evolve', label: `Evolucionar ${issue.key}`, origin: { kind: 'story', key: issue.key, project }, issue },
          )
        }
        if (body.mode !== 'qa') options.push({ kind: 'new_need', label: 'Crear HU nueva', origin: { kind: 'need', text: body.text, project } })
        proposal.project = project
        proposal.project_changed = project !== body.project
        proposal.ignored_projects = []
        proposal.recognized = recognized.map(summaryOf)
        proposal.similar = similar
        proposal.options = options
        return HttpResponse.json(proposal as JsonBodyType)
      }),
    ),
    http.post(
      `${API}/start/sources`,
      mutation(async ({ request }) => {
        const { origin } = (await request.json()) as SourcesIn
        const card = origin.key ? issueCard(origin.key) : undefined
        const required: SourcePreview[] = card
          ? [
              {
                ref: card.key,
                kind: 'jira',
                title: card.issue_type === 'Epic' ? `Épica de origen: ${card.summary}` : `HU de origen: ${card.summary}`,
                category: card.issue_type,
                required: true,
              },
            ]
          : []
        return HttpResponse.json([...required, ...MOCK_SOURCES] as JsonBodyType)
      }),
    ),

    // Conversaciones
    http.get(`${API}/conversations`, query(() => HttpResponse.json(db.conversations as JsonBodyType))),
    http.post(
      `${API}/conversations`,
      mutation(async ({ request }) => {
        const body = (await request.json()) as ConversationCreateIn
        const id = crypto.randomUUID()
        const now = new Date().toISOString()
        const title = mockTitle(body)
        const conversation: ConversationOut = {
          ...example<ConversationOut>('POST /api/v1/conversations 202'),
          id,
          title,
          project: body.origin.project,
          flow: body.flow,
          mode: body.flow === 'tests' ? 'qa' : 'functional',
          state: 'generating',
          progress: GENERATION_STEPS.map((step) => ({ ...step, state: 'pending' })),
          feedback: body.feedback,
          updated_at: now,
        }
        db.runs.set(id, { conversation, script: generationScript() })
        const current = db.session
        const summary: ConversationSummary = {
          thread_id: id,
          username: current?.username ?? '',
          project_key: body.origin.project,
          mode: conversation.mode,
          origin_kind: body.origin.kind,
          origin_key: body.origin.key ?? null,
          title,
          status: 'started',
          version: null,
          created_at: now,
          updated_at: now,
        }
        db.conversations.unshift(summary)
        return HttpResponse.json(conversation as JsonBodyType, { status: 202 })
      }),
    ),
    http.get<{ id: string }>(
      `${API}/conversations/:id`,
      query(({ params }) => {
        const run = runFor(params.id)
        return run
          ? HttpResponse.json(run.conversation as JsonBodyType)
          : error(404, 'not_found', 'No existe esa conversación o no es tuya.')
      }),
    ),
    http.post<{ id: string }>(
      `${API}/conversations/:id/iterate`,
      mutation(async ({ request, params }) => {
        const run = runFor(params.id)
        if (!run) return error(404, 'not_found', 'No existe esa conversación o no es tuya.')
        if (run.conversation.state !== 'in_review') {
          return error(409, 'not_in_review', 'La conversación no tiene una propuesta en revisión (está generando o ya terminó).')
        }
        const { feedback } = (await request.json()) as IterateIn
        run.previous = run.conversation
        run.pendingFeedback = feedback
        run.conversation = {
          ...run.conversation,
          state: 'generating',
          feedback: [...run.conversation.feedback, feedback],
          progress: GENERATION_STEPS.map((step) => ({ ...step, state: 'pending' })),
        }
        run.script = generationScript()
        setSummary(params.id, { status: 'started' })
        return HttpResponse.json(run.conversation as JsonBodyType, { status: 202 })
      }),
    ),
    http.post<{ id: string }>(
      `${API}/conversations/:id/discard`,
      mutation(({ params }) => {
        const run = runFor(params.id)
        if (!run) return error(404, 'not_found', 'No existe esa conversación o no es tuya.')
        if (run.conversation.state !== 'in_review') {
          return error(409, 'not_in_review', 'La conversación no tiene una propuesta en revisión (está generando o ya terminó).')
        }
        run.conversation = { ...run.conversation, state: 'discarded', review: null }
        setSummary(params.id, { status: 'discarded' })
        return HttpResponse.json(run.conversation as JsonBodyType)
      }),
    ),
    http.get<{ id: string }>(
      `${API}/conversations/:id/events`,
      query(({ params }) => {
        const run = runFor(params.id)
        if (!run) return error(404, 'not_found', 'No existe esa conversación o no es tuya.')
        const encoder = new TextEncoder()
        const stream = new ReadableStream<Uint8Array>({
          async start(controller) {
            while (run.script.length > 0) {
              await delay(db.stepDelayMs)
              const step = run.script.shift()
              if (!step) break
              run.conversation.progress = run.conversation.progress.map((item) =>
                item.node === step.node ? step : item,
              )
              controller.enqueue(encoder.encode(sse('progress', step)))
            }
            if (run.conversation.state === 'generating') {
              await delay(db.stepDelayMs)
              const reviewed = run.previous
                ? nextVersion(run.previous, run.pendingFeedback ?? '')
                : example<ConversationOut>('GET /api/v1/conversations/{conversation_id} 200')
              run.previous = undefined
              run.pendingFeedback = undefined
              run.conversation = {
                ...reviewed,
                id: run.conversation.id,
                title: run.conversation.title,
                project: run.conversation.project,
                flow: run.conversation.flow,
                mode: run.conversation.mode,
                feedback: run.conversation.feedback,
                progress: run.conversation.progress,
                state: 'in_review',
              }
              setSummary(run.conversation.id, { status: 'in_review', version: run.conversation.review?.version ?? 1 })
              controller.enqueue(encoder.encode(sse('review_ready', run.conversation)))
            }
            controller.close()
          },
        })
        return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } })
      }),
    ),

    // Ajustes
    http.get(`${API}/settings`, query(() => HttpResponse.json(db.settings as JsonBodyType))),
    http.get(
      `${API}/settings/usage`,
      query(() =>
        db.usage === 'unavailable'
          ? error(503, 'service_unavailable', 'No se pudo leer el consumo de hoy.')
          : HttpResponse.json(db.usage as JsonBodyType),
      ),
    ),

    // Lo que la API simulada aún no cubre.
    http.all(`${API}/*`, () => error(404, 'not_found', 'Aún no está en la API simulada del frontend.')),
  ]
}
