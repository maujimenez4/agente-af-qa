import { useEffect, useId, useState } from 'react'
import { api, isAbortError, toApiError } from '../../api/client.ts'
import type { ApiError, MemoryOut, MemorySummary, ProjectSummary } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { DownloadButton } from '../../components/Download/index.ts'
import p from '../../components/Proposal/Proposal.module.css'
import { EmptyState, ErrorCard, Skeleton } from '../../components/States/index.ts'
import styles from './Memory.module.css'
import {
  INDEXED_TEXT,
  LIST_NOTE,
  MEMORY_LIMIT,
  MEMORY_SEARCH_DEBOUNCE_MS,
  MEMORY_SECTIONS,
  memoryDate,
  memoryFileName,
  memoryShortDate,
  NO_MATCHES,
  NO_MEMORIES,
  sectionItems,
  sectionText,
} from './memoryText.ts'

export interface MemoryScreenProps {
  /** Memoria que abrir al entrar (p. ej. *Ver la memoria* en el Resultado). */
  openKey?: string
}

type Load<T> = { status: 'loading' } | { status: 'error'; error: ApiError } | { status: 'ready'; data: T }

/** El valor tras `delay` ms sin cambios (el buscador no pide la lista en cada pulsación). */
function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/** Resultado de la petición `request`; mientras no llega el suyo (o tras cambiar de petición), «cargando». */
type Answer<T> = { request: string; load: Load<T> }

function settle<T>(request: string, promise: Promise<T>, set: (answer: Answer<T>) => void): void {
  promise
    .then((data) => set({ request, load: { status: 'ready', data } }))
    .catch((cause: unknown) => {
      if (!isAbortError(cause)) set({ request, load: { status: 'error', error: toApiError(cause) } })
    })
}

/** Lista de `GET /memories` con los filtros; una petición nueva cancela la anterior. */
function useMemoryList(project: string, q: string, attempt: number): Load<MemorySummary[]> {
  const request = JSON.stringify([project, q, attempt])
  const [answer, setAnswer] = useState<Answer<MemorySummary[]>>()
  useEffect(() => {
    const controller = new AbortController()
    settle(request, api.memories({ project: project || null, q, limit: MEMORY_LIMIT }, controller.signal), setAnswer)
    return () => controller.abort()
  }, [request, project, q])
  return answer?.request === request ? answer.load : { status: 'loading' }
}

/** Una memoria con su contenido (`GET /memories/{key}`); sin clave, nada. */
function useMemory(key: string | undefined, attempt: number): Load<MemoryOut> | undefined {
  const request = JSON.stringify([key ?? null, attempt])
  const [answer, setAnswer] = useState<Answer<MemoryOut>>()
  useEffect(() => {
    if (!key) return
    const controller = new AbortController()
    settle(request, api.memory(key, controller.signal), setAnswer)
    return () => controller.abort()
  }, [request, key])
  if (!key) return undefined
  return answer?.request === request ? answer.load : { status: 'loading' }
}

