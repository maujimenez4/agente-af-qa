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
      setupFiles: ['./src/test/setup.ts'],
      css: true,
      restoreMocks: true,
      unstubGlobals: true,
    },
  }
})
