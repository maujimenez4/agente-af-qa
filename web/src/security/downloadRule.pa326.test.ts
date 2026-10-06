// @vitest-environment node
// PA-326 · la regla de ESLint que deja asignar `href` y crear un blob: solo en src/security/download.ts
// (eslint.config.js; downloadText). Se lintan fragmentos con la configuración real del proyecto (cwd = web/).
import { ESLint } from 'eslint'
import { beforeAll, describe, expect, it } from 'vitest'

const DOWNLOAD = /downloadText\(\)/
let eslint: ESLint

// La primera pasada carga la configuración y los plugins: se paga aquí, una vez.
beforeAll(async () => {
  eslint = new ESLint()
  await eslint.lintText('export {}\n', { filePath: 'src/components/fragmento-ficticio.ts' })
}, 15_000)

/** Mensajes de no-restricted-* de una función con `body` en un archivo cualquiera del código. */
async function lint(body: string, filePath = 'src/components/fragmento-ficticio.ts'): Promise<string[]> {
  const code = `export function fragmento(a: HTMLAnchorElement, x: string, b: Blob): unknown {
  ${body}
  return undefined
}
`
  const [result] = await eslint.lintText(code, { filePath })
  return (result?.messages ?? []).filter((message) => message.ruleId?.startsWith('no-restricted')).map((message) => message.message)
}

describe('regla de descarga (href asignado y createObjectURL)', () => {
  it.each([
    ['a.href = x', 'a.href = x'],
    ["a['href'] = x", "a['href'] = x"],
    ['location.href = x', 'location.href = x'],
    ['window.location.href = x', 'window.location.href = x'],
    ['URL.createObjectURL(b)', 'void URL.createObjectURL(b)'],
    ['window.URL.createObjectURL(b)', 'void window.URL.createObjectURL(b)'],
  ])('%s → error', async (_name, body) => {
    const messages = await lint(body)
    expect(messages.some((message) => DOWNLOAD.test(message))).toBe(true)
  })

  it('el mismo código en un .tsx también da error', async () => {
    const messages = await lint('a.href = x', 'src/screens/fragmento-ficticio.tsx')
    expect(messages.some((message) => DOWNLOAD.test(message))).toBe(true)
  })

  it.each([
    ['leer a.href', 'void a.href'],
    ["leer a['href']", "void a['href']"],
    ['comparar location.href', "if (location.href === x) return 'igual'"],
    ['asignar otra propiedad', "a.download = 'matriz-DEMO-3.md'"],
    ['revokeObjectURL', 'URL.revokeObjectURL(x)'],
  ])('%s → sin error', async (_name, body) => {
    expect(await lint(body)).toEqual([])
  })

  it('a[`href`] = x (plantilla sin expresiones) → error', async () => {
    const messages = await lint('a[`href`] = x')
    expect(messages.some((message) => DOWNLOAD.test(message))).toBe(true)
  })

  it.each([
    "a.setAttribute('href', x)",
    "a.setAttribute('src', x)",
    "a.setAttribute('action', x)",
    "a.setAttribute('formaction', x)",
    "a.setAttribute('xlink:href', x)",
    "a.setAttribute('HREF', x)",
    "a.setAttribute('Src', x)",
    "a.setAttribute('formAction', x)",
    "a.setAttribute('XLink:Href', x)",
    "a.setAttributeNS(null, 'href', x)",
    "a.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', x)",
    "a.setAttributeNS(null, 'SRC', x)",
    'a.setAttribute(`href`, x)',
    "a['setAttribute']('href', x)",
    "a['setAttribute']('class', x)",
    "URL['createObjectURL'](b)",
    'const { createObjectURL } = URL',
  ])('%s → error', async (body) => {
    const messages = await lint(body)
    expect(messages.some((message) => DOWNLOAD.test(message))).toBe(true)
  })

  it.each([
    "a.setAttribute('class', x)",
    "a.setAttribute('title', x)",
    "a.setAttribute('download', 'matriz-DEMO-3.md')",
    "a.setAttribute('data-href', x)",
    "a.setAttribute('hreflang', x)",
    "a.setAttributeNS(null, 'class', x)",
    "void a.getAttribute('href')",
    "a.removeAttribute('href')",
  ])('%s → sin error', async (body) => {
    expect(await lint(body)).toEqual([])
  })

  it.each([
    ['Object.assign con href', 'Object.assign(a, { href: x })'],
    ['clave en una variable', "const k = 'href'\n  a[k] = x"],
  ])('limitación anotada: %s no da error', async (_name, body) => {
    // Fuera del alcance de la regla (selectores de AST): documentado como limitación, no como garantía.
    expect(await lint(body)).toEqual([])
  })

  it('src/security/download.ts cumple la regla con su excepción justificada', async () => {
    const [result] = await eslint.lintFiles(['src/security/download.ts'])
    expect(result?.errorCount).toBe(0)
    expect(result?.warningCount).toBe(0)
  })
})
