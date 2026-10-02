// Genera web/src/api/schema.d.ts desde el contrato docs/api/openapi.yaml (T-55).
//   node tools/api-types/generate.mjs           → escribe el archivo
//   node tools/api-types/generate.mjs --check   → falla si el archivo no coincide con el contrato
import { readFile, writeFile } from 'node:fs/promises'
import openapiTS, { astToString } from 'openapi-typescript'

const contract = new URL('../../../docs/api/openapi.yaml', import.meta.url)
const output = new URL('../../src/api/schema.d.ts', import.meta.url)

const HEADER = `// GENERADO desde docs/api/openapi.yaml con openapi-typescript: no editar a mano.
// Regenerar con: npm run api:types (y comprobar con npm run api:check).
`

const ast = await openapiTS(contract, { alphabetize: true })
const generated = HEADER + astToString(ast).replace(/\r\n/g, '\n')

if (process.argv.includes('--check')) {
  const current = (await readFile(output, 'utf8').catch(() => '')).replace(/\r\n/g, '\n')
  if (current !== generated) {
    console.error('src/api/schema.d.ts no coincide con docs/api/openapi.yaml: ejecuta npm run api:types.')
    process.exit(1)
  }
  console.log('src/api/schema.d.ts está al día con el contrato.')
} else {
  await writeFile(output, generated)
  console.log('Tipos generados en src/api/schema.d.ts.')
}
