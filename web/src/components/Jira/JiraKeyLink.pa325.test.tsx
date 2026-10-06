// PA-325 · JiraKeyLink: la clave de Jira enlazada con `SettingsOut.jira_browse_url` (siempre por safeHref) y, sin
// destino seguro, solo el texto. Datos sintéticos (DEMO-21, prefijo del ejemplo de GET /settings).
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { JiraKeyLink, jiraIssueUrl } from './index.ts'
import { jiraIssueUrl as fromResultText } from '../../screens/Result/resultText.ts'

const BROWSE = 'https://villaficticia-ejemplo.atlassian.net/browse/'

describe('PA-325 · JiraKeyLink con destino seguro', () => {
  it('test_link_points_to_issue_with_example_prefix', () => {
    /** PA-325: con el prefijo del ejemplo, enlace a `…/browse/DEMO-21` en otra pestaña, sin opener ni referrer. */
    render(<JiraKeyLink jiraKey="DEMO-21" browseUrl={BROWSE} />)
    const link = screen.getByRole('link', { name: /DEMO-21/ })
    expect(link).toHaveAttribute('href', `${BROWSE}DEMO-21`)
    expect(link).toHaveAttribute('target', '_blank')
    const rel = (link.getAttribute('rel') ?? '').split(/\s+/)
    expect(rel).toContain('noopener')
    expect(rel).toContain('noreferrer')
  })

  it('test_link_accessible_name_announces_jira_new_tab', () => {
    /** PA-325: el nombre accesible es la clave y avisa de que se abre en Jira, en otra pestaña. */
    render(<JiraKeyLink jiraKey="DEMO-21" browseUrl={BROWSE} />)
    const link = screen.getByRole('link')
    // jsdom (dom-accessibility-api) recorta el espacio inicial del texto oculto: se admite con o sin él.
    expect(link).toHaveAccessibleName(/^DEMO-21\s*\(se abre en Jira, en otra pestaña\)$/)
    expect(link).toHaveAccessibleName(/se abre en Jira/)
  })

  it('test_link_hint_is_visually_hidden', () => {
    /** PA-325: el aviso «se abre en Jira» es solo para lectores de pantalla (visually-hidden). */
    render(<JiraKeyLink jiraKey="DEMO-21" browseUrl={BROWSE} />)
    expect(screen.getByText(/se abre en Jira/)).toHaveClass('visually-hidden')
  })

  it('test_link_with_multi_digit_and_underscore_key', () => {
    /** PA-325 (límite): claves válidas con dígitos y guion bajo en el proyecto también se enlazan. */
    render(<JiraKeyLink jiraKey="DEMO_2-1000" browseUrl={BROWSE} />)
    expect(screen.getByRole('link', { name: /DEMO_2-1000/ })).toHaveAttribute('href', `${BROWSE}DEMO_2-1000`)
  })
})

describe('PA-325 · JiraKeyLink sin destino seguro: solo texto', () => {
  it.each([
    ['null', null, 'DEMO-3'],
    ['undefined', undefined, 'DEMO-3'],
    ['vacío', '', 'DEMO-3'],
    ['prefijo http:', 'http://villaficticia-ejemplo.atlassian.net/browse/', 'DEMO-3'],
    ['prefijo con query', 'https://villaficticia-ejemplo.atlassian.net/browse/?origen=ficticio', 'DEMO-3'],
    ['prefijo con fragmento', 'https://villaficticia-ejemplo.atlassian.net/browse/#ficticio', 'DEMO-3'],
    ['prefijo sin «/» final', 'https://villaficticia-ejemplo.atlassian.net/browse', 'DEMO-3'],
    ['prefijo javascript:', 'javascript:alert(1)//', 'DEMO-3'],
    ['clave en minúsculas', BROWSE, 'demo-3'],
    ['clave con ruta', BROWSE, 'DEMO-3/../x'],
    ['clave javascript:', BROWSE, 'javascript:alert(1)'],
  ])('test_plain_text_without_link_when_%s', (_case, browseUrl, jiraKey) => {
    /** PA-325: con `null`, prefijo o clave no válidos, la clave va como texto, sin `<a>`. */
    const { container } = render(<JiraKeyLink jiraKey={jiraKey} browseUrl={browseUrl} />)
    expect(container.querySelector('a')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
    expect(container).toHaveTextContent(jiraKey)
    expect(container.textContent).toBe(jiraKey)
  })
})

describe('PA-325 · jiraIssueUrl trasladada a components/Jira', () => {
  it('test_result_text_reexports_same_function', () => {
    /** PA-325: `screens/Result/resultText.ts` reexporta la misma `jiraIssueUrl` (sin copia divergente). */
    expect(fromResultText).toBe(jiraIssueUrl)
    expect(jiraIssueUrl(BROWSE, 'DEMO-2')).toBe(`${BROWSE}DEMO-2`)
  })
})
