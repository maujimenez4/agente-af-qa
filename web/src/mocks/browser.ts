// API simulada en el navegador: solo con `npm run dev` y VITE_API_MOCK=1 (src/main.tsx).
import { setupWorker } from 'msw/browser'
import { createMockDb, forcedApprovalFrom, forcedCoverageFrom, manyConversations, manyConversationsFrom, noMemoriesFrom, takenFrom } from './db.ts'
import { createHandlers } from './handlers.ts'

export async function startMockApi(): Promise<void> {
  const db = createMockDb()
  // Revisión en el navegador de casos que la pantalla no provoca sola (web/README.md, «API simulada»).
  db.forceApprove = forcedApprovalFrom(window.location.search)
  db.forceTaken = takenFrom(window.location.search)
  db.forceCoverage = forcedCoverageFrom(window.location.search)
  if (noMemoriesFrom(window.location.search)) db.memories = []
  const [example] = db.conversations
  if (example && manyConversationsFrom(window.location.search)) db.conversations = manyConversations(example)
  const worker = setupWorker(...createHandlers(db))
  await worker.start({ serviceWorker: { url: '/mockServiceWorker.js' }, onUnhandledFrame: 'bypass', quiet: true })
}
