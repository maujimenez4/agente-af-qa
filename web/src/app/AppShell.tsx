import { useState } from 'react'
import { api, toApiError } from '../api/client.ts'
import type { ApiError, ConversationOut, PublishOutcome, UserOut } from '../api/types.ts'
import { ErrorCard } from '../components/States/index.ts'
import { Button } from '../components/Button/index.ts'
import { ConversationList, conversationTitle } from '../components/ConversationList/index.ts'
import { homeZone, Rail, type Zone } from '../components/Rail/index.ts'
import { useUsage } from '../hooks/useUsage.ts'
import { ChooseInJira, type JiraPick } from '../screens/ChooseInJira/ChooseInJira.tsx'
import { HomeScreen, type StartRequest } from '../screens/Home/HomeScreen.tsx'
import { OriginScreen } from '../screens/Origin/OriginScreen.tsx'
import { GeneratingScreen } from '../screens/Generating/GeneratingScreen.tsx'
import { IterateScreen } from '../screens/Iterate/IterateScreen.tsx'
import { ReceiptScreen } from '../screens/Receipt/ReceiptScreen.tsx'
import { ResultScreen } from '../screens/Result/ResultScreen.tsx'
import { hasResult } from '../screens/Result/resultText.ts'
import { useSession } from '../session/sessionContext.ts'
import styles from './AppShell.module.css'
import { SoonScreen } from './SoonScreen.tsx'
import { useConversations } from './useConversations.ts'

export interface AppShellProps {
  user: UserOut
}

// Marco de la app con sesión (UI.md §2): carril, lista de conversaciones y zona de trabajo.
// Navegación por estado, sin router (DESIGN-DECISIONS.md §4 bis).
export function AppShell({ user }: AppShellProps) {
  const { logout } = useSession()
  const [zone, setZone] = useState<Zone>(homeZone(user.role))
  const usage = useUsage()

  return (
    <div className={styles.shell}>
      <Rail
        userRole={user.role}
        username={user.username}
        active={zone}
        usage={usage}
        onNavigate={setZone}
        onLogout={() => void logout()}
      />
      {user.role === 'admin' ? (
        <main className={styles.main}>
          <SoonScreen
            title="Disponible pronto"
            text="Los ajustes (conexiones, modelos, documentos y usuarios) llegarán después del punto de control de la demo."
          />
        </main>
      ) : (
        <WorkZone user={user} />
      )}
    </div>
  )
}

type WorkView =
  | { name: 'home' }
  | { name: 'origin'; request: StartRequest }
  // Sin `request` al retomar desde la lista: no hay una petición de Origen a la que volver.
  | { name: 'generating'; conversation: ConversationOut; request?: StartRequest }
  | { name: 'ready'; conversation: ConversationOut }
  | { name: 'receipt'; conversation: ConversationOut }
  | { name: 'result'; conversation: ConversationOut & { result: PublishOutcome } }
  | { name: 'closed'; conversation: ConversationOut }

// Conversaciones ya cerradas: aprobar y publicar llegan después de T-57 (recibo y resultado).
const CLOSED_TEXT: Partial<Record<ConversationOut['state'], string>> = {
  approved: 'Propuesta aprobada. El recibo y el resultado llegan después del punto de control de la demo.',
  simulated: 'Publicación simulada. El resultado llega después del punto de control de la demo.',
  published: 'Publicada en Jira. El resultado llega después del punto de control de la demo.',
  discarded: 'Propuesta descartada: no se publicó nada en Jira.',
  // Solo si la API no trae `error`: si lo trae, se muestra su mensaje tal cual (UI.md §7).
  error: 'Esta conversación no puede continuar. Empieza una nueva; nada se ha escrito en Jira.',
}

