// Genera desde el contrato docs/api/openapi.yaml (T-55):
//   - web/src/api/schema.d.ts: tipos (openapi-typescript);
//   - web/src/api/examples.json: el ejemplo de cada respuesta y los de components.examples (PA-118), para la API simulada (MSW).
//   node tools/api-types/generate.mjs           → escribe los archivos
//   node tools/api-types/generate.mjs --check   → falla si no coinciden con el contrato
import { readFile, writeFile } from 'node:fs/promises'
import yaml from 'js-yaml'
import openapiTS, { astToString } from 'openapi-typescript'

const contract = new URL('../../../docs/api/openapi.yaml', import.meta.url)
const schemaFile = new URL('../../src/api/schema.d.ts', import.meta.url)
const examplesFile = new URL('../../src/api/examples.json', import.meta.url)

const HEADER = `// GENERADO desde docs/api/openapi.yaml con openapi-typescript: no editar a mano.
// Regenerar con: npm run api:types (y comprobar con npm run api:check).
`

const ast = await openapiTS(contract, { alphabetize: true })
const schema = HEADER + astToString(ast).replace(/\r\n/g, '\n')

// Clave: «MÉTODO /ruta código», p. ej. «GET /api/v1/projects 200».
const document = yaml.load(await readFile(contract, 'utf8'))
const examples = {}
for (const [path, operations] of Object.entries(document.paths)) {
  for (const [method, operation] of Object.entries(operations)) {
    for (const [status, response] of Object.entries(operation.responses ?? {})) {
      const example = Object.values(response.content ?? {})
        .map((media) => media.example)
        .find((value) => value !== undefined)
      if (example !== undefined) examples[`${method.toUpperCase()} ${path} ${status}`] = example
    }
  }
}
// PA-118: los ejemplos con nombre (p. ej. «components.examples.ConversationQaInReview»), solo su `value`.
for (const [name, entry] of Object.entries(document.components?.examples ?? {})) {
  if (entry?.value !== undefined) examples[`components.examples.${name}`] = entry.value
}
const examplesJson = `${JSON.stringify(examples, null, 2)}\n`

const outputs = [
  [schemaFile, schema, 'src/api/schema.d.ts'],
  [examplesFile, examplesJson, 'src/api/examples.json'],
]

if (process.argv.includes('--check')) {
  let stale = false
  for (const [file, expected, name] of outputs) {
    const current = (await readFile(file, 'utf8').catch(() => '')).replace(/\r\n/g, '\n')
    if (current !== expected) {
      console.error(`${name} no coincide con docs/api/openapi.yaml: ejecuta npm run api:types.`)
      stale = true
    }
  }
  if (stale) process.exit(1)
  console.log('Tipos y ejemplos al día con el contrato.')
} else {
  for (const [file, content, name] of outputs) {
    await writeFile(file, content)
    console.log(`Generado ${name}.`)
  }
}
