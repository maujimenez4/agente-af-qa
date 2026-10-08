import { useEffect, useState } from 'react'
import { api, ApiRequestError, isAbortError, toApiError } from '../../api/client.ts'
import type { ApiError, IssueSummary, ProjectSummary } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { Listbox, type ListboxItem } from '../../components/Listbox/index.ts'
import { Modal } from '../../components/Modal/index.ts'
import { ErrorCard } from '../../components/States/index.ts'
import styles from './ChooseInJira.module.css'

/** Espera entre pulsaciones antes de buscar en Jira. */
export const SEARCH_DEBOUNCE_MS = 300
/** Largo máximo de la búsqueda (`q` de `GET /projects/{key}/search`, contrato). */
export const SEARCH_MAX_LENGTH = 200

export interface JiraPick {
  project: ProjectSummary
  /** Épica (crear una HU nueva dentro de ella) o HU. Sin origen, solo cambia el proyecto. */
  origin?: IssueSummary
}

export interface ChooseInJiraProps {
  initialProject?: string
  onCancel: () => void
  onPick: (pick: JiraPick) => void
}

/**
 * PA-460: cada lista sabe si su carga está en curso, llegó o falló, para no decir «no tiene épicas» mientras Jira
 * responde. `round` vuelve a pedirla (su «Reintentar»).
 */
type Load = { status: 'loading' } | { status: 'ready' } | { status: 'error'; error: ApiError }
const LOADING: Load = { status: 'loading' }
const READY: Load = { status: 'ready' }
const failed = (cause: unknown): Load => ({ status: 'error', error: toApiError(cause) })

const toItems = (issues: readonly IssueSummary[]): ListboxItem[] =>
  issues.map((issue) => ({ id: issue.key, itemKey: issue.key, label: issue.summary }))

