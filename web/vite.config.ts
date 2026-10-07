import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // API simulada (MSW) solo con `npm run dev:mock` (o VITE_API_MOCK=1): mockServiceWorker.js nunca entra en el build.
  const mockApi = command === 'serve' && (mode === 'mock' || env.VITE_API_MOCK === '1')

  return {
    plugins: [react()],
    publicDir: mockApi ? 'mock-public' : false,
    server: {
      // Solo web/ y el contrato de la API (las pruebas lo leen). Nunca la raíz del repo: ahí está el .env.
      fs: { allow: ['.', '../docs/api'] },
      // API real en desarrollo (DESIGN-DECISIONS.md §4): mismo origen y SIN changeOrigin, porque la API
      // compara Origin con Host. API_PROXY_TARGET no lleva prefijo VITE_: no llega al navegador.
      proxy: mockApi ? undefined : { '/api': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000' } },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./vitest.network.ts', './src/test/setup.ts'],
      css: true,
      restoreMocks: true,
      unstubGlobals: true,
      // Pruebas de pantalla con MSW y SSE simulado: con todos los núcleos ocupados se acercan a los 5 s
      // por defecto. 15 s evita falsos fallos por carga sin ocultar un bloqueo real.
      testTimeout: 15_000,
      // La mitad de los núcleos (Vitest usa todos menos uno): con jsdom y MSW, más hilos no acaban antes y
      // saturan el equipo; el primer arranque de la app en cada archivo es lo que más lo nota (DESIGN-DECISIONS.md §7).
      maxWorkers: '50%',
    },
  }
})