// Flujos fuera de la demo de T-57 (DESIGN-DECISIONS.md §4 bis).
const SOON_FLOWS: Partial<Record<StartRequest['flow'], { title: string; text: string }>> = {
  review: {
    title: 'Revisar la calidad: disponible pronto',
    text: 'El informe INVEST y los hallazgos de una HU llegan después del punto de control de la demo.',
  },
  tests: {
    title: 'Preparar pruebas: disponible pronto',
    text: 'El flujo de QA (casos, cobertura, datos y estrategia) llega después del punto de control de la demo.',
  },
}

function WorkZone({ user }: { user: UserOut }) {
  const { conversations, error: conversationsError, reload } = useConversations()
  const [currentId, setCurrentId] = useState<string | undefined>()
  const [view, setView] = useState<WorkView>({ name: 'home' })
  // «Elegir en Jira» (Mixta 1b): abierto con el proyecto de Inicio; lo elegido vuelve a Inicio.
  const [jira, setJira] = useState<{ initialProject?: string } | null>(null)
  const [picked, setPicked] = useState<JiraPick | undefined>()
  const [openError, setOpenError] = useState<ApiError | undefined>()

  // Retomar una conversación de la lista (T-52): según su estado, Generando, Iterar o un aviso.
  const openConversation = async (threadId: string) => {
    setOpenError(undefined)
    try {
      const conversation = await api.conversation(threadId)
      if (conversation.state === 'generating') {
        setView({ name: 'generating', conversation })
      } else if (conversation.state === 'in_review') {
        setView({ name: 'ready', conversation })
      } else if (hasResult(conversation)) {
        setView({ name: 'result', conversation })
      } else {
        setView({ name: 'closed', conversation })
      }
    } catch (cause) {
      setOpenError(toApiError(cause))
    }
  }

  return (
    <>
      <ConversationList
        conversations={conversations}
        error={conversationsError}
        onRetry={reload}
        currentId={currentId}
        onNew={() => {
          setCurrentId(undefined)
          setPicked(undefined)
          setView({ name: 'home' })
        }}
        onSelect={(threadId) => {
          setCurrentId(threadId)
          void openConversation(threadId)
        }}
      />
      <main className={styles.main}>
        {openError && (
          <div className={styles.banner}>
            <ErrorCard key={`${openError.code}-${openError.message}`} error={openError} onAction={() => setOpenError(undefined)} />
          </div>
        )}
        {view.name === 'home' && (
          <HomeScreen
            user={user}
            onStart={(request) => setView({ name: 'origin', request })}
            onOpenJira={(project) => setJira({ initialProject: project?.key })}
            pickedOrigin={picked?.origin}
            pickedProject={picked?.project}
          />
        )}
        {view.name === 'origin' && (
          <OriginOrSoon
            request={view.request}
            onBack={() => setView({ name: 'home' })}
            onGenerating={(conversation) => {
              setView({ name: 'generating', conversation, request: view.request })
              reload()
            }}
          />
        )}
        {view.name === 'generating' && (
          <GeneratingScreen
            key={view.conversation.id}
            conversation={view.conversation}
            onReady={(conversation) => {
              setView({ name: 'ready', conversation })
              reload()
            }}
            onRetry={() => {
              if (view.request) {
                setView({ name: 'origin', request: view.request })
              } else {
                setCurrentId(undefined)
                setView({ name: 'home' })
              }
            }}
          />
        )}
        {view.name === 'ready' && (
          <IterateScreen
            key={view.conversation.id}
            conversation={view.conversation}
            onDiscarded={() => {
              setCurrentId(undefined)
              setView({ name: 'home' })
              reload()
            }}
            onRestart={() => {
              setCurrentId(undefined)
              setView({ name: 'home' })
            }}
            onReview={(conversation) => setView({ name: 'receipt', conversation })}
          />
        )}
        {view.name === 'receipt' && (
          <ReceiptScreen
            key={view.conversation.id}
            conversation={view.conversation}
            onBack={(conversation) => setView({ name: 'ready', conversation })}
            onDone={(conversation) => {
              if (conversation.state === 'in_review') setView({ name: 'ready', conversation })
              else if (hasResult(conversation)) setView({ name: 'result', conversation })
              else setView({ name: 'closed', conversation })
              reload()
            }}
            onDiscarded={() => {
              setCurrentId(undefined)
              setView({ name: 'home' })
              reload()
            }}
            onRestart={() => {
              setCurrentId(undefined)
              setView({ name: 'home' })
            }}
          />
        )}
        {view.name === 'result' && <ResultScreen key={view.conversation.id} conversation={view.conversation} />}
        {view.name === 'closed' && (
          <ClosedConversation
            conversation={view.conversation}
            onRestart={() => {
              setCurrentId(undefined)
              setView({ name: 'home' })
            }}
            onRetried={(conversation) => {
              setView({ name: 'generating', conversation })
              reload()
            }}
          />
        )}
      </main>
      {jira && (
        <ChooseInJira
          initialProject={jira.initialProject}
          onCancel={() => setJira(null)}
          onPick={(pick) => {
            setPicked(pick)
            setJira(null)
          }}
        />
      )}
    </>
  )
}

