import { useEffect, useState } from 'react'
import { api, ApiRequestError, toApiError } from '../../api/client.ts'
import type { ApiError, ConversationOut, IssueSummary, ProjectSummary, SettingsOut, StartProposal, UserOut } from '../../api/types.ts'
import { IconButton } from '../../components/Button/index.ts'
import { FlowCard } from '../../components/Card/index.ts'
import { Chip } from '../../components/Chip/index.ts'
import { Composer, ModelTag, ProjectButton, ToolButton } from '../../components/Composer/index.ts'
import { QLogo } from '../../components/QMark/index.ts'
import { ErrorCard, Notice, SIMULATION_NOTICE } from '../../components/States/index.ts'
import { DISABLED_HINT, defaultFlow, FLOWS, type FlowId } from './flows.ts'
import styles from './Home.module.css'
import { QaHandoffs } from './QaHandoffs.tsx'
import { ASSISTANT_NAME, HOME_CONTROL, HOME_GREETING_AFTER, HOME_GREETING_BEFORE, HOME_WRITE_HINT } from '../../text/assistant.ts'

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
  /** QA recogió una HU pendiente (T-54): su conversación, ya generando. Sin él, no hay lista de pendientes. */
  onTaken?: (conversation: ConversationOut) => void
}

function modelLabel(settings: SettingsOut | undefined, task: string): string {
  const override = settings?.tasks.find((item) => item.task === task)?.override
  return override ? `${override.provider} · ${override.model}` : 'Modelo automático'
}

function recentLabel(issue: IssueSummary): string {
  return issue.issue_type === 'Epic' ? `Épica · ${issue.summary}` : issue.summary
}

// Mixta 1 · Inicio (UI.md §4.1): flujo por rol, proyecto, compositor, recientes y aviso de simulación.
export function HomeScreen({ user, onStart, onOpenJira, pickedOrigin, pickedProject, onTaken }: HomeScreenProps) {
  const [flow, setFlow] = useState<FlowId>(defaultFlow(user.permissions))
  const [text, setText] = useState('')
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectKey, setProjectKey] = useState<string | undefined>()
  const [settings, setSettings] = useState<SettingsOut | undefined>()
  const [recents, setRecents] = useState<IssueSummary[]>([])
  const [origin, setOrigin] = useState<IssueSummary | undefined>(pickedOrigin)
  const [error, setError] = useState<ApiError | undefined>()
  const [sending, setSending] = useState(false)
  // Reintentar (UI.md §7) vuelve a cargar proyectos y ajustes.
  const [round, setRound] = useState(0)

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
        setError(undefined)
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
  }, [round])

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
      setError(toApiError(cause))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.content}>
        <header className={`${styles.hero} ${styles.rise}`}>
          {/* PA-478: la Q a 56 px y el saludo de FAQ encima de la pregunta. */}
          <QLogo size={56} />
          <p className={styles.greeting}>
            {HOME_GREETING_BEFORE}
            <b>{ASSISTANT_NAME}</b>
            {HOME_GREETING_AFTER}
          </p>
          <h1 className={styles.title}>¿En qué trabajamos hoy?</h1>
          <p className={styles.lead}>Elige qué hacemos y de qué partimos. Después lo mejoramos conversando.</p>
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

        {error && (
          <ErrorCard
            key={`${error.code}-${error.message}`}
            error={error}
            onAction={() => {
              setError(undefined)
              setRound((current) => current + 1)
            }}
          />
        )}

        <div className={`${styles.write} ${styles.rise} ${styles.d2}`}>
          <p className={styles.writeHint}>{HOME_WRITE_HINT}</p>
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

        {onTaken && user.permissions.includes('generate_tests') && (
          <div className={`${styles.rise} ${styles.d2}`}>
            <QaHandoffs onTaken={onTaken} />
          </div>
        )}

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

        <p className={styles.control}>{HOME_CONTROL}</p>
      </div>
    </div>
  )
}
