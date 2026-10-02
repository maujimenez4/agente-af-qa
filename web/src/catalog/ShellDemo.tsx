import { useId, useState } from 'react'
import { ConversationList, ConversationsToggle } from '../components/ConversationList/index.ts'
import { Rail, type Role, type Zone } from '../components/Rail/index.ts'
import { DEMO_CONVERSATIONS, DEMO_NOW } from '../fixtures/conversations.ts'
import { DemoButton } from './DemoButton.tsx'
import styles from './Catalog.module.css'

const USERS: Record<Role, { username: string; usage: number; zone: Zone }> = {
  functional: { username: 'af-demo', usage: 24, zone: 'work' },
  qa: { username: 'qa-demo', usage: 95, zone: 'work' },
  admin: { username: 'admin-demo', usage: 2, zone: 'history' },
}

export function ShellDemo() {
  const [role, setRole] = useState<Role>('functional')
  const [zone, setZone] = useState<Zone>('work')
  const [currentId, setCurrentId] = useState<string | undefined>()
  const [showList, setShowList] = useState(true)
  const [withUsage, setWithUsage] = useState(true)
  const [empty, setEmpty] = useState(false)
  const listId = useId()
  const user = USERS[role]

  return (
    <section className={styles.section} aria-labelledby="marco">
      <h2 id="marco" className={styles.sectionTitle}>
        Carril y lista de conversaciones
      </h2>
      <div className={styles.row} role="group" aria-label="Opciones de la demo">
        {(Object.keys(USERS) as Role[]).map((value) => (
          <DemoButton
            key={value}
            pressed={role === value}
            onClick={() => {
              setRole(value)
              setZone(USERS[value].zone)
            }}
          >
            {USERS[value].username}
          </DemoButton>
        ))}
        <DemoButton
          pressed={withUsage}
          onClick={() => setWithUsage(!withUsage)}
        >
          Con consumo de tokens
        </DemoButton>
        <DemoButton pressed={empty} onClick={() => setEmpty(!empty)}>
          Sin conversaciones
        </DemoButton>
      </div>
      <div className={styles.frame}>
        <Rail
          userRole={role}
          username={user.username}
          active={zone}
          usagePercent={withUsage ? user.usage : undefined}
          onNavigate={setZone}
          onLogout={() => setRole('functional')}
        />
        {showList && (
          <ConversationList
            id={listId}
            conversations={empty ? [] : DEMO_CONVERSATIONS}
            currentId={currentId}
            now={DEMO_NOW}
            onNew={() => setCurrentId(undefined)}
            onSelect={setCurrentId}
          />
        )}
        <div className={styles.frameMain}>
          <ConversationsToggle expanded={showList} controls={listId} onToggle={() => setShowList(!showList)} />
        </div>
      </div>
    </section>
  )
}
