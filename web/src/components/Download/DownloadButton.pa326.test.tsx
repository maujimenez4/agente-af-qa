// Botón de descarga de un texto de la API (PA-326: «Descargar la matriz»). Sin texto o con nombre no seguro no se
// pinta; el texto se descarga tal cual y nunca se inserta como HTML. Datos sintéticos.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest'
import * as download from '../../security/download.ts'
import { DownloadButton } from './DownloadButton.tsx'

const MATRIX = '# Matriz de cobertura · DEMO-3\n\n| CA/RN | Casos de prueba | Nº |\n|---|---|---|\n| CA-01 | CP-01 | 1 |\n'

let spy: MockInstance<typeof download.downloadText>

beforeEach(() => {
  spy = vi.spyOn(download, 'downloadText').mockReturnValue(true)
})

afterEach(() => vi.restoreAllMocks())

describe('DownloadButton', () => {
  it('test_download_button_renders_label_and_accessible_description', () => {
    render(<DownloadButton label="Descargar la matriz" fileName="matriz-DEMO-3.md" text={MATRIX} />)
    const button = screen.getByRole('button', { name: 'Descargar la matriz' })
    expect(button).toHaveAccessibleDescription('Descarga el archivo matriz-DEMO-3.md.')
  })

  it.each([
    ['sin texto (undefined)', undefined],
    ['con texto null', null],
    ['con texto vacío', ''],
  ])('test_download_button_is_not_rendered_%s', (_name, text) => {
    const { container } = render(<DownloadButton label="Descargar la matriz" fileName="matriz-DEMO-3.md" text={text} />)
    expect(screen.queryByRole('button')).toBeNull()
    expect(container).toBeEmptyDOMElement()
  })

  it.each(['../matriz.md', '.oculto', 'a/b.md', 'a\\b.md', '', 'a'.repeat(101)])('test_download_button_is_not_rendered_with_unsafe_name_%s', (fileName) => {
    const { container } = render(<DownloadButton label="Descargar la matriz" fileName={fileName} text={MATRIX} />)
    expect(screen.queryByRole('button')).toBeNull()
    expect(container).toBeEmptyDOMElement()
  })

  it('test_download_button_click_downloads_the_text_as_is', async () => {
    render(<DownloadButton label="Descargar la matriz" fileName="matriz-DEMO-3.md" text={MATRIX} />)
    await userEvent.click(screen.getByRole('button', { name: 'Descargar la matriz' }))
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith('matriz-DEMO-3.md', MATRIX, 'text/markdown')
  })

  it('test_download_button_passes_the_type', async () => {
    render(<DownloadButton label="Descargar las notas" fileName="notas-DEMO-3.txt" text="notas ficticias" type="text/plain" />)
    await userEvent.click(screen.getByRole('button', { name: 'Descargar las notas' }))
    expect(spy).toHaveBeenCalledWith('notas-DEMO-3.txt', 'notas ficticias', 'text/plain')
  })

  it('test_download_button_with_script_text_never_puts_it_in_the_dom_as_html', async () => {
    const hostile = '<script>alert(1)</script><img src=x onerror=alert(1)>'
    const { container } = render(<DownloadButton label="Descargar la matriz" fileName="matriz-DEMO-3.md" text={hostile} />)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).not.toContain('alert(1)')
    await userEvent.click(screen.getByRole('button', { name: 'Descargar la matriz' }))
    expect(spy).toHaveBeenCalledWith('matriz-DEMO-3.md', hostile, 'text/markdown')
    expect(document.querySelector('script')).toBeNull()
    expect(document.body.innerHTML).not.toContain('onerror')
  })
})
