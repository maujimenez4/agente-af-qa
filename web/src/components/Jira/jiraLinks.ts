// Enlaces a Jira (PA-318, PA-325): `{jira_browse_url}{clave}`, siempre por `safeHref`.
import { safeHref } from '../../security/safeHref.ts'

const ISSUE_KEY = /^[A-Z][A-Z0-9_]*-\d+$/

/**
 * «Abrir DEMO-3 en Jira» (PA-318): `{jira_browse_url}{clave}`. Solo con un prefijo `https` y una clave de Jira
 * válida; si no, `undefined` y la acción sigue «disponible pronto». El prefijo tiene que acabar en «/», sin query
 * ni fragmento: si no, la clave se pegaría al host (otro sitio). El enlace pasa además por `safeHref`.
 */
export function jiraIssueUrl(browseUrl: string | null | undefined, key: string | undefined): string | undefined {
  if (!browseUrl || !key || !ISSUE_KEY.test(key)) return undefined
  let base: URL
  try {
    base = new URL(browseUrl)
  } catch {
    return undefined
  }
  if (base.protocol !== 'https:' || !base.pathname.endsWith('/') || base.search || base.hash || !browseUrl.endsWith('/')) return undefined
  const url = new URL(key, base)
  return url.origin === base.origin ? safeHref(url.href) : undefined
}
