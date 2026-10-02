import { useEffect, useState } from 'react'
import { api, ApiRequestError } from '../../api/client.ts'
import type { ApiError, IssueSummary, ProjectSummary, SettingsOut, StartProposal, UserOut } from '../../api/types.ts'
import { IconButton } from '../../components/Button/index.ts'
import { FlowCard } from '../../components/Card/index.ts'
import { Chip } from '../../components/Chip/index.ts'
import { Composer, ModelTag, ProjectButton, ToolButton } from '../../components/Composer/index.ts'
import { QLogo } from '../../components/QMark/index.ts'
import { ErrorCard, Notice, SIMULATION_NOTICE } from '../../components/States/index.ts'
import { DISABLED_HINT, defaultFlow, FLOWS, type FlowId } from './flows.ts'
import styles from './Home.module.css'

/** Lo que Inicio pasa a la siguiente pantalla (Origen y fuentes). */
export interface StartRequest {
  flow: FlowId
  text: string
  project: string
  /** Origen elegido en Jira o en los recientes, si lo hay. */
  origin?: IssueSummary
  /** Propuesta del arranque guiado (POST /start/propose), si se escribió texto. */
  proposal?: StartProposal
}

export interface HomeScreenProps {
  user: UserOut
  onStart: (request: StartRequest) => void
  /** Abre «Elegir en Jira» (Mixta 1b). Sin él, el botón sale desactivado. */
  onOpenJira?: (project: ProjectSummary | undefined) => void
  /** Origen elegido fuera de Inicio (p. ej. en «Elegir en Jira»). */
  pickedOrigin?: IssueSummary
  /** Proyecto elegido fuera de Inicio. */
  pickedProject?: ProjectSummary
}

function modelLabel(settings: SettingsOut | undefined, task: string): string {
  const override = settings?.tasks.find((item) => item.task === task)?.override
  return override ? `${override.provider} · ${override.model}` : 'Modelo automático'
}

function recentLabel(issue: IssueSummary): string {
  return issue.issue_type === 'Epic' ? `Épica · ${issue.summary}` : issue.summary
}

