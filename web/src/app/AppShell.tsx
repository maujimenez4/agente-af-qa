import { useState } from 'react'
import type { UserOut } from '../api/types.ts'
import { Button } from '../components/Button/index.ts'
import { ConversationList } from '../components/ConversationList/index.ts'
import { homeZone, Rail, type Zone } from '../components/Rail/index.ts'
import { useUsage } from '../hooks/useUsage.ts'
import { ChooseInJira, type JiraPick } from '../screens/ChooseInJira/ChooseInJira.tsx'
import { HomeScreen, type StartRequest } from '../screens/Home/HomeScreen.tsx'
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

type WorkView = { name: 'home' } | { name: 'origin'; request: StartRequest }

function WorkZone({ user }: { user: UserOut }) {
  const { conversations } = useConversations()
  const [currentId, setCurrentId] = useState<string | undefined>()
  const [view, setView] = useState<WorkView>({ name: 'home' })
  // «Elegir en Jira» (Mixta 1b): abierto con el proyecto de Inicio; lo elegido vuelve a Inicio.
  const [jira, setJira] = useState<{ initialProject?: string } | null>(null)
  const [picked, setPicked] = useState<JiraPick | undefined>()

  return (
    <>
      <ConversationList
        conversations={conversations}
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
        {view.name === 'origin' && <OriginPending request={view.request} onBack={() => setView({ name: 'home' })} />}
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

// Provisional hasta la pantalla Origen y fuentes (Mixta 2): enseña lo que llegaría.
function OriginPending({ request, onBack }: { request: StartRequest; onBack: () => void }) {
  const options = request.proposal?.options.map((option) => option.label).join(' · ')
  return (
    <div className={styles.centered}>
      <section className={styles.soon} aria-labelledby="origin-pending">
        <h1 id="origin-pending" className={styles.soonTitle}>
          Origen y fuentes
        </h1>
        <p className={styles.soonText}>Siguiente pantalla del bloque de la demo. Esto es lo que recibiría:</p>
        <p>
          Proyecto <b>{request.project}</b>
          {request.origin && (
            <>
              {' '}
              · origen <b>{request.origin.key}</b>
            </>
          )}
          {request.text && <> · «{request.text}»</>}
        </p>
        {options && <p className={styles.soonText}>Opciones del arranque guiado: {options}</p>}
        <Button onClick={onBack}>Volver al inicio</Button>
      </section>
    </div>
  )
}
