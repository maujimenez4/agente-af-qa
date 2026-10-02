import { useState } from 'react'
import { api, toApiError } from '../api/client.ts'
import type { ApiError, ConversationOut, UserOut } from '../api/types.ts'
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
  | { name: 'generating'; conversation: ConversationOut; request: StartRequest }
  | { name: 'ready'; conversation: ConversationOut }
  | { name: 'closed'; conversation: ConversationOut }

// Conversaciones ya cerradas: aprobar y publicar llegan después de T-57 (recibo y resultado).
const CLOSED_TEXT: Partial<Record<ConversationOut['state'], string>> = {
  approved: 'Propuesta aprobada. El recibo y el resultado llegan después del punto de control de la demo.',
  simulated: 'Publicación simulada. El resultado llega después del punto de control de la demo.',
  published: 'Publicada en Jira. El resultado llega después del punto de control de la demo.',
  discarded: 'Propuesta descartada: no se publicó nada en Jira.',
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
        setView({ name: 'generating', conversation, request: { flow: conversation.flow, text: '', project: conversation.project } })
      } else if (conversation.state === 'in_review') {
        setView({ name: 'ready', conversation })
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
            onRetry={() => setView({ name: 'origin', request: view.request })}
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
          />
        )}
        {view.name === 'closed' && (
          <SoonScreen
            title={conversationTitle(view.conversation.title)}
            text={CLOSED_TEXT[view.conversation.state] ?? 'Esta conversación ya terminó.'}
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
