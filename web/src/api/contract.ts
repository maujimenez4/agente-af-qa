// Tipos de respuesta sacados de las rutas del contrato (`paths` de schema.d.ts).
// Los usa client.contract.ts para que `tsc` falle si el cliente espera otra forma que la del contrato.
import type { paths } from './schema'

type Method = 'get' | 'post' | 'put' | 'delete'

type JsonOf<R> = R extends { content: { 'application/json': infer J } } ? J : void

/** Cuerpo de la respuesta correcta (200, 201, 202 o 204) de `METHOD path`. */
export type ResponseOf<P extends keyof paths, M extends Method> = paths[P][M] extends { responses: infer R }
  ? R extends { 200: infer X }
    ? JsonOf<X>
    : R extends { 201: infer X }
      ? JsonOf<X>
      : R extends { 202: infer X }
        ? JsonOf<X>
        : R extends { 204: unknown }
          ? void
          : never
  : never

/** Igualdad exacta de tipos (no basta con que uno sea asignable al otro). */
export type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false

export type Expect<T extends true> = T