// Conversación terminada: su aviso o, si acabó en error, la tarjeta con el mensaje de la API tal cual.
// /retry ya no puede repetir nada: solo queda empezar otra. Con un fallo pasajero (429, 503…) se puede volver a pedir.
const RETRY_FINAL = new Set<string>(['not_in_error', 'handoff_unavailable'])

// En error se puede repetir el paso que falló con POST /retry (PA-276); un 409 not_in_error se muestra.
function ClosedConversation({
  conversation,
  onRestart,
  onRetried,
}: {
  conversation: ConversationOut
  onRestart: () => void
  onRetried: (conversation: ConversationOut) => void
}) {
  const [retryError, setRetryError] = useState<ApiError | undefined>()
  const [retrying, setRetrying] = useState(false)
  const title = conversationTitle(conversation.title)
  // En error siempre se puede pedir /retry (docs/api/README.md), aunque la API no traiga `error`.
  if (conversation.state === 'error') {
    const shown = retryError ?? conversation.error
    const retry = async () => {
      setRetrying(true)
      setRetryError(undefined)
      try {
        onRetried(await api.retry(conversation.id))
      } catch (cause) {
        setRetryError(toApiError(cause))
      } finally {
        setRetrying(false)
      }
    }
    return (
      <SoonScreen title={title} text={shown ? 'Nada se ha escrito en Jira.' : (CLOSED_TEXT.error ?? '')}>
        {/* El mensaje de la API tal cual; las acciones van fuera de la tarjeta. */}
        {shown && <ErrorCard error={shown} />}
        <span className={styles.closedActions}>
          {!(retryError && RETRY_FINAL.has(retryError.code)) && (
            <Button variant="primary" disabled={retrying} onClick={() => void retry()}>
              Reintentar
            </Button>
          )}
          <Button onClick={onRestart}>Empezar una conversación nueva</Button>
        </span>
      </SoonScreen>
    )
  }
  return <SoonScreen title={title} text={CLOSED_TEXT[conversation.state] ?? 'Esta conversación ya terminó.'} />
}

function OriginOrSoon({
  request,
  onBack,
  onGenerating,
}: {
  request: StartRequest
  onBack: () => void
  onGenerating: (conversation: ConversationOut) => void
}) {
  const soon = SOON_FLOWS[request.flow]
  if (!soon) return <OriginScreen request={request} onBack={onBack} onGenerating={onGenerating} />
  return (
    <div className={styles.centered}>
      <section className={styles.soon} aria-labelledby="flow-soon">
        <h1 id="flow-soon" className={styles.soonTitle}>
          {soon.title}
        </h1>
        <p className={styles.soonText}>{soon.text}</p>
        <Button onClick={onBack}>Volver al inicio</Button>
      </section>
    </div>
  )
}