// Memoria (PA-329; T-33 en la API): las memorias de las HU publicadas, para los tres roles. Solo lectura.
export function MemoryScreen({ openKey }: MemoryScreenProps) {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [project, setProject] = useState('')
  const [search, setSearch] = useState('')
  const q = useDebounced(search.trim(), MEMORY_SEARCH_DEBOUNCE_MS)
  const [listAttempt, setListAttempt] = useState(0)
  const list = useMemoryList(project, q, listAttempt)
  const [selected, setSelected] = useState<string | undefined>(openKey)
  const [detailAttempt, setDetailAttempt] = useState(0)
  const detail = useMemory(selected, detailAttempt)
  const projectId = useId()
  const searchId = useId()

  useEffect(() => {
    // Sin la lista de proyectos, el selector se queda en «Todos los proyectos».
    api
      .projects()
      .then((out) => setProjects(out.projects))
      .catch(() => setProjects([]))
  }, [])

  const filtered = Boolean(project || q)

  return (
    <div className={styles.zone}>
      <aside className={styles.list} aria-label="Memorias">
        <h1 className={styles.heading}>Memoria</h1>
        <label htmlFor={projectId} className="visually-hidden">
          Proyecto
        </label>
        <select id={projectId} className={styles.control} value={project} onChange={(event) => setProject(event.target.value)}>
          <option value="">Todos los proyectos</option>
          {projects.map((item) => (
            <option key={item.key} value={item.key}>
              {item.key} · {item.name}
            </option>
          ))}
        </select>
        <label htmlFor={searchId} className="visually-hidden">
          Buscar en las memorias
        </label>
        <input
          id={searchId}
          type="search"
          className={styles.control}
          placeholder="Buscar en las memorias"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className={styles.items}>
          {list.status === 'loading' && (
            <div role="status" aria-label="Cargando las memorias">
              <Skeleton lines={4} />
            </div>
          )}
          {list.status === 'error' && <ErrorCard key={listAttempt} error={list.error} onAction={() => setListAttempt((n) => n + 1)} />}
          {list.status === 'ready' && list.data.length === 0 && (
            <p className={styles.empty} role="status">
              {filtered ? NO_MATCHES : NO_MEMORIES}
            </p>
          )}
          {list.status === 'ready' && list.data.length > 0 && (
            <ul className={styles.memories}>
              {list.data.map((item) => (
                <li key={item.key}>
                  <button
                    type="button"
                    className={styles.memory}
                    aria-current={item.key === selected ? 'true' : undefined}
                    onClick={() => {
                      setSelected(item.key)
                      setDetailAttempt(0)
                    }}
                  >
                    <span className={styles.memoryHead}>
                      <span className={styles.key}>{item.key}</span>
                      <span className={styles.meta}>v{item.version}</span>
                      <span className={styles.dot} data-indexed={item.indexed ? '' : undefined} aria-hidden="true" />
                      <span className="visually-hidden">{INDEXED_TEXT[`${item.indexed}`].label}</span>
                    </span>
                    <span className={styles.memoryTitle}>{item.title}</span>
                    <span className={styles.meta}>
                      {item.project}
                      {memoryShortDate(item.updated_at) ? ` · ${memoryShortDate(item.updated_at)}` : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <p className={styles.note}>{LIST_NOTE}</p>
      </aside>
      <main className={styles.detail} aria-label="Memoria elegida">
        {!detail && (
          <EmptyState title="Elige una memoria" text="Verás su objetivo, alcance, reglas, criterios y decisiones, tal como quedaron al publicar la HU." />
        )}
        {detail?.status === 'loading' && (
          <div role="status" aria-label="Cargando la memoria" className={styles.card}>
            <Skeleton lines={6} />
          </div>
        )}
        {detail?.status === 'error' && (
          <ErrorCard key={`${selected}-${detailAttempt}`} error={detail.error} onAction={() => setDetailAttempt((n) => n + 1)} />
        )}
        {detail?.status === 'ready' && <MemoryDetail memory={detail.data} />}
      </main>
    </div>
  )
}

function MemoryDetail({ memory }: { memory: MemoryOut }) {
  const indexed = INDEXED_TEXT[`${memory.indexed}`]
  const titleId = useId()
  const date = memoryDate(memory.updated_at)
  return (
    <article className={styles.card} aria-labelledby={titleId}>
      <header className={styles.detailHead}>
        <div className={styles.detailTitle}>
          <h2 id={titleId} className={styles.title}>
            {memory.key} · Memoria v{memory.version}
          </h2>
          <p className={styles.meta}>
            Proyecto {memory.project}
            {date ? ` · Actualizada el ${date}` : ''}
          </p>
        </div>
        <span className={styles.status}>
          <Badge tone={memory.indexed ? 'success' : 'neutral'} icon={memory.indexed ? 'done' : undefined}>
            {indexed.label}
          </Badge>
        </span>
        <DownloadButton label="Descargar la memoria" fileName={memoryFileName(memory.key)} text={memory.markdown} />
      </header>
      <p className={styles.indexNote}>{indexed.note}</p>
      {MEMORY_SECTIONS.map((section) => (
        <section key={section.field} className={styles.section} aria-label={section.title}>
          <h3 className={p.sectionTitle}>{section.title}</h3>
          {section.kind === 'text' ? (
            <TextOrEmpty text={sectionText(memory.memory, section.field)} />
          ) : (
            <ItemsOrEmpty items={sectionItems(memory.memory, section.field)} />
          )}
        </section>
      ))}
    </article>
  )
}

function TextOrEmpty({ text }: { text: string }) {
  return text ? <p className={styles.text}>{text}</p> : <p className={p.empty}>Sin datos.</p>
}

function ItemsOrEmpty({ items }: { items: string[] }) {
  if (items.length === 0) return <p className={p.empty}>Ninguno.</p>
  return (
    <ul className={p.bullets}>
      {items.map((item, index) => (
        <li key={`${index}-${item}`}>{item}</li>
      ))}
    </ul>
  )
}
