import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    // Solo web/ y el contrato de la API (las pruebas lo leen). Nunca la raíz del repo: ahí está el .env.
    fs: { allow: ['.', '../docs/api'] },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    restoreMocks: true,
    unstubGlobals: true,
  },
})
