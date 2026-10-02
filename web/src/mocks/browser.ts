// API simulada en el navegador: solo con `npm run dev` y VITE_API_MOCK=1 (src/main.tsx).
import { setupWorker } from 'msw/browser'
import { createMockDb } from './db.ts'
import { createHandlers } from './handlers.ts'

export async function startMockApi(): Promise<void> {
  const worker = setupWorker(...createHandlers(createMockDb()))
  await worker.start({ serviceWorker: { url: '/mockServiceWorker.js' }, onUnhandledFrame: 'bypass', quiet: true })
}
