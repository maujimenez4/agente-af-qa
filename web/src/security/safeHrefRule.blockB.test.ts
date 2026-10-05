// @vitest-environment node
// Bloque B · la regla de ESLint que exige safeHref() (eslint.config.js, PA-308; web/README.md, «Reglas»).
// Se lintan fragmentos con la configuración real del proyecto (cwd = web/, donde corre Vitest).
import { ESLint } from 'eslint'
import { beforeAll, describe, expect, it } from 'vitest'

const UNSAFE = /safeHref\(\)/
let eslint: ESLint

beforeAll(() => {
  eslint = new ESLint()
})

/** Mensajes de no-restricted-syntax / no-restricted-properties de un componente con `jsx`. */
async function lint(jsx: string, prelude = ''): Promise<string[]> {
  const code = `import { safeHref } from './safeHref.ts'
${prelude}
export function Fragmento({ x }: { x: string }) {
  return ${jsx}
}
`
  const [result] = await eslint.lintText(code, { filePath: 'src/security/fragmento-ficticio.tsx' })
  return (result?.messages ?? []).filter((message) => message.ruleId?.startsWith('no-restricted')).map((message) => message.message)
}

describe('regla safeHref en atributos con URL', () => {
  it.each([
    '<a href={x}>enlace</a>',
    '<img src={x} alt="" />',
    '<form action={x}><button type="submit">Enviar</button></form>',
    '<button formAction={x} type="submit">Enviar</button>',
    '<a href={`/ruta/${x}`}>enlace</a>',
    '<a href={x as string}>enlace</a>',
    "<a href={safeHref(x) ?? '#'}>enlace</a>",
    '<a href={String(x)}>enlace</a>',
    '<img srcSet={x} alt="" />',
    '<video poster={x} />',
  ])('%s → error', async (jsx) => {
    const messages = await lint(jsx)
    expect(messages.some((message) => UNSAFE.test(message))).toBe(true)
  })

  it.each([
    '<a href={safeHref(x)}>enlace</a>',
    '<a href="/api/v1/ruta-ficticia">enlace</a>',
    "<a href={'#seccion'}>enlace</a>",
    '<a href={`/ruta-fija`}>enlace</a>',
    '<img src={safeHref(x)} alt="" />',
    '<form action={safeHref(x)}><button type="submit">Enviar</button></form>',
    '<span title={x}>texto</span>',
  ])('%s → sin error', async (jsx) => {
    expect(await lint(jsx)).toEqual([])
  })

  it('el spread de props en un elemento con URL también da error', async () => {
    const messages = await lint('<a {...{ href: x }}>enlace</a>')
    expect(messages.some((message) => UNSAFE.test(message))).toBe(true)
  })

  it('xlink:href con namespace da error', async () => {
    const messages = await lint('<svg><use xlink:href={x} /></svg>')
    expect(messages.some((message) => UNSAFE.test(message))).toBe(true)
  })

  it('window.open y location.assign con datos dan error', async () => {
    const messages = await lint('<button type="button" onClick={() => { window.open(x); location.assign(x) }}>Abrir</button>')
    expect(messages.filter((message) => UNSAFE.test(message))).toHaveLength(2)
  })

  it('dangerouslySetInnerHTML y srcDoc siguen prohibidos', async () => {
    expect(await lint('<div dangerouslySetInnerHTML={{ __html: x }} />')).toHaveLength(1)
    expect(await lint('<iframe title="ficticio" srcDoc={x} />')).toHaveLength(1)
  })
})
