// Comprobación en tiempo de compilación: lo que devuelve cada método de `api` es exactamente la
// respuesta de su ruta en el contrato. Si el contrato cambia de forma (p. ej. /start/sources pasó de
// una lista a {sources, budget}), `tsc` falla aquí tras `npm run api:types`. No genera código.
import type { api } from './client.ts'
import type { Equal, Expect, ResponseOf } from './contract.ts'

type Returns<K extends keyof typeof api> = Awaited<ReturnType<(typeof api)[K]>>

const V = '/api/v1'
type V = typeof V

export type ClientContractChecks = [
  Expect<Equal<Returns<'login'>, ResponseOf<`${V}/auth/login`, 'post'>>>,
  Expect<Equal<Returns<'logout'>, ResponseOf<`${V}/auth/logout`, 'post'>>>,
  Expect<Equal<Returns<'me'>, ResponseOf<`${V}/auth/me`, 'get'>>>,
  Expect<Equal<Returns<'projects'>, ResponseOf<`${V}/projects`, 'get'>>>,
  Expect<Equal<Returns<'chooseProject'>, ResponseOf<`${V}/projects/choose`, 'post'>>>,
  Expect<Equal<Returns<'epics'>, ResponseOf<`${V}/projects/{project}/epics`, 'get'>>>,
  Expect<Equal<Returns<'search'>, ResponseOf<`${V}/projects/{project}/search`, 'get'>>>,
  Expect<Equal<Returns<'stories'>, ResponseOf<`${V}/epics/{key}/stories`, 'get'>>>,
  Expect<Equal<Returns<'issue'>, ResponseOf<`${V}/issues/{key}`, 'get'>>>,
  Expect<Equal<Returns<'propose'>, ResponseOf<`${V}/start/propose`, 'post'>>>,
  Expect<Equal<Returns<'sources'>, ResponseOf<`${V}/start/sources`, 'post'>>>,
  Expect<Equal<Returns<'conversations'>, ResponseOf<`${V}/conversations`, 'get'>>>,
  Expect<Equal<Returns<'createConversation'>, ResponseOf<`${V}/conversations`, 'post'>>>,
  Expect<Equal<Returns<'conversation'>, ResponseOf<`${V}/conversations/{conversation_id}`, 'get'>>>,
  Expect<Equal<Returns<'iterate'>, ResponseOf<`${V}/conversations/{conversation_id}/iterate`, 'post'>>>,
  Expect<Equal<Returns<'discard'>, ResponseOf<`${V}/conversations/{conversation_id}/discard`, 'post'>>>,
  Expect<Equal<Returns<'approve'>, ResponseOf<`${V}/conversations/{conversation_id}/approve`, 'post'>>>,
  Expect<Equal<Returns<'cancel'>, ResponseOf<`${V}/conversations/{conversation_id}/cancel`, 'post'>>>,
  Expect<Equal<Returns<'retry'>, ResponseOf<`${V}/conversations/{conversation_id}/retry`, 'post'>>>,
  Expect<Equal<Returns<'settings'>, ResponseOf<`${V}/settings`, 'get'>>>,
  Expect<Equal<Returns<'usage'>, ResponseOf<`${V}/settings/usage`, 'get'>>>,
]
