import { useState } from 'react'
import type { UserOut } from '../api/types.ts'
import { ConversationList } from '../components/ConversationList/index.ts'
import { homeZone, Rail, type Zone } from '../components/Rail/index.ts'
import { useUsage } from '../hooks/useUsage.ts'
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
        <WorkZone />
      )}
    </div>
  )
}

function WorkZone() {
  const { conversations } = useConversations()
  const [currentId, setCurrentId] = useState<string | undefined>()

  return (
    <>
      <ConversationList
        conversations={conversations}
        currentId={currentId}
        onNew={() => setCurrentId(undefined)}
        onSelect={setCurrentId}
      />
      <main className={styles.main}>
        <SoonScreen title="¿En qué trabajamos hoy?" text="La pantalla de inicio llega en el siguiente paso." />
      </main>
    </>
  )
}
