import { useState } from 'react'
import { Badge, CaseKindBadge } from '../components/Badge/index.ts'
import { Button, IconButton } from '../components/Button/index.ts'
import { Card, FlowCard } from '../components/Card/index.ts'
import { Chip } from '../components/Chip/index.ts'
import type { IconName } from '../components/Icon/index.ts'
import type { Role } from '../components/Rail/index.ts'
import styles from './Catalog.module.css'
import { DemoButton } from './DemoButton.tsx'

type FlowId = 'need' | 'evolve' | 'review' | 'tests'

// Textos del lienzo (MixtoInicio).
const FLOWS: ReadonlyArray<{ id: FlowId; label: string; hint: string; icon: IconName; role: Role }> = [
  {
    id: 'need',
    label: 'Nueva necesidad',
    hint: 'Describe lo que hace falta; si ya existe una HU parecida te la propongo.',
    icon: 'new',
    role: 'functional',
  },
  {
    id: 'evolve',
    label: 'Evolucionar una HU',
    hint: 'Parte de una HU de Jira y propón su nueva versión con el diff.',
    icon: 'work',
    role: 'functional',
  },
  {
    id: 'review',
    label: 'Revisar la calidad de una HU',
    hint: 'Informe con INVEST, ambigüedades y huecos. No cambia nada en Jira.',
    icon: 'searchSource',
    role: 'functional',
  },
  { id: 'tests', label: 'Preparar pruebas', hint: 'Casos, cobertura, datos y estrategia de una HU.', icon: 'tests', role: 'qa' },
]

const ROLE_HINT: Record<'functional' | 'qa', string> = {
  functional: 'Disponible para el rol de analista funcional.',
  qa: 'Disponible para el rol QA.',
}

function FlowCardsDemo() {
  const [role, setRole] = useState<'functional' | 'qa'>('functional')
  const [picked, setPicked] = useState<FlowId>('need')

  return (
    <>
      <div className={styles.row} role="group" aria-label="Rol de la demo">
        {(['functional', 'qa'] as const).map((value) => (
          <DemoButton
            key={value}
            pressed={role === value}
            onClick={() => {
              setRole(value)
              setPicked(value === 'qa' ? 'tests' : 'need')
            }}
          >
            {value === 'qa' ? 'qa-demo' : 'af-demo'}
          </DemoButton>
        ))}
      </div>
      <div className={styles.flows}>
        {FLOWS.map((flow) => (
          <FlowCard
            key={flow.id}
            label={flow.label}
            hint={flow.hint}
            icon={flow.icon}
            selected={picked === flow.id}
            onSelect={() => setPicked(flow.id)}
            disabledHint={flow.role === role ? undefined : ROLE_HINT[flow.role === 'qa' ? 'qa' : 'functional']}
          />
        ))}
      </div>
    </>
  )
}

export function ComponentsDemo() {
  return (
    <section className={styles.section} aria-labelledby="componentes">
      <h2 id="componentes" className={styles.sectionTitle}>
        Botones, chips, badges y tarjetas
      </h2>

      <h3 className={styles.groupTitle}>Botones · 44 px</h3>
      <div className={styles.row}>
        <Button variant="primary">Aprobar y publicar</Button>
        <Button variant="secondary" icon="new">
          Nueva conversación
        </Button>
        <Button variant="ghost">Descartar</Button>
        <Button variant="danger">Volver a generar</Button>
        <Button variant="primary" disabled>
          Aprobar y publicar
        </Button>
      </div>

      <h3 className={styles.groupTitle}>Botones · 36 y 28 px, y solo icono</h3>
      <div className={styles.row}>
        <Button size="md" variant="secondary">
          Evolucionar DEMO-3
        </Button>
        <Button size="md" variant="ghost" icon="model">
          Modelo automático
        </Button>
        <Button size="sm" variant="ghost">
          Confirmar
        </Button>
        <Button size="sm" variant="ghost" icon="searchSource">
          Pedir fuente
        </Button>
        <IconButton icon="send" label="Enviar" variant="primary" />
        <IconButton icon="stop" label="Detener" variant="secondary" />
        <IconButton icon="panelRight" label="Plegar panel" />
        <IconButton icon="close" label="Cerrar" />
      </div>

      <h3 className={styles.groupTitle}>Chips</h3>
      <div className={styles.row}>
        <Chip>Busca la fuente del CA-04</Chip>
        <Chip>Añade un criterio de error</Chip>
        <Chip>Revisa INVEST</Chip>
        <Chip variant="recent" issueKey="DEMO-3">
          Renovar un préstamo desde la app
        </Chip>
        <Chip variant="recent" issueKey="DEMO-1">
          Préstamo digital
        </Chip>
      </div>

      <h3 className={styles.groupTitle}>Badges</h3>
      <div className={styles.row}>
        <Badge>Búsqueda en Jira por texto · sin IA</Badge>
        <Badge tone="cite">DOC-01</Badge>
        <Badge tone="new">Cambiado en v2</Badge>
        <Badge tone="new">Nueva</Badge>
        <Badge tone="success">Publicada por el agente</Badge>
        <CaseKindBadge kind="Positivo" />
        <CaseKindBadge kind="Negativo" />
        <CaseKindBadge kind="Alterno" />
        <CaseKindBadge kind="Excepción" />
        <Badge tone="plain">Must</Badge>
      </div>
      <div className={styles.row}>
        <Badge size="md" tone="warning">
          Aprobada · simulada
        </Badge>
        <Badge size="md" tone="new">
          Publicada
        </Badge>
        <Badge size="md" tone="error">
          Publicada en parte
        </Badge>
        <Badge size="md" tone="success" icon="done">
          Todos los CA cubiertos
        </Badge>
      </div>

      <h3 className={styles.groupTitle}>Tarjetas de flujo (según el rol)</h3>
      <FlowCardsDemo />

      <h3 className={styles.groupTitle}>Tarjeta base</h3>
      <div className={styles.cards}>
        <Card title="Antes de generar" headingLevel={3} description="Se puede cambiar solo antes de generar.">
          <Button variant="primary">Generar propuesta</Button>
        </Card>
      </div>
    </section>
  )
}
