// @vitest-environment node
// PA-312 · la regla de ESLint contra el almacenamiento del navegador (eslint.config.js, BROWSER_STORAGE): la Cache API,
// `self`/`globalThis` y la desestructuración de `document`/`window`/`self`/`globalThis`. Se lintan fragmentos con la
// configuración real del proyecto (cwd = web/). Solo fragmentos ficticios.
import { ESLint } from 'eslint'
import { beforeAll, describe, expect, it } from 'vitest'

const STORAGE = /almacenamiento del navegador/
let eslint: ESLint

// La primera pasada carga la configuración y los plugins: se paga aquí, una vez.
beforeAll(async () => {
  eslint = new ESLint()
  await eslint.lintText('export {}\n', { filePath: 'src/components/fragmento-ficticio.ts' })
}, 15_000)

/** Mensajes de no-restricted-* de una función con `body` en un archivo cualquiera del código. */
async function lint(body: string, filePath = 'src/components/fragmento-ficticio.ts'): Promise<string[]> {
  const code = `export function fragmento(): unknown {
  ${body}
  return undefined
}
`
  const [result] = await eslint.lintText(code, { filePath })
  return (result?.messages ?? []).filter((message) => message.ruleId?.startsWith('no-restricted')).map((message) => message.message)
}

const hasStorageError = (messages: string[]) => messages.some((message) => STORAGE.test(message))

describe('PA-312 · formas nuevas que dan error de almacenamiento', () => {
  it.each([
    ['caches (global)', "void caches.open('cache-ficticia')"],
    ['globalThis.indexedDB', "void globalThis.indexedDB.open('bd-ficticia')"],
    ['self.localStorage', "void self.localStorage.getItem('clave-ficticia')"],
    ['self.sessionStorage', "void self.sessionStorage.getItem('clave-ficticia')"],
    ['self.indexedDB', "void self.indexedDB.open('bd-ficticia')"],
    ['window.caches', "void window.caches.open('cache-ficticia')"],
    ['self.caches', "void self.caches.open('cache-ficticia')"],
    ['globalThis.caches', "void globalThis.caches.open('cache-ficticia')"],
  ])('test_storage_rule_errors_on_%s', async (_name, body) => {
    /** PA-312: cada acceso nuevo al almacenamiento del navegador da error. */
    expect(hasStorageError(await lint(body))).toBe(true)
  })

  const TARGETS = ['document', 'window', 'self', 'globalThis'] as const
  const STORES = ['cookie', 'localStorage', 'sessionStorage', 'indexedDB', 'caches'] as const
  const pairs = TARGETS.flatMap((target) => STORES.map((store) => [target, store] as const))

  it.each(pairs)('test_storage_rule_errors_on_declaration_destructuring_const_{ %s.%s }', async (target, store) => {
    /** PA-312: `const { <almacén> } = <objeto global>` da error. */
    expect(hasStorageError(await lint(`const { ${store} } = ${target}\n  void ${store}`))).toBe(true)
  })

  it.each(pairs)('test_storage_rule_errors_on_assignment_destructuring_({ %s.%s } = …)', async (target, store) => {
    /** PA-312: `({ <almacén> } = <objeto global>)` (en asignación) da error. */
    expect(hasStorageError(await lint(`let ${store}: unknown\n  ;({ ${store} } = ${target})\n  void ${store}`))).toBe(true)
  })

  it('test_storage_rule_errors_on_renamed_destructuring', async () => {
    /** PA-312: renombrar al desestructurar (`const { localStorage: almacen } = window`) también da error. */
    expect(hasStorageError(await lint('const { localStorage: almacen } = window\n  void almacen'))).toBe(true)
  })

  it('test_storage_rule_errors_on_destructuring_in_tsx', async () => {
    /** PA-312: el mismo código en un .tsx también da error. */
    expect(hasStorageError(await lint('const { cookie } = document\n  void cookie', 'src/screens/fragmento-ficticio.tsx'))).toBe(true)
  })
})

describe('PA-312 · lo que había sigue dando error', () => {
  it.each([
    ['localStorage', "void localStorage.getItem('clave-ficticia')"],
    ['sessionStorage', "void sessionStorage.getItem('clave-ficticia')"],
    ['indexedDB', "void indexedDB.open('bd-ficticia')"],
    ['window.localStorage', "void window.localStorage.getItem('clave-ficticia')"],
    ['globalThis.sessionStorage', "void globalThis.sessionStorage.getItem('clave-ficticia')"],
    ['document.cookie', 'void document.cookie'],
  ])('test_storage_rule_still_errors_on_%s', async (_name, body) => {
    /** PA-312 (regresión): las formas anteriores siguen prohibidas. */
    expect(hasStorageError(await lint(body))).toBe(true)
  })
})

describe('PA-312 · sin falsos positivos', () => {
  it.each([
    ['document.title', 'void document.title'],
    ['leer window.location.href', 'void window.location.href'],
    ['const { title } = document', 'const { title } = document\n  void title'],
    ['self.addEventListener', "self.addEventListener('message', () => undefined)"],
    // «desestructurar cookie de otro objeto» da error desde PA-342 (precio aceptado; storageRule.pa342.test.ts).
    ['asignar desestructurando title de document', 'let title: string\n  ;({ title } = document)\n  void title'],
  ])('test_storage_rule_no_error_on_%s', async (_name, body) => {
    /** PA-312: lo que no es almacenamiento del navegador no da error de almacenamiento. */
    expect(hasStorageError(await lint(body))).toBe(false)
  })
})
