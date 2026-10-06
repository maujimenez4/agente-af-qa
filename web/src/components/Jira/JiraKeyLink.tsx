import { safeHref } from '../../security/safeHref.ts'
import styles from './JiraKeyLink.module.css'
import { jiraIssueUrl } from './jiraLinks.ts'

export interface JiraKeyLinkProps {
  /** Clave de Jira tal como llega de la API (DEMO-21). */
  jiraKey: string
  /** `SettingsOut.jira_browse_url`; con `null` (o un prefijo o una clave no válidos), la clave va como texto. */
  browseUrl: string | null | undefined
}

// Clave de Jira enlazada a su incidencia (PA-325), en otra pestaña y anunciándolo a los lectores de pantalla.
// El destino sale de `jiraIssueUrl`, que ya lo pasa por `safeHref`; sin destino seguro, solo el texto.
export function JiraKeyLink({ jiraKey, browseUrl }: JiraKeyLinkProps) {
  const href = jiraIssueUrl(browseUrl, jiraKey)
  if (!href) return <>{jiraKey}</>
  return (
    <a className={styles.link} href={safeHref(href)} target="_blank" rel="noopener noreferrer">
      {jiraKey}
      <span className="visually-hidden"> (se abre en Jira, en otra pestaña)</span>
    </a>
  )
}
