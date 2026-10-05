import { useEffect, useState } from 'react'
import { api } from '../../api/client.ts'
import type { IssueCard, IssueSummary, StartOption, StartProposal } from '../../api/types.ts'
import { Badge } from '../../components/Badge/index.ts'
import { Button } from '../../components/Button/index.ts'
import { AssistantMessage, FoundIssue } from '../../components/Chat/index.ts'
import { capabilitiesLine } from './conversation.ts'

export interface ProposalMessageProps {
  proposal: StartProposal
  /** `qa` en el flujo de pruebas: cambia la línea de capacidades. */
  mode: 'functional' | 'qa'
  /** Sin opciones activas: hay una propuesta más nueva, ya hay operación o se espera otra. */
  disabled: boolean
  onChoose: (option: StartOption, project: string) => void
  /** HU elegida en Jira o en los recientes (Inicio): se muestra si la propuesta no trae ninguna. */
  origin?: IssueSummary
}

function testCasesText(count: number | null | undefined): string | undefined {
  if (count === null || count === undefined) return undefined
  if (count === 0) return 'sin casos de prueba en Jira'
  return `${count} ${count === 1 ? 'caso de prueba' : 'casos de prueba'} en Jira`
}

// En QA (UI.md §6.1) la ficha añade los casos que ya tiene en Jira (PA-104) y si la publicó el agente.
function issueDetail(issue: IssueSummary, card: IssueCard | undefined, qa = false): string {
  if (!card) return `${issue.issue_type} · ${issue.status}`
  const parts = [
    card.epic_key ? `Épica ${card.epic_key}` : undefined,
    `${card.criteria_count} criterios y ${card.rules_count} reglas`,
    qa ? testCasesText(card.test_cases) : undefined,
    qa && card.published_by_agent ? 'publicada por el agente' : undefined,
  ]
  return parts.filter(Boolean).join(' · ')
}

// Respuesta del arranque guiado (POST /start/propose) en Origen y fuentes (UI.md §4.3).
export function ProposalMessage({ proposal, mode, disabled, onChoose, origin }: ProposalMessageProps) {
  const project = proposal.project
  const shown = proposal.recognized[0] ?? proposal.similar[0] ?? origin
  const recognized = proposal.recognized.length > 0
  const [card, setCard] = useState<IssueCard | undefined>()

  useEffect(() => {
    if (!shown) return
    let cancelled = false
    api
      .issue(shown.key)
      .then((value) => !cancelled && setCard(value))
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [shown])

  return (
    <AssistantMessage>
      {proposal.project_changed && (
        <p>
          La clave es del proyecto <b>{project}</b>: la conversación pasa a {project}.
        </p>
      )}
      {proposal.ignored_projects.length > 0 && (
        <p>Las claves de otros proyectos ({proposal.ignored_projects.join(', ')}) no se usan en esta conversación.</p>
      )}
      {shown ? (
        <>
          <Badge icon="search">{recognized ? 'Clave reconocida en Jira · sin IA' : 'Búsqueda en Jira por texto · sin IA'}</Badge>
          <p>
            {recognized
              ? `He reconocido ${shown.key} en el proyecto ${project}.`
              : `En el proyecto ${project} hay una HU parecida. ¿La evolucionamos o creamos una nueva?`}
          </p>
        </>
      ) : (
        <p>No he encontrado HU parecidas en el proyecto {project}.</p>
      )}
      {/* Tras una búsqueda por texto, qué puede hacer el agente (fallo real: «Crea un proyecto…»). */}
      {!recognized && <p>{capabilitiesLine(mode)}</p>}
      <FoundIssue
        title={shown ? `${shown.key}, ${shown.summary}` : 'HU nueva'}
        detail={shown ? issueDetail(shown, card, mode === 'qa') : `En el proyecto ${project}`}
        actions={proposal.options.map((option, index) => (
          <Button
            key={option.label}
            size="md"
            variant={index === 0 ? 'primary' : 'secondary'}
            disabled={disabled}
            onClick={() => onChoose(option, project)}
          >
            {option.label}
          </Button>
        ))}
      />
    </AssistantMessage>
  )
}
