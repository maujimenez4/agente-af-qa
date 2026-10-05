// Ejemplos de respuesta del contrato (src/api/examples.json, generado con `npm run api:types`).
import examples from '../api/examples.json'

type ExampleKey = keyof typeof examples

/** Copia profunda del ejemplo: cada handler puede modificar el suyo sin tocar el original. */
export function example<T>(key: ExampleKey): T {
  return structuredClone(examples[key]) as T
}