// Mixta 1 · Inicio (UI.md §4.1): flujo por rol, proyecto, compositor, recientes y aviso de simulación.
export function HomeScreen({ user, onStart, onOpenJira, pickedOrigin, pickedProject }: HomeScreenProps) {
  const [flow, setFlow] = useState<FlowId>(defaultFlow(user.permissions))
  const [text, setText] = useState('')
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectKey, setProjectKey] = useState<string | undefined>()
  const [settings, setSettings] = useState<SettingsOut | undefined>()
  const [recents, setRecents] = useState<IssueSummary[]>([])
  const [origin, setOrigin] = useState<IssueSummary | undefined>(pickedOrigin)
  const [error, setError] = useState<ApiError | undefined>()
  const [sending, setSending] = useState(false)

  // Lo que llega de «Elegir en Jira» sustituye a lo elegido aquí.
  const [seenPick, setSeenPick] = useState({ origin: pickedOrigin, project: pickedProject })
  if (seenPick.origin !== pickedOrigin || seenPick.project !== pickedProject) {
    setSeenPick({ origin: pickedOrigin, project: pickedProject })
    // Un proyecto nuevo sin origen quita el origen anterior, que era de otro proyecto.
    setOrigin(pickedOrigin ?? (pickedProject && pickedProject.key !== projectKey ? undefined : origin))
    if (pickedProject) setProjectKey(pickedProject.key)
  }

  useEffect(() => {
    let cancelled = false
    const fail = (cause: unknown) => {
      if (!cancelled && cause instanceof ApiRequestError) setError(cause.error)
    }
    api
      .projects()
      .then((value) => {
        if (cancelled) return
        setProjects(value.projects)
        setProjectKey((current) => current ?? value.preselected ?? value.projects[0]?.key)
      })
      .catch(fail)
    api
      .settings()
      .then((value) => {
        if (!cancelled) setSettings(value)
      })
      .catch(fail)
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!projectKey) return
    let cancelled = false
    api
      .search(projectKey)
      .then((items) => {
        if (!cancelled) setRecents(items.slice(0, 4))
      })
      .catch(() => {
        if (!cancelled) setRecents([])
      })
    return () => {
      cancelled = true
    }
  }, [projectKey])

  const project = projects.find((item) => item.key === projectKey) ?? pickedProject
  const current = FLOWS.find((item) => item.id === flow) ?? FLOWS[0]
  const canSubmit = Boolean(projectKey) && (text.trim().length > 0 || origin !== undefined) && !sending

  const submit = async () => {
    if (!projectKey) return
    setError(undefined)
    if (!text.trim()) {
      onStart({ flow, text: '', project: projectKey, origin })
      return
    }
    setSending(true)
    try {
      const proposal = await api.propose({ text: text.trim(), project: projectKey, mode: flow === 'tests' ? 'qa' : 'functional' })
      onStart({ flow, text: text.trim(), project: projectKey, origin, proposal })
    } catch (cause) {
      if (cause instanceof ApiRequestError) setError(cause.error)
      else throw cause
    } finally {
      setSending(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.content}>
        <header className={`${styles.hero} ${styles.rise}`}>
          <div className={styles.mark} aria-hidden="true">
            <QLogo size={30} />
          </div>
          <h1 className={styles.title}>¿En qué trabajamos hoy?</h1>
          <p className={styles.lead}>
            Elige qué hacemos y de qué partimos. Después lo mejoramos conversando. Nada se publica en Jira sin tu
            aprobación.
          </p>
        </header>

        <div className={`${styles.flows} ${styles.rise} ${styles.d1}`} role="group" aria-label="Qué quieres hacer">
          {FLOWS.map((item) => {
            const allowed = user.permissions.includes(item.permission)
            return (
              <FlowCard
                key={item.id}
                label={item.label}
                hint={item.hint}
                icon={item.icon}
                selected={flow === item.id}
                onSelect={() => setFlow(item.id)}
                disabledHint={allowed ? undefined : DISABLED_HINT[item.permission]}
              />
            )
          })}
        </div>

        {error && <ErrorCard key={`${error.code}-${error.message}`} error={error} />}

        <div className={`${styles.rise} ${styles.d2}`}>
          <Composer
            placeholder={current?.placeholder ?? ''}
            value={text}
            onChange={setText}
            onSubmit={() => void submit()}
            canSubmit={canSubmit}
            attachment={
              origin && (
                <p className={styles.origin}>
                  <span>
                    Origen: <b>{origin.key}</b> · {origin.summary}
                  </span>
                  <IconButton icon="close" label={`Quitar el origen ${origin.key}`} size="sm" onClick={() => setOrigin(undefined)} />
                </p>
              )
            }
            tools={
              <>
                <ProjectButton
                  projectKey={project?.key}
                  projectName={project?.name}
                  onClick={() => onOpenJira?.(project)}
                  disabled={!onOpenJira}
                />
                <ToolButton icon="work" onClick={() => onOpenJira?.(project)} disabled={!onOpenJira}>
                  Elegir en Jira
                </ToolButton>
                <ModelTag label={modelLabel(settings, flow === 'tests' ? 'generate_tests' : 'generate_story')} />
              </>
            }
          />
        </div>

        {projectKey && recents.length > 0 && (
          <section className={styles.recents} aria-labelledby="recents-title">
            <h2 id="recents-title" className={styles.recentsTitle}>
              Recientes en {projectKey}
            </h2>
            {recents.map((issue) => (
              <Chip key={issue.key} variant="recent" issueKey={issue.key} onClick={() => setOrigin(issue)}>
                {recentLabel(issue)}
              </Chip>
            ))}
          </section>
        )}

        {settings?.publish_mode === 'simulation' && <Notice>{SIMULATION_NOTICE}</Notice>}
      </div>
    </div>
  )
}
