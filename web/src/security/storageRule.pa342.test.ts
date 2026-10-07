// @vitest-environment node
// PA-342 · la regla de ESLint contra el almacenamiento del navegador cubre también la desestructuración anidada, la
// de `globalThis.window`, la de un parámetro, las claves entre comillas, los alias y el resto de los objetos globales.
// Se lintan fragmentos con la configuración real del proyecto (cwd = web/). Solo fragmentos ficticios.
import { ESLint } from 'eslint'
import { beforeAll, describe, expect, it } from 'vitest'

const STORAGE = /almacenamiento del navegador/
const ALIAS = /Sin alias ni resto/
let eslint: ESLint

// La primera pasada carga la configuración y los plugins: se paga aquí, una vez.
beforeAll(async () => {
  eslint = new ESLint()
  await eslint.lintText('export {}\n', { filePath: 'src/components/fragmento-ficticio.ts' })
}, 15_000)

/** Mensajes de no-restricted-* de una función con `body`. */
async function lint(body: string): Promise<string[]> {
  const code = `export function fragmento(): unknown {
  ${body}
  return undefined
}
`
  const [result] = await eslint.lintText(code, { filePath: 'src/components/fragmento-ficticio.ts' })
  return (result?.messages ?? []).filter((message) => message.ruleId?.startsWith('no-restricted')).map((message) => message.message)
}

describe('PA-342 · desestructuración que antes se escapaba', () => {
  it.each([
    ['anidada de window', 'const { document: { cookie } } = window\n  void cookie'],
    ['anidada más honda', 'const { self: { window: { localStorage } } } = globalThis\n  void localStorage'],
    ['de globalThis.window', 'const { localStorage } = globalThis.window\n  void localStorage'],
    ['de window.document', 'const { cookie } = window.document\n  void cookie'],
    ['en un parámetro', 'const leer = ({ cookie }: Document) => cookie\n  void leer'],
    ['en un parámetro con valor por defecto', 'const leer = ({ sessionStorage } = window) => sessionStorage\n  void leer'],
    ['con la clave entre comillas', "const { 'localStorage': almacen } = window\n  void almacen"],
    ['de otro objeto (precio aceptado: solo esos cinco nombres)', "const { cookie } = { cookie: 'valor-ficticio' }\n  void cookie"],
  ])('test_storage_rule_errors_on_%s', async (_name, body) => {
    expect((await lint(body)).some((message) => STORAGE.test(message))).toBe(true)
  })
})

describe('PA-342 · alias y resto de los objetos globales', () => {
  it.each([
    ['alias de window', 'const w = window\n  void w.localStorage'],
    ['alias de document', 'const d = document\n  void d.cookie'],
    ['alias de self', 'const s = self\n  void s'],
    ['alias de globalThis.window', 'const w = globalThis.window\n  void w'],
    ['alias de window.document', 'const d = window.document\n  void d'],
    ['alias por asignación', 'let w: unknown\n  w = window\n  void w'],
    ['resto de window', 'const { ...todo } = window\n  void todo'],
    ['resto de globalThis.window', 'const { ...todo } = globalThis.window\n  void todo'],
    ['resto por asignación', 'let todo: unknown\n  ;({ ...todo } = document)\n  void todo'],
    // security-reviewer de la PR 2: con un tipo por medio o como valor por defecto.
    ['alias con as', 'const d = document as Document\n  void d.cookie'],
    ['alias con !', 'const w = window!\n  void w'],
    ['alias con satisfies', 'const w = window satisfies Window\n  void w'],
    ['alias por asignación con as', 'let d: Document\n  d = document as Document\n  void d'],
    ['parámetro con document por defecto', 'const leer = (x: Document = document) => x.cookie\n  void leer'],
    ['parámetro con window as por defecto', 'const leer = (x = window as Window) => x\n  void leer'],
    ['desestructuración con window por defecto', 'const { w = window } = {} as { w?: Window }\n  void w'],
  ])('test_storage_rule_errors_on_%s', async (_name, body) => {
    const messages = await lint(body)
    expect(messages.some((message) => STORAGE.test(message) && ALIAS.test(message))).toBe(true)
  })
})

describe('PA-342 · sin falsos positivos', () => {
  it.each([
    ['leer window.location', 'const lugar = window.location\n  void lugar'],
    ['desestructurar title de document', 'const { title } = document\n  void title'],
    ['desestructurar de window.location', 'const { href } = window.location\n  void href'],
    ['resto de un objeto propio', "const { ...copia } = { clave: 'valor-ficticio' }\n  void copia"],
    ['parámetro con otra clave', 'const leer = ({ title }: Document) => title\n  void leer'],
    ['parámetro con otro valor por defecto', "const saludar = (nombre = 'ficticio') => nombre\n  void saludar"],
    ['window.location con as', 'const lugar = window.location as Location\n  void lugar'],
  ])('test_storage_rule_no_error_on_%s', async (_name, body) => {
    expect((await lint(body)).some((message) => STORAGE.test(message))).toBe(false)
  })

  it('test_storage_rule_known_limit_global_passed_as_argument', async () => {
    // Límite conocido (DESIGN-DECISIONS §7): pasar el objeto global como argumento no se ve con selectores; se revisa a
    // mano. La prueba fija el límite: si un día la regla lo detecta, hay que actualizar la documentación.
    expect((await lint('const leer = (x: Document) => x.title\n  void leer(document)')).some((message) => STORAGE.test(message))).toBe(false)
  })
})
