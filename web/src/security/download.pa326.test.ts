// Descarga de un texto de la API como archivo (src/security/download.ts, PA-326: la matriz de cobertura).
// jsdom no trae URL.createObjectURL ni revokeObjectURL: se simulan. Datos sintéticos.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { downloadText, safeFileName } from './download.ts'

const BLOB_URL = 'blob:http://localhost/ficticio-0001'

describe('safeFileName', () => {
  it.each(['matriz-DEMO-3.md', 'estrategia-DEMO-3.md', 'memoria_DEMO-3.md', 'a', 'MATRIZ_demo-3.v2.md', 'a'.repeat(100)])('test_safe_file_name_accepts_%s', (name) => {
    expect(safeFileName(name)).toBe(name)
  })

  it.each([
    ['ruta relativa', '../x.md'],
    ['nombre oculto', '.oculto'],
    ['barra', 'a/b.md'],
    ['barra invertida', 'a\\b.md'],
    ['cadena vacía', ''],
    ['más de 100 caracteres', 'a'.repeat(101)],
    ['dos puntos seguidos', 'a..md'],
    ['espacio', 'matriz DEMO-3.md'],
    ['dos puntos de unidad', 'C:x.md'],
    ['carácter nulo', 'a\u0000.md'],
    ['salto de línea', 'a\n.md'],
    ['empieza por guion', '-x.md'],
    ['no ASCII (Ñ)', 'Ñandú-1.txt'],
    ['homoglifo cirílico', 'matriz-ДЕМО-3.md'],
    ['superíndices', 'matriz-¹².md'],
    ['bidi U+202E', 'matriz-‮dm.md'],
    ['acaba en punto', 'matriz-DEMO-3.'],
    ['reservado CON', 'CON'],
    ['reservado nul.md', 'nul.md'],
    ['reservado COM1.md', 'COM1.md'],
    ['reservado lpt9', 'lpt9.txt'],
    ['reservado aux con mayúsculas', 'AuX.md'],
  ])('test_safe_file_name_rejects_%s', (_name, value) => {
    expect(safeFileName(value)).toBeUndefined()
  })

  it.each([
    ['undefined', undefined],
    ['null', null],
    ['número', 3],
    ['objeto', { toString: () => 'matriz-DEMO-3.md' }],
    ['lista', ['matriz-DEMO-3.md']],
  ])('test_safe_file_name_rejects_non_string_%s', (_name, value) => {
    expect(safeFileName(value)).toBeUndefined()
  })
})

describe('downloadText', () => {
  let createObjectURL: ReturnType<typeof vi.fn<(blob: Blob) => string>>
  let revokeObjectURL: ReturnType<typeof vi.fn<(url: string) => void>>
  let clicked: HTMLAnchorElement[]

  beforeEach(() => {
    vi.useFakeTimers()
    createObjectURL = vi.fn<(blob: Blob) => string>(() => BLOB_URL)
    revokeObjectURL = vi.fn<(url: string) => void>()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, writable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, writable: true, value: revokeObjectURL })
    clicked = []
    // jsdom no navega: se registra el enlace en el momento del clic (aún en el DOM).
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      expect(document.body.contains(this)).toBe(true)
      clicked.push(this)
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    Reflect.deleteProperty(URL, 'createObjectURL')
    Reflect.deleteProperty(URL, 'revokeObjectURL')
  })

  it('test_download_text_creates_markdown_blob_with_exact_text', async () => {
    const text = '# Matriz de cobertura · DEMO-3\n\n| CA-01 | CP-01 | 1 |\n<script>alert(1)</script>\n'
    expect(downloadText('matriz-DEMO-3.md', text, 'text/markdown')).toBe(true)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const blob = createObjectURL.mock.calls[0]?.[0] as Blob
    expect(blob).toBeInstanceOf(Blob)
    expect(blob.type).toBe('text/markdown;charset=utf-8')
    expect(await blob.text()).toBe(text)
  })

  it('test_download_text_defaults_to_markdown_and_supports_plain_text', async () => {
    downloadText('matriz-DEMO-3.md', 'x')
    downloadText('notas-DEMO-3.txt', 'y', 'text/plain')
    expect((createObjectURL.mock.calls[0]?.[0] as Blob).type).toBe('text/markdown;charset=utf-8')
    expect((createObjectURL.mock.calls[1]?.[0] as Blob).type).toBe('text/plain;charset=utf-8')
  })

  it('test_download_text_clicks_a_hidden_link_with_download_name_and_removes_it', () => {
    const before = document.body.querySelectorAll('a').length
    downloadText('matriz-DEMO-3.md', 'texto ficticio')
    expect(clicked).toHaveLength(1)
    const link = clicked[0] as HTMLAnchorElement
    expect(link.download).toBe('matriz-DEMO-3.md')
    expect(link.getAttribute('href')).toBe(BLOB_URL)
    expect(link.hidden).toBe(true)
    expect(link.rel).toBe('noopener')
    expect(link.isConnected).toBe(false)
    expect(document.body.querySelectorAll('a')).toHaveLength(before)
  })

  it('test_download_text_revokes_the_url_on_the_next_tick', () => {
    downloadText('matriz-DEMO-3.md', 'texto ficticio')
    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.runAllTimers()
    expect(revokeObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith(BLOB_URL)
  })

  it('test_download_text_removes_link_and_revokes_even_if_click_throws', () => {
    vi.mocked(HTMLAnchorElement.prototype.click).mockImplementation(() => {
      throw new Error('fallo ficticio del clic')
    })
    expect(() => downloadText('matriz-DEMO-3.md', 'texto ficticio')).toThrow('fallo ficticio del clic')
    expect(document.body.querySelectorAll('a[download]')).toHaveLength(0)
    vi.runAllTimers()
    expect(revokeObjectURL).toHaveBeenCalledWith(BLOB_URL)
  })

  it.each(['../x.md', '.oculto', 'a/b.md', 'a\\b.md', '', 'a'.repeat(101)])('test_download_text_with_unsafe_name_%s_returns_false_and_creates_no_url', (name) => {
    expect(downloadText(name, 'texto ficticio')).toBe(false)
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(clicked).toHaveLength(0)
    vi.runAllTimers()
    expect(revokeObjectURL).not.toHaveBeenCalled()
  })

  it('test_download_text_never_inserts_the_text_as_html', () => {
    downloadText('matriz-DEMO-3.md', '<img src=x onerror=alert(1)>')
    expect(document.body.querySelector('img')).toBeNull()
    expect(document.body.innerHTML).not.toContain('onerror')
  })
})