// Mixta 1b · Elegir en Jira (UI.md §4.2): proyectos, épicas y HU, con buscador por texto o clave.
export function ChooseInJira({ initialProject, onCancel, onPick }: ChooseInJiraProps) {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectKey, setProjectKey] = useState<string | undefined>(initialProject)
  const [epics, setEpics] = useState<IssueSummary[]>([])
  const [epicKey, setEpicKey] = useState<string | undefined>()
  const [stories, setStories] = useState<IssueSummary[]>([])
  const [storyKey, setStoryKey] = useState<string | undefined>()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<IssueSummary[] | undefined>()
  // Estado de cada carga (PA-460) y la vuelta con la que se pidió (su «Reintentar»).
  const [projectsLoad, setProjectsLoad] = useState<Load>(LOADING)
  const [epicsLoad, setEpicsLoad] = useState<Load>(LOADING)
  const [storiesLoad, setStoriesLoad] = useState<Load>(READY)
  const [searchLoad, setSearchLoad] = useState<Load>(READY)
  const [rounds, setRounds] = useState({ projects: 0, epics: 0, stories: 0, search: 0 })
  // Error al fijar el proyecto con «Usar…» (no es de ninguna lista).
  const [useError, setUseError] = useState<ApiError | undefined>()
  const [choosing, setChoosing] = useState(false)

  const retry = (list: keyof typeof rounds) => setRounds((current) => ({ ...current, [list]: current[list] + 1 }))

  useEffect(() => {
    let cancelled = false
    api
      .projects()
      .then((value) => {
        if (cancelled) return
        setProjects(value.projects)
        setProjectKey((current) => current ?? value.preselected ?? value.projects[0]?.key)
        setProjectsLoad(READY)
        // Sin proyecto que elegir, no hay épicas que cargar.
        if (!initialProject && !(value.preselected ?? value.projects[0]?.key)) setEpicsLoad(READY)
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setProjectsLoad(failed(cause))
        if (!initialProject) setEpicsLoad(READY)
      })
    return () => {
      cancelled = true
    }
  }, [rounds.projects, initialProject])

  useEffect(() => {
    if (!projectKey) return
    let cancelled = false
    api
      .epics(projectKey)
      .then((value) => {
        if (cancelled) return
        setEpics(value)
        setEpicsLoad(READY)
      })
      .catch((cause: unknown) => !cancelled && setEpicsLoad(failed(cause)))
    return () => {
      cancelled = true
    }
  }, [projectKey, rounds.epics])

  useEffect(() => {
    if (!epicKey) return
    let cancelled = false
    api
      .stories(epicKey)
      .then((value) => {
        if (cancelled) return
        setStories(value)
        setStoriesLoad(READY)
      })
      .catch((cause: unknown) => !cancelled && setStoriesLoad(failed(cause)))
    return () => {
      cancelled = true
    }
  }, [epicKey, rounds.stories])

  // Búsqueda por texto o clave en el proyecto, con espera entre pulsaciones.
  useEffect(() => {
    const q = query.trim()
    if (!projectKey || !q) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api
        .search(projectKey, q, controller.signal)
        .then((items) => {
          setResults(items)
          setSearchLoad(READY)
        })
        .catch((cause: unknown) => {
          if (!isAbortError(cause)) setSearchLoad(failed(cause))
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [projectKey, query, rounds.search])

  const searching = query.trim().length > 0
  const visibleProjects = searching
    ? projects.filter((item) => `${item.key} ${item.name}`.toLowerCase().includes(query.trim().toLowerCase()))
    : projects
  const epicList = searching ? (results ?? []).filter((issue) => issue.issue_type === 'Epic') : epics
  const storyList = searching ? (results ?? []).filter((issue) => issue.issue_type !== 'Epic') : stories

  const project = projects.find((item) => item.key === projectKey)
  const epic = epicList.find((item) => item.key === epicKey) ?? epics.find((item) => item.key === epicKey)
  const story = storyList.find((item) => item.key === storyKey) ?? stories.find((item) => item.key === storyKey)

  const selectProject = (key: string) => {
    if (key === projectKey) return
    setProjectKey(key)
    setEpicKey(undefined)
    setStoryKey(undefined)
    setEpics([])
    setStories([])
    setResults(undefined)
    setEpicsLoad(LOADING)
    setStoriesLoad(READY)
    if (searching) setSearchLoad(LOADING)
  }

  const selectEpic = (key: string) => {
    if (key === epicKey) return
    setEpicKey(key)
    setStoryKey(undefined)
    if (!searching) {
      setStories([])
      setStoriesLoad(LOADING)
    }
  }

  const changeQuery = (value: string) => {
    setQuery(value)
    if (value.trim()) setSearchLoad(LOADING)
    else {
      setResults(undefined)
      setSearchLoad(READY)
    }
  }

  const use = async (origin?: IssueSummary) => {
    if (!project) return
    setChoosing(true)
    setUseError(undefined)
    try {
      if (project.key !== initialProject) await api.chooseProject(project.key)
      onPick({ project, origin })
    } catch (cause) {
      if (cause instanceof ApiRequestError) setUseError(cause.error)
    } finally {
      setChoosing(false)
    }
  }

  /** La tarjeta de error de una carga, con su «Reintentar» (vuelve a pedir solo esa lista). */
  const loadError = (load: Load, list: keyof typeof rounds, onRetry?: () => void) =>
    load.status === 'error' ? (
      <ErrorCard
        key={`${list}-${rounds[list]}-${load.error.code}`}
        error={load.error}
        onAction={() => {
          onRetry?.()
          retry(list)
        }}
      />
    ) : undefined

  // Con búsqueda, épicas y HU salen de la misma consulta: su carga y su error son los de la búsqueda.
  const epicsShown = searching ? searchLoad : epicsLoad
  const storiesShown = searching ? searchLoad : storiesLoad
  const epicsList: keyof typeof rounds = searching ? 'search' : 'epics'
  const storiesList: keyof typeof rounds = searching ? 'search' : 'stories'

  const selection = story ?? epic
  const footer = (
    <>
      <p className={styles.selection} aria-live="polite">
        {selection ? (
          <>
            Seleccionada: <b>{`${selection.key} · ${selection.summary}`}</b>{' '}
            <span className={styles.muted}>
              (proyecto {projectKey}
              {story && epicKey ? `, épica ${epicKey}` : ''})
            </span>
          </>
        ) : (
          <span className={styles.muted}>Elige una épica o una HU.</span>
        )}
      </p>
      <Button onClick={onCancel}>Cancelar</Button>
      {!selection && project && project.key !== initialProject && (
        <Button onClick={() => void use()} disabled={choosing}>
          Usar el proyecto {project.key}
        </Button>
      )}
      {epic && (
        <Button variant={story ? 'secondary' : 'primary'} onClick={() => void use(epic)} disabled={choosing}>
          Usar la épica {epic.key}
        </Button>
      )}
      {story && (
        <Button variant="primary" onClick={() => void use(story)} disabled={choosing}>
          Usar {story.key}
        </Button>
      )}
    </>
  )

  return (
    <Modal title="Elegir en Jira" onClose={onCancel} footer={footer}>
      <div className={styles.search}>
        <label htmlFor="jira-search" className="visually-hidden">
          Buscar en Jira
        </label>
        <input
          id="jira-search"
          data-autofocus
          className={styles.searchInput}
          type="search"
          maxLength={SEARCH_MAX_LENGTH}
          placeholder={`Buscar por texto o clave en el proyecto ${projectKey ?? ''}`.trim()}
          value={query}
          onChange={(event) => changeQuery(event.target.value)}
        />
      </div>
      {useError && (
        <div className={styles.error}>
          <ErrorCard key={`${useError.code}-${useError.message}`} error={useError} onAction={() => setUseError(undefined)} />
        </div>
      )}
      <div className={styles.columns}>
        <Listbox
          label="Proyectos"
          heading={`Proyectos que ve la conexión (${visibleProjects.length})`}
          items={visibleProjects.map((item) => ({ id: item.key, itemKey: item.key, label: item.name }))}
          selectedId={projectKey}
          onSelect={selectProject}
          emptyText="Ningún proyecto coincide."
          loadingText={projectsLoad.status === 'loading' ? 'Cargando proyectos…' : undefined}
          error={loadError(projectsLoad, 'projects', () => setProjectsLoad(LOADING))}
        />
        <Listbox
          label={searching ? `Épicas encontradas en ${projectKey}` : `Épicas de ${projectKey}`}
          heading={searching ? `Épicas encontradas (${epicList.length})` : `Épicas de ${projectKey} (${epicList.length})`}
          items={toItems(epicList)}
          selectedId={epicKey}
          onSelect={selectEpic}
          emptyText={searching ? 'Ninguna épica coincide.' : 'Este proyecto no tiene épicas.'}
          loadingText={epicsShown.status === 'loading' ? (searching ? 'Buscando…' : 'Cargando épicas…') : undefined}
          error={loadError(epicsShown, epicsList, () => (searching ? setSearchLoad(LOADING) : setEpicsLoad(LOADING)))}
          note={<p className={styles.note}>Elegir la épica sirve para crear una HU nueva dentro de ella.</p>}
        />
        <Listbox
          label={searching ? `HU encontradas en ${projectKey}` : epicKey ? `HU de ${epicKey}` : 'HU'}
          heading={searching ? `HU encontradas (${storyList.length})` : epicKey ? `HU de ${epicKey} (${storyList.length})` : 'HU'}
          items={toItems(storyList)}
          selectedId={storyKey}
          onSelect={setStoryKey}
          emptyText={searching ? 'Ninguna HU coincide.' : epicKey ? 'Esta épica no tiene HU.' : 'Elige una épica para ver sus HU.'}
          loadingText={storiesShown.status === 'loading' ? (searching ? 'Buscando…' : 'Cargando HU…') : undefined}
          error={
            // Una carga, un error: el de la búsqueda va (con su «Reintentar») en la columna de épicas.
            searching && searchLoad.status === 'error' ? (
              <p className={styles.note} role="status">
                La búsqueda no se pudo hacer.
              </p>
            ) : (
              loadError(storiesShown, storiesList, () => setStoriesLoad(LOADING))
            )
          }
        />
      </div>
    </Modal>
  )
}
