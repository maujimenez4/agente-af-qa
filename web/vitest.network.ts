// PA-127: MSW 3 intercepta `fetch` en el socket. Si undici reutiliza una conexión abierta, a veces la petición
// no se atribuye a `fetch`, MSW la deja pasar y sale a la red real (`fetch failed`; con `/auth/me`, la prueba
// arranca en el login). Una conexión nueva por petición (`reset: true`) lo evita. Solo en las pruebas: va
// aparte de src/test/setup.ts para que los tipos de Node no entren en el proyecto de la app.
import { Agent, setGlobalDispatcher } from 'undici'

setGlobalDispatcher(new Agent().compose((dispatch) => (options, handler) => dispatch({ ...options, reset: true }, handler)))
