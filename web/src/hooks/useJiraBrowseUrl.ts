import { useEffect, useState } from 'react'
import { api } from '../api/client.ts'

/**
 * `SettingsOut.jira_browse_url` (PA-318). Solo se pide si hay algo que abrir en Jira; si falla, `null` y no hay
 * enlace (la clave se queda como texto).
 */
export function useJiraBrowseUrl(needed: boolean): string | null {
  const [browseUrl, setBrowseUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!needed) return
    let cancelled = false
    api
      .settings()
      .then((settings) => {
        if (!cancelled) setBrowseUrl(settings.jira_browse_url ?? null)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [needed])
  return browseUrl
}
