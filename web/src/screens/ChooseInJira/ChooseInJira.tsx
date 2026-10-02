import { useEffect, useState } from 'react'
import { api, ApiRequestError, isAbortError } from '../../api/client.ts'
import type { ApiError, IssueSummary, ProjectSummary } from '../../api/types.ts'
import { Button } from '../../components/Button/index.ts'
import { Listbox, type ListboxItem } from '../../components/Listbox/index.ts'
import { Modal } from '../../components/Modal/index.ts'
import { ErrorCard } from '../../components/States/index.ts'
import styles from './ChooseInJira.module.css'

/** Espera entre pulsaciones antes de buscar en Jira. */
export const SEARCH_DEBOUNCE_MS = 300

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
  const [error, setError] = useState<ApiError | undefined>()
  const [choosing, setChoosing] = useState(false)
  // Reintentar (UI.md §7) vuelve a pedir lo que falló.
  const [round, setRound] = useState(0)

  const fail = (cause: unknown) => {
    if (cause instanceof ApiRequestError) setError(cause.error)
  }

  useEffect(() => {
    let cancelled = false
    api
      .projects()
      .then((value) => {
        if (cancelled) return
        setError(undefined)
        setProjects(value.projects)
        setProjectKey((current) => current ?? value.preselected ?? value.projects[0]?.key)
      })
      .catch((cause: unknown) => !cancelled && fail(cause))
    return () => {
      cancelled = true
    }
  }, [round])

  useEffect(() => {
    if (!projectKey) return
    let cancelled = false
    api
      .epics(projectKey)
      .then((value) => {
        if (cancelled) return
        setError(undefined)
        setEpics(value)
      })
      .catch((cause: unknown) => !cancelled && fail(cause))
    return () => {
      cancelled = true
    }
  }, [projectKey, round])

  useEffect(() => {
    if (!epicKey) return
    let cancelled = false
    api
      .stories(epicKey)
      .then((value) => {
        if (cancelled) return
        setError(undefined)
        setStories(value)
      })
      .catch((cause: unknown) => !cancelled && fail(cause))
    return () => {
      cancelled = true
    }
  }, [epicKey, round])

  // Búsqueda por texto o clave en el proyecto, con espera entre pulsaciones.
  useEffect(() => {
    const q = query.trim()
    if (!projectKey || !q) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      api
        .search(projectKey, q, controller.signal)
        .then((items) => {
          setError(undefined)
          setResults(items)
        })
        .catch((cause: unknown) => {
          if (!isAbortError(cause)) fail(cause)
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [projectKey, query, round])

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
  }

  const selectEpic = (key: string) => {
    if (key === epicKey) return
    setEpicKey(key)
    setStoryKey(undefined)
    if (!searching) setStories([])
  }

  const use = async (origin?: IssueSummary) => {
    if (!project) return
    setChoosing(true)
    try {
      if (project.key !== initialProject) await api.chooseProject(project.key)
      onPick({ project, origin })
    } catch (cause) {
      fail(cause)
    } finally {
      setChoosing(false)
    }
  }

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
          placeholder={`Buscar por texto o clave en el proyecto ${projectKey ?? ''}`.trim()}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            if (!event.target.value.trim()) setResults(undefined)
          }}
        />
      </div>
      {error && (
        <div className={styles.error}>
          <ErrorCard
            key={`${error.code}-${error.message}`}
            error={error}
            onAction={() => {
              setError(undefined)
              setRound((current) => current + 1)
            }}
          />
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
        />
        <Listbox
          label={searching ? `Épicas encontradas en ${projectKey}` : `Épicas de ${projectKey}`}
          heading={searching ? `Épicas encontradas (${epicList.length})` : `Épicas de ${projectKey} (${epicList.length})`}
          items={toItems(epicList)}
          selectedId={epicKey}
          onSelect={selectEpic}
          emptyText={searching ? 'Ninguna épica coincide.' : 'Este proyecto no tiene épicas.'}
          note={<p className={styles.note}>Elegir la épica sirve para crear una HU nueva dentro de ella.</p>}
        />
        <Listbox
          label={searching ? `HU encontradas en ${projectKey}` : epicKey ? `HU de ${epicKey}` : 'HU'}
          heading={searching ? `HU encontradas (${storyList.length})` : epicKey ? `HU de ${epicKey} (${storyList.length})` : 'HU'}
          items={toItems(storyList)}
          selectedId={storyKey}
          onSelect={setStoryKey}
          emptyText={searching ? 'Ninguna HU coincide.' : epicKey ? 'Esta épica no tiene HU.' : 'Elige una épica para ver sus HU.'}
        />
      </div>
    </Modal>
  )
}

