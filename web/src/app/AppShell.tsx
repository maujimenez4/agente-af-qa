import { useState } from 'react'
import type { ConversationOut, UserOut } from '../api/types.ts'
import { Button } from '../components/Button/index.ts'
import { ConversationList } from '../components/ConversationList/index.ts'
import { homeZone, Rail, type Zone } from '../components/Rail/index.ts'
import { useUsage } from '../hooks/useUsage.ts'
import { ChooseInJira, type JiraPick } from '../screens/ChooseInJira/ChooseInJira.tsx'
import { HomeScreen, type StartRequest } from '../screens/Home/HomeScreen.tsx'
import { OriginScreen } from '../screens/Origin/OriginScreen.tsx'
import { GeneratingScreen } from '../screens/Generating/GeneratingScreen.tsx'
import { readyHeadline } from '../screens/Generating/headline.ts'
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
        onSelect={setCurrentId}
      />
      <main className={styles.main}>
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
          <SoonScreen
            title={view.conversation.title}
            text={`${readyHeadline(view.conversation)}. La pantalla Iterar llega en el siguiente paso.`}
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
